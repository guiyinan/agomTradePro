"""Provider-to-fact synchronization use cases for Data Center."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, cast

from apps.data_center.application.dtos import (
    MacroFailoverDecision,
    SyncFinancialRequest,
    SyncFundNavRequest,
    SyncResult,
    SyncSectorMembershipRequest,
    SyncValuationRequest,
)
from apps.data_center.domain.entities import (
    FinancialFact,
    ProviderConfig,
    RawAudit,
)
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_source_evidence import FinancialFactDecisionEvidence
from apps.data_center.domain.protocols import (
    FinancialFactRepositoryProtocol,
    FundNavRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    RawAuditRepositoryProtocol,
    SectorMembershipRepositoryProtocol,
    UnifiedDataProviderProtocol,
    ValuationFactRepositoryProtocol,
)
from core.exceptions import InvalidInputError

from .batch_identity import ProviderAssetIdentityError, require_single_asset_identity
from .provider_health_recorder import persist_provider_health_metric
from .publication_sync import (
    PublishFinancialBatchUseCase,
    PublishFundNavBatchUseCase,
    PublishSectorMembershipBatchUseCase,
    PublishValuationBatchUseCase,
)
from .sync_transaction import (
    DataProviderHealthAuditWriter,
)

if TYPE_CHECKING:
    from .sync_macro_use_cases import (
        MacroFailoverPolicy,
        MacroFailoverPolicyProvider,
        PreparedMacroSync,
        SyncMacroBatchUseCase,
        SyncMacroUseCase,
    )
    from .sync_market_use_cases import SyncPriceUseCase, SyncQuoteUseCase
    from .sync_news_capital_use_cases import SyncCapitalFlowUseCase, SyncNewsUseCase

FactT = TypeVar("FactT")


class FinancialResponseArtifactVerifier(Protocol):
    """Read-only port proving that a typed response reference is retained and audited."""

    def __call__(
        self,
        provider: ProviderConfig,
        reference: FinancialResponseArtifactRef,
    ) -> bool:
        """Return whether the exact encrypted body and matching audit link exist."""


class FinancialSourceTimeArtifactVerifier(Protocol):
    """Read-only port proving that an independent source-time artifact is retained."""

    def __call__(
        self,
        provider: ProviderConfig,
        evidence: FinancialFactDecisionEvidence,
    ) -> bool:
        """Recompute the exact unique row match from retained bodies and its contract."""


RECOVERABLE_DATA_CENTER_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
    ProviderAssetIdentityError,
    InvalidInputError,
)


def _sync_status(stored_count: int) -> tuple[str, str]:
    """Return audit and DTO status without treating zero writes as success."""

    if stored_count > 0:
        return "ok", "success"
    return "noop", "noop"


def _publication_attempt_hash(
    *,
    dataset_key: str,
    publication_key: str,
    provider_name: str,
    run_id: str,
    ingested_run_id: str,
    blocked_reason: str,
) -> str:
    """Hash one blocked publication attempt without exception text."""

    payload = {
        "blocked_reason": blocked_reason,
        "dataset_key": dataset_key,
        "ingested_run_id": ingested_run_id,
        "provider_name": provider_name,
        "publication_key": publication_key,
        "run_id": run_id,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(
        b"agomtradepro:data-center:publication-attempt:v1\0" + encoded
    ).hexdigest()


def _build_sync_audit(
    provider_name: str,
    capability: str,
    request_params: Mapping[str, object],
    status: str,
    row_count: int,
    latency_ms: float,
    error_message: str = "",
    *,
    fetched_at: datetime | None = None,
    run_id: str = "",
    ingested_run_id: str = "",
) -> RawAudit:
    params_hash = hashlib.sha256(
        json.dumps(dict(request_params), ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()
    return RawAudit(
        provider_name=provider_name,
        capability=capability,
        request_params=dict(request_params),
        status=status,
        row_count=row_count,
        latency_ms=latency_ms,
        error_message=error_message,
        fetched_at=fetched_at or datetime.now(UTC),
        request_params_hash=params_hash,
        redacted=True,
        payload_size_bytes=0,
        run_id=run_id,
        ingested_run_id=ingested_run_id,
    )


class _BaseSyncUseCase:
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        *,
        data_provider_health_audit_writer: DataProviderHealthAuditWriter | None = None,
    ) -> None:
        self._provider_repo = provider_repo
        self._provider_registry = provider_registry
        self._raw_audit_repo = raw_audit_repo
        self._data_provider_health_audit_writer = data_provider_health_audit_writer

    def _get_provider(self, provider_id: int) -> tuple[ProviderConfig, UnifiedDataProviderProtocol]:
        config = self._provider_repo.get_by_id(provider_id)
        if config is None:
            raise ValueError(f"Provider not found: {provider_id}")
        provider = self._provider_registry.get_by_id(provider_id)
        if provider is None:
            raise ValueError(f"Provider adapter unavailable: {provider_id}")
        return config, provider

    @staticmethod
    def _normalize_fact_source(
        fact: FactT,
        *,
        source_type: str,
        provider_name: str,
    ) -> FactT:
        updates: dict[str, Any] = {"source": source_type}
        if hasattr(fact, "extra"):
            next_extra = dict(getattr(fact, "extra", {}) or {})
            next_extra["source_type"] = source_type
            next_extra.setdefault("provider_name", provider_name)
            updates["extra"] = next_extra
        return cast(FactT, dataclasses.replace(cast(Any, fact), **updates))

    @classmethod
    def _normalize_fact_sources(
        cls,
        facts: list[FactT],
        *,
        source_type: str,
        provider_name: str,
    ) -> list[FactT]:
        return [
            cls._normalize_fact_source(
                fact,
                source_type=source_type,
                provider_name=provider_name,
            )
            for fact in facts
        ]

    def _persist_provider_health_metric(
        self,
        config: ProviderConfig,
        *,
        capability: str,
        latency_ms: float,
        success: bool,
        error: str = "",
        recorded_at: datetime | None = None,
        output_count: int | None = None,
        run_id: str | None = None,
        ingested_run_id: str | None = None,
    ) -> None:
        persist_provider_health_metric(
            self._provider_repo,
            self._provider_registry,
            config,
            capability=capability,
            latency_ms=latency_ms,
            success=success,
            error=error,
            recorded_at=recorded_at,
            output_count=output_count,
            audit_writer=self._data_provider_health_audit_writer,
            run_id=run_id,
            ingested_run_id=ingested_run_id,
        )

    def _record_outcome(
        self,
        config: ProviderConfig,
        *,
        provider_name: str,
        capability: str,
        request_params: Mapping[str, object],
        status: str,
        row_count: int,
        latency_ms: float,
        error_message: str = "",
    ) -> None:
        """Persist one consistent health and raw-audit outcome."""
        if status == "noop" and not error_message:
            error_message = "provider completed without output"
        self._persist_provider_health_metric(
            config,
            capability=capability,
            latency_ms=latency_ms,
            success=status == "ok",
            error=error_message,
            output_count=row_count,
        )
        self._raw_audit_repo.log(
            _build_sync_audit(
                provider_name,
                capability,
                request_params,
                status,
                row_count,
                latency_ms,
                error_message,
            )
        )


class SyncFundNavUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: FundNavRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishFundNavBatchUseCase | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._publication_publisher = publication_publisher

    def execute(self, request: SyncFundNavRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        params = {
            "fund_code": request.fund_code,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
        }
        try:
            facts = provider.fetch_fund_nav(request.fund_code, request.start, request.end)
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            stored_count = self._facts.bulk_upsert(facts)
            if self._publication_publisher is not None and facts:
                self._publication_publisher.execute(
                    facts,
                    provider_name=provider.provider_name(),
                )
            audit_status, result_status = _sync_status(stored_count)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="fund_nav",
                request_params=params,
                status=audit_status,
                row_count=stored_count,
                latency_ms=latency_ms,
            )
            return SyncResult("fund_nav", provider.provider_name(), stored_count, result_status)
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="fund_nav",
                request_params=params,
                status="error",
                row_count=0,
                latency_ms=latency_ms,
                error_message=str(exc),
            )
            raise


@dataclasses.dataclass(frozen=True, slots=True)
class FinancialSourceEvidenceProbeResult:
    """Bounded provider-read result produced without normalized fact writes."""

    provider_id: int
    provider_name: str
    requested_asset_code: str
    fact_count: int
    complete_fact_count: int
    block_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate deterministic counts and reason evidence."""

        if isinstance(self.provider_id, bool) or not isinstance(self.provider_id, int):
            raise ValueError("financial source probe provider_id is invalid")
        if self.provider_id <= 0 or not self.provider_name or not self.requested_asset_code:
            raise ValueError("financial source probe identity is required")
        if (
            isinstance(self.fact_count, bool)
            or not isinstance(self.fact_count, int)
            or self.fact_count < 0
        ):
            raise ValueError("financial source probe fact_count is invalid")
        if (
            isinstance(self.complete_fact_count, bool)
            or not isinstance(self.complete_fact_count, int)
            or not 0 <= self.complete_fact_count <= self.fact_count
        ):
            raise ValueError("financial source probe complete_fact_count is invalid")
        if not isinstance(self.block_reasons, tuple) or any(
            not isinstance(reason, str) or not reason or reason != reason.strip()
            for reason in self.block_reasons
        ):
            raise ValueError("financial source probe block_reasons are invalid")
        if tuple(sorted(set(self.block_reasons))) != self.block_reasons:
            raise ValueError("financial source probe block_reasons must be sorted and unique")

    @property
    def decision_ready(self) -> bool:
        """Return whether every fetched fact has complete bound decision evidence."""

        return (
            self.fact_count > 0
            and self.complete_fact_count == self.fact_count
            and not self.block_reasons
        )

    def to_dict(self) -> dict[str, object]:
        """Return a bounded JSON-safe probe result without provider fact values."""

        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "requested_asset_code": self.requested_asset_code,
            "fact_count": self.fact_count,
            "complete_fact_count": self.complete_fact_count,
            "decision_ready": self.decision_ready,
            "block_reasons": list(self.block_reasons),
        }


