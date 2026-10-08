"""Collect one real, isolated AKShare financial-slice S6 receipt."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

import redis
from django.conf import settings

from apps.data_center.akshare_financial_capture_composition import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT_URL,
)
from apps.data_center.akshare_financial_slice_sync_composition import (
    make_sync_akshare_financial_slices_use_case,
)
from apps.data_center.application.egress_service import preview_route
from apps.data_center.application.financial_slice_sync import (
    FinancialAnnouncementSlice,
    FinancialSliceSyncRequest,
    FinancialSliceSyncResult,
)
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.entities import ProviderConfig, RawAudit
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_source_evidence import (
    FINANCIAL_FACT_DATASET_KEY,
    FinancialFactDecisionEvidence,
    FinancialFactSourceEvidence,
)
from apps.data_center.domain.financial_source_time_evidence import (
    FINANCIAL_SOURCE_TIME_DATASET_KEY,
    FinancialSourceTimeArtifactRef,
    FinancialSourceTimeWitness,
)
from apps.data_center.infrastructure.akshare_financial_slice_sync import (
    akshare_financial_deployment_region,
    load_akshare_financial_slice_sync_budget,
)
from apps.data_center.infrastructure.financial_decision_evidence_codec import (
    decode_financial_decision_evidence,
)
from apps.data_center.infrastructure.financial_fact_write_guard import source_evidence_from_model
from apps.data_center.infrastructure.financial_response_artifact_config import (
    resolve_financial_response_artifact_config,
)
from apps.data_center.infrastructure.financial_response_body_store import (
    FinancialResponseBodyStore,
)
from apps.data_center.infrastructure.financial_source_time_audit import (
    StrictFinancialSourceTimeAuditLinkVerifier,
)
from apps.data_center.infrastructure.financial_source_time_body_store import (
    FinancialSourceTimeBodyStore,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_SOURCE_TIMEZONE,
    akshare_notice_date_match_contract,
)
from apps.data_center.infrastructure.isolated_write_rehearsal_runner import (
    preflight_isolated_write_rehearsal,
)
from apps.data_center.infrastructure.models import (
    AssetMasterModel,
    FinancialFactModel,
    ProviderConfigModel,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.rehearsal_identity import (
    RehearsalProviderIdentity,
    akshare_financial_route_role,
    load_rehearsal_identities,
    rehearsal_identities_digest,
    verify_configured_rehearsal_identities,
)
from core.exceptions import DataFetchError

_ASSET_CODE = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_CANDIDATE = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DATABASE_HOST = re.compile(r"^agom-s6-postgres-[a-z0-9-]+$")
_DATABASE_NAME = re.compile(r"^agom_release_rehearsal_[a-z0-9_]+$")
_REDIS_HOST = re.compile(r"^agom-s6-redis-[a-z0-9-]+$")
_PROOF_CASES = (
    "tests.unit.data_center.test_akshare_financial_capture::test_akshare_financial_capture_provider_failure_does_not_retain_any_artifact",
    "tests.unit.data_center.test_akshare_financial_capture::test_akshare_financial_slice_sync_evidence_rejection_writes_zero_facts",
    "tests.unit.data_center.test_akshare_financial_capture::test_akshare_financial_slice_sync_partial_provider_failure_writes_zero_facts",
)
_SOURCE_EVIDENCE_TEST = "candidate_regression_evidence"
_SYNC_FAILURE_CODES = {
    "owner_approved_capture_capability_unavailable": (
        "REHEARSAL_FINANCIAL_SLICE_CAPTURE_UNAVAILABLE"
    ),
    "akshare_provider_or_capture_failed": ("REHEARSAL_FINANCIAL_SLICE_PROVIDER_OR_CAPTURE_FAILED"),
    "financial_source_evidence_incomplete_or_mismatched": (
        "REHEARSAL_FINANCIAL_SLICE_SOURCE_EVIDENCE_INVALID"
    ),
    "financial_slice_batch_empty_or_ambiguous": ("REHEARSAL_FINANCIAL_SLICE_EMPTY_OR_AMBIGUOUS"),
    "financial_fact_atomic_batch_write_failed": ("REHEARSAL_FINANCIAL_SLICE_ATOMIC_WRITE_FAILED"),
}


@dataclass(frozen=True, slots=True)
class _RequestSeed:
    """One untrusted snapshot row used only to construct the provider request."""

    asset_code: str
    announcement_date: date
    basis: str
    fact_id_sha256: str
    selection_sha256: str


@dataclass(frozen=True, slots=True)
class _VerifiedFinancialFacts:
    """Typed new facts and their one verified pair of provider artifacts."""

    facts: tuple[FinancialFactModel, ...]
    decision: FinancialFactDecisionEvidence
    source_time: FinancialSourceTimeWitness
    verified_capture_ids: frozenset[UUID]


def collect_akshare_financial_slice_rehearsal(
    *,
    candidate_sha: str,
    target_trade_date: date,
    universe_sha256: str,
    provider_identities_sha256: str,
    provider_identities_path: Path,
    expected_database_name: str,
    expected_database_host: str,
    expected_redis_host: str,
    candidate_regression_evidence_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Run exactly one source-pinned AKShare slice and emit only verified evidence."""

    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_OUTPUT_EXISTS")
    if (
        _CANDIDATE.fullmatch(candidate_sha) is None
        or _SHA256.fullmatch(universe_sha256) is None
        or _SHA256.fullmatch(provider_identities_sha256) is None
        or not isinstance(target_trade_date, date)
        or isinstance(target_trade_date, datetime)
    ):
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_IDENTITY_INVALID")

    started_at = datetime.now(UTC)
    identities = verify_configured_rehearsal_identities(
        load_rehearsal_identities(provider_identities_path)
    )
    if rehearsal_identities_digest(identities) != provider_identities_sha256:
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_PROVIDER_SNAPSHOT_MISMATCH")
    identity_attestation, candidate_image_id, database_identity_sha256 = (
        preflight_isolated_write_rehearsal(
            candidate_sha=candidate_sha,
            source_root=Path(settings.BASE_DIR),
            expected_database_name=expected_database_name,
            expected_database_host=expected_database_host,
            require_ephemeral_host=True,
        )
    )
    redis_host = _verify_isolated_redis(expected_redis_host)
    failure_evidence = _verify_failure_evidence(
        candidate_regression_evidence_path,
        expected_candidate=candidate_sha,
    )
    provider, provider_identity = _select_provider(identities)
    egress_routes = _require_akshare_financial_egress_routes(provider)
    budget = load_akshare_financial_slice_sync_budget()
    if (
        budget is None
        or budget.max_slices != 1
        or budget.provider_requests_per_slice != 2
        or budget.max_provider_requests != 2
    ):
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_BUDGET_INVALID")
    seed = _select_request_seed(
        target_trade_date=target_trade_date,
        provider_id=_provider_id(provider),
        provider_identities_sha256=provider_identities_sha256,
        database_identity_sha256=database_identity_sha256,
    )

    provider_started_at = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix="agom-s6-financial-") as temporary_directory:
        artifact_root = Path(temporary_directory).resolve()
        use_case = make_sync_akshare_financial_slices_use_case(artifact_storage_root=artifact_root)
        result = use_case.execute(
            FinancialSliceSyncRequest(
                provider_id=_provider_id(provider),
                source="akshare",
                slices=(FinancialAnnouncementSlice(seed.asset_code, seed.announcement_date),),
                period_limit=8,
            )
        )
        _require_successful_sync(result, _provider_id(provider))
        verified_facts = _verify_persisted_pair(
            seed=seed,
            provider=provider,
            provider_started_at=provider_started_at,
            stored_count=result.stored,
            artifact_root=artifact_root,
        )
        captures = _capture_evidence(
            verified_facts,
            provider_id=_provider_id(provider),
        )

    finished_at = datetime.now(UTC)
    report: dict[str, object] = {
        "schema": "release.akshare-financial-slice.v1",
        "kind": "akshare_financial_slice",
        "candidate_sha": candidate_sha,
        "candidate_image_id": candidate_image_id,
        "candidate_source_attestation": identity_attestation,
        "target_trade_date": target_trade_date.isoformat(),
        "universe_sha256": universe_sha256,
        "provider_identities": [asdict(identity) for identity in identities],
        "provider_identities_sha256": provider_identities_sha256,
        "evidence_mode": "isolated_postgresql_redis_real_provider",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "outcome": "success",
        "release_ready": False,
        "remaining_release_gates": ["release_approval", "deployment_authorization"],
        "database": {
            "vendor": "postgresql",
            "scope": "disposable",
            "release_rehearsal_guard": True,
            "host": expected_database_host,
            "name": expected_database_name,
            "identity_sha256": database_identity_sha256,
        },
        "redis": {
            "scope": "disposable",
            "host": redis_host,
            "expected_host": expected_redis_host,
            "ping_verified": True,
        },
        "selected_provider": {
            "provider_id": _provider_id(provider),
            "source_type": "akshare",
            "frozen_identity_role": provider_identity.role,
            "frozen_identity_source": provider_identity.source,
            "frozen_route_identity_sha256": _canonical_sha256(asdict(provider_identity)),
        },
        "financial_route": {
            "provider_route_identity": asdict(provider_identity),
            "provider_route_identity_sha256": _canonical_sha256(asdict(provider_identity)),
            "endpoint": akshare_notice_date_match_contract().endpoint,
            "source_time_contract": akshare_notice_date_match_contract().to_dict(),
        },
        "egress_routes": list(egress_routes),
        "request_seed": {
            "asset_code": seed.asset_code,
            "announcement_date": seed.announcement_date.isoformat(),
            "basis": seed.basis,
            "source": "akshare",
            "provenance_is_seed_only": True,
            "legacy_fact_id_sha256": seed.fact_id_sha256,
            "selection_sha256": seed.selection_sha256,
        },
        "sync": {
            **result.to_dict(),
            "provider_request_count": 2,
            "typed_fact_evidence_count": len(verified_facts.facts),
            "source_time_witness_count": len(verified_facts.facts),
            "period_limit": 8,
            "max_period_rows_per_capture": budget.max_period_rows_per_capture,
        },
        "captures": captures,
        "failure_evidence": failure_evidence,
    }
    _write_report(output_dir, report)
    return report


