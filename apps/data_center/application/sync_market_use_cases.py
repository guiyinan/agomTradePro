"""Audited price-bar and quote synchronization use cases."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import datetime

from apps.data_center.application.dtos import SyncPriceRequest, SyncQuoteRequest, SyncResult
from apps.data_center.domain.entities import PriceBar, ProviderConfig, QuoteSnapshot
from apps.data_center.domain.protocols import (
    PriceBarRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    QuoteSnapshotRepositoryProtocol,
    RawAuditRepositoryProtocol,
)
from core.integration.data_center_audit import (
    AuditOutcome,
    DataFetchAuditObservation,
    DataPublicationAuditObservation,
)

from .publication_sync import PublishPriceBarBatchUseCase, PublishQuoteSnapshotBatchUseCase
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
from .sync_use_cases import (
    RECOVERABLE_DATA_CENTER_EXCEPTIONS,
    _BaseSyncUseCase,
    _build_sync_audit,
    _publication_attempt_hash,
    _sync_status,
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


__all__ = ["SyncPriceUseCase", "SyncQuoteUseCase"]