@dataclasses.dataclass(frozen=True, slots=True)
class PreparedFinancialSync:
    """One source-verified fetched batch that can be written without refetching."""

    config: ProviderConfig
    provider_name: str
    request: SyncFinancialRequest
    facts: tuple[FinancialFact, ...]
    probe: FinancialSourceEvidenceProbeResult
    started_at: datetime

    def __post_init__(self) -> None:
        """Reject mismatched or mutable prepared-batch identities."""

        if not isinstance(self.config, ProviderConfig):
            raise ValueError("prepared financial config must be typed")
        if self.config.id != self.probe.provider_id:
            raise ValueError("prepared financial provider id mismatch")
        if not self.provider_name or self.provider_name != self.probe.provider_name:
            raise ValueError("prepared financial provider identity mismatch")
        if self.request.asset_code != self.probe.requested_asset_code:
            raise ValueError("prepared financial request identity mismatch")
        if len(self.facts) != self.probe.fact_count or not self.probe.decision_ready:
            raise ValueError("prepared financial batch is not decision ready")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("prepared financial started_at must be timezone-aware")


def _financial_source_probe_result(
    *,
    provider: ProviderConfig,
    provider_name: str,
    requested_periods: int,
    requested_asset_code: str,
    facts: list[FinancialFact],
    artifact_verifier: FinancialResponseArtifactVerifier | None,
    source_time_artifact_verifier: FinancialSourceTimeArtifactVerifier | None,
) -> FinancialSourceEvidenceProbeResult:
    """Classify a fetched batch without exposing values or inferring source evidence."""

    require_single_asset_identity(
        requested_asset_code=requested_asset_code,
        returned_asset_codes=[fact.asset_code for fact in facts],
        label="financial",
    )
    reasons: set[str] = set()
    complete_fact_count = 0
    natural_keys: set[tuple[str, object, object, str, str]] = set()
    if not facts:
        reasons.add("financial_provider_facts_empty")
    for fact in facts:
        fact_reasons = _financial_fact_source_block_reasons(
            fact,
            provider=provider,
            provider_name=provider_name,
            requested_periods=requested_periods,
            artifact_verifier=artifact_verifier,
            source_time_artifact_verifier=source_time_artifact_verifier,
        )
        natural_key = (
            fact.asset_code,
            fact.period_end,
            fact.period_type,
            fact.metric_code,
            fact.source,
        )
        if natural_key in natural_keys:
            fact_reasons.add("financial_natural_key_duplicate")
        natural_keys.add(natural_key)
        if not fact_reasons:
            complete_fact_count += 1
        reasons.update(fact_reasons)
    return FinancialSourceEvidenceProbeResult(
        provider_id=int(provider.id or 0),
        provider_name=provider_name,
        requested_asset_code=requested_asset_code,
        fact_count=len(facts),
        complete_fact_count=complete_fact_count,
        block_reasons=tuple(sorted(reasons)),
    )


