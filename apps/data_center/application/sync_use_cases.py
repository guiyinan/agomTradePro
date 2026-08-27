"""Provider-to-fact synchronization use cases for Data Center."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar, cast

from apps.audit.application.data_fetch_audit import DataFetchAuditObservation
from apps.audit.application.data_publication_audit import DataPublicationAuditObservation
from apps.audit.domain.system_audit_event import AuditOutcome
from apps.data_center.application.dtos import (
    MacroFailoverDecision,
    SyncFinancialRequest,
    SyncFundNavRequest,
    SyncPriceRequest,
    SyncQuoteRequest,
    SyncResult,
    SyncSectorMembershipRequest,
    SyncValuationRequest,
)
from apps.data_center.domain.entities import (
    PriceBar,
    ProviderConfig,
    QuoteSnapshot,
    RawAudit,
)
from apps.data_center.domain.protocols import (
    FinancialFactRepositoryProtocol,
    FundNavRepositoryProtocol,
    PriceBarRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    QuoteSnapshotRepositoryProtocol,
    RawAuditRepositoryProtocol,
    SectorMembershipRepositoryProtocol,
    UnifiedDataProviderProtocol,
    ValuationFactRepositoryProtocol,
)

from .provider_health_recorder import persist_provider_health_metric
from .publication_sync import (
    PublishFinancialBatchUseCase,
    PublishFundNavBatchUseCase,
    PublishPriceBarBatchUseCase,
    PublishQuoteSnapshotBatchUseCase,
    PublishSectorMembershipBatchUseCase,
    PublishValuationBatchUseCase,
)
from .sync_identity import (
    IssueSyncExecutionIdentityCommand,
    IssueSyncExecutionIdentityUseCase,
    SyncExecutionIdentity,
    SyncExecutionIdentityIssuer,
)
from .sync_transaction import (
    DataCenterSyncClock,
    DataCenterSyncUnitOfWork,
    DataFetchAuditWriter,
    DataProviderHealthAuditWriter,
    DataPublicationAuditWriter,
    DataPublicationQualityRecorder,
)

if TYPE_CHECKING:
    from .sync_macro_use_cases import (
        MacroFailoverPolicy,
        MacroFailoverPolicyProvider,
        PreparedMacroSync,
        SyncMacroBatchUseCase,
        SyncMacroUseCase,
    )
    from .sync_news_capital_use_cases import SyncCapitalFlowUseCase, SyncNewsUseCase

FactT = TypeVar("FactT")

RECOVERABLE_DATA_CENTER_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
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


class SyncPriceUseCase(_BaseSyncUseCase):
    """Synchronize price bars with facts, evidence, publication, and audit atomically."""

    dataset_key = "equity.price.bar"
    capability = "historical_price"
    publication_key = "current"

    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: PriceBarRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishPriceBarBatchUseCase | None = None,
        *,
        sync_identity_issuer: SyncExecutionIdentityIssuer,
        sync_unit_of_work: DataCenterSyncUnitOfWork,
        data_fetch_audit_writer: DataFetchAuditWriter,
        data_publication_audit_writer: DataPublicationAuditWriter,
        publication_quality_recorder: DataPublicationQualityRecorder | None = None,
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
        self._clock = clock

    def execute(self, request: SyncPriceRequest) -> SyncResult:
        """Fetch and atomically persist one canonical historical-price batch."""

        config, provider = self._get_provider(request.provider_id)
        provider_name = provider.provider_name()
        request_params: Mapping[str, object] = {
            "asset_code": request.asset_code,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
        }
        started_at = self._clock.now()
        try:
            bars = provider.fetch_price_history(request.asset_code, request.start, request.end)
            bars = [
                dataclasses.replace(
                    bar,
                    source=str(bar.source or config.source_type).strip(),
                )
                for bar in bars
            ]
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as error:
            self._commit_price_fetch_failure(
                config=config,
                provider_name=provider_name,
                request_params=request_params,
                started_at=started_at,
                error=error,
            )
            raise
        return self._commit_price_fetch_success(
            config=config,
            provider_name=provider_name,
            request_params=request_params,
            bars=bars,
            started_at=started_at,
        )

    def _issue_identity(self, *, provider_name: str) -> SyncExecutionIdentity:
        """Issue one price-sync identity inside the active transaction."""

        return self._identity_use_case.execute(
            IssueSyncExecutionIdentityCommand(
                dataset_key=self.dataset_key,
                provider_name=provider_name,
            )
        )

    def _commit_price_fetch_success(
        self,
        *,
        config: ProviderConfig,
        provider_name: str,
        request_params: Mapping[str, object],
        bars: list[PriceBar],
        started_at: datetime,
    ) -> SyncResult:
        """Commit price facts, exact evidence, and canonical events in one UOW."""

        publication_error: ValueError | None = None
        publication_blocked_reason: str | None = None
        with self._sync_unit_of_work.atomic():
            identity = self._issue_identity(provider_name=provider_name)
            correlated_bars = [
                dataclasses.replace(bar, ingested_run_id=identity.ingested_run_id) for bar in bars
            ]
            stored_count = self._facts.bulk_upsert(correlated_bars) if correlated_bars else 0
            publication = None
            if self._publication_publisher is not None and correlated_bars:
                publication_at = self._clock.now()
                try:
                    publication = self._publication_publisher.execute(
                        correlated_bars,
                        provider_name=provider_name,
                        publication_key=self.publication_key,
                        run_id=identity.run_id,
                        published_at=publication_at,
                    )
                except ValueError as error:
                    publication_error = error
                    publication_blocked_reason = "publication_policy_rejected"
                if publication is None and publication_error is None:
                    publication_error = ValueError("price publication returned no result")
                    publication_blocked_reason = "publication_no_result"
            audit_status, result_status = _sync_status(stored_count)
            recorded_at = self._clock.now()
            latency_ms = max(0.0, (recorded_at - started_at).total_seconds() * 1000)
            self._persist_provider_health_metric(
                config,
                capability=self.capability,
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
                    self.capability,
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
                    capability=self.capability,
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
            if self._publication_publisher is not None and correlated_bars:
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
                        publication_key=self.publication_key,
                        provider_name=provider_name,
                        run_id=identity.run_id,
                        ingested_run_id=identity.ingested_run_id,
                        blocked_reason=blocked_reason,
                    )
                    publication_observation = DataPublicationAuditObservation(
                        dataset_key=identity.dataset_key,
                        publication_key=self.publication_key,
                        publication_id=f"publication-attempt-{attempt_hash[:48]}",
                        publication_version="attempt-v1",
                        publication_hash=attempt_hash,
                        provider_key=provider_name,
                        run_id=identity.run_id,
                        ingested_run_id=identity.ingested_run_id,
                        member_count=0,
                        coverage_requested_count=len(correlated_bars),
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
            self.capability,
            provider_name,
            stored_count,
            result_status,
            run_id=identity.run_id,
            ingested_run_id=identity.ingested_run_id,
            publication_id=publication.publication_id if publication is not None else None,
            publication_version=publication.policy_version if publication is not None else None,
            publication_hash=publication.publication_hash if publication is not None else None,
        )

    def _commit_price_fetch_failure(
        self,
        *,
        config: ProviderConfig,
        provider_name: str,
        request_params: Mapping[str, object],
        started_at: datetime,
        error: BaseException,
    ) -> None:
        """Persist one sanitized failed price fetch before reraising its error."""

        with self._sync_unit_of_work.atomic():
            identity = self._issue_identity(provider_name=provider_name)
            recorded_at = self._clock.now()
            latency_ms = max(0.0, (recorded_at - started_at).total_seconds() * 1000)
            error_class = type(error).__name__
            self._persist_provider_health_metric(
                config,
                capability=self.capability,
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
                    self.capability,
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
                    capability=self.capability,
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


class SyncQuoteUseCase(_BaseSyncUseCase):
    """Synchronize quote snapshots with evidence and publication atomically."""

    dataset_key = "equity.quote.snapshot"
    capability = "realtime_quote"
    publication_key = "current"

    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: QuoteSnapshotRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishQuoteSnapshotBatchUseCase | None = None,
        *,
        sync_identity_issuer: SyncExecutionIdentityIssuer,
        sync_unit_of_work: DataCenterSyncUnitOfWork,
        data_fetch_audit_writer: DataFetchAuditWriter,
        data_publication_audit_writer: DataPublicationAuditWriter,
        publication_quality_recorder: DataPublicationQualityRecorder | None = None,
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
        self._clock = clock

    def execute(self, request: SyncQuoteRequest) -> SyncResult:
        """Fetch and atomically persist one canonical quote snapshot batch."""

        config, provider = self._get_provider(request.provider_id)
        provider_name = provider.provider_name()
        request_params: Mapping[str, object] = {"asset_codes": list(request.asset_codes)}
        started_at = self._clock.now()
        try:
            quotes = provider.fetch_quote_snapshots(request.asset_codes)
            quotes = self._normalize_fact_sources(
                quotes,
                source_type=config.source_type,
                provider_name=provider_name,
            )
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as error:
            self._commit_quote_fetch_failure(
                config=config,
                provider_name=provider_name,
                request_params=request_params,
                started_at=started_at,
                error=error,
            )
            raise
        return self._commit_quote_fetch_success(
            config=config,
            provider_name=provider_name,
            request_params=request_params,
            quotes=quotes,
            started_at=started_at,
        )

    def _issue_identity(self, *, provider_name: str) -> SyncExecutionIdentity:
        """Issue one quote-sync identity inside the active transaction."""

        return self._identity_use_case.execute(
            IssueSyncExecutionIdentityCommand(
                dataset_key=self.dataset_key,
                provider_name=provider_name,
            )
        )

    def _commit_quote_fetch_success(
        self,
        *,
        config: ProviderConfig,
        provider_name: str,
        request_params: Mapping[str, object],
        quotes: list[QuoteSnapshot],
        started_at: datetime,
    ) -> SyncResult:
        """Commit quote facts, exact evidence, and canonical events in one UOW."""

        publication_error: ValueError | None = None
        publication_blocked_reason: str | None = None
        with self._sync_unit_of_work.atomic():
            identity = self._issue_identity(provider_name=provider_name)
            correlated_quotes = [
                dataclasses.replace(quote, ingested_run_id=identity.ingested_run_id)
                for quote in quotes
            ]
            stored_count = self._facts.bulk_upsert(correlated_quotes) if correlated_quotes else 0
            publication = None
            if self._publication_publisher is not None and correlated_quotes:
                publication_at = self._clock.now()
                try:
                    publication = self._publication_publisher.execute(
                        correlated_quotes,
                        provider_name=provider_name,
                        publication_key=self.publication_key,
                        run_id=identity.run_id,
                        published_at=publication_at,
                    )
                except ValueError as error:
                    publication_error = error
                    publication_blocked_reason = "publication_policy_rejected"
                if publication is None and publication_error is None:
                    publication_error = ValueError("quote publication returned no result")
                    publication_blocked_reason = "publication_no_result"
            audit_status, result_status = _sync_status(stored_count)
            recorded_at = self._clock.now()
            latency_ms = max(0.0, (recorded_at - started_at).total_seconds() * 1000)
            self._persist_provider_health_metric(
                config,
                capability=self.capability,
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
                    self.capability,
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
                    capability=self.capability,
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
            if self._publication_publisher is not None and correlated_quotes:
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
                        publication_key=self.publication_key,
                        provider_name=provider_name,
                        run_id=identity.run_id,
                        ingested_run_id=identity.ingested_run_id,
                        blocked_reason=blocked_reason,
                    )
                    publication_observation = DataPublicationAuditObservation(
                        dataset_key=identity.dataset_key,
                        publication_key=self.publication_key,
                        publication_id=f"publication-attempt-{attempt_hash[:48]}",
                        publication_version="attempt-v1",
                        publication_hash=attempt_hash,
                        provider_key=provider_name,
                        run_id=identity.run_id,
                        ingested_run_id=identity.ingested_run_id,
                        member_count=0,
                        coverage_requested_count=len(correlated_quotes),
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
            self.capability,
            provider_name,
            stored_count,
            result_status,
            run_id=identity.run_id,
            ingested_run_id=identity.ingested_run_id,
            publication_id=publication.publication_id if publication is not None else None,
            publication_version=publication.policy_version if publication is not None else None,
            publication_hash=publication.publication_hash if publication is not None else None,
        )

    def _commit_quote_fetch_failure(
        self,
        *,
        config: ProviderConfig,
        provider_name: str,
        request_params: Mapping[str, object],
        started_at: datetime,
        error: BaseException,
    ) -> None:
        """Persist one sanitized failed quote fetch before reraising its error."""

        with self._sync_unit_of_work.atomic():
            identity = self._issue_identity(provider_name=provider_name)
            recorded_at = self._clock.now()
            latency_ms = max(0.0, (recorded_at - started_at).total_seconds() * 1000)
            error_class = type(error).__name__
            self._persist_provider_health_metric(
                config,
                capability=self.capability,
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
                    self.capability,
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
                    capability=self.capability,
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


class SyncFinancialUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: FinancialFactRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishFinancialBatchUseCase | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._publication_publisher = publication_publisher

    def execute(self, request: SyncFinancialRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        params = {"asset_code": request.asset_code, "periods": request.periods}
        try:
            facts = provider.fetch_financials(request.asset_code, periods=request.periods)
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
                capability="financial",
                request_params=params,
                status=audit_status,
                row_count=stored_count,
                latency_ms=latency_ms,
            )
            return SyncResult("financial", provider.provider_name(), stored_count, result_status)
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="financial",
                request_params=params,
                status="error",
                row_count=0,
                latency_ms=latency_ms,
                error_message=str(exc),
            )
            raise


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
    "MacroFailoverDecision",
    "MacroFailoverPolicy",
    "MacroFailoverPolicyProvider",
    "PreparedMacroSync",
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