def _verify_isolated_redis(expected_host: str) -> str:
    """Ping only the exact isolated Redis endpoint named by the S6 environment."""

    redis_url = os.environ.get("REDIS_URL", "")
    configured_host = os.environ.get("REDIS_HOST", "")
    try:
        parsed = urlsplit(redis_url)
    except ValueError as exc:
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_REDIS_INVALID") from exc
    if (
        not _REDIS_HOST.fullmatch(expected_host)
        or configured_host != expected_host
        or parsed.scheme not in {"redis", "rediss"}
        or parsed.hostname != expected_host
    ):
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_REDIS_INVALID")
    client = redis.Redis.from_url(redis_url)
    try:
        if client.ping() is not True:
            raise ValueError("REHEARSAL_FINANCIAL_SLICE_REDIS_UNAVAILABLE")
    except redis.RedisError as exc:
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_REDIS_UNAVAILABLE") from exc
    finally:
        client.close()
    return expected_host


def _verify_failure_evidence(path: Path, *, expected_candidate: str) -> dict[str, object]:
    """Bind zero-write fault-injection contracts to the official candidate JUnit file."""

    report = _read_json_object(path)
    if (
        report.get("schema") != "release.candidate-regression-evidence.v1"
        or report.get("kind") != "candidate_regression_evidence"
        or report.get("candidate_sha") != expected_candidate
        or report.get("outcome") != "success"
    ):
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_FAILURE_EVIDENCE_INVALID")
    required_tests = report.get("required_tests")
    artifacts = report.get("junit_artifacts")
    if not isinstance(required_tests, list) or not set(_PROOF_CASES).issubset(
        cast(list[str], required_tests)
    ):
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_FAILURE_EVIDENCE_INVALID")
    if not isinstance(artifacts, list):
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_FAILURE_EVIDENCE_INVALID")
    artifact = next(
        (
            cast(dict[str, object], item)
            for item in cast(list[object], artifacts)
            if isinstance(item, dict) and item.get("path") == "financial-slice-sync-contracts.xml"
        ),
        None,
    )
    if artifact is None:
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_FAILURE_EVIDENCE_INVALID")
    junit_path = path.parent / "financial-slice-sync-contracts.xml"
    if junit_path.is_symlink() or not junit_path.is_file():
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_FAILURE_EVIDENCE_INVALID")
    junit_bytes = junit_path.read_bytes()
    junit_sha = _sha256(junit_bytes)
    if artifact.get("sha256") != junit_sha:
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_FAILURE_EVIDENCE_INVALID")
    try:
        junit_root = ET.fromstring(junit_bytes)
    except ET.ParseError as exc:
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_FAILURE_EVIDENCE_INVALID") from exc
    if (
        junit_root.findall(".//failure")
        or junit_root.findall(".//error")
        or junit_root.findall(".//skipped")
    ):
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_FAILURE_EVIDENCE_INVALID")
    observed = {
        f"{case.get('classname', '')}::{case.get('name', '')}"
        for case in junit_root.findall(".//testcase")
    }
    if not set(_PROOF_CASES).issubset(observed):
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_FAILURE_EVIDENCE_INVALID")
    return {
        "source": _SOURCE_EVIDENCE_TEST,
        "failure_isolated_before_real_provider_egress": True,
        "zero_fact_write_test_cases": list(_PROOF_CASES),
        "junit_sha256": junit_sha,
    }