def _financial_fact_source_block_reasons(
    fact: FinancialFact,
    *,
    provider: ProviderConfig,
    provider_name: str,
    requested_periods: int,
    artifact_verifier: FinancialResponseArtifactVerifier | None,
    source_time_artifact_verifier: FinancialSourceTimeArtifactVerifier | None,
) -> set[str]:
    """Return bounded fail-closed reasons for one provider financial fact."""

    reasons: set[str] = set()
    evidence = fact.source_evidence
    if evidence is None:
        reasons.add("financial_source_evidence_missing")
    elif not evidence.is_complete:
        reasons.add("financial_source_evidence_incomplete")

    available_at = fact.available_at
    if available_at is None:
        reasons.add("financial_available_at_missing")
    fetched_at = fact.fetched_at
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        reasons.add("financial_fetched_at_invalid")
    decision_evidence = fact.decision_evidence
    if decision_evidence is None:
        reasons.add("financial_decision_evidence_missing")
    else:
        artifact_reference = decision_evidence.artifact_reference
        artifact_evidence = artifact_reference.evidence
        request_scope = artifact_evidence.request_scope
        completed_at = artifact_evidence.response_completed_at
        if request_scope.provider_name != provider_name:
            reasons.add("financial_response_provider_identity_mismatch")
        if request_scope.period_limit != requested_periods:
            reasons.add("financial_response_period_limit_mismatch")
        if artifact_verifier is None or not artifact_verifier(provider, artifact_reference):
            reasons.add("financial_response_artifact_not_retained")
        if evidence is None or evidence.raw_payload_hash != artifact_evidence.body_sha256:
            reasons.add("financial_response_body_hash_mismatch")
        if evidence is None or evidence.source_record_id != decision_evidence.native_row_id:
            reasons.add("financial_native_row_identity_mismatch")
        if decision_evidence.native_asset_code != fact.asset_code:
            reasons.add("financial_native_asset_identity_mismatch")
        if decision_evidence.native_period_end != fact.period_end:
            reasons.add("financial_native_period_identity_mismatch")
        source_time_witness = decision_evidence.source_time_witness
        if evidence is not None and evidence.announced_at is not None and available_at is not None:
            if source_time_witness is None:
                reasons.add("financial_source_time_artifact_missing")
            else:
                if source_time_artifact_verifier is None or not source_time_artifact_verifier(
                    provider, decision_evidence
                ):
                    reasons.add("financial_source_time_artifact_not_retained")
                if (
                    source_time_witness.announced_at != evidence.announced_at
                    or source_time_witness.available_at != available_at
                    or source_time_witness.native_asset_code != fact.asset_code
                    or source_time_witness.native_period_end != fact.period_end
                    or source_time_witness.financial_native_row_id
                    != decision_evidence.native_row_id
                ):
                    reasons.add("financial_source_time_witness_mismatch")
        if (
            evidence is not None
            and evidence.announced_at is not None
            and available_at is not None
            and fetched_at.tzinfo is not None
            and fetched_at.utcoffset() is not None
            and not evidence.announced_at <= available_at <= completed_at <= fetched_at
        ):
            reasons.add("financial_source_time_order_invalid")
    return reasons


