"""Concrete runtime ports for receipt-gated financial publication workflows."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.utils import timezone

from apps.data_center.akshare_financial_slice_sync_composition import (
    make_sync_akshare_financial_slices_use_case,
)
from apps.data_center.application.financial_publication_capacity import (
    FinancialCapacityBinding,
    FinancialCapacityBindingSource,
    FinancialCapacityBuildIdentitySource,
    FinancialCapacityManifestSnapshot,
    FinancialCapacityManifestSource,
    FinancialCapacitySliceAttempt,
    FinancialCapacitySliceEvidence,
    FinancialCapacitySliceRunner,
    FinancialCapacityWorkflowError,
    FinancialPublicationSlice,
    FinancialWorkflowStage,
)
from apps.data_center.application.financial_scope_capacity_input import (
    FinancialScopeCapacityInput,
    resolve_current_financial_scope_capacity_input,
    validate_capacity_scope_input,
)
from apps.data_center.application.financial_slice_sync import (
    FinancialAnnouncementSlice,
    FinancialSliceSyncRequest,
)
from apps.data_center.composition import (
    get_provider_config_repository,
)
from apps.data_center.infrastructure.akshare_financial_slice_rehearsal import (
    _capture_evidence,
    _RequestSeed,
    _seed_date,
    _verify_persisted_pair,
)
from apps.data_center.infrastructure.akshare_financial_slice_sync import (
    akshare_financial_deployment_region,
    load_akshare_financial_slice_sync_budget,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.financial_capacity_build_identity import (
    FileFinancialCapacityBuildIdentitySource,
)
from apps.data_center.infrastructure.financial_capacity_checkpoint_repository import (
    DjangoFinancialCapacityCheckpointRepository,
)
from apps.data_center.infrastructure.financial_capacity_governance import (
    DjangoFinancialCapacityGovernanceSource,
)
from apps.data_center.infrastructure.financial_capacity_publisher_runtime import (
    AtomicFinancialPolicyV3Publisher,
)
from apps.data_center.infrastructure.financial_decision_evidence_codec import (
    decode_financial_decision_evidence,
)
from apps.data_center.infrastructure.financial_response_artifact_config import (
    resolve_financial_response_artifact_config,
)
from apps.data_center.infrastructure.financial_scope_discovery_governance import (
    DjangoFinancialScopeManifestReviewSource,
)
from apps.data_center.infrastructure.financial_scope_manifest_current_pointer import (
    DjangoFinancialScopeManifestCurrentPointerSource,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    akshare_notice_date_match_contract,
)
from apps.data_center.infrastructure.models import AssetMasterModel, FinancialFactModel
from core.exceptions import DataFetchError, DataValidationError, InvalidInputError

_FINANCIAL_CAPACITY_MANIFEST_CHUNK_SIZE = 1_000
_FINANCIAL_CAPACITY_MAX_TYPED_ROWS_PER_ASSET = 20_000
_FINANCIAL_CAPACITY_MAX_TYPED_CANDIDATES_PER_ASSET = 100
_FINANCIAL_CAPACITY_MAX_TYPED_ROWS_GLOBAL = 600_000


def _canonical_sha256(payload: object) -> str:
    """Return a stable SHA-256 digest for identity material."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class DjangoFinancialCapacityBindingSource(FinancialCapacityBindingSource):
    """Snapshot exact active AKShare, parser, deployment-region, and policy identities."""

    def __init__(
        self,
        *,
        isolation_attestation_sha256: str = "",
        build_identity_source: FinancialCapacityBuildIdentitySource | None = None,
    ) -> None:
        """Bind isolation evidence and the image identity reader for this runtime."""

        self._isolation_attestation_sha256 = isolation_attestation_sha256
        self._build_identity_source = (
            build_identity_source
            or FileFinancialCapacityBuildIdentitySource(Path(settings.AGOM_BUILD_IDENTITY_PATH))
        )

    def snapshot(self, *, environment: str, candidate_sha: str) -> FinancialCapacityBinding:
        """Read all runtime identities; reject ambiguity and policy drift."""

        runtime_source_commit = self._build_identity_source.source_commit()
        if runtime_source_commit != candidate_sha:
            raise FinancialCapacityWorkflowError(
                "financial capacity candidate SHA does not match runtime build identity"
            )
        providers = get_provider_config_repository().get_active_by_type("akshare")
        if len(providers) != 1:
            raise FinancialCapacityWorkflowError(
                "financial capacity requires one exact active AKShare provider"
            )
        provider = providers[0]
        if provider.id is None or provider.is_active is not True:
            raise FinancialCapacityWorkflowError(
                "financial capacity active AKShare provider identity is invalid"
            )
        policy = PublicationPolicyRepository().get_active("equity.financial.fact")
        if policy is None or policy.policy_version != "3":
            raise FinancialCapacityWorkflowError(
                "financial capacity requires the active policy-v3 publication contract"
            )
        contract = akshare_notice_date_match_contract()
        region = akshare_financial_deployment_region()
        if not region or region == "unknown":
            raise FinancialCapacityWorkflowError(
                "financial capacity deployment region is unavailable"
            )
        parser_id = contract.parser_version
        provider_identity = {
            "provider_id": provider.id,
            "provider_name": provider.name,
            "provider_source": provider.source_type,
            "active": provider.is_active,
            "priority": provider.priority,
            "api_endpoint": provider.api_endpoint,
            "http_url": provider.http_url,
            "extra_config": provider.extra_config,
            "credential_ref": provider.credential_ref,
        }
        parser_identity = {
            "parser_id": parser_id,
            "parser_version": contract.parser_version,
            "contract_sha256": contract.contract_sha256,
        }
        return FinancialCapacityBinding(
            environment=environment,
            candidate_sha=candidate_sha,
            provider_id=provider.id,
            provider_name=provider.name,
            provider_source=provider.source_type,
            provider_identity_sha256=_canonical_sha256(provider_identity),
            contract_id=contract.contract_id,
            contract_version=contract.contract_version,
            contract_sha256=contract.contract_sha256,
            parser_id=parser_id,
            parser_sha256=_canonical_sha256(parser_identity),
            deployment_region=region,
            publication_policy_version=policy.policy_version,
            publication_policy_sha256=policy.content_hash,
            isolation_attestation_sha256=(
                self._isolation_attestation_sha256 if environment == "isolated" else ""
            ),
        )


