"""Read-only PostgreSQL and real-provider composition for market rehearsals."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from django.db import connection, transaction

from apps.data_center.application.market_calendar import latest_completed_cn_market_session
from apps.data_center.application.market_provider_rehearsal import (
    assess_market_probe,
    rehearsal_digest,
    select_rehearsal_sample,
)
from apps.data_center.application.query_services import list_active_stock_codes_for_backfill
from apps.data_center.composition import get_provider_registry
from apps.data_center.domain.contracts import PublicationPolicy
from apps.data_center.domain.entities import QuoteSnapshot, ValuationFact
from apps.data_center.domain.protocols import (
    CurrentValuationBatchProviderProtocol,
    SessionQuoteBatchProviderProtocol,
)
from apps.data_center.domain.publication_policy_identity import publication_policy_content_hash
from core.exceptions import AgomTradeProException, DataFetchError

from .rehearsal_http_capture import RehearsalHttpCapture
from .rehearsal_identity import (
    RehearsalProviderIdentity,
    parse_rehearsal_identities,
    rehearsal_identities_digest,
    verify_configured_rehearsal_identities,
)
from .rehearsal_response_store import RehearsalResponseContext, RehearsalResponseStore


@runtime_checkable
class _SourceIdentity(Protocol):
    def provider_source(self) -> str: ...


def market_rehearsal_source_digest(root: Path) -> str:
    """Bind actual provider/application source and dependency manifests inside the candidate."""
    if any(not (root / directory).is_dir() for directory in ("apps", "core", "shared")):
        raise ValueError("candidate source tree is incomplete")
    files = sorted(
        path
        for directory in ("apps", "core", "shared")
        for path in (root / directory).rglob("*.py")
        if "__pycache__" not in path.parts
    )
    files.extend(root / name for name in ("pyproject.toml", "requirements-prod.txt"))
    if not files or any(not path.is_file() for path in files):
        raise ValueError("candidate source tree is incomplete")
    manifest = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    return rehearsal_digest(manifest)


def verify_candidate_source(root: Path, candidate_sha: str) -> str:
    """Bind evidence to either the image build identity or a clean exact Git checkout."""
    identity_path = root / ".agom-build-identity.json"
    if identity_path.is_file():
        try:
            payload: object = json.loads(identity_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("REHEARSAL_CANDIDATE_SOURCE_INVALID") from exc
        if not isinstance(payload, dict) or payload.get("source_commit") != candidate_sha:
            raise ValueError("REHEARSAL_CANDIDATE_SOURCE_MISMATCH")
        release_manifest_value = os.environ.get("AGOM_RELEASE_MANIFEST_PATH", "").strip()
        runtime_image_id = os.environ.get("AGOM_CANDIDATE_IMAGE_ID", "").strip()
        if (
            not release_manifest_value
            or re.fullmatch(r"sha256:[0-9a-f]{64}", runtime_image_id) is None
        ):
            raise ValueError("REHEARSAL_CANDIDATE_SOURCE_UNATTESTED")
        release_manifest_path = Path(release_manifest_value)
        if not release_manifest_path.is_absolute():
            release_manifest_path = root / release_manifest_path
        if release_manifest_path.is_symlink() or not release_manifest_path.is_file():
            raise ValueError("REHEARSAL_CANDIDATE_SOURCE_UNATTESTED")
        try:
            release_payload: object = json.loads(release_manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("REHEARSAL_CANDIDATE_SOURCE_INVALID") from exc
        if (
            not isinstance(release_payload, dict)
            or release_payload.get("source_commit") != candidate_sha
            or release_payload.get("image_id") != runtime_image_id
        ):
            raise ValueError("REHEARSAL_CANDIDATE_SOURCE_MISMATCH")
        return "image_release_manifest"
    if not (root / ".git").exists():
        raise ValueError("REHEARSAL_CANDIDATE_SOURCE_UNATTESTED")
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("REHEARSAL_CANDIDATE_SOURCE_UNATTESTED") from exc
    if head != candidate_sha:
        raise ValueError("REHEARSAL_CANDIDATE_SOURCE_MISMATCH")
    if status:
        raise ValueError("REHEARSAL_CANDIDATE_SOURCE_DIRTY")
    return "clean_git_checkout"


def verify_candidate_release_image(root: Path, candidate_sha: str) -> tuple[str, str]:
    """Require a candidate source attestation backed by the exact runtime image digest."""

    attestation = verify_candidate_source(root, candidate_sha)
    image_id = os.environ.get("AGOM_CANDIDATE_IMAGE_ID", "").strip()
    if (
        attestation != "image_release_manifest"
        or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
    ):
        raise ValueError("REHEARSAL_CANDIDATE_IMAGE_UNATTESTED")
    return attestation, image_id


def canonical_publication_policy_evidence(policy: PublicationPolicy) -> dict[str, object]:
    """Return JSON-safe canonical content, digest and identity for a publication policy."""

    content: dict[str, object] = {
        "encoding": "publication-policy-v1",
        "dataset_key": policy.dataset.value,
        "contract_version": policy.dataset.contract_version,
        "schema_version": policy.dataset.schema_version,
        "policy_version": policy.policy_version,
        "minimum_coverage_ratio": float(policy.minimum_coverage_ratio),
        "allow_partial": policy.allow_partial,
        "conflict_action": policy.conflict_action,
        "required_evidence": list(policy.required_evidence),
        "retention_days": policy.retention_days,
    }
    content_hash = publication_policy_content_hash(policy)
    return {
        "content": content,
        "content_sha256": content_hash,
        "identity": policy.identity,
    }


def _probe(
    *,
    dataset: Literal["equity.quote.snapshot", "equity.valuation.fact"],
    fetch: Callable[[], list[QuoteSnapshot] | list[ValuationFact]],
    sample: tuple[str, ...],
    target_date: date,
    capture: RehearsalHttpCapture,
    response_context: RehearsalResponseContext | None = None,
    receipt_start: int | None = None,
    receipt_end: int | None = None,
    captured_started_at: datetime | None = None,
    captured_finished_at: datetime | None = None,
) -> dict[str, object]:
    if (captured_started_at is None) != (captured_finished_at is None):
        raise ValueError("captured probe clocks must be provided together")
    started = captured_started_at or datetime.now(UTC)
    first_receipt = len(capture.receipts) if receipt_start is None else receipt_start
    facts: list[QuoteSnapshot] | list[ValuationFact] = []
    try:
        if captured_started_at is not None:
            facts = fetch()
        else:
            with (
                capture.provider_probe(response_context)
                if response_context is not None
                else nullcontext()
            ):
                facts = fetch()
        finished = captured_finished_at or datetime.now(UTC)
        result = assess_market_probe(
            dataset=dataset,
            facts=facts,
            sample=sample,
            target_date=target_date,
            started_at=started,
            finished_at=finished,
        )
    except (AgomTradeProException, OSError, RuntimeError, ValueError, TypeError) as exc:
        # Provider exception text may contain transport credentials. Keep it out of artifacts.
        error_code = (
            exc.code
            if isinstance(exc, AgomTradeProException)
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,127}", exc.code)
            else "REHEARSAL_PROVIDER_FAILED"
        )
        result = {
            "dataset": dataset,
            "outcome": "failed",
            "requested": len(sample),
            "succeeded": 0,
            "failed": len(sample),
            "stored": 0,
            "issues": [{"code": error_code}],
            "started_at": started.isoformat(),
            "finished_at": (captured_finished_at or datetime.now(UTC)).isoformat(),
            "publication_updated": False,
        }
    last_receipt = len(capture.receipts) if receipt_end is None else receipt_end
    receipts = capture.receipts[first_receipt:last_receipt]
    result["receipt_indexes"] = list(range(first_receipt, last_receipt))
    if not any(
        receipt.status_code == 200 and receipt.body_bytes > 0 and not receipt.error_code
        for receipt in receipts
    ):
        result["outcome"] = "blocked"
        result["transport_error_code"] = "REHEARSAL_REAL_RESPONSE_MISSING"
    if any(receipt.error_code for receipt in receipts):
        result["outcome"] = "blocked"
        result["transport_error_code"] = "REHEARSAL_TRANSPORT_FAILURE"
    if response_context is not None and (
        not receipts or any(receipt.response_artifact is None for receipt in receipts)
    ):
        result["outcome"] = "blocked"
        result["transport_error_code"] = "REHEARSAL_RETAINED_RESPONSE_MISSING"
    response_hashes = {receipt.body_sha256 for receipt in receipts if receipt.body_sha256}
    if any(
        isinstance(fact, ValuationFact) and fact.raw_payload_hash not in response_hashes
        for fact in facts
    ):
        result["outcome"] = "blocked"
        result["transport_error_code"] = "REHEARSAL_SOURCE_RESPONSE_MISMATCH"
    return result


def run_market_provider_rehearsal(
    *,
    quote_provider_id: int,
    valuation_provider_id: int,
    candidate_sha: str,
    source_root: Path,
    target_trade_date: date | None = None,
    sample_size: int = 50,
    max_dispatches: int = 100,
    max_seconds: float = 180.0,
    response_evidence_root: Path | None = None,
    provider_identities: tuple[RehearsalProviderIdentity, ...] | None = None,
    max_response_bytes: int = 8_000_000,
    max_total_response_bytes: int = 32_000_000,
) -> dict[str, object]:
    """Probe configured live providers in a database-enforced read-only transaction.

    This command reports provider-read evidence only. Release eligibility also
    requires independent capacity, source-unit, staging-write and regression
    evidence; the probe must never substitute for that combined gate.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", candidate_sha):
        raise ValueError("candidate_sha must be a full lowercase commit SHA")
    if (response_evidence_root is None) != (provider_identities is None):
        raise ValueError("REHEARSAL_RETENTION_CONTEXT_REQUIRED")
    identities: dict[str, RehearsalProviderIdentity] = {}
    identity_digest = ""
    if provider_identities is not None:
        checked = parse_rehearsal_identities([asdict(value) for value in provider_identities])
        identities = {identity.role: identity for identity in checked}
        if any(identity.source != "tushare" for identity in checked):
            raise ValueError("REHEARSAL_RESPONSE_FORMAT_UNSUPPORTED")
        if (
            identities["quote"].provider_id != quote_provider_id
            or identities["valuation"].provider_id != valuation_provider_id
        ):
            raise ValueError("REHEARSAL_PROVIDER_IDENTITY_MISMATCH")
        verify_configured_rehearsal_identities(checked)
        identity_digest = rehearsal_identities_digest(checked)
    if connection.vendor != "postgresql" or connection.in_atomic_block:
        raise DataFetchError(
            "Rehearsal requires a fresh PostgreSQL transaction",
            code="REHEARSAL_READ_ONLY_UNAVAILABLE",
        )
    if min(quote_provider_id, valuation_provider_id) <= 0:
        raise ValueError("explicit configured provider ids are required")
    started = datetime.now(UTC)
    source_attestation, candidate_image_id = verify_candidate_release_image(
        source_root, candidate_sha
    )
    source_digest = market_rehearsal_source_digest(source_root)
    response_store = (
        RehearsalResponseStore(
            response_evidence_root,
            max_responses=max_dispatches,
            max_response_bytes=max_response_bytes,
            max_total_bytes=max_total_response_bytes,
        )
        if response_evidence_root is not None
        else None
    )
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", ["30000"])
        registered_universe = tuple(sorted(set(list_active_stock_codes_for_backfill())))
        universe = registered_universe
        sample: tuple[str, ...] = ()
        eligible_universe: tuple[str, ...] = ()
        excluded_universe: tuple[str, ...] = ()
        valuation_missing_target_session_codes: tuple[str, ...] = ()
        valuation_policy_identity = ""
        valuation_minimum_coverage_ratio: float | None = None
        valuation_policy_sha256 = ""
        valuation_policy_snapshot: dict[str, object] | None = None
        valuation_scope: list[ValuationFact] = []
        valuation_scope_context: RehearsalResponseContext | None = None
        valuation_receipt_start = 0
        valuation_receipt_end = 0
        valuation_call_started: datetime | None = None
        valuation_call_finished: datetime | None = None
        target_date: date | None = target_trade_date
        stage_error_code = ""
        probes: list[dict[str, object]] = []
        capture = (
            RehearsalHttpCapture(max_dispatches=max_dispatches, max_seconds=max_seconds)
            if response_store is None
            else RehearsalHttpCapture(
                max_dispatches=max_dispatches,
                max_seconds=max_seconds,
                max_body_bytes=max_response_bytes,
                response_store=response_store,
            )
        )
        with capture:
            if target_date is None:
                try:
                    target_date = latest_completed_cn_market_session(started)
                except (
                    AgomTradeProException,
                    OSError,
                    PermissionError,
                    RuntimeError,
                    TypeError,
                    ValueError,
                ):
                    stage_error_code = "REHEARSAL_CALENDAR_UNAVAILABLE"
            if target_date is None:
                stage_error_code = stage_error_code or "REHEARSAL_SESSION_UNAVAILABLE"
            elif not stage_error_code:
                try:
                    registry = get_provider_registry()
                    quotes = registry.get_by_id(quote_provider_id)
                    valuations = registry.get_by_id(valuation_provider_id)
                except (
                    AgomTradeProException,
                    OSError,
                    PermissionError,
                    RuntimeError,
                    TypeError,
                    ValueError,
                ):
                    stage_error_code = "REHEARSAL_PROVIDER_SETUP_FAILED"
                    quotes = None
                    valuations = None
                if not isinstance(quotes, SessionQuoteBatchProviderProtocol) or not isinstance(
                    valuations, CurrentValuationBatchProviderProtocol
                ):
                    stage_error_code = stage_error_code or "REHEARSAL_PROVIDER_UNAVAILABLE"
                elif identities and any(
                    not isinstance(provider, _SourceIdentity)
                    or provider.provider_source() != identities[role].source
                    for role, provider in (("quote", quotes), ("valuation", valuations))
                ):
                    stage_error_code = "REHEARSAL_PROVIDER_IDENTITY_MISMATCH"
                else:
                    try:
                        assert target_date is not None
                        valuation_scope_context = (
                            RehearsalResponseContext(
                                candidate_sha=candidate_sha,
                                target_trade_date=target_date.isoformat(),
                                universe_sha256=rehearsal_digest(universe),
                                provider_identities_sha256=identity_digest,
                                provider_id=identities["valuation"].provider_id,
                                provider_source=identities["valuation"].source,
                                endpoint_id=identities["valuation"].endpoint_id,
                                dataset="equity.valuation.fact",
                                sample_codes=registered_universe,
                            )
                            if identities
                            else None
                        )
                        valuation_receipt_start = len(capture.receipts)
                        valuation_call_started = datetime.now(UTC)
                        with (
                            capture.provider_probe(valuation_scope_context)
                            if valuation_scope_context is not None
                            else nullcontext()
                        ):
                            valuation_scope = valuations.fetch_current_valuations(
                                list(registered_universe), target_date
                            )
                        valuation_call_finished = datetime.now(UTC)
                        valuation_receipt_end = len(capture.receipts)
                        requested = set(registered_universe)
                        returned = [fact.asset_code for fact in valuation_scope]
                        eligible_universe = tuple(
                            sorted(
                                fact.asset_code
                                for fact in valuation_scope
                                if fact.val_date == target_date
                            )
                        )
                        if (
                            not eligible_universe
                            or len(returned) != len(set(returned))
                            or len(eligible_universe) != len(set(eligible_universe))
                            or not set(returned).issubset(requested)
                        ):
                            raise ValueError("invalid valuation eligibility scope")
                        valuation_missing_target_session_codes = tuple(
                            sorted(requested - set(eligible_universe))
                        )
                        from .publication_policy_repository import (
                            PublicationPolicyRepository,
                        )

                        policy = PublicationPolicyRepository().get_active("equity.valuation.fact")
                        if policy is None:
                            raise ValueError("valuation policy unavailable")
                        valuation_policy_identity = policy.identity
                        valuation_minimum_coverage_ratio = policy.minimum_coverage_ratio
                        valuation_policy_snapshot = canonical_publication_policy_evidence(policy)
                        valuation_policy_sha256 = str(valuation_policy_snapshot["content_sha256"])
                        if valuation_missing_target_session_codes:
                            eligible_universe = ()
                            sample = ()
                            stage_error_code = "REHEARSAL_VALUATION_SCOPE_INCOMPLETE"
                        elif len(eligible_universe) != len(registered_universe):
                            raise ValueError("valuation target-session scope is incomplete")
                        elif len(eligible_universe) / len(registered_universe) < (
                            policy.minimum_coverage_ratio
                        ):
                            raise ValueError("valuation coverage below active policy")
                        else:
                            eligible_universe = registered_universe
                            sample = select_rehearsal_sample(eligible_universe, sample_size)
                    except (
                        AgomTradeProException,
                        OSError,
                        PermissionError,
                        RuntimeError,
                        TypeError,
                        ValueError,
                    ):
                        stage_error_code = "REHEARSAL_ELIGIBLE_SCOPE_UNAVAILABLE"

                    def response_context(
                        role: str,
                        dataset: Literal["equity.quote.snapshot", "equity.valuation.fact"],
                    ) -> RehearsalResponseContext | None:
                        if not identities:
                            return None
                        identity = identities[role]
                        assert target_date is not None
                        return RehearsalResponseContext(
                            candidate_sha=candidate_sha,
                            target_trade_date=target_date.isoformat(),
                            universe_sha256=rehearsal_digest(universe),
                            provider_identities_sha256=identity_digest,
                            provider_id=identity.provider_id,
                            provider_source=identity.source,
                            endpoint_id=identity.endpoint_id,
                            dataset=dataset,
                            sample_codes=sample,
                        )

                    if not stage_error_code:
                        sampled_valuations = [
                            fact for fact in valuation_scope if fact.asset_code in sample
                        ]
                        probes = [
                            _probe(
                                dataset="equity.valuation.fact",
                                fetch=lambda: sampled_valuations,
                                sample=sample,
                                target_date=target_date,
                                capture=capture,
                                response_context=valuation_scope_context,
                                receipt_start=valuation_receipt_start,
                                receipt_end=valuation_receipt_end,
                                captured_started_at=valuation_call_started,
                                captured_finished_at=valuation_call_finished,
                            ),
                            _probe(
                                dataset="equity.quote.snapshot",
                                fetch=lambda: quotes.fetch_quote_snapshots_for_session(
                                    list(sample), target_date
                                ),
                                sample=sample,
                                target_date=target_date,
                                capture=capture,
                                response_context=response_context("quote", "equity.quote.snapshot"),
                            ),
                        ]
        transport = capture.to_dict()
        within_budget = time.monotonic() - capture.started <= max_seconds
    if provider_identities is not None:
        verify_configured_rehearsal_identities(checked)
    source_unchanged = source_digest == market_rehearsal_source_digest(source_root)
    final_attestation, final_image_id = verify_candidate_release_image(source_root, candidate_sha)
    if final_attestation != source_attestation or final_image_id != candidate_image_id:
        raise ValueError("REHEARSAL_CANDIDATE_IMAGE_CHANGED")
    outcome = (
        "success"
        if within_budget
        and source_unchanged
        and not stage_error_code
        and len(probes) == 2
        and all(probe["outcome"] == "success" for probe in probes)
        else "blocked"
    )
    return {
        "schema": "market.provider-rehearsal.v1",
        "mode": "read_only_live_provider",
        "candidate_sha": candidate_sha,
        "candidate_image_id": candidate_image_id,
        "source_tree_sha256": source_digest,
        "candidate_source_attestation": source_attestation,
        "source_unchanged": source_unchanged,
        "outcome": outcome,
        "release_ready": False,
        "remaining_release_gates": [
            "real_response_unit_replay",
            "full_universe_capacity",
            "isolated_write_rehearsal",
            "candidate_regression_evidence",
        ],
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "target_trade_date": target_date.isoformat() if target_date is not None else None,
        "stage_error_code": stage_error_code,
        "universe_count": len(universe),
        "registered_universe_count": len(registered_universe),
        "asset_codes": list(universe),
        "universe_sha256": rehearsal_digest(universe),
        "eligible_asset_codes": list(eligible_universe),
        "eligible_asset_count": len(eligible_universe),
        "excluded_asset_codes": list(excluded_universe),
        "excluded_asset_count": len(excluded_universe),
        "valuation_missing_target_session_codes": list(valuation_missing_target_session_codes),
        "valuation_policy_identity": valuation_policy_identity,
        "valuation_policy_sha256": valuation_policy_sha256,
        "valuation_policy_snapshot": valuation_policy_snapshot,
        "valuation_minimum_coverage_ratio": valuation_minimum_coverage_ratio,
        "sample": list(sample),
        "sample_sha256": rehearsal_digest(sample),
        "sample_size": len(sample),
        "quote_provider_id": quote_provider_id,
        "provider_identities": [asdict(identity) for identity in (provider_identities or ())],
        "provider_identities_sha256": identity_digest,
        "response_retention_enabled": response_store is not None,
        "valuation_provider_id": valuation_provider_id,
        "probes": probes,
        "transport": transport,
        "stored": 0,
        "publication_updated": False,
        "database_read_only": True,
        "capacity_estimate": None,
        "capacity_note": "Transport dispatches are measured; vendor quota, full-scale locks and write cost need separate evidence.",
    }