def _with_verified_financial_transport_metadata(fact: FinancialFact) -> FinancialFact:
    """Project verified transport metadata needed by persisted publication evidence."""

    decision_evidence = fact.decision_evidence
    if decision_evidence is None:
        raise ValueError("verified financial decision evidence is required")
    artifact = decision_evidence.artifact_reference
    source_time = decision_evidence.source_time_witness
    if source_time is None:
        raise ValueError("verified financial source-time witness is required")
    source_time_artifact = source_time.artifact_reference
    return dataclasses.replace(
        fact,
        extra={
            **fact.extra,
            "financial_response_capture_id": str(artifact.capture_id),
            "raw_payload_scope": artifact.evidence.body_scope.value,
            "response_scope_basis": artifact.evidence.response_scope_basis.value,
            "financial_source_time_capture_id": str(source_time_artifact.capture_id),
            "financial_source_time_body_sha256": source_time_artifact.body_sha256,
            "financial_source_time_row_sha256": source_time.row_projection_sha256,
            "financial_source_time_match_contract_id": source_time.governed_match_contract_id,
            "financial_source_time_match_contract_version": (
                source_time.governed_match_contract_version
            ),
            "financial_source_time_match_contract_sha256": (
                source_time.governed_match_contract_sha256
            ),
            "financial_source_time_matched_row_count": source_time.matched_row_count,
        },
    )


class SyncFinancialUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: FinancialFactRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishFinancialBatchUseCase | None = None,
        artifact_verifier: FinancialResponseArtifactVerifier | None = None,
        source_time_artifact_verifier: FinancialSourceTimeArtifactVerifier | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._publication_publisher = publication_publisher
        self._artifact_verifier = artifact_verifier
        self._source_time_artifact_verifier = source_time_artifact_verifier

    def probe_source_evidence(
        self,
        request: SyncFinancialRequest,
    ) -> FinancialSourceEvidenceProbeResult:
        """Fetch and classify source evidence without fact, publication, or sync-audit writes."""

        config, provider = self._get_provider(request.provider_id)
        facts = self._fetch_normalized(
            request,
            config=config,
            provider=provider,
        )
        return _financial_source_probe_result(
            provider=config,
            provider_name=provider.provider_name(),
            requested_periods=request.periods,
            requested_asset_code=request.asset_code,
            facts=facts,
            artifact_verifier=self._artifact_verifier,
            source_time_artifact_verifier=self._source_time_artifact_verifier,
        )

    def prepare_for_write(self, request: SyncFinancialRequest) -> PreparedFinancialSync:
        """Fetch and validate one immutable batch for a later no-refetch write."""

        config, provider = self._get_provider(request.provider_id)
        return self._prepare_for_write(
            request,
            config=config,
            provider=provider,
            started_at=datetime.now(UTC),
        )

    def execute(self, request: SyncFinancialRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        params = {"asset_code": request.asset_code, "periods": request.periods}
        try:
            prepared = self._prepare_for_write(
                request,
                config=config,
                provider=provider,
                started_at=started,
            )
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            self._record_financial_error(
                config=config,
                provider_name=provider.provider_name(),
                params=params,
                started_at=started,
                error=exc,
            )
            raise
        return self.execute_prepared(prepared)

    def execute_prepared(self, prepared: PreparedFinancialSync) -> SyncResult:
        """Write one source-verified prepared batch without another provider fetch."""

        params = {
            "asset_code": prepared.request.asset_code,
            "periods": prepared.request.periods,
        }
        try:
            facts = list(prepared.facts)
            probe = _financial_source_probe_result(
                provider=prepared.config,
                provider_name=prepared.provider_name,
                requested_periods=prepared.request.periods,
                requested_asset_code=prepared.request.asset_code,
                facts=facts,
                artifact_verifier=self._artifact_verifier,
                source_time_artifact_verifier=self._source_time_artifact_verifier,
            )
            if probe != prepared.probe or not probe.decision_ready:
                raise InvalidInputError(
                    "prepared financial evidence changed before write",
                    code="FINANCIAL_SOURCE_EVIDENCE_REQUIRED",
                    details={"block_reasons": list(probe.block_reasons)},
                )
            stored_count = self._facts.bulk_upsert(facts)
            if self._publication_publisher is not None and facts:
                self._publication_publisher.execute(facts, provider_name=prepared.provider_name)
            audit_status, result_status = _sync_status(stored_count)
            latency_ms = (datetime.now(UTC) - prepared.started_at).total_seconds() * 1000
            self._record_outcome(
                prepared.config,
                provider_name=prepared.provider_name,
                capability="financial",
                request_params=params,
                status=audit_status,
                row_count=stored_count,
                latency_ms=latency_ms,
            )
            return SyncResult("financial", prepared.provider_name, stored_count, result_status)
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            self._record_financial_error(
                config=prepared.config,
                provider_name=prepared.provider_name,
                params=params,
                started_at=prepared.started_at,
                error=exc,
            )
            raise

    def _prepare_for_write(
        self,
        request: SyncFinancialRequest,
        *,
        config: ProviderConfig,
        provider: UnifiedDataProviderProtocol,
        started_at: datetime,
    ) -> PreparedFinancialSync:
        """Return the exact fetched facts only when their typed witness is complete."""

        facts = self._fetch_normalized(request, config=config, provider=provider)
        provider_name = provider.provider_name()
        probe = _financial_source_probe_result(
            provider=config,
            provider_name=provider_name,
            requested_periods=request.periods,
            requested_asset_code=request.asset_code,
            facts=facts,
            artifact_verifier=self._artifact_verifier,
            source_time_artifact_verifier=self._source_time_artifact_verifier,
        )
        if not probe.decision_ready:
            raise InvalidInputError(
                "financial provider facts require complete source evidence before write",
                code="FINANCIAL_SOURCE_EVIDENCE_REQUIRED",
                details={"block_reasons": list(probe.block_reasons)},
            )
        facts = [_with_verified_financial_transport_metadata(fact) for fact in facts]
        return PreparedFinancialSync(
            config=config,
            provider_name=provider_name,
            request=request,
            facts=tuple(facts),
            probe=probe,
            started_at=started_at,
        )

    def _record_financial_error(
        self,
        *,
        config: ProviderConfig,
        provider_name: str,
        params: dict[str, object],
        started_at: datetime,
        error: Exception,
    ) -> None:
        """Persist the bounded failure outcome for a direct financial sync."""

        latency_ms = (datetime.now(UTC) - started_at).total_seconds() * 1000
        self._record_outcome(
            config,
            provider_name=provider_name,
            capability="financial",
            request_params=params,
            status="error",
            row_count=0,
            latency_ms=latency_ms,
            error_message=str(error),
        )

    def _fetch_normalized(
        self,
        request: SyncFinancialRequest,
        *,
        config: ProviderConfig,
        provider: UnifiedDataProviderProtocol,
    ) -> list[FinancialFact]:
        """Fetch one financial batch and normalize provider identity without writing."""

        facts = provider.fetch_financials(request.asset_code, periods=request.periods)
        normalized = self._normalize_fact_sources(
            facts,
            source_type=config.source_type,
            provider_name=provider.provider_name(),
        )
        require_single_asset_identity(
            requested_asset_code=request.asset_code,
            returned_asset_codes=[fact.asset_code for fact in normalized],
            label="financial",
        )
        return normalized


class SyncValuationUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: ValuationFactRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishValuationBatchUseCase | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._publication_publisher = publication_publisher

    def execute(self, request: SyncValuationRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        params = {
            "asset_code": request.asset_code,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
        }
        try:
            facts = provider.fetch_valuations(request.asset_code, request.start, request.end)
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            require_single_asset_identity(
                requested_asset_code=request.asset_code,
                returned_asset_codes=[fact.asset_code for fact in facts],
                label="valuation",
            )
            stored_count = self._facts.bulk_upsert(facts)
            if self._publication_publisher is not None and facts:
                self._publication_publisher.execute(
                    facts,
                    provider_name=provider.provider_name(),
                )
            audit_status, result_status = _sync_status(stored_count)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="valuation",
                request_params=params,
                status=audit_status,
                row_count=stored_count,
                latency_ms=latency_ms,
            )
            return SyncResult("valuation", provider.provider_name(), stored_count, result_status)
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="valuation",
                request_params=params,
                status="error",
                row_count=0,
                latency_ms=latency_ms,
                error_message=str(exc),
            )
            raise


class SyncSectorMembershipUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: SectorMembershipRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishSectorMembershipBatchUseCase | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._publication_publisher = publication_publisher

    def execute(self, request: SyncSectorMembershipRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        params = {
            "sector_code": request.sector_code,
            "sector_name": request.sector_name,
            "effective_date": (
                request.effective_date.isoformat() if request.effective_date else None
            ),
        }
        try:
            facts = provider.fetch_sector_memberships(
                sector_code=request.sector_code,
                sector_name=request.sector_name,
                effective_date=request.effective_date,
            )
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            stored_count = self._facts.bulk_upsert(facts)
            if self._publication_publisher is not None and facts:
                self._publication_publisher.execute(
                    facts,
                    provider_name=provider.provider_name(),
                )
            audit_status, result_status = _sync_status(stored_count)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="sector_membership",
                request_params=params,
                status=audit_status,
                row_count=stored_count,
                latency_ms=latency_ms,
            )
            return SyncResult(
                "sector_membership", provider.provider_name(), stored_count, result_status
            )
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="sector_membership",
                request_params=params,
                status="error",
                row_count=0,
                latency_ms=latency_ms,
                error_message=str(exc),
            )
            raise


def __getattr__(name: str) -> object:
    """Resolve moved sync classes without a sibling import cycle."""

    if name in {"SyncPriceUseCase", "SyncQuoteUseCase"}:
        from . import sync_market_use_cases

        return getattr(sync_market_use_cases, name)

    if name in {
        "MacroFailoverPolicy",
        "MacroFailoverPolicyProvider",
        "PreparedMacroSync",
        "SyncMacroBatchUseCase",
        "SyncMacroUseCase",
    }:
        from . import sync_macro_use_cases

        return getattr(sync_macro_use_cases, name)

    if name in {"SyncCapitalFlowUseCase", "SyncNewsUseCase"}:
        from . import sync_news_capital_use_cases

        return getattr(sync_news_capital_use_cases, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "FinancialResponseArtifactVerifier",
    "FinancialSourceEvidenceProbeResult",
    "MacroFailoverDecision",
    "MacroFailoverPolicy",
    "MacroFailoverPolicyProvider",
    "PreparedMacroSync",
    "PreparedFinancialSync",
    "RECOVERABLE_DATA_CENTER_EXCEPTIONS",
    "SyncCapitalFlowUseCase",
    "SyncFinancialUseCase",
    "SyncFundNavUseCase",
    "SyncMacroUseCase",
    "SyncMacroBatchUseCase",
    "SyncNewsUseCase",
    "SyncPriceUseCase",
    "SyncQuoteUseCase",
    "SyncSectorMembershipUseCase",
    "SyncValuationUseCase",
]