class _DjangoFinancialCapacityManifestReader(FinancialCapacityManifestSource):
    """Freeze one isolated qualification seed or a full isolated/production universe."""

    def freeze(
        self,
        *,
        stage: FinancialWorkflowStage,
        environment: Literal["isolated", "production"],
        binding: FinancialCapacityBinding,
        scope_input: FinancialScopeCapacityInput | None = None,
    ) -> FinancialCapacityManifestSnapshot:
        """Resolve scope from the exact stage and runtime binding without provider egress."""

        expected_environment = "production" if stage == "formal_publication" else "isolated"
        if environment != expected_environment or binding.environment != environment:
            raise FinancialCapacityWorkflowError(
                "financial capacity manifest stage and binding environment do not match"
            )

        active_asset_query = AssetMasterModel._default_manager.filter(
            asset_type="stock",
            exchange__in=("SSE", "SZSE", "BSE"),
            is_active=True,
        ).order_by("code")
        active_codes = tuple(active_asset_query.values_list("code", flat=True))
        if not active_codes:
            raise FinancialCapacityWorkflowError("financial capacity active asset scope is empty")
        active_universe_sha256 = _canonical_sha256(active_codes)
        active_code_set = set(active_codes)
        rows = (
            FinancialFactModel._default_manager.filter(
                asset_code__in=active_asset_query.values("code"),
                source="akshare",
                decision_evidence__schema="financial-fact-decision-evidence.v2",
                available_at__isnull=False,
                available_at__lte=timezone.now(),
            )
            .only(
                "id",
                "asset_code",
                "period_end",
                "report_date",
                "announced_at",
                "available_at",
                "decision_evidence",
                "source_record_id",
                "raw_payload_hash",
                "extra",
            )
            .order_by("asset_code", "-available_at", "-id")
        )
        unresolved_assets = set(active_codes)
        scan_count_by_asset: dict[str, int] = {}
        candidate_identities_by_asset: dict[str, set[tuple[date | None, date | None]]] = {}
        latest_dates: dict[str, date] = {}
        latest_source_identities: dict[str, dict[str, object]] = {}
        latest_source_record_ids: dict[str, str] = {}
        seed_row: tuple[FinancialFactModel, date, str] | None = None
        seed_pair_count = 0
        global_scan_count = 0
        for row in rows.iterator(chunk_size=_FINANCIAL_CAPACITY_MANIFEST_CHUNK_SIZE):
            if row.asset_code not in active_code_set:
                continue
            if stage == "qualification" and seed_row is not None:
                if row.asset_code != seed_row[0].asset_code:
                    break
            elif stage != "qualification" and row.asset_code not in unresolved_assets:
                continue
            scan_count = scan_count_by_asset.get(row.asset_code, 0) + 1
            scan_count_by_asset[row.asset_code] = scan_count
            global_scan_count += 1
            if global_scan_count > _FINANCIAL_CAPACITY_MAX_TYPED_ROWS_GLOBAL:
                raise FinancialCapacityWorkflowError(
                    "financial capacity global typed source-time scan guard exceeded"
                )
            if scan_count > _FINANCIAL_CAPACITY_MAX_TYPED_ROWS_PER_ASSET:
                raise FinancialCapacityWorkflowError(
                    "financial capacity typed source-time scan guard exceeded"
                )
            try:
                announcement_date, basis = _seed_date(row)
            except (DataFetchError, DataValidationError, TypeError, ValueError):
                announcement_date, basis = None, "unavailable"
            candidate_identity = (
                row.report_date if type(row.report_date) is date else None,
                announcement_date if type(announcement_date) is date else None,
            )
            candidate_identities = candidate_identities_by_asset.setdefault(
                row.asset_code,
                set(),
            )
            candidate_identities.add(candidate_identity)
            if len(candidate_identities) > _FINANCIAL_CAPACITY_MAX_TYPED_CANDIDATES_PER_ASSET:
                raise FinancialCapacityWorkflowError(
                    "financial capacity typed announcement candidate guard exceeded"
                )
            if (
                type(announcement_date) is not date
                or not basis.startswith("typed_source_time_")
                or not _typed_announcement_row_matches(row, announcement_date)
            ):
                continue
            typed_row = (row, announcement_date, basis)
            if stage == "qualification":
                if seed_row is None:
                    seed_row = typed_row
                if (
                    row.asset_code == seed_row[0].asset_code
                    and row.report_date == seed_row[1]
                    and announcement_date == seed_row[1]
                ):
                    seed_pair_count += 1
                    if row.id == seed_row[0].id:
                        latest_source_identities[row.asset_code] = _typed_source_identity(row)
                        if row.source_record_id:
                            latest_source_record_ids[row.asset_code] = row.source_record_id
            elif row.asset_code in unresolved_assets:
                latest_dates[row.asset_code] = typed_row[1]
                latest_source_identities[row.asset_code] = _typed_source_identity(row)
                if row.source_record_id:
                    latest_source_record_ids[row.asset_code] = row.source_record_id
                unresolved_assets.remove(row.asset_code)
                candidate_identities_by_asset.pop(row.asset_code, None)
                scan_count_by_asset.pop(row.asset_code, None)
                if not unresolved_assets:
                    break

        if stage == "qualification":
            if seed_row is None:
                raise FinancialCapacityWorkflowError(
                    "financial capacity isolated typed announcement seed is unavailable"
                )
            seed_slice = _verified_isolated_seed(
                seed_row,
                seed_pair_count,
                binding=binding,
            )
            typed_source_snapshot_sha256 = _canonical_sha256(
                [latest_source_identities[seed_slice.asset_code]]
            )
            return FinancialCapacityManifestSnapshot.build(
                slices=(seed_slice,),
                active_universe_sha256=active_universe_sha256,
                typed_source_snapshot_sha256=typed_source_snapshot_sha256,
            )

        if unresolved_assets:
            raise FinancialCapacityWorkflowError(
                "financial capacity typed announcement scope is incomplete"
            )
        slices = tuple(
            FinancialPublicationSlice(
                asset_code=asset_code,
                announcement_date=latest_dates[asset_code],
            )
            for asset_code in active_codes
        )
        frozen_slices = tuple(sorted(slices))
        typed_source_snapshot_sha256 = _canonical_sha256(
            [latest_source_identities[item.asset_code] for item in frozen_slices]
        )
        snapshot = FinancialCapacityManifestSnapshot.build(
            slices=frozen_slices,
            active_universe_sha256=active_universe_sha256,
            typed_source_snapshot_sha256=typed_source_snapshot_sha256,
        )
        if scope_input is not None:
            validate_capacity_scope_input(
                scope_input=scope_input,
                active_asset_codes=active_codes,
                snapshot=snapshot,
                typed_source_record_ids=latest_source_record_ids,
            )
        return snapshot


