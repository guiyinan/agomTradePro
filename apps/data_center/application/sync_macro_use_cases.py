"""Canonical audited macro synchronization use cases for Data Center."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping
from datetime import date, datetime
from typing import Protocol

from apps.audit.application.data_failover_audit import DataFailoverAuditObservation
from apps.audit.application.data_fetch_audit import DataFetchAuditObservation
from apps.audit.application.data_publication_audit import DataPublicationAuditObservation
from apps.audit.application.data_validation_audit import DataValidationRejectedObservation
from apps.audit.domain.system_audit_event import AuditOutcome
from apps.data_center.application.dtos import (
    MacroFailoverDecision,
    SyncMacroBatchRequest,
    SyncMacroBatchResult,
    SyncMacroRequest,
    SyncResult,
)
from apps.data_center.domain.entities import (
    MacroFact,
    ProviderConfig,
    RawAuditReference,
)
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.protocols import (
    IndicatorCatalogRepositoryProtocol,
    IndicatorUnitRuleRepositoryProtocol,
    MacroFactRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    RawAuditRepositoryProtocol,
)
from apps.data_center.domain.rules import macro_series_are_consistent

from .macro_fact_governance import MacroFactGovernanceNormalizer
from .macro_publication import PublishMacroBatchUseCase
from .sync_identity import (
    IssueSyncExecutionIdentityCommand,
    IssueSyncExecutionIdentityUseCase,
    SyncExecutionIdentity,
    SyncExecutionIdentityIssuer,
)
from .sync_transaction import (
    DataCenterSyncClock,
    DataCenterSyncUnitOfWork,
    DataFailoverAuditWriter,
    DataFetchAuditWriter,
    DataProviderHealthAuditWriter,
    DataPublicationAuditWriter,
    DataPublicationQualityRecorder,
    DataValidationAuditWriter,
)
from .sync_use_cases import (
    RECOVERABLE_DATA_CENTER_EXCEPTIONS,
    _BaseSyncUseCase,
    _build_sync_audit,
    _publication_attempt_hash,
    _sync_status,
)


@dataclasses.dataclass(frozen=True, slots=True)
class PreparedMacroSync:
    """Fetched and governed macro facts awaiting one audited commit."""

    config: ProviderConfig
    provider_name: str
    indicator_code: str
    request_params: Mapping[str, object]
    facts: tuple[MacroFact, ...]
    started_at: datetime


@dataclasses.dataclass(frozen=True, slots=True)
class MacroFailoverPolicy:
    """Runtime-backed permission and tolerance for macro provider failover."""

    enabled: bool
    tolerance: float

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")
        if (
            isinstance(self.tolerance, bool)
            or not isinstance(self.tolerance, (int, float))
            or not math.isfinite(float(self.tolerance))
            or not 0.0 <= float(self.tolerance) <= 1.0
        ):
            raise ValueError("tolerance must be between 0 and 1")


class MacroFailoverPolicyProvider(Protocol):
    """Load one authoritative macro failover policy snapshot."""

    def get_policy(self) -> MacroFailoverPolicy:
        """Return one validated runtime policy or raise."""


class SyncMacroUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: MacroFactRepositoryProtocol,
        catalog_repo: IndicatorCatalogRepositoryProtocol,
        unit_rule_repo: IndicatorUnitRuleRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishMacroBatchUseCase | None = None,
        *,
        sync_identity_issuer: SyncExecutionIdentityIssuer,
        sync_unit_of_work: DataCenterSyncUnitOfWork,
        data_fetch_audit_writer: DataFetchAuditWriter,
        data_publication_audit_writer: DataPublicationAuditWriter,
        publication_quality_recorder: DataPublicationQualityRecorder | None = None,
        data_validation_audit_writer: DataValidationAuditWriter,
        data_failover_audit_writer: DataFailoverAuditWriter | None = None,
        clock: DataCenterSyncClock,
        data_provider_health_audit_writer: DataProviderHealthAuditWriter | None = None,
    ) -> None:
        super().__init__(
            provider_repo,
            provider_registry,
            raw_audit_repo,
            data_provider_health_audit_writer=data_provider_health_audit_writer,
        )
        self._facts = fact_repo
        self._normalizer = MacroFactGovernanceNormalizer(catalog_repo, unit_rule_repo)
        self._publication_publisher = publication_publisher
        if (publication_publisher is None) != (publication_quality_recorder is None):
            raise ValueError(
                "publication publisher and quality recorder must be configured together"
            )
        self._publication_quality_recorder = publication_quality_recorder
        self._identity_use_case = IssueSyncExecutionIdentityUseCase(sync_identity_issuer)
        self._sync_unit_of_work = sync_unit_of_work
        self._data_fetch_audit_writer = data_fetch_audit_writer
        self._data_publication_audit_writer = data_publication_audit_writer
        self._data_validation_audit_writer = data_validation_audit_writer
        self._data_failover_audit_writer = data_failover_audit_writer
        self._clock = clock

    def _normalize_macro_facts(
        self,
        *,
        indicator_code: str,
        source_type: str,
        provider_name: str,
        facts: list[MacroFact],
    ) -> list[MacroFact]:
        if any(fact.indicator_code != indicator_code for fact in facts):
            raise ValueError(f"Provider returned a mismatched indicator for {indicator_code}")
        return self._normalizer.normalize_many(
            facts,
            source_type=source_type,
            provider_name=provider_name,
        )

    def execute(self, request: SyncMacroRequest) -> SyncResult:
        """Fetch, govern, and commit one macro request without failover."""

        return self.commit(self.prepare(request))

    def prepare(self, request: SyncMacroRequest) -> PreparedMacroSync:
        """Fetch and govern one provider result, auditing any rejection."""

        config, provider = self._get_provider(request.provider_id)
        provider_name = provider.provider_name()
        started = self._clock.now()
        params = {
            "indicator_code": request.indicator_code,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
        }
        try:
            facts = provider.fetch_macro_series(request.indicator_code, request.start, request.end)
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            self._commit_macro_fetch_failure(
                config=config,
                provider_name=provider_name,
                request_params=params,
                started_at=started,
                error=exc,
            )
            raise
        indicator_mismatch = any(fact.indicator_code != request.indicator_code for fact in facts)
        try:
            normalized = self._normalize_macro_facts(
                indicator_code=request.indicator_code,
                source_type=config.source_type,
                provider_name=provider_name,
                facts=facts,
            )
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            self._commit_macro_validation_failure(
                config=config,
                provider_name=provider_name,
                request_params=params,
                facts=facts,
                started_at=started,
                error=exc,
                rejection_reason=(
                    "indicator_mismatch"
                    if indicator_mismatch
                    else self._validation_rejection_reason(exc)
                ),
            )
            raise
        return PreparedMacroSync(
            config=config,
            provider_name=provider_name,
            indicator_code=request.indicator_code,
            request_params=params,
            facts=tuple(normalized),
            started_at=started,
        )

    def commit(
        self,
        prepared: PreparedMacroSync,
        *,
        failover_decision: MacroFailoverDecision | None = None,
        verification: PreparedMacroSync | None = None,
    ) -> SyncResult:
        """Commit one prepared result and optional verified failover evidence."""

        if not isinstance(prepared, PreparedMacroSync):
            raise TypeError("prepared must be a PreparedMacroSync")
        if (failover_decision is None) != (verification is None):
            raise ValueError("failover decision and verification must be supplied together")
        if failover_decision is not None:
            if self._data_failover_audit_writer is None:
                raise RuntimeError("failover audit writer is not configured")
            if failover_decision.to_provider != prepared.provider_name:
                raise ValueError("failover destination differs from the selected provider")
            if verification is None:
                raise ValueError("verified failover requires an independent result")
            if failover_decision.verification_provider != verification.provider_name:
                raise ValueError("failover verifier differs from the prepared evidence")
            if prepared.indicator_code != verification.indicator_code:
                raise ValueError("failover evidence indicator differs from the selected result")
            if not verification.facts:
                raise ValueError("failover verification requires governed facts")
        return self._commit_macro_fetch_success(
            config=prepared.config,
            provider_name=prepared.provider_name,
            indicator_code=prepared.indicator_code,
            request_params=prepared.request_params,
            facts=list(prepared.facts),
            started_at=prepared.started_at,
            failover_decision=failover_decision,
            verification=verification,
        )

    def block_failover(
        self,
        prepared: PreparedMacroSync,
        *,
        from_provider: str,
        tolerance: float,
        observed_deviation: float | None,
        reason_code: str,
        error_class: str,
        verification: PreparedMacroSync | None = None,
    ) -> None:
        """Commit exact fetched evidence for a blocked provider switch."""

        if not isinstance(prepared, PreparedMacroSync) or not prepared.facts:
            raise ValueError("blocked failover requires a prepared non-empty result")
        failover_writer = self._data_failover_audit_writer
        if failover_writer is None:
            raise RuntimeError("failover audit writer is not configured")
        if verification is not None:
            if verification.provider_name in {from_provider, prepared.provider_name}:
                raise ValueError("failover verification provider must be independent")
            if verification.indicator_code != prepared.indicator_code or not verification.facts:
                raise ValueError("failover verification evidence is invalid")
        with self._sync_unit_of_work.atomic():
            identity = self._issue_identity(provider_name=prepared.provider_name)
            recorded_at = self._clock.now()
            reference = self._persist_prepared_fetch_evidence(
                prepared,
                identity=identity,
                recorded_at=recorded_at,
                health_success=False,
                error_class=error_class,
                audit_status="error",
            )
            if verification is not None:
                self._persist_prepared_fetch_evidence(
                    verification,
                    identity=identity,
                    recorded_at=recorded_at,
                    health_success=True,
                    error_class="",
                    audit_status="ok",
                )
            failover_writer.write(
                DataFailoverAuditObservation(
                    dataset_key=identity.dataset_key,
                    capability="macro",
                    from_provider=from_provider,
                    to_provider=prepared.provider_name,
                    run_id=reference.run_id,
                    ingested_run_id=reference.ingested_run_id,
                    raw_audit_id=reference.raw_audit_id,
                    raw_audit_version=reference.version,
                    raw_audit_content_hash=reference.content_hash,
                    tolerance=tolerance,
                    observed_deviation=None,
                    reason_code=reason_code,
                    outcome=AuditOutcome.STARTED,
                    occurred_at=recorded_at,
                    recorded_at=recorded_at,
                )
            )
            failover_writer.write(
                DataFailoverAuditObservation(
                    dataset_key=identity.dataset_key,
                    capability="macro",
                    from_provider=from_provider,
                    to_provider=prepared.provider_name,
                    run_id=reference.run_id,
                    ingested_run_id=reference.ingested_run_id,
                    raw_audit_id=reference.raw_audit_id,
                    raw_audit_version=reference.version,
                    raw_audit_content_hash=reference.content_hash,
                    tolerance=tolerance,
                    observed_deviation=observed_deviation,
                    reason_code=reason_code,
                    error_class=error_class,
                    outcome=AuditOutcome.BLOCKED,
                    occurred_at=recorded_at,
                    recorded_at=recorded_at,
                )
            )

    def exhaust_failover(
        self,
        *,
        indicator_code: str,
        start: date,
        end: date,
        from_provider: str,
        attempted_provider_names: tuple[str, ...],
        tolerance: float,
    ) -> None:
        """Commit one exact aggregate record when no failover candidate remains."""

        if not indicator_code.strip() or not from_provider.strip():
            raise ValueError("failover exhaustion selectors must be non-empty")
        if end < start:
            raise ValueError("failover exhaustion end cannot precede start")
        if any(not name.strip() for name in attempted_provider_names):
            raise ValueError("attempted provider names must be non-empty")
        if attempted_provider_names and attempted_provider_names[0] != from_provider:
            raise ValueError("attempted providers must begin with the primary provider")
        MacroFailoverPolicy(enabled=True, tolerance=tolerance)
        failover_writer = self._data_failover_audit_writer
        if failover_writer is None:
            raise RuntimeError("failover audit writer is not configured")
        exhausted_provider = "macro-provider-candidates"
        if exhausted_provider == from_provider:
            exhausted_provider = "macro-provider-candidates-unavailable"
        request_params: Mapping[str, object] = {
            "indicator_code": indicator_code,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "attempted_provider_names": list(attempted_provider_names),
            "attempted_provider_count": len(attempted_provider_names),
        }
        with self._sync_unit_of_work.atomic():
            identity = self._issue_identity(provider_name=exhausted_provider)
            recorded_at = self._clock.now()
            error_class = "ProviderCandidatesExhausted"
            persisted_audit = self._raw_audit_repo.log(
                _build_sync_audit(
                    exhausted_provider,
                    "macro",
                    request_params,
                    "error",
                    0,
                    0.0,
                    error_class,
                    fetched_at=recorded_at,
                    run_id=identity.run_id,
                    ingested_run_id=identity.ingested_run_id,
                )
            )
            reference = persisted_audit.exact_reference()
            self._data_fetch_audit_writer.write(
                DataFetchAuditObservation(
                    provider_key=exhausted_provider,
                    capability="macro",
                    dataset_key=identity.dataset_key,
                    run_id=reference.run_id,
                    ingested_run_id=reference.ingested_run_id,
                    raw_audit_id=reference.raw_audit_id,
                    raw_audit_version=reference.version,
                    raw_audit_content_hash=reference.content_hash,
                    outcome=AuditOutcome.FAILED,
                    row_count=0,
                    error_class=error_class,
                    occurred_at=recorded_at,
                    recorded_at=recorded_at,
                )
            )
            for outcome in (AuditOutcome.STARTED, AuditOutcome.BLOCKED):
                failover_writer.write(
                    DataFailoverAuditObservation(
                        dataset_key=identity.dataset_key,
                        capability="macro",
                        from_provider=from_provider,
                        to_provider=exhausted_provider,
                        run_id=reference.run_id,
                        ingested_run_id=reference.ingested_run_id,
                        raw_audit_id=reference.raw_audit_id,
                        raw_audit_version=reference.version,
                        raw_audit_content_hash=reference.content_hash,
                        tolerance=tolerance,
                        observed_deviation=None,
                        reason_code="failover_candidates_exhausted",
                        error_class=(error_class if outcome is AuditOutcome.BLOCKED else None),
                        outcome=outcome,
                        occurred_at=recorded_at,
                        recorded_at=recorded_at,
                    )
                )

    def _persist_prepared_fetch_evidence(
        self,
        prepared: PreparedMacroSync,
        *,
        identity: SyncExecutionIdentity,
        recorded_at: datetime,
        health_success: bool,
        error_class: str,
        audit_status: str,
    ) -> RawAuditReference:
        """Persist one prepared provider result and its exact fetch event."""

        row_count = len(prepared.facts)
        if row_count <= 0:
            raise ValueError("prepared fetch evidence requires rows")
        latency_ms = max(0.0, (recorded_at - prepared.started_at).total_seconds() * 1000)
        self._persist_provider_health_metric(
            prepared.config,
            capability="macro",
            latency_ms=latency_ms,
            success=health_success,
            error=error_class,
            output_count=row_count,
            recorded_at=recorded_at,
            run_id=identity.run_id,
            ingested_run_id=identity.ingested_run_id,
        )
        persisted_audit = self._raw_audit_repo.log(
            _build_sync_audit(
                prepared.provider_name,
                "macro",
                prepared.request_params,
                audit_status,
                row_count,
                latency_ms,
                error_class,
                fetched_at=recorded_at,
                run_id=identity.run_id,
                ingested_run_id=identity.ingested_run_id,
            )
        )
        reference = persisted_audit.exact_reference()
        self._data_fetch_audit_writer.write(
            DataFetchAuditObservation(
                provider_key=prepared.provider_name,
                capability="macro",
                dataset_key=identity.dataset_key,
                run_id=reference.run_id,
                ingested_run_id=reference.ingested_run_id,
                raw_audit_id=reference.raw_audit_id,
                raw_audit_version=reference.version,
                raw_audit_content_hash=reference.content_hash,
                outcome=AuditOutcome.SUCCESS,
                row_count=row_count,
                occurred_at=recorded_at,
                recorded_at=recorded_at,
            )
        )
        return reference

    def _issue_identity(self, *, provider_name: str) -> SyncExecutionIdentity:
        """Issue one identity inside the active sync transaction."""

        return self._identity_use_case.execute(
            IssueSyncExecutionIdentityCommand(
                dataset_key="macro.fact",
                provider_name=provider_name,
            )
        )

    def _commit_macro_fetch_success(
        self,
        *,
        config: ProviderConfig,
        provider_name: str,
        indicator_code: str,
        request_params: Mapping[str, object],
        facts: list[MacroFact],
        started_at: datetime,
        failover_decision: MacroFailoverDecision | None,
        verification: PreparedMacroSync | None,
    ) -> SyncResult:
        """Commit facts, professional evidence, and fetch event in one UOW."""

        publication_error: ValueError | None = None
        publication_blocked_reason: str | None = None
        with self._sync_unit_of_work.atomic():
            identity = self._issue_identity(provider_name=provider_name)
            correlated_facts = [
                dataclasses.replace(fact, ingested_run_id=identity.ingested_run_id)
                for fact in facts
            ]
            stored_count = self._facts.bulk_upsert(correlated_facts) if correlated_facts else 0
            publication = None
            if self._publication_publisher is not None and correlated_facts:
                publication_at = self._clock.now()
                try:
                    publication = self._publication_publisher.execute(
                        correlated_facts,
                        provider_name=provider_name,
                        publication_key=indicator_code,
                        run_id=identity.run_id,
                        published_at=publication_at,
                    )
                except ValueError as error:
                    publication_error = error
                    publication_blocked_reason = "publication_policy_rejected"
                if publication is None and publication_error is None:
                    publication_error = ValueError("macro publication returned no result")
                    publication_blocked_reason = "publication_no_result"
            audit_status, result_status = _sync_status(stored_count)
            recorded_at = self._clock.now()
            latency_ms = max(0.0, (recorded_at - started_at).total_seconds() * 1000)
            self._persist_provider_health_metric(
                config,
                capability="macro",
                latency_ms=latency_ms,
                success=stored_count > 0,
                output_count=stored_count,
                recorded_at=recorded_at,
                run_id=identity.run_id,
                ingested_run_id=identity.ingested_run_id,
            )
            persisted_audit = self._raw_audit_repo.log(
                _build_sync_audit(
                    provider_name,
                    "macro",
                    request_params,
                    audit_status,
                    stored_count,
                    latency_ms,
                    fetched_at=recorded_at,
                    run_id=identity.run_id,
                    ingested_run_id=identity.ingested_run_id,
                )
            )
            reference = persisted_audit.exact_reference()
            self._data_fetch_audit_writer.write(
                DataFetchAuditObservation(
                    provider_key=provider_name,
                    capability="macro",
                    dataset_key=identity.dataset_key,
                    run_id=reference.run_id,
                    ingested_run_id=reference.ingested_run_id,
                    raw_audit_id=reference.raw_audit_id,
                    raw_audit_version=reference.version,
                    raw_audit_content_hash=reference.content_hash,
                    outcome=(AuditOutcome.SUCCESS if stored_count > 0 else AuditOutcome.NOOP),
                    row_count=stored_count,
                    occurred_at=recorded_at,
                    recorded_at=recorded_at,
                )
            )
            if verification is not None:
                verification_count = len(verification.facts)
                verification_latency_ms = max(
                    0.0,
                    (recorded_at - verification.started_at).total_seconds() * 1000,
                )
                self._persist_provider_health_metric(
                    verification.config,
                    capability="macro",
                    latency_ms=verification_latency_ms,
                    success=True,
                    output_count=verification_count,
                    recorded_at=recorded_at,
                    run_id=identity.run_id,
                    ingested_run_id=identity.ingested_run_id,
                )
                verification_audit = self._raw_audit_repo.log(
                    _build_sync_audit(
                        verification.provider_name,
                        "macro",
                        verification.request_params,
                        "ok",
                        verification_count,
                        verification_latency_ms,
                        fetched_at=recorded_at,
                        run_id=identity.run_id,
                        ingested_run_id=identity.ingested_run_id,
                    )
                )
                verification_reference = verification_audit.exact_reference()
                self._data_fetch_audit_writer.write(
                    DataFetchAuditObservation(
                        provider_key=verification.provider_name,
                        capability="macro",
                        dataset_key=identity.dataset_key,
                        run_id=verification_reference.run_id,
                        ingested_run_id=verification_reference.ingested_run_id,
                        raw_audit_id=verification_reference.raw_audit_id,
                        raw_audit_version=verification_reference.version,
                        raw_audit_content_hash=verification_reference.content_hash,
                        outcome=AuditOutcome.SUCCESS,
                        row_count=verification_count,
                        occurred_at=recorded_at,
                        recorded_at=recorded_at,
                    )
                )
            if failover_decision is not None:
                failover_writer = self._data_failover_audit_writer
                if failover_writer is None:
                    raise RuntimeError("failover audit writer is not configured")
                failover_writer.write(
                    DataFailoverAuditObservation(
                        dataset_key=identity.dataset_key,
                        capability="macro",
                        from_provider=failover_decision.from_provider,
                        to_provider=failover_decision.to_provider,
                        run_id=reference.run_id,
                        ingested_run_id=reference.ingested_run_id,
                        raw_audit_id=reference.raw_audit_id,
                        raw_audit_version=reference.version,
                        raw_audit_content_hash=reference.content_hash,
                        tolerance=failover_decision.tolerance,
                        observed_deviation=None,
                        reason_code=failover_decision.reason_code,
                        outcome=AuditOutcome.STARTED,
                        occurred_at=recorded_at,
                        recorded_at=recorded_at,
                    )
                )
                failover_writer.write(
                    DataFailoverAuditObservation(
                        dataset_key=identity.dataset_key,
                        capability="macro",
                        from_provider=failover_decision.from_provider,
                        to_provider=failover_decision.to_provider,
                        run_id=reference.run_id,
                        ingested_run_id=reference.ingested_run_id,
                        raw_audit_id=reference.raw_audit_id,
                        raw_audit_version=reference.version,
                        raw_audit_content_hash=reference.content_hash,
                        tolerance=failover_decision.tolerance,
                        observed_deviation=failover_decision.observed_deviation,
                        reason_code=failover_decision.reason_code,
                        outcome=AuditOutcome.SUCCESS,
                        occurred_at=recorded_at,
                        recorded_at=recorded_at,
                    )
                )
            if self._publication_publisher is not None and correlated_facts:
                if publication is not None:
                    publication_observation = DataPublicationAuditObservation(
                        dataset_key=publication.dataset_key,
                        publication_key=publication.publication_key,
                        publication_id=publication.publication_id,
                        publication_version=publication.policy_version,
                        publication_hash=publication.publication_hash,
                        provider_key=provider_name,
                        run_id=identity.run_id,
                        ingested_run_id=identity.ingested_run_id,
                        member_count=publication.member_count,
                        coverage_requested_count=publication.coverage.requested_count,
                        coverage_eligible_count=publication.coverage.eligible_count,
                        coverage_selected_count=publication.coverage.selected_count,
                        outcome=AuditOutcome.PUBLISHED,
                        raw_audit_id=reference.raw_audit_id,
                        raw_audit_version=reference.version,
                        raw_audit_content_hash=reference.content_hash,
                        occurred_at=publication.published_at or recorded_at,
                        recorded_at=recorded_at,
                    )
                else:
                    blocked_reason = publication_blocked_reason
                    if blocked_reason is None or publication_error is None:
                        raise RuntimeError("publication block evidence is incomplete")
                    attempt_hash = _publication_attempt_hash(
                        dataset_key=identity.dataset_key,
                        publication_key=indicator_code,
                        provider_name=provider_name,
                        run_id=identity.run_id,
                        ingested_run_id=identity.ingested_run_id,
                        blocked_reason=blocked_reason,
                    )
                    publication_observation = DataPublicationAuditObservation(
                        dataset_key=identity.dataset_key,
                        publication_key=indicator_code,
                        publication_id=f"publication-attempt-{attempt_hash[:48]}",
                        publication_version="attempt-v1",
                        publication_hash=attempt_hash,
                        provider_key=provider_name,
                        run_id=identity.run_id,
                        ingested_run_id=identity.ingested_run_id,
                        member_count=0,
                        coverage_requested_count=len(correlated_facts),
                        coverage_eligible_count=0,
                        coverage_selected_count=0,
                        outcome=AuditOutcome.BLOCKED,
                        raw_audit_id=reference.raw_audit_id,
                        raw_audit_version=reference.version,
                        raw_audit_content_hash=reference.content_hash,
                        occurred_at=recorded_at,
                        recorded_at=recorded_at,
                        blocked_reason=blocked_reason,
                        error_class=type(publication_error).__name__,
                    )
                self._data_publication_audit_writer.write(publication_observation)
                if publication is not None:
                    quality_recorder = self._publication_quality_recorder
                    if quality_recorder is None:
                        raise RuntimeError("publication quality recorder is not configured")
                    quality_recorder.execute(
                        publication_id=publication.publication_id,
                        run_id=identity.run_id,
                        ingested_run_id=identity.ingested_run_id,
                        provider_key=provider_name,
                    )
        if publication_error is not None:
            raise publication_error
        return SyncResult(
            "macro",
            provider_name,
            stored_count,
            result_status,
            run_id=identity.run_id,
            ingested_run_id=identity.ingested_run_id,
            publication_id=publication.publication_id if publication is not None else None,
            publication_version=publication.policy_version if publication is not None else None,
            publication_hash=publication.publication_hash if publication is not None else None,
        )

    def _commit_macro_fetch_failure(
        self,
        *,
        config: ProviderConfig,
        provider_name: str,
        request_params: Mapping[str, object],
        started_at: datetime,
        error: BaseException,
    ) -> None:
        """Persist a failed fetch observation without leaking exception text."""

        with self._sync_unit_of_work.atomic():
            identity = self._issue_identity(provider_name=provider_name)
            recorded_at = self._clock.now()
            latency_ms = max(0.0, (recorded_at - started_at).total_seconds() * 1000)
            error_class = type(error).__name__
            self._persist_provider_health_metric(
                config,
                capability="macro",
                latency_ms=latency_ms,
                success=False,
                error=error_class,
                recorded_at=recorded_at,
                output_count=0,
                run_id=identity.run_id,
                ingested_run_id=identity.ingested_run_id,
            )
            persisted_audit = self._raw_audit_repo.log(
                _build_sync_audit(
                    provider_name,
                    "macro",
                    request_params,
                    "error",
                    0,
                    latency_ms,
                    error_class,
                    fetched_at=recorded_at,
                    run_id=identity.run_id,
                    ingested_run_id=identity.ingested_run_id,
                )
            )
            reference = persisted_audit.exact_reference()
            self._data_fetch_audit_writer.write(
                DataFetchAuditObservation(
                    provider_key=provider_name,
                    capability="macro",
                    dataset_key=identity.dataset_key,
                    run_id=reference.run_id,
                    ingested_run_id=reference.ingested_run_id,
                    raw_audit_id=reference.raw_audit_id,
                    raw_audit_version=reference.version,
                    raw_audit_content_hash=reference.content_hash,
                    outcome=AuditOutcome.FAILED,
                    row_count=0,
                    occurred_at=recorded_at,
                    recorded_at=recorded_at,
                    error_class=error_class,
                )
            )

    @staticmethod
    def _validation_rejection_reason(error: BaseException) -> str:
        """Map a validation exception class to one stable non-sensitive reason."""

        if isinstance(error, TypeError):
            return "schema_rejected"
        if isinstance(error, ValueError):
            return "governance_rejected"
        return "validation_rejected"

    def _commit_macro_validation_failure(
        self,
        *,
        config: ProviderConfig,
        provider_name: str,
        request_params: Mapping[str, object],
        facts: list[MacroFact],
        started_at: datetime,
        error: BaseException,
        rejection_reason: str,
    ) -> None:
        """Commit a successful fetch and rejected validation in one UOW."""

        fetched_count = len(facts)
        if fetched_count <= 0:
            raise RuntimeError("validation rejection requires fetched rows") from error
        with self._sync_unit_of_work.atomic():
            identity = self._issue_identity(provider_name=provider_name)
            recorded_at = self._clock.now()
            latency_ms = max(0.0, (recorded_at - started_at).total_seconds() * 1000)
            error_class = type(error).__name__
            self._persist_provider_health_metric(
                config,
                capability="macro",
                latency_ms=latency_ms,
                success=False,
                error=error_class,
                recorded_at=recorded_at,
                output_count=fetched_count,
                run_id=identity.run_id,
                ingested_run_id=identity.ingested_run_id,
            )
            persisted_audit = self._raw_audit_repo.log(
                _build_sync_audit(
                    provider_name,
                    "macro",
                    request_params,
                    "error",
                    fetched_count,
                    latency_ms,
                    error_class,
                    fetched_at=recorded_at,
                    run_id=identity.run_id,
                    ingested_run_id=identity.ingested_run_id,
                )
            )
            reference = persisted_audit.exact_reference()
            self._data_fetch_audit_writer.write(
                DataFetchAuditObservation(
                    provider_key=provider_name,
                    capability="macro",
                    dataset_key=identity.dataset_key,
                    run_id=reference.run_id,
                    ingested_run_id=reference.ingested_run_id,
                    raw_audit_id=reference.raw_audit_id,
                    raw_audit_version=reference.version,
                    raw_audit_content_hash=reference.content_hash,
                    outcome=AuditOutcome.SUCCESS,
                    row_count=fetched_count,
                    occurred_at=recorded_at,
                    recorded_at=recorded_at,
                )
            )
            self._data_validation_audit_writer.write(
                DataValidationRejectedObservation(
                    dataset_key=identity.dataset_key,
                    validator_key="macro_fact_governance.v1",
                    provider_key=provider_name,
                    run_id=reference.run_id,
                    ingested_run_id=reference.ingested_run_id,
                    raw_audit_id=reference.raw_audit_id,
                    raw_audit_version=reference.version,
                    raw_audit_content_hash=reference.content_hash,
                    rejection_reason=rejection_reason,
                    error_class=error_class,
                    rejected_count=fetched_count,
                    occurred_at=recorded_at,
                    recorded_at=recorded_at,
                )
            )


class SyncMacroBatchUseCase:
    """Select one configured macro provider and synchronize an indicator batch."""

    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        sync_use_case: SyncMacroUseCase,
        *,
        failover_policy_provider: MacroFailoverPolicyProvider | None = None,
    ) -> None:
        self._provider_repo = provider_repo
        self._provider_registry = provider_registry
        self._sync_use_case = sync_use_case
        self._failover_policy_provider = failover_policy_provider

    def execute(self, request: SyncMacroBatchRequest) -> SyncMacroBatchResult:
        if request.source or self._failover_policy_provider is None:
            return self._execute_single_provider(request)
        policy = self._failover_policy_provider.get_policy()
        if not isinstance(policy, MacroFailoverPolicy):
            raise TypeError("macro failover policy provider returned an invalid policy")
        if not policy.enabled:
            return self._execute_single_provider(request)
        configs = self._list_provider_configs(None)
        if not configs:
            for indicator_code in request.indicator_codes:
                self._sync_use_case.exhaust_failover(
                    indicator_code=indicator_code,
                    start=request.start,
                    end=request.end,
                    from_provider="macro-provider-policy",
                    attempted_provider_names=(),
                    tolerance=policy.tolerance,
                )
            raise ValueError("No active macro provider configured")

        stored_count = 0
        errors: list[str] = []
        selected_provider = configs[0].name
        for indicator_code in request.indicator_codes:
            try:
                result = self._execute_indicator_with_failover(
                    request,
                    indicator_code=indicator_code,
                    configs=configs,
                    tolerance=policy.tolerance,
                )
            except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
                errors.append(f"{indicator_code}: {self._bounded_batch_error(exc)}")
                continue
            stored_count += result.stored_count
            selected_provider = result.provider_name

        return SyncMacroBatchResult(
            provider_name=selected_provider,
            stored_count=stored_count,
            errors=errors,
        )

    def _execute_single_provider(self, request: SyncMacroBatchRequest) -> SyncMacroBatchResult:
        """Preserve explicit-source and disabled-policy single-provider behavior."""

        config = self._select_provider(request.source)
        if config.id is None:
            raise ValueError(f"Provider has no persistent id: {config.name}")

        stored_count = 0
        errors: list[str] = []
        for indicator_code in request.indicator_codes:
            try:
                result = self._sync_use_case.execute(
                    SyncMacroRequest(
                        provider_id=config.id,
                        indicator_code=indicator_code,
                        start=request.start,
                        end=request.end,
                    )
                )
            except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
                errors.append(f"{indicator_code}: {self._bounded_batch_error(exc)}")
                continue
            stored_count += result.stored_count

        return SyncMacroBatchResult(
            provider_name=config.name,
            stored_count=stored_count,
            errors=errors,
        )

    def _execute_indicator_with_failover(
        self,
        request: SyncMacroBatchRequest,
        *,
        indicator_code: str,
        configs: list[ProviderConfig],
        tolerance: float,
    ) -> SyncResult:
        """Use two independent governed fallbacks before accepting a switch."""

        primary = configs[0]
        primary_request = self._request_for_config(request, indicator_code, primary)
        try:
            primary_prepared = self._sync_use_case.prepare(primary_request)
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS:
            primary_prepared = None
        if primary_prepared is not None:
            primary_result = self._sync_use_case.commit(primary_prepared)
            if primary_prepared.facts:
                return primary_result

        candidates: list[PreparedMacroSync] = []
        for config in configs[1:]:
            try:
                prepared = self._sync_use_case.prepare(
                    self._request_for_config(request, indicator_code, config)
                )
            except RECOVERABLE_DATA_CENTER_EXCEPTIONS:
                continue
            if not prepared.facts:
                self._sync_use_case.commit(prepared)
                continue
            candidates.append(prepared)

        if len(candidates) < 2:
            if candidates:
                self._sync_use_case.block_failover(
                    candidates[0],
                    from_provider=primary.name,
                    tolerance=tolerance,
                    observed_deviation=None,
                    reason_code="failover_consistency_evidence_missing",
                    error_class="ConsistencyEvidenceUnavailable",
                )
            else:
                self._sync_use_case.exhaust_failover(
                    indicator_code=indicator_code,
                    start=request.start,
                    end=request.end,
                    from_provider=primary.name,
                    attempted_provider_names=tuple(config.name for config in configs),
                    tolerance=tolerance,
                )
            raise RuntimeError("macro_failover_consistency_evidence_missing")

        first_comparison: tuple[PreparedMacroSync, PreparedMacroSync, float | None] | None = None
        for index, candidate in enumerate(candidates[:-1]):
            for verifier in candidates[index + 1 :]:
                consistent, deviation = self._compare_prepared_macro_series(
                    candidate,
                    verifier,
                    tolerance=tolerance,
                )
                if first_comparison is None:
                    first_comparison = (candidate, verifier, deviation)
                if consistent and deviation is not None:
                    decision = MacroFailoverDecision(
                        from_provider=primary.name,
                        to_provider=candidate.provider_name,
                        verification_provider=verifier.provider_name,
                        tolerance=tolerance,
                        observed_deviation=deviation,
                        reason_code="primary_unavailable_fallback_verified",
                    )
                    return self._sync_use_case.commit(
                        candidate,
                        failover_decision=decision,
                        verification=verifier,
                    )

        comparison = first_comparison
        if comparison is None:
            raise RuntimeError("macro_failover_consistency_evidence_missing")
        candidate, verifier, deviation = comparison
        if deviation is None:
            reason_code = "failover_consistency_evidence_missing"
            error_class = "ConsistencyEvidenceUnavailable"
            public_error = "macro_failover_consistency_evidence_missing"
        else:
            reason_code = "failover_consistency_rejected"
            error_class = "ConsistencyError"
            public_error = "macro_failover_consistency_rejected"
        self._sync_use_case.block_failover(
            candidate,
            from_provider=primary.name,
            tolerance=tolerance,
            observed_deviation=deviation,
            reason_code=reason_code,
            error_class=error_class,
            verification=verifier,
        )
        raise RuntimeError(public_error)

    @staticmethod
    def _request_for_config(
        request: SyncMacroBatchRequest,
        indicator_code: str,
        config: ProviderConfig,
    ) -> SyncMacroRequest:
        """Bind one server-selected provider id to a batch indicator."""

        if config.id is None:
            raise ValueError("macro provider has no persistent id")
        return SyncMacroRequest(
            provider_id=config.id,
            indicator_code=indicator_code,
            start=request.start,
            end=request.end,
        )

    @staticmethod
    def _compare_prepared_macro_series(
        candidate: PreparedMacroSync,
        verifier: PreparedMacroSync,
        *,
        tolerance: float,
    ) -> tuple[bool, float | None]:
        """Compare canonical-unit observations at overlapping reporting dates."""

        candidate_values = {fact.reporting_period: fact.value for fact in candidate.facts}
        verifier_values = {fact.reporting_period: fact.value for fact in verifier.facts}
        return macro_series_are_consistent(
            candidate_values,
            verifier_values,
            tolerance=tolerance,
        )

    @staticmethod
    def _bounded_batch_error(error: BaseException) -> str:
        """Return only stable application reasons or an exception class token."""

        message = str(error)
        if message in {
            "macro_failover_consistency_evidence_missing",
            "macro_failover_consistency_rejected",
        }:
            return message
        return type(error).__name__

    def _select_provider(self, source: str | None) -> ProviderConfig:
        configs = self._list_provider_configs(source)
        if configs:
            return configs[0]
        suffix = f" for source {source!r}" if source else ""
        raise ValueError(f"No active macro provider configured{suffix}")

    def _list_provider_configs(self, source: str | None) -> list[ProviderConfig]:
        """Return active supported provider configs in canonical priority order."""

        requested = source.strip().lower() if source else ""
        configs = sorted(
            (config for config in self._provider_repo.list_all() if config.is_active),
            key=lambda config: config.priority,
        )
        selected: list[ProviderConfig] = []
        for config in configs:
            if requested and requested not in {config.name.lower(), config.source_type.lower()}:
                continue
            if config.id is None:
                continue
            provider = self._provider_registry.get_by_id(config.id)
            if provider is not None and provider.supports(DataCapability.MACRO):
                selected.append(config)
        return selected