def _select_provider(
    identities: tuple[RehearsalProviderIdentity, ...],
) -> tuple[ProviderConfig, RehearsalProviderIdentity]:
    """Select one active AKShare row already represented by the frozen snapshot."""

    eligible = tuple(
        identity
        for identity in identities
        if identity.source == "akshare_financial"
        and identity.role == akshare_financial_route_role(identity.provider_id)
    )
    if len(eligible) != 1:
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_PROVIDER_IDENTITY_AMBIGUOUS")
    provider_identity = eligible[0]
    rows = tuple(
        ProviderConfigModel.objects.filter(
            pk=provider_identity.provider_id,
            source_type="akshare",
            is_active=True,
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    if len(rows) != 1:
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_PROVIDER_AMBIGUOUS")
    provider_id = int(rows[0])
    from apps.data_center.composition import get_provider_config_repository

    provider = get_provider_config_repository().get_by_id(provider_id)
    if (
        not isinstance(provider, ProviderConfig)
        or provider.id != provider_id
        or provider.source_type != "akshare"
        or provider.is_active is not True
    ):
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_PROVIDER_INVALID")
    return provider, provider_identity


def _select_request_seed(
    *,
    target_trade_date: date,
    provider_id: int,
    provider_identities_sha256: str,
    database_identity_sha256: str,
) -> _RequestSeed:
    """Choose a legal asset/date from isolated AKShare facts without using report_date."""

    assets = tuple(
        code
        for code in AssetMasterModel.objects.filter(
            asset_type="stock",
            exchange__in=("SSE", "SZSE", "BSE"),
            is_active=True,
        )
        .order_by("code")
        .values_list("code", flat=True)
        if isinstance(code, str) and _ASSET_CODE.fullmatch(code)
    )
    cutoff = datetime.combine(
        target_trade_date + timedelta(days=1),
        time.min,
        tzinfo=ZoneInfo(AKSHARE_SOURCE_TIMEZONE),
    ).astimezone(UTC)
    rows = (
        FinancialFactModel.objects.filter(
            asset_code__in=assets,
            source="akshare",
            available_at__isnull=False,
            available_at__lte=cutoff,
        )
        .only(
            "id",
            "asset_code",
            "period_end",
            "source",
            "announced_at",
            "available_at",
            "decision_evidence",
            "source_record_id",
            "raw_payload_hash",
        )
        .order_by("-available_at", "asset_code", "pk")[:5000]
    )
    for row in rows:
        if not isinstance(row.asset_code, str) or row.asset_code not in assets:
            continue
        announcement_date, basis = _seed_date(row)
        if announcement_date is None or announcement_date > target_trade_date:
            continue
        fact_id_sha256 = _sha256(str(row.pk))
        selection_material: dict[str, object] = {
            "asset_code": row.asset_code,
            "announcement_date": announcement_date.isoformat(),
            "basis": basis,
            "legacy_fact_id_sha256": fact_id_sha256,
            "provider_id": provider_id,
            "provider_identities_sha256": provider_identities_sha256,
            "database_identity_sha256": database_identity_sha256,
            "target_trade_date": target_trade_date.isoformat(),
            "announced_at": row.announced_at.isoformat() if row.announced_at else None,
            "available_at": row.available_at.isoformat() if row.available_at else None,
        }
        return _RequestSeed(
            asset_code=row.asset_code,
            announcement_date=announcement_date,
            basis=basis,
            fact_id_sha256=fact_id_sha256,
            selection_sha256=_canonical_sha256(selection_material),
        )
    raise ValueError("REHEARSAL_FINANCIAL_SLICE_SEED_UNAVAILABLE")


def _seed_date(row: FinancialFactModel) -> tuple[date | None, str]:
    """Extract a request-only notice date, preferring typed source evidence."""

    decision = decode_financial_decision_evidence(row.decision_evidence)
    if (
        isinstance(decision, FinancialFactDecisionEvidence)
        and decision.source_time_witness is not None
        and decision.native_asset_code == row.asset_code
        and decision.native_period_end == row.period_end
        and decision.native_row_id == row.source_record_id
    ):
        return (
            decision.source_time_witness.financial_announced_date,
            "typed_source_time_announcement_date_untrusted",
        )
    source_evidence = source_evidence_from_model(row)
    if isinstance(source_evidence, FinancialFactSourceEvidence) and source_evidence.announced_at:
        return (
            source_evidence.announced_at.astimezone(ZoneInfo(AKSHARE_SOURCE_TIMEZONE)).date(),
            "legacy_announced_at_date_untrusted",
        )
    available_at = row.available_at
    if isinstance(available_at, datetime) and available_at.utcoffset() is not None:
        return available_at.date(), "legacy_available_at_date_untrusted"
    return None, "unavailable"


def _require_successful_sync(result: FinancialSliceSyncResult, provider_id: int) -> None:
    """Fail unless the one request produced complete evidence and one atomic batch."""

    if (
        result.outcome != "success"
        or result.source != "akshare"
        or result.provider_id != provider_id
        or result.requested != 1
        or result.succeeded != 1
        or result.failed != 0
        or result.stored <= 0
        or result.planned_provider_requests != 2
        or result.atomic_fact_write_count != 1
    ):
        raise DataFetchError(
            "S6 AKShare financial slice did not meet its controlled write contract",
            code=_SYNC_FAILURE_CODES.get(
                str(result.failure_reason or ""),
                "REHEARSAL_FINANCIAL_SLICE_SYNC_INVALID",
            ),
        )


def _require_akshare_financial_egress_routes(
    provider: ProviderConfig,
) -> tuple[dict[str, object], ...]:
    """Require both registered AKShare financial routes before any provider request."""

    provider_id = _provider_id(provider)
    region = akshare_financial_deployment_region()
    evidence: list[dict[str, object]] = []
    for dataset_key in (
        FINANCIAL_FACT_DATASET_KEY,
        FINANCIAL_SOURCE_TIME_DATASET_KEY,
    ):
        decision = preview_route(
            EgressRequestContext(
                provider_id=provider_id,
                dataset_key=dataset_key,
                target_url=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT_URL,
                deployment_region=region,
            )
        )
        if decision.rule_id is None or decision.reason != "matched_rule":
            raise DataFetchError(
                "S6 AKShare financial slice requires both registered egress routes",
                code="REHEARSAL_FINANCIAL_SLICE_EGRESS_ROUTE_REQUIRED",
            )
        evidence.append(
            {
                "dataset_key": dataset_key,
                "rule_id": decision.rule_id,
                "strategy": decision.strategy.value,
                "matched_domain": decision.matched_domain,
                "candidate_count": len(decision.candidates),
                "deployment_region": region,
            }
        )
    return tuple(evidence)


def _verify_persisted_pair(
    *,
    seed: _RequestSeed,
    provider: ProviderConfig,
    provider_started_at: datetime,
    stored_count: int,
    artifact_root: Path,
) -> _VerifiedFinancialFacts:
    """Re-read typed facts, both encrypted bodies, and exact provider audit links."""

    expected_contract = akshare_notice_date_match_contract()
    rows = tuple(
        FinancialFactModel.objects.filter(
            asset_code=seed.asset_code,
            source="akshare",
            report_date=seed.announcement_date,
        ).only(
            "id",
            "asset_code",
            "period_end",
            "source",
            "report_date",
            "announced_at",
            "available_at",
            "fetched_at",
            "extra",
            "decision_evidence",
            "source_record_id",
            "raw_payload_hash",
        )
    )
    evidence_rows: list[FinancialFactModel] = []
    decision_evidence: list[FinancialFactDecisionEvidence] = []
    witness_evidence: list[FinancialSourceTimeWitness] = []
    for row in rows:
        source = source_evidence_from_model(row)
        decision = decode_financial_decision_evidence(row.decision_evidence)
        if not isinstance(source, FinancialFactSourceEvidence) or not source.is_complete:
            continue
        if not isinstance(decision, FinancialFactDecisionEvidence):
            continue
        witness = decision.source_time_witness
        if witness is None:
            continue
        request_scope = decision.artifact_reference.evidence.request_scope
        if (
            row.asset_code != seed.asset_code
            or row.source != "akshare"
            or row.report_date != seed.announcement_date
            or decision.native_asset_code != seed.asset_code
            or decision.native_period_end != row.period_end
            or decision.native_row_id != row.source_record_id
            or request_scope.provider_name != "akshare"
            or request_scope.dataset_key != FINANCIAL_FACT_DATASET_KEY
            or request_scope.asset_code != seed.asset_code
            or witness.artifact_reference.dataset_key != FINANCIAL_SOURCE_TIME_DATASET_KEY
            or witness.financial_announced_date != seed.announcement_date
            or witness.native_asset_code != seed.asset_code
            or witness.native_period_end != row.period_end
            or witness.financial_native_row_id != decision.native_row_id
            or source.source_record_id != decision.native_row_id
            or source.raw_payload_hash != decision.artifact_reference.body_sha256
            or source.announced_at != witness.announced_at
            or row.available_at != witness.available_at
            or witness.source_timezone != expected_contract.source_timezone
            or witness.governed_match_contract_id != expected_contract.contract_id
            or witness.governed_match_contract_version != expected_contract.contract_version
            or witness.governed_match_contract_sha256 != expected_contract.contract_sha256
            or decision.artifact_reference.evidence.response_completed_at < provider_started_at
            or witness.artifact_reference.response_completed_at < provider_started_at
        ):
            continue
        evidence_rows.append(row)
        decision_evidence.append(decision)
        witness_evidence.append(witness)
    if len(evidence_rows) != stored_count or not evidence_rows:
        raise DataFetchError(
            "S6 could not read back the exact typed fact batch",
            code="REHEARSAL_FINANCIAL_SLICE_TYPED_FACTS_INVALID",
        )
    financial_refs = {
        item.artifact_reference.capture_id: item.artifact_reference for item in decision_evidence
    }
    source_time_refs = {
        item.artifact_reference.capture_id: item.artifact_reference for item in witness_evidence
    }
    if len(financial_refs) != 1 or len(source_time_refs) != 1:
        raise DataFetchError(
            "S6 financial facts do not share one independent capture pair",
            code="REHEARSAL_FINANCIAL_SLICE_CAPTURE_PAIR_INVALID",
        )
    financial_reference = next(iter(financial_refs.values()))
    source_time_reference = next(iter(source_time_refs.values()))
    if financial_reference.capture_id == source_time_reference.capture_id:
        raise DataFetchError(
            "S6 financial capture identifiers are not independent",
            code="REHEARSAL_FINANCIAL_SLICE_CAPTURE_PAIR_INVALID",
        )
    verified_capture_ids = _verify_artifact_bytes(
        financial_reference,
        source_time_reference,
        provider=provider,
        artifact_root=artifact_root,
    )
    return _VerifiedFinancialFacts(
        facts=tuple(evidence_rows),
        decision=decision_evidence[0],
        source_time=witness_evidence[0],
        verified_capture_ids=verified_capture_ids,
    )


def _verify_artifact_bytes(
    financial_reference: FinancialResponseArtifactRef,
    source_time_reference: FinancialSourceTimeArtifactRef,
    *,
    provider: ProviderConfig,
    artifact_root: Path,
) -> frozenset[UUID]:
    """Authenticate both stored body bytes and their one exact RawAudit each."""

    runtime = resolve_financial_response_artifact_config()
    if runtime is None:
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_CAPTURE_CONFIG_MISSING")
    financial_store = FinancialResponseBodyStore(
        artifact_root,
        encryption_key=runtime.encryption_key,
        encryption_key_ref=runtime.encryption_key_ref,
        encryption_key_version=runtime.encryption_key_version,
        max_body_bytes=runtime.max_body_bytes,
    )
    source_time_store = FinancialSourceTimeBodyStore(
        artifact_root,
        encryption_key=runtime.encryption_key,
        encryption_key_ref=runtime.encryption_key_ref,
        encryption_key_version=runtime.encryption_key_version,
        max_body_bytes=runtime.max_body_bytes,
    )
    financial_body = financial_store.read(financial_reference)
    source_time_body = source_time_store.read(source_time_reference)
    if (
        not financial_body
        or not source_time_body
        or _sha256(financial_body) != financial_reference.body_sha256
        or len(financial_body) != financial_reference.body_size_bytes
        or _sha256(source_time_body) != source_time_reference.body_sha256
        or len(source_time_body) != source_time_reference.body_size_bytes
    ):
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_BODY_INVALID")
    raw_audits = RawAuditRepository()
    financial_audits = raw_audits.list_by_artifact_capture_id(financial_reference.capture_id)
    source_time_audits = raw_audits.list_by_source_time_artifact_capture_id(
        source_time_reference.capture_id
    )
    if len(financial_audits) != 1 or len(source_time_audits) != 1:
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_RAW_AUDIT_CARDINALITY_INVALID")
    verifier = StrictFinancialSourceTimeAuditLinkVerifier(
        expected_provider_id=_provider_id(provider)
    )
    if (
        verifier.verify_financial(financial_audits[0], financial_reference)
        != _provider_id(provider)
        or verifier.verify_source_time(source_time_audits[0], source_time_reference)
        != _provider_id(provider)
        or financial_audits[0].status != "ok"
        or source_time_audits[0].status != "ok"
    ):
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_RAW_AUDIT_PROVIDER_INVALID")
    return frozenset((financial_reference.capture_id, source_time_reference.capture_id))


def _capture_evidence(
    verified: _VerifiedFinancialFacts,
    *,
    provider_id: int,
) -> list[dict[str, object]]:
    """Return report-safe raw-body and audit metadata without exposing body bytes."""

    financial_reference = verified.decision.artifact_reference
    source_time_reference = verified.source_time.artifact_reference
    expected_capture_ids = frozenset(
        (financial_reference.capture_id, source_time_reference.capture_id)
    )
    if verified.verified_capture_ids != expected_capture_ids:
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_BODY_INVALID")
    raw_audits = RawAuditRepository()
    financial_audits = raw_audits.list_by_artifact_capture_id(financial_reference.capture_id)
    source_time_audits = raw_audits.list_by_source_time_artifact_capture_id(
        source_time_reference.capture_id
    )
    if len(financial_audits) != 1 or len(source_time_audits) != 1:
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_RAW_AUDIT_CARDINALITY_INVALID")
    pairs: tuple[
        tuple[FinancialResponseArtifactRef | FinancialSourceTimeArtifactRef, RawAudit], ...
    ] = (
        (financial_reference, financial_audits[0]),
        (source_time_reference, source_time_audits[0]),
    )
    captures: list[dict[str, object]] = []
    for reference, audit in pairs:
        if isinstance(reference, FinancialResponseArtifactRef):
            evidence = reference.evidence
            dataset_key = evidence.request_scope.dataset_key
            raw_link = audit.extra.get("financial_response_artifact")
            response_hash = evidence.body_sha256
        else:
            dataset_key = reference.dataset_key
            raw_link = audit.extra.get("financial_source_time_artifact")
            response_hash = reference.body_sha256
        if not isinstance(raw_link, dict):
            raise ValueError("REHEARSAL_FINANCIAL_SLICE_RAW_AUDIT_LINK_INVALID")
        raw_provider_id = raw_link.get("provider_id")
        if raw_provider_id != provider_id:
            raise ValueError("REHEARSAL_FINANCIAL_SLICE_RAW_AUDIT_PROVIDER_INVALID")
        captures.append(
            {
                "dataset_key": dataset_key,
                "capture_id": str(reference.capture_id),
                "raw_audit_id": audit.raw_audit_id,
                "raw_audit_count": 1,
                "raw_audit_status": audit.status,
                "raw_audit_provider_id": raw_provider_id,
                "body_sha256": reference.body_sha256,
                "raw_audit_body_sha256": response_hash,
                "body_size_bytes": reference.body_size_bytes,
                "typed_evidence_count": len(verified.facts),
                "witness_coverage_count": len(verified.facts),
            }
        )
    return captures


def _provider_id(provider: ProviderConfig) -> int:
    """Narrow the provider row identity to a positive integer."""

    value = provider.id
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_PROVIDER_INVALID")
    return value


def _read_json_object(path: Path) -> dict[str, object]:
    """Read one bounded JSON object from a regular non-symlink input."""

    if path.is_symlink() or not path.is_file():
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_INPUT_INVALID")
    raw = path.read_bytes()
    if not raw or len(raw) > 16_777_216:
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_INPUT_INVALID")
    try:
        payload: object = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_INPUT_INVALID") from exc
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        raise ValueError("REHEARSAL_FINANCIAL_SLICE_INPUT_INVALID")
    return cast(dict[str, object], payload)


def _write_report(output_dir: Path, payload: dict[str, object]) -> None:
    """Publish one exclusive, fsync-backed JSON report by atomic replacement."""

    output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    report_path = output_dir / "akshare-financial-slice.json"
    temporary_path = output_dir / ".akshare-financial-slice.json.tmp"
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with temporary_path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary_path, report_path)
    if os.name != "nt":
        directory_fd = os.open(output_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def _canonical_sha256(payload: object) -> str:
    """Hash one canonical JSON value without adding defaults or sorting lists."""

    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return _sha256(raw)


def _sha256(value: bytes | str) -> str:
    """Return a lowercase SHA-256 for exact bytes or UTF-8 text."""

    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


__all__ = [
    "collect_akshare_financial_slice_rehearsal",
    "verify_configured_rehearsal_identities",
]