class DjangoFinancialCapacityManifestSource(FinancialCapacityManifestSource):
    """Freeze workflow input through the current persisted reviewed scope and typed facts."""

    def __init__(self) -> None:
        """Bind the current-pointer reader and persistent dual-review event source."""

        self._reader = _DjangoFinancialCapacityManifestReader()
        self._pointer_source = DjangoFinancialScopeManifestCurrentPointerSource()
        self._review_source = DjangoFinancialScopeManifestReviewSource()

    def freeze(
        self,
        *,
        stage: FinancialWorkflowStage,
        environment: Literal["isolated", "production"],
        binding: FinancialCapacityBinding,
    ) -> FinancialCapacityManifestSnapshot:
        """Require reviewed scope for full capacity/formal stages; keep N=1 qualification separate."""

        if stage == "qualification":
            return self._reader.freeze(
                stage=stage,
                environment=environment,
                binding=binding,
            )
        scope_input = resolve_current_financial_scope_capacity_input(
            pointer_source=self._pointer_source,
            review_source=self._review_source,
            binding=binding,
            environment=environment,
            now=timezone.now(),
        )
        typed_snapshot = self._reader.freeze(
            stage=stage,
            environment=environment,
            binding=binding,
            scope_input=scope_input,
        )
        candidate = scope_input.reviewed_manifest.candidate
        reviewed_scope_snapshot_sha256 = _canonical_sha256(
            {
                "typed_source_snapshot_sha256": typed_snapshot.typed_source_snapshot_sha256,
                "reviewed_scope_manifest_sha256": candidate.manifest_sha256,
                "reviewed_scope_report_sha256": scope_input.report_sha256,
            }
        )
        return FinancialCapacityManifestSnapshot.build(
            slices=typed_snapshot.slices,
            active_universe_sha256=typed_snapshot.active_universe_sha256,
            typed_source_snapshot_sha256=reviewed_scope_snapshot_sha256,
        )


