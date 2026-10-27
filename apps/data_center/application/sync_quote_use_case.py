"""Audited quote synchronization use case."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import date, datetime

from apps.data_center.application.dtos import SyncQuoteRequest, SyncResult
from apps.data_center.domain.entities import ProviderConfig, QuoteSnapshot
from apps.data_center.domain.protocols import (
    DatasetContractRepositoryProtocol,
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
from .provider_response_payload import ProviderResponsePayloadReference
from .publication_sync import PublishQuoteSnapshotBatchUseCase
from .quote_metric_normalization import normalize_quote_snapshot_change_pct
from .quote_response_capture import (
    CapturedQuoteSnapshotResponse,
    ExactQuoteResponseProviderProtocol,
    ProviderResponsePayloadRetainerProtocol,
)
from .quote_session_capture import (
    CapturedQuoteSessionResponse,
    QuoteSessionCaptureOrigin,
    RetainedQuoteSessionCapture,
    SessionQuoteResponseProviderProtocol,
    validate_quote_session_capture_binding,
)
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


def _validate_exact_quote_capture(
    response: CapturedQuoteSnapshotResponse,
    *,
    provider_id: int | None,
    provider_name: str,
    asset_code: str,
    target_trade_date: date,
) -> None:
    """Recheck one quote/capture binding at fetch and transaction boundaries."""

    if not isinstance(response, CapturedQuoteSnapshotResponse):
        raise DataFetchError(
            "Exact quote provider returned no typed response capture",
            code="CURRENT_QUOTE_RESPONSE_CAPTURE_INVALID",
        )
    scope = response.request_scope
    capture = response.capture
    quote = response.quote
    if (
        provider_id is None
        or scope.provider_id != provider_id
        or scope.provider_name != provider_name
        or scope.dataset_key != "equity.quote.snapshot"
        or scope.api_name != "daily"
        or scope.asset_code != asset_code
        or scope.trade_date != target_trade_date
        or quote.asset_code != asset_code
        or not capture.payload_matches_body()
        or quote.fetched_at != capture.response_completed_at
    ):
        raise DataFetchError(
            "Exact quote response does not match its request identity",
            code="CURRENT_QUOTE_RESPONSE_SCOPE_MISMATCH",
        )
    extra = quote.extra
    expected_record_id = (
        f"tushare:daily:{target_trade_date.strftime('%Y%m%d')}:{asset_code}:"
        f"{capture.body_sha256[:16]}"
    )
    if (
        extra.get("raw_payload_hash") != capture.body_sha256
        or extra.get("raw_payload_scope") != "batch_response_body"
        or extra.get("source_record_id") != expected_record_id
    ):
        raise DataFetchError(
            "Exact quote facts are not bound to their provider response body",
            code="CURRENT_QUOTE_RESPONSE_BODY_MISMATCH",
        )


def _validate_quote_payload_reference(
    reference: ProviderResponsePayloadReference,
    *,
    captured_response: CapturedQuoteSnapshotResponse,
    run_id: str,
) -> None:
    """Require the immutable RawPayload reference to bind this exact sync run."""

    scope = captured_response.request_scope
    capture = captured_response.capture
    if not isinstance(reference, ProviderResponsePayloadReference):
        raise DataFetchError(
            "Retained quote payload reference is invalid",
            code="CURRENT_QUOTE_RESPONSE_REFERENCE_MISMATCH",
        )
    if (
        reference.provider_name != scope.provider_name
        or reference.dataset_key != scope.dataset_key
        or reference.body_sha256 != capture.body_sha256
        or reference.body_size_bytes != capture.body_size_bytes
        or reference.response_completed_at != capture.response_completed_at
        or reference.transport != capture.transport
        or reference.run_id != run_id
    ):
        raise DataFetchError(
            "Retained quote payload reference does not match its sync identity",
            code="CURRENT_QUOTE_RESPONSE_REFERENCE_MISMATCH",
        )


class _QuoteSessionCaptureBinder:
    """Bind an advertised full-session response to one issuer-backed RawPayload."""

    __slots__ = ("_config", "_provider_name", "_started_at", "_use_case")

    def __init__(
        self,
        use_case: SyncQuoteUseCase,
        *,
        config: ProviderConfig,
        provider_name: str,
        started_at: datetime,
    ) -> None:
        """Capture the already-resolved provider and network start context."""

        self._use_case = use_case
        self._config = config
        self._provider_name = provider_name
        self._started_at = started_at

    def bind(self, response: CapturedQuoteSessionResponse) -> RetainedQuoteSessionCapture:
        """Issue the parent identity and retain the one full-session response."""

        return self._use_case._retain_quote_session_capture(
            response,
            config=self._config,
            provider_name=self._provider_name,
            started_at=self._started_at,
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
        dataset_contract_repository: DatasetContractRepositoryProtocol | None = None,
        sync_identity_issuer: SyncExecutionIdentityIssuer,
        sync_unit_of_work: DataCenterSyncUnitOfWork,
        data_fetch_audit_writer: DataFetchAuditWriter,
        data_publication_audit_writer: DataPublicationAuditWriter,
        publication_quality_recorder: DataPublicationQualityRecorder | None = None,
        clock: DataCenterSyncClock,
        data_provider_health_audit_writer: DataProviderHealthAuditWriter | None = None,
        provider_response_payload_retainer: ProviderResponsePayloadRetainerProtocol | None = None,
    ) -> None:
        super().__init__(
            provider_repo,
            provider_registry,
            raw_audit_repo,
            data_provider_health_audit_writer=data_provider_health_audit_writer,
        )
        self._facts = fact_repo
        self._dataset_contracts = dataset_contract_repository
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
        self._provider_response_payload_retainer = provider_response_payload_retainer

    def execute(self, request: SyncQuoteRequest) -> SyncResult:
        """Fetch and atomically persist one canonical quote snapshot batch."""

        config, provider = self._get_provider(request.provider_id)
        provider_name = provider.provider_name()
        request_params: dict[str, object] = {"asset_codes": list(request.asset_codes)}
        if request.target_trade_date is not None:
            request_params["target_trade_date"] = request.target_trade_date.isoformat()
        started_at = self._clock.now()
        captured_response: CapturedQuoteSnapshotResponse | None = None
        try:
            if (
                request.require_exact_asset_codes is True
                and len(request.asset_codes) == 1
                and isinstance(provider, ExactQuoteResponseProviderProtocol)
            ):
                if self._provider_response_payload_retainer is None:
                    raise DataFetchError(
                        "Exact quote response retention is not configured",
                        code="CURRENT_QUOTE_RESPONSE_RETENTION_UNAVAILABLE",
                    )
                target_trade_date = request.target_trade_date
                if target_trade_date is None:
                    from apps.data_center.application.market_calendar import (
                        latest_completed_cn_market_session,
                    )

                    target_trade_date = latest_completed_cn_market_session(started_at)
                if target_trade_date is None:
                    raise DataFetchError(
                        "No completed CN market session is available for exact quote capture",
                        code="CURRENT_QUOTE_SESSION_UNAVAILABLE",
                    )
                captured_response = provider.fetch_quote_snapshot_with_capture(
                    request.asset_codes[0],
                    target_trade_date,
                )
                _validate_exact_quote_capture(
                    captured_response,
                    provider_id=config.id,
                    provider_name=provider_name,
                    asset_code=request.asset_codes[0],
                    target_trade_date=target_trade_date,
                )
                request_params["target_trade_date"] = target_trade_date.isoformat()
                request_params["exact_quote_request_scope"] = (
                    captured_response.request_scope.to_payload()
                )
                quotes = [captured_response.quote]
            elif request.target_trade_date is not None:
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
            quotes = self._normalize_quote_metrics(quotes)
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
            captured_response=captured_response,
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
            if not (
                isinstance(provider, SessionQuoteBatchProviderProtocol)
                or isinstance(provider, SessionQuoteResponseProviderProtocol)
            ):
                raise DataFetchError(
                    "Provider cannot fetch an explicit quote session",
                    code="CURRENT_QUOTE_SESSION_UNSUPPORTED",
                )
            capture_binder: _QuoteSessionCaptureBinder | None = None
            if isinstance(provider, SessionQuoteResponseProviderProtocol):
                if self._provider_response_payload_retainer is None:
                    raise DataFetchError(
                        "Full-session quote response retention is not configured",
                        code="CURRENT_QUOTE_SESSION_CAPTURE_RETENTION_UNAVAILABLE",
                    )
                capture_binder = _QuoteSessionCaptureBinder(
                    self,
                    config=config,
                    provider_name=provider_name,
                    started_at=started_at,
                )
            return prepare_quote_session(
                provider=provider,
                provider_id=provider_id,
                provider_name=provider_name,
                source_type=config.source_type,
                asset_codes=asset_codes,
                target_trade_date=target_trade_date,
                missing_asset_verifier=missing_asset_verifier,
                capture_binder=capture_binder,
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

    def _retain_quote_session_capture(
        self,
        response: CapturedQuoteSessionResponse,
        *,
        config: ProviderConfig,
        provider_name: str,
        started_at: datetime,
    ) -> RetainedQuoteSessionCapture:
        """Persist one captured session under a real server-issued parent identity."""

        retainer = self._provider_response_payload_retainer
        if retainer is None:
            raise DataFetchError(
                "Full-session quote response retention is not configured",
                code="CURRENT_QUOTE_SESSION_CAPTURE_RETENTION_UNAVAILABLE",
            )
        scope = response.request_scope
        if (
            scope.provider_id != config.id
            or scope.provider_name != provider_name
            or scope.dataset_key != self.dataset_key
        ):
            raise DataFetchError(
                "Full-session quote response does not match its selected provider",
                code="CURRENT_QUOTE_SESSION_CAPTURE_SCOPE_MISMATCH",
            )
        completed_at = response.capture.response_completed_at
        latency_ms = max(0.0, (completed_at - started_at).total_seconds() * 1000)
        with self._sync_unit_of_work.atomic():
            identity = self._issue_identity(provider_name=provider_name)
            reference = retainer.execute(
                response.capture,
                provider_name=scope.provider_name,
                dataset_key=scope.dataset_key,
                api_name=scope.api_name,
                request_params=scope.request_params(),
                sensitive_values=response.sensitive_values,
                run_id=identity.run_id,
            )
            capture_origin = QuoteSessionCaptureOrigin(identity=identity, request_scope=scope)
            validate_quote_session_capture_binding(
                capture_origin,
                reference,
                request_scope=scope,
                response=response,
            )
            self._persist_provider_health_metric(
                config,
                capability=self.capability,
                latency_ms=latency_ms,
                success=True,
                output_count=len(response.quotes),
                recorded_at=completed_at,
                run_id=identity.run_id,
                ingested_run_id=identity.ingested_run_id,
            )
        return RetainedQuoteSessionCapture(
            capture_origin=capture_origin,
            payload_reference=reference,
        )

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
        quotes = self._normalize_quote_metrics(quotes)
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
            prepared_session=prepared,
        )

    def _normalize_quote_metrics(self, quotes: list[QuoteSnapshot]) -> list[QuoteSnapshot]:
        """Qualify provider metric candidates against the active typed quote contract."""

        contract_repository = self._dataset_contracts
        if contract_repository is None:
            contract = None
        else:
            try:
                contract = contract_repository.get_active_for_execution(self.dataset_key)
            except ValueError as error:
                raise DataFetchError(
                    "Active quote metric contract is ambiguous",
                    code="QUOTE_METRIC_CONTRACT_AMBIGUOUS",
                ) from error
        return [normalize_quote_snapshot_change_pct(quote, contract) for quote in quotes]

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
        captured_response: CapturedQuoteSnapshotResponse | None = None,
        prepared_session: PreparedQuoteSession | None = None,
    ) -> SyncResult:
        """Commit quote facts, exact evidence, and canonical events in one UOW."""

        publication_error: ValueError | None = None
        publication_blocked_reason: str | None = None
        response_payload_reference: ProviderResponsePayloadReference | None = None
        quote_session_capture: dict[str, object] | None = None
        if prepared_session is not None:
            if (prepared_session.capture_origin is None) != (
                prepared_session.payload_reference is None
            ):
                raise DataFetchError(
                    "Prepared quote session capture binding is incomplete",
                    code="CURRENT_QUOTE_SESSION_CAPTURE_BINDING_INVALID",
                )
            if prepared_session.capture_origin is not None:
                session_reference = prepared_session.payload_reference
                if session_reference is None:
                    raise DataFetchError(
                        "Prepared quote session payload reference is missing",
                        code="CURRENT_QUOTE_SESSION_CAPTURE_BINDING_INVALID",
                    )
                response_payload_reference = session_reference
                quote_session_capture = prepared_session.capture_evidence()
                if quote_session_capture is None:
                    raise DataFetchError(
                        "Prepared quote session capture evidence is missing",
                        code="CURRENT_QUOTE_SESSION_CAPTURE_BINDING_INVALID",
                    )
                validate_quote_session_capture_binding(
                    prepared_session.capture_origin,
                    session_reference,
                    request_scope=prepared_session.capture_origin.request_scope,
                )
                if any(
                    quote.extra.get("quote_session_capture") != quote_session_capture
                    for quote in quotes
                ):
                    raise DataFetchError(
                        "Quote facts detached from their retained session response",
                        code="CURRENT_QUOTE_SESSION_CAPTURE_FACT_MISMATCH",
                    )
        with self._sync_unit_of_work.atomic():
            identity = self._issue_identity(provider_name=provider_name)
            if captured_response is not None:
                _validate_exact_quote_capture(
                    captured_response,
                    provider_id=config.id,
                    provider_name=provider_name,
                    asset_code=captured_response.request_scope.asset_code,
                    target_trade_date=captured_response.request_scope.trade_date,
                )
                retainer = self._provider_response_payload_retainer
                if retainer is None:
                    raise DataFetchError(
                        "Exact quote response retention is not configured",
                        code="CURRENT_QUOTE_RESPONSE_RETENTION_UNAVAILABLE",
                    )
                retained_reference = retainer.execute(
                    captured_response.capture,
                    provider_name=captured_response.request_scope.provider_name,
                    dataset_key=captured_response.request_scope.dataset_key,
                    api_name=captured_response.request_scope.api_name,
                    request_params=captured_response.request_scope.request_params(),
                    sensitive_values=captured_response.sensitive_values,
                    run_id=identity.run_id,
                )
                _validate_quote_payload_reference(
                    retained_reference,
                    captured_response=captured_response,
                    run_id=identity.run_id,
                )
                response_payload_reference = retained_reference
                if len(quotes) != 1 or quotes[0].asset_code != captured_response.quote.asset_code:
                    raise DataFetchError(
                        "Exact quote batch no longer matches its response capture",
                        code="CURRENT_QUOTE_RESPONSE_SCOPE_MISMATCH",
                    )
                quote = quotes[0]
                quote_extra = dict(quote.extra)
                quote_extra["provider_response_request_scope"] = (
                    captured_response.request_scope.to_payload()
                )
                quote_extra["provider_response_payload_reference"] = retained_reference.to_payload()
                quotes = [dataclasses.replace(quote, extra=quote_extra)]
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
            if prepared_session is None or prepared_session.capture_origin is None:
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
            audit_extra: dict[str, object] = {"source_type": config.source_type}
            if quote_session_capture is not None:
                audit_extra["quote_session_capture"] = quote_session_capture
            sync_audit = _build_sync_audit(
                provider_name,
                self.capability,
                request_params,
                audit_status,
                stored_count,
                latency_ms,
                fetched_at=recorded_at,
                run_id=identity.run_id,
                ingested_run_id=identity.ingested_run_id,
                extra=audit_extra,
            )
            if response_payload_reference is not None:
                sync_audit = dataclasses.replace(
                    sync_audit,
                    response_payload_hash=response_payload_reference.payload_hash,
                )
            persisted_audit = self._raw_audit_repo.log(sync_audit)
            reference = persisted_audit.exact_reference()
            if (
                reference.run_id != identity.run_id
                or reference.ingested_run_id != identity.ingested_run_id
            ):
                raise DataFetchError(
                    "Quote RawAudit reference does not match the sync identity",
                    code="CURRENT_QUOTE_RAW_AUDIT_IDENTITY_INVALID",
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
                        provider_key=publication.selected_source,
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
            raw_audit_reference=reference,
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
                    extra={"source_type": config.source_type},
                )
            )
            reference = persisted_audit.exact_reference()
            if (
                reference.run_id != identity.run_id
                or reference.ingested_run_id != identity.ingested_run_id
            ):
                raise DataFetchError(
                    "Quote RawAudit reference does not match the sync identity",
                    code="CURRENT_QUOTE_RAW_AUDIT_IDENTITY_INVALID",
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
                    outcome=AuditOutcome.FAILED,
                    row_count=0,
                    occurred_at=recorded_at,
                    recorded_at=recorded_at,
                    error_class=error_class,
                )
            )


__all__ = ["SyncQuoteUseCase"]
