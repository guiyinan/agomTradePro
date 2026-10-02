"""Audited price-bar and quote synchronization use cases."""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Mapping
from datetime import date, datetime

from apps.data_center.application.dtos import SyncPriceRequest, SyncQuoteRequest, SyncResult
from apps.data_center.domain.entities import (
    PriceBar,
    ProviderConfig,
    QuoteSnapshot,
    RawAuditReference,
)
from apps.data_center.domain.model_market_data import ModelDailyBar
from apps.data_center.domain.protocols import (
    PriceBarRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    QuoteSnapshotRepositoryProtocol,
    RawAuditRepositoryProtocol,
    SessionQuoteBatchProviderProtocol,
)
from core.exceptions import DataFetchError
from core.integration.data_center_audit import (
    AuditOutcome,
    DataFetchAuditObservation,
    DataPublicationAuditObservation,
)

from .batch_identity import require_exact_asset_identities
from .full_market_task_support import asset_code_scope_sha256
from .model_history_preparation import (
    ModelHistoryFetchAuditResult,
    ModelHistoryReferenceSnapshot,
)
from .publication_sync import PublishPriceBarBatchUseCase, PublishQuoteSnapshotBatchUseCase
from .quote_session_prefetch import (
    PreparedQuoteSession,
    QuoteSessionMissingAssetVerifier,
    prepare_quote_session,
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
        result, _reference = self._commit_price_fetch_success(
            config=config,
            provider_name=provider_name,
            request_params=request_params,
            bars=bars,
            started_at=started_at,
        )
        return result

    def record_model_history_fetch_success(
        self,
        *,
        provider_id: int,
        asset_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
        rows: tuple[ModelDailyBar, ...],
        request_details: Mapping[str, object],
        reference_snapshot: ModelHistoryReferenceSnapshot,
    ) -> ModelHistoryFetchAuditResult:
        """Commit one already-normalized provider fetch with its exact audit reference."""

        config, provider = self._get_provider(provider_id)
        provider_name = provider.provider_name()
        request_params = self._model_history_request_params(
            asset_codes=asset_codes,
            start_date=start_date,
            end_date=end_date,
            request_details=request_details,
        )
        started_at = self._clock.now()
        try:
            self._validate_model_history_rows(
                source_type=config.source_type,
                asset_codes=asset_codes,
                start_date=start_date,
                end_date=end_date,
                rows=rows,
            )
            bars = [
                PriceBar(
                    asset_code=row.asset_code,
                    bar_date=row.trade_date,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                    amount=row.amount,
                    source=config.source_type,
                )
                for row in rows
            ]
        except (ValueError, TypeError, DataFetchError) as error:
            self._commit_price_fetch_failure(
                config=config,
                provider_name=provider_name,
                request_params=request_params,
                started_at=started_at,
                error=error,
                extra={"source_type": config.source_type},
            )
            raise
        if (
            reference_snapshot.asset_codes != tuple(sorted(set(asset_codes)))
            or reference_snapshot.start_date != start_date
            or reference_snapshot.end_date != end_date
        ):
            scope_error = DataFetchError(
                "Model history reference snapshot does not match the fetch scope",
                code="MODEL_MARKET_REFERENCE_SNAPSHOT_SCOPE_INVALID",
            )
            self._commit_price_fetch_failure(
                config=config,
                provider_name=provider_name,
                request_params=request_params,
                started_at=started_at,
                error=scope_error,
                extra={"source_type": config.source_type},
            )
            raise scope_error
        try:
            sync_result, reference = self._commit_price_fetch_success(
                config=config,
                provider_name=provider_name,
                request_params=request_params,
                bars=bars,
                started_at=started_at,
                expected_count=len(bars),
                reference_snapshot=reference_snapshot,
                extra={"source_type": config.source_type},
            )
        except DataFetchError as error:
            self._commit_price_fetch_failure(
                config=config,
                provider_name=provider_name,
                request_params=request_params,
                started_at=started_at,
                error=error,
                extra={"source_type": config.source_type},
            )
            raise
        stored_asset_codes = tuple(sorted({bar.asset_code for bar in bars}))
        return ModelHistoryFetchAuditResult(
            provider_name=provider_name,
            stored_count=sync_result.stored_count,
            stored_asset_codes=stored_asset_codes,
            raw_audit_reference=reference,
        )

    def record_model_history_fetch_failure(
        self,
        *,
        provider_id: int,
        asset_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
        error: BaseException,
        request_details: Mapping[str, object],
    ) -> RawAuditReference:
        """Commit a sanitized stable RawAudit for one failed provider attempt."""

        config, provider = self._get_provider(provider_id)
        request_params = self._model_history_request_params(
            asset_codes=asset_codes,
            start_date=start_date,
            end_date=end_date,
            request_details=request_details,
        )
        return self._commit_price_fetch_failure(
            config=config,
            provider_name=provider.provider_name(),
            request_params=request_params,
            started_at=self._clock.now(),
            error=error,
            extra={"source_type": config.source_type},
        )

    @staticmethod
    def _model_history_request_params(
        *,
        asset_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
        request_details: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Build bounded, provider-secret-free model-history audit parameters."""

        if (
            start_date > end_date
            or not asset_codes
            or len(set(asset_codes)) != len(asset_codes)
            or any(not code or code != code.strip().upper() for code in asset_codes)
        ):
            raise DataFetchError(
                "Model history fetch scope is invalid", code="MODEL_MARKET_AUDIT_SCOPE_INVALID"
            )
        details = dict(request_details)
        allowed_detail_keys = {"provider_fetch_kind", "provider_trade_date"}
        if set(details) - allowed_detail_keys:
            raise DataFetchError(
                "Model history audit request details exceed the bounded contract",
                code="MODEL_MARKET_AUDIT_SCOPE_INVALID",
            )
        if any(
            not isinstance(value, str) or not value or len(value) > 64 for value in details.values()
        ):
            raise DataFetchError(
                "Model history audit request details are invalid",
                code="MODEL_MARKET_AUDIT_SCOPE_INVALID",
            )
        request_params = {
            **details,
            "asset_count": len(asset_codes),
            "asset_codes_sha256": asset_code_scope_sha256(asset_codes),
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        }
        if len(json.dumps(request_params, ensure_ascii=False, separators=(",", ":"))) > 512:
            raise DataFetchError(
                "Model history audit request exceeds its storage bound",
                code="MODEL_MARKET_AUDIT_SCOPE_INVALID",
            )
        return request_params

    @staticmethod
    def _validate_model_history_rows(
        *,
        source_type: str,
        asset_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
        rows: tuple[ModelDailyBar, ...],
    ) -> None:
        """Reject mismatched or duplicate observations before assigning lineage."""

        allowed_codes = set(asset_codes)
        seen: set[tuple[str, date]] = set()
        for row in rows:
            identity = (row.asset_code, row.trade_date)
            prices = (row.open, row.high, row.low, row.close)
            if (
                row.asset_code not in allowed_codes
                or not start_date <= row.trade_date <= end_date
                or identity in seen
                or row.source != source_type
                or any(not math.isfinite(value) or value <= 0 for value in prices)
                or row.high < max(prices)
                or row.low > min(prices)
                or not math.isfinite(row.volume)
                or row.volume < 0
                or not math.isfinite(row.change_percent)
                or row.adjustment_factor is None
                or not math.isfinite(row.adjustment_factor)
                or row.adjustment_factor <= 0
                or (row.amount is not None and (not math.isfinite(row.amount) or row.amount < 0))
            ):
                raise DataFetchError(
                    "Invalid normalized model history batch",
                    code="MODEL_MARKET_INVALID",
                )
            seen.add(identity)

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
        expected_count: int | None = None,
        reference_snapshot: ModelHistoryReferenceSnapshot | None = None,
        extra: Mapping[str, object] | None = None,
    ) -> tuple[SyncResult, RawAuditReference]:
        """Commit price facts, exact evidence, and canonical events in one UOW."""

        publication_error: ValueError | None = None
        publication_blocked_reason: str | None = None
        with self._sync_unit_of_work.atomic():
            if reference_snapshot is not None:
                current = self._facts.get_bars_for_assets(
                    reference_snapshot.asset_codes,
                    start=reference_snapshot.start_date,
                    end=reference_snapshot.end_date,
                    limit=5000,
                )
                current_snapshot = ModelHistoryReferenceSnapshot.from_bars(
                    reference_snapshot.asset_codes,
                    reference_snapshot.start_date,
                    reference_snapshot.end_date,
                    current,
                )
                if current_snapshot.content_hash != reference_snapshot.content_hash:
                    raise DataFetchError(
                        "Model history reference state changed before atomic persistence",
                        code="MODEL_MARKET_REFERENCE_SNAPSHOT_CHANGED",
                    )
            identity = self._issue_identity(provider_name=provider_name)
            correlated_bars = [
                dataclasses.replace(bar, ingested_run_id=identity.ingested_run_id) for bar in bars
            ]
            stored_count = self._facts.bulk_upsert(correlated_bars) if correlated_bars else 0
            if expected_count is not None and stored_count != expected_count:
                raise DataFetchError(
                    "Model history facts were not fully persisted",
                    code="MODEL_MARKET_AUDIT_FACT_COUNT_MISMATCH",
                    details={"expected_count": expected_count, "stored_count": stored_count},
                )
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
                    extra=extra,
                )
            )
            reference = persisted_audit.exact_reference()
            if (
                reference.run_id != identity.run_id
                or reference.ingested_run_id != identity.ingested_run_id
            ):
                raise DataFetchError(
                    "Persisted price audit identity does not match the fact batch",
                    code="MODEL_MARKET_AUDIT_IDENTITY_MISMATCH",
                )
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
        return (
            SyncResult(
                self.capability,
                provider_name,
                stored_count,
                result_status,
                run_id=identity.run_id,
                ingested_run_id=identity.ingested_run_id,
                publication_id=publication.publication_id if publication is not None else None,
                publication_version=publication.policy_version if publication is not None else None,
                publication_hash=publication.publication_hash if publication is not None else None,
            ),
            reference,
        )

    def _commit_price_fetch_failure(
        self,
        *,
        config: ProviderConfig,
        provider_name: str,
        request_params: Mapping[str, object],
        started_at: datetime,
        error: BaseException,
        extra: Mapping[str, object] | None = None,
    ) -> RawAuditReference:
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
                    extra=extra,
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
            return reference


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
            if request.target_trade_date is not None:
                from apps.data_center.domain.protocols import SessionQuoteBatchProviderProtocol

                if not isinstance(provider, SessionQuoteBatchProviderProtocol):
                    raise DataFetchError(
                        "Provider cannot fetch an explicit quote session",
                        code="CURRENT_QUOTE_SESSION_UNSUPPORTED",
                    )
                quotes = provider.fetch_quote_snapshots_for_session(
                    request.asset_codes,
                    request.target_trade_date,
                )
            else:
                quotes = provider.fetch_quote_snapshots(request.asset_codes)
            quotes = self._normalize_fact_sources(
                quotes,
                source_type=config.source_type,
                provider_name=provider_name,
            )
            if request.require_exact_asset_codes:
                require_exact_asset_identities(
                    requested_asset_codes=request.asset_codes,
                    returned_asset_codes=[quote.asset_code for quote in quotes],
                    label="quote",
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

    def prepare_session(
        self,
        *,
        provider_id: int,
        asset_codes: tuple[str, ...],
        target_trade_date: date,
        missing_asset_verifier: QuoteSessionMissingAssetVerifier | None = None,
    ) -> PreparedQuoteSession:
        """Fetch and freeze one provider session for subsequent bounded writes.

        The default remains exact scope.  A verifier is supplied only by the
        full-market orchestration when every missing row must be proven to be a
        target-day full suspension before it can be excluded.
        """

        config, provider = self._get_provider(provider_id)
        provider_name = provider.provider_name()
        request_params: Mapping[str, object] = {
            "asset_count": len(asset_codes),
            "quote_session_universe_sha256": asset_code_scope_sha256(asset_codes),
            "target_trade_date": target_trade_date.isoformat(),
            "quote_session_prefetch": True,
        }
        started_at = self._clock.now()
        try:
            if not isinstance(provider, SessionQuoteBatchProviderProtocol):
                raise DataFetchError(
                    "Provider cannot fetch an explicit quote session",
                    code="CURRENT_QUOTE_SESSION_UNSUPPORTED",
                )
            return prepare_quote_session(
                provider=provider,
                provider_id=provider_id,
                provider_name=provider_name,
                source_type=config.source_type,
                asset_codes=asset_codes,
                target_trade_date=target_trade_date,
                missing_asset_verifier=missing_asset_verifier,
            )
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS + (DataFetchError,) as error:
            self._commit_quote_fetch_failure(
                config=config,
                provider_name=provider_name,
                request_params=request_params,
                started_at=started_at,
                error=error,
            )
            raise

    def execute_prefetched_session_batch(
        self, request: SyncQuoteRequest, prepared: PreparedQuoteSession
    ) -> SyncResult:
        """Persist one exact batch from a task-local frozen market-session response."""

        if not isinstance(prepared, PreparedQuoteSession):
            raise DataFetchError(
                "A prepared quote session is required",
                code="CURRENT_QUOTE_SESSION_SCOPE_INVALID",
            )
        if (
            request.require_exact_asset_codes is not True
            or request.target_trade_date != prepared.target_trade_date
            or request.provider_id != prepared.provider_id
            or tuple(request.asset_codes)
            != tuple(str(code or "").strip().upper() for code in request.asset_codes)
        ):
            raise DataFetchError(
                "Prepared quote batch request does not match its frozen session",
                code="CURRENT_QUOTE_SESSION_SCOPE_MISMATCH",
            )
        config, provider = self._get_provider(request.provider_id)
        provider_name = provider.provider_name()
        if provider_name != prepared.provider_name or config.source_type != prepared.source_type:
            raise DataFetchError(
                "Prepared quote session provider identity changed",
                code="CURRENT_QUOTE_SESSION_PROVIDER_MISMATCH",
            )
        quotes = self._normalize_fact_sources(
            list(prepared.quote_rows_for(tuple(request.asset_codes))),
            source_type=config.source_type,
            provider_name=provider_name,
        )
        request_params: Mapping[str, object] = {
            "asset_codes": list(request.asset_codes),
            "target_trade_date": prepared.target_trade_date.isoformat(),
            "quote_session_universe_sha256": prepared.universe_sha256,
            "quote_session_rows_sha256": prepared.quote_rows_sha256,
            "quote_session_response_completed_at": (
                prepared.response_completed_at.isoformat()
                if prepared.response_completed_at is not None
                else None
            ),
            "quote_session_raw_response_sha256s": list(prepared.raw_response_sha256s),
            "quote_session_available_codes": list(prepared.available_codes),
            "quote_session_eligible_codes": list(prepared.eligible_codes),
            "quote_session_excluded_codes": list(prepared.excluded_codes),
        }
        return self._commit_quote_fetch_success(
            config=config,
            provider_name=provider_name,
            request_params=request_params,
            quotes=quotes,
            started_at=self._clock.now(),
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
            stored_asset_codes=tuple(quote.asset_code for quote in correlated_quotes),
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