def _typed_source_identity(row: FinancialFactModel) -> dict[str, object]:
    """Return stable typed-fact and dual-artifact IDs for a source revision digest."""

    decision = decode_financial_decision_evidence(row.decision_evidence)
    if decision is None or decision.source_time_witness is None:
        return {
            "fact_id": row.id,
            "asset_code": row.asset_code,
            "report_date": row.report_date.isoformat() if row.report_date is not None else None,
            "available_at": row.available_at.isoformat() if row.available_at is not None else None,
            "synthetic_test_row": True,
        }
    witness = decision.source_time_witness
    source_artifact = witness.artifact_reference
    return {
        "fact_id": row.id,
        "asset_code": row.asset_code,
        "period_end": row.period_end.isoformat(),
        "report_date": row.report_date.isoformat() if row.report_date is not None else None,
        "announced_at": row.announced_at.isoformat() if row.announced_at is not None else None,
        "available_at": row.available_at.isoformat() if row.available_at is not None else None,
        "source_record_id": row.source_record_id,
        "raw_payload_hash": row.raw_payload_hash,
        "financial_capture_id": str(decision.artifact_reference.capture_id),
        "financial_body_sha256": decision.artifact_reference.evidence.body_sha256,
        "source_time_capture_id": str(source_artifact.capture_id),
        "source_time_body_sha256": source_artifact.body_sha256,
    }


def _typed_announcement_row_matches(
    row: FinancialFactModel,
    announcement_date: date,
) -> bool:
    """Require the typed witness to match the exact persisted fact row and contract."""

    decision = decode_financial_decision_evidence(row.decision_evidence)
    if decision is None or decision.source_time_witness is None:
        return False
    witness = decision.source_time_witness
    contract = akshare_notice_date_match_contract()
    financial_artifact = decision.artifact_reference
    source_time_artifact = witness.artifact_reference
    extra = row.extra if isinstance(row.extra, dict) else {}
    return (
        row.available_at is not None
        and row.available_at == witness.available_at
        and row.raw_payload_hash == financial_artifact.evidence.body_sha256
        and row.report_date == announcement_date
        and row.announced_at == witness.announced_at
        and decision.native_asset_code == row.asset_code
        and decision.native_period_end == row.period_end
        and decision.native_row_id == row.source_record_id
        and witness.financial_announced_date == announcement_date
        and witness.native_asset_code == row.asset_code
        and witness.native_period_end == row.period_end
        and witness.financial_native_row_id == row.source_record_id
        and witness.source_timezone == contract.source_timezone
        and witness.governed_match_contract_id == contract.contract_id
        and witness.governed_match_contract_version == contract.contract_version
        and witness.governed_match_contract_sha256 == contract.contract_sha256
        and (
            "financial_response_capture_id" not in extra
            or extra["financial_response_capture_id"] == str(financial_artifact.capture_id)
        )
        and (
            "financial_source_time_capture_id" not in extra
            or extra["financial_source_time_capture_id"] == str(source_time_artifact.capture_id)
        )
        and (
            "financial_source_time_body_sha256" not in extra
            or extra["financial_source_time_body_sha256"] == source_time_artifact.body_sha256
        )
    )


def _verified_isolated_seed(
    seed_row: tuple[FinancialFactModel, date, str],
    pair_row_count: int,
    *,
    binding: FinancialCapacityBinding,
) -> FinancialPublicationSlice:
    """Select and independently reverify one deterministic S6 typed fact pair."""

    if pair_row_count <= 0:
        raise FinancialCapacityWorkflowError(
            "financial capacity isolated typed announcement seed is unavailable"
        )
    row, announcement_date, basis = seed_row

    providers = get_provider_config_repository().get_active_by_type("akshare")
    if len(providers) != 1 or providers[0].id != binding.provider_id:
        raise FinancialCapacityWorkflowError(
            "financial capacity isolated seed provider identity is unavailable"
        )
    artifact_runtime = resolve_financial_response_artifact_config()
    if artifact_runtime is None:
        raise FinancialCapacityWorkflowError(
            "financial capacity isolated seed retained artifacts are unavailable"
        )

    seed = _RequestSeed(
        asset_code=row.asset_code,
        announcement_date=announcement_date,
        basis=basis,
        fact_id_sha256=_canonical_sha256(str(row.id)),
        selection_sha256=_canonical_sha256(
            {
                "candidate_sha": binding.candidate_sha,
                "binding": binding.to_dict(),
                "asset_code": row.asset_code,
                "announcement_date": announcement_date.isoformat(),
                "fact_id_sha256": _canonical_sha256(str(row.id)),
            }
        ),
    )
    try:
        _verify_persisted_pair(
            seed=seed,
            provider=providers[0],
            provider_started_at=datetime.min.replace(tzinfo=UTC),
            stored_count=pair_row_count,
            artifact_root=artifact_runtime.root,
        )
    except (DataFetchError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise FinancialCapacityWorkflowError(
            "financial capacity isolated typed seed failed independent verification"
        ) from exc
    return FinancialPublicationSlice(
        asset_code=row.asset_code,
        announcement_date=announcement_date,
    )


class ControlledAkshareFinancialCapacitySliceRunner(FinancialCapacitySliceRunner):
    """Use only the exact dual-capture AKShare slice use case and inspect persisted evidence."""

    def execute(
        self,
        *,
        binding: FinancialCapacityBinding,
        item: FinancialPublicationSlice,
        run_id: UUID,
    ) -> FinancialCapacitySliceAttempt:
        """Synchronize one pair, then verify bodies, RawAudit links, typed evidence, and write."""

        if binding.provider_source != "akshare" or binding.provider_id <= 0:
            raise FinancialCapacityWorkflowError(
                "financial capacity slice requires the bound AKShare provider"
            )
        budget = load_akshare_financial_slice_sync_budget()
        if budget is None:
            raise DataFetchError(
                "financial capacity request budget is unavailable",
                code="financial_sync_request_budget_unavailable",
            )
        provider_repository = get_provider_config_repository()
        provider = provider_repository.get_by_id(binding.provider_id)
        if (
            provider is None
            or provider.id != binding.provider_id
            or provider.is_active is not True
            or provider.source_type != "akshare"
        ):
            raise DataFetchError(
                "financial capacity exact AKShare provider row is unavailable",
                code="exact_active_akshare_provider_required",
            )
        if type(run_id) is not UUID:
            raise DataFetchError(
                "financial capacity workflow run identity is invalid",
                code="financial_capacity_workflow_run_identity_invalid",
            )
        started_at = datetime.now(UTC)
        started_tick = time.monotonic_ns()
        use_case = make_sync_akshare_financial_slices_use_case(max_route_attempts=1)
        result = use_case.execute(
            FinancialSliceSyncRequest(
                provider_id=binding.provider_id,
                source="akshare",
                slices=(
                    FinancialAnnouncementSlice(
                        item.asset_code,
                        item.announcement_date,
                    ),
                ),
                period_limit=budget.max_period_rows_per_capture,
                run_id=run_id,
            )
        )
        duration_ms = max(0, (time.monotonic_ns() - started_tick) // 1_000_000)
        evidence: FinancialCapacitySliceEvidence | None = None
        try:
            if result.outcome == "success":
                artifact_runtime = resolve_financial_response_artifact_config()
                if artifact_runtime is None:
                    raise DataFetchError(
                        "financial capacity retained body configuration is unavailable",
                        code="financial_response_artifact_config_invalid",
                    )
                seed = _RequestSeed(
                    asset_code=item.asset_code,
                    announcement_date=item.announcement_date,
                    basis="frozen_capacity_manifest",
                    fact_id_sha256=_canonical_sha256(
                        {
                            "asset_code": item.asset_code,
                            "announcement_date": item.announcement_date.isoformat(),
                        }
                    ),
                    selection_sha256=_canonical_sha256(
                        {
                            "candidate_sha": binding.candidate_sha,
                            "provider_identity_sha256": binding.provider_identity_sha256,
                            "manifest_slice": {
                                "asset_code": item.asset_code,
                                "announcement_date": item.announcement_date.isoformat(),
                            },
                        }
                    ),
                )
                verified = _verify_persisted_pair(
                    seed=seed,
                    provider=provider,
                    provider_started_at=started_at,
                    stored_count=result.stored,
                    artifact_root=artifact_runtime.root,
                )
                captures = _capture_evidence(verified, provider_id=binding.provider_id)
                if len(captures) != 2:
                    raise DataFetchError(
                        "financial capacity raw capture evidence is incomplete",
                        code="financial_capacity_capture_evidence_invalid",
                    )
                financial_capture, source_time_capture = captures
                evidence = FinancialCapacitySliceEvidence(
                    asset_code=item.asset_code,
                    announcement_date=item.announcement_date,
                    financial_body_sha256=_text(financial_capture, "body_sha256"),
                    source_time_body_sha256=_text(source_time_capture, "body_sha256"),
                    financial_body_size_bytes=_integer(financial_capture, "body_size_bytes"),
                    source_time_body_size_bytes=_integer(source_time_capture, "body_size_bytes"),
                    financial_capture_id=_text(financial_capture, "capture_id"),
                    source_time_capture_id=_text(source_time_capture, "capture_id"),
                    financial_raw_audit_id=_text(financial_capture, "raw_audit_id"),
                    source_time_raw_audit_id=_text(source_time_capture, "raw_audit_id"),
                    financial_raw_audit_count=_integer(financial_capture, "raw_audit_count"),
                    source_time_raw_audit_count=_integer(source_time_capture, "raw_audit_count"),
                    typed_financial_evidence_count=_integer(
                        financial_capture,
                        "typed_evidence_count",
                    ),
                    source_time_witness_count=_integer(
                        source_time_capture,
                        "witness_coverage_count",
                    ),
                    atomic_fact_write_count=result.atomic_fact_write_count,
                    stored=result.stored,
                    duration_ms=duration_ms,
                )
        except (
            DataFetchError,
            DataValidationError,
            InvalidInputError,
            IndexError,
            KeyError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return FinancialCapacitySliceAttempt(
                result=result,
                evidence=None,
                observed_provider_requests=result.observed_provider_requests,
                duration_ms=duration_ms,
                error_code="financial_capacity_post_write_evidence_invalid",
            )
        return FinancialCapacitySliceAttempt(
            result=result,
            evidence=evidence,
            observed_provider_requests=result.observed_provider_requests,
            duration_ms=duration_ms,
            error_code=result.failure_reason or "",
        )


def _text(payload: dict[str, object], key: str) -> str:
    """Require one exact non-empty evidence string."""

    value = payload.get(key)
    if type(value) is not str or not value:
        raise FinancialCapacityWorkflowError(
            f"financial capacity capture evidence {key} is invalid"
        )
    return value


def _integer(payload: dict[str, object], key: str) -> int:
    """Require one exact non-negative evidence count."""

    value = payload.get(key)
    if type(value) is not int or value < 0:
        raise FinancialCapacityWorkflowError(
            f"financial capacity capture evidence {key} is invalid"
        )
    return value


def make_django_financial_capacity_ports(
    *,
    isolation_attestation_sha256: str = "",
    build_identity_source: FinancialCapacityBuildIdentitySource | None = None,
) -> tuple[
    DjangoFinancialCapacityCheckpointRepository,
    DjangoFinancialCapacityBindingSource,
    DjangoFinancialCapacityManifestSource,
    ControlledAkshareFinancialCapacitySliceRunner,
    AtomicFinancialPolicyV3Publisher,
    DjangoFinancialCapacityGovernanceSource,
    DjangoFinancialCapacityGovernanceSource,
    DjangoFinancialCapacityGovernanceSource,
]:
    """Build the DB-backed production workflow ports without executing provider calls."""

    governance_source = DjangoFinancialCapacityGovernanceSource()
    return (
        DjangoFinancialCapacityCheckpointRepository(),
        DjangoFinancialCapacityBindingSource(
            isolation_attestation_sha256=isolation_attestation_sha256,
            build_identity_source=build_identity_source,
        ),
        DjangoFinancialCapacityManifestSource(),
        ControlledAkshareFinancialCapacitySliceRunner(),
        AtomicFinancialPolicyV3Publisher(),
        governance_source,
        governance_source,
        governance_source,
    )


__all__ = [
    "AtomicFinancialPolicyV3Publisher",
    "ControlledAkshareFinancialCapacitySliceRunner",
    "DjangoFinancialCapacityBindingSource",
    "DjangoFinancialCapacityManifestSource",
    "make_django_financial_capacity_ports",
]
