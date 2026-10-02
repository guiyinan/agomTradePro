"""Current valuation batch synchronization."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import date, datetime

from apps.data_center.application.dtos import SyncValuationBatchResult
from apps.data_center.domain.entities import ProviderConfig, ValuationFact
from apps.data_center.domain.protocols import (
    CurrentValuationBatchProviderProtocol,
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    RawAuditRepositoryProtocol,
    ValuationFactRepositoryProtocol,
)
from core.exceptions import DataFetchError
from core.integration.data_center_audit import AuditOutcome, DataFetchAuditObservation

from .batch_identity import require_exact_asset_identities
from .publication_sync import PublishValuationBatchUseCase
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
)
from .sync_use_cases import RECOVERABLE_DATA_CENTER_EXCEPTIONS, _BaseSyncUseCase, _build_sync_audit


class SyncCurrentValuationBatchUseCase(_BaseSyncUseCase):
    """Persist current valuation coverage with exact same-UOW lineage."""

    dataset_key = "equity.valuation.fact"
    capability = "valuation"

    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: ValuationFactRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishValuationBatchUseCase | None = None,
        *,
        sync_identity_issuer: SyncExecutionIdentityIssuer,
        sync_unit_of_work: DataCenterSyncUnitOfWork,
        data_fetch_audit_writer: DataFetchAuditWriter,
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
        self._identity_use_case = IssueSyncExecutionIdentityUseCase(sync_identity_issuer)
        self._sync_unit_of_work = sync_unit_of_work
        self._data_fetch_audit_writer = data_fetch_audit_writer
        self._clock = clock

    def execute(
        self,
        *,
        provider_id: int,
        asset_codes: list[str],
        as_of_date: date,
        require_exact_asset_codes: bool = False,
    ) -> SyncValuationBatchResult:
        """Fetch one valuation row per available asset and commit its lineage."""

        config, provider = self._get_provider(provider_id)
        provider_name = provider.provider_name()
        started_at = self._clock.now()
        request_params: Mapping[str, object] = {
            "asset_count": len(asset_codes),
            "as_of_date": as_of_date.isoformat(),
        }
        try:
            if isinstance(provider, CurrentValuationBatchProviderProtocol):
                facts = provider.fetch_current_valuations(asset_codes, as_of_date)
            else:
                facts = []
                for asset_code in asset_codes:
                    facts.extend(provider.fetch_valuations(asset_code, as_of_date, as_of_date))
            facts = [
                dataclasses.replace(fact, source=str(fact.source or config.source_type).strip())
                for fact in facts
            ]
            if require_exact_asset_codes:
                require_exact_asset_identities(
                    requested_asset_codes=asset_codes,
                    returned_asset_codes=[fact.asset_code for fact in facts],
                    label="valuation",
                )
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS + (DataFetchError,) as error:
            self._commit_fetch_failure(
                config=config,
                provider_name=provider_name,
                request_params=request_params,
                started_at=started_at,
                error=error,
            )
            raise
        return self._commit_fetch_success(
            config=config,
            provider_name=provider_name,
            request_params=request_params,
            facts=facts,
            requested_asset_codes=asset_codes,
            started_at=started_at,
        )

    def _issue_identity(self, *, provider_name: str) -> SyncExecutionIdentity:
        """Issue one valuation-sync identity inside the active transaction."""

        return self._identity_use_case.execute(
            IssueSyncExecutionIdentityCommand(
                dataset_key=self.dataset_key,
                provider_name=provider_name,
            )
        )

    def _commit_fetch_success(
        self,
        *,
        config: ProviderConfig,
        provider_name: str,
        request_params: Mapping[str, object],
        facts: list[ValuationFact],
        requested_asset_codes: list[str],
        started_at: datetime,
    ) -> SyncValuationBatchResult:
        """Commit valuation facts, health, and exact fetch audit in one UOW."""

        with self._sync_unit_of_work.atomic():
            identity = self._issue_identity(provider_name=provider_name)
            correlated_facts = [
                dataclasses.replace(fact, ingested_run_id=identity.ingested_run_id)
                for fact in facts
            ]
            stored_count = self._facts.bulk_upsert(correlated_facts) if correlated_facts else 0
            if self._publication_publisher is not None and correlated_facts:
                self._publication_publisher.execute(
                    correlated_facts,
                    provider_name=provider_name,
                )

            succeeded_asset_codes = sorted({fact.asset_code for fact in correlated_facts})
            complete = len(succeeded_asset_codes) == len(requested_asset_codes)
            if stored_count > 0:
                result_status = "success" if complete else "partial"
                audit_status = "ok"
                audit_outcome = AuditOutcome.SUCCESS
                audit_error_class: str | None = None
                error_message = "" if complete else "valuation_batch_incomplete"
            else:
                if not requested_asset_codes:
                    result_status = "noop"
                    audit_status = "skipped"
                    audit_outcome = AuditOutcome.NOOP
                    audit_error_class = None
                    error_message = "empty_valuation_scope"
                else:
                    result_status = "failed" if not succeeded_asset_codes else "noop"
                    audit_status = "error"
                    audit_outcome = AuditOutcome.FAILED
                    audit_error_class = "valuation_batch_incomplete"
                    error_message = "valuation_batch_incomplete"

            recorded_at = self._clock.now()
            latency_ms = max(0.0, (recorded_at - started_at).total_seconds() * 1000)
            provider_error_message = "" if stored_count > 0 else error_message
            self._persist_provider_health_metric(
                config,
                capability=self.capability,
                latency_ms=latency_ms,
                success=stored_count > 0,
                error=provider_error_message,
                recorded_at=recorded_at,
                output_count=stored_count,
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
                    provider_error_message,
                    fetched_at=recorded_at,
                    run_id=identity.run_id,
                    ingested_run_id=identity.ingested_run_id,
                    extra={"source_type": config.source_type},
                )
            )
            reference = persisted_audit.exact_reference()
            _require_reference_identity(reference.run_id, identity.run_id, "run_id")
            _require_reference_identity(
                reference.ingested_run_id,
                identity.ingested_run_id,
                "ingested_run_id",
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
                    outcome=audit_outcome,
                    row_count=stored_count if audit_outcome is AuditOutcome.SUCCESS else 0,
                    occurred_at=recorded_at,
                    recorded_at=recorded_at,
                    error_class=audit_error_class,
                )
            )

        return SyncValuationBatchResult(
            domain=self.capability,
            provider_name=provider_name,
            stored_count=stored_count,
            status=result_status,
            succeeded_asset_codes=succeeded_asset_codes,
            returned_asset_codes=tuple(fact.asset_code for fact in correlated_facts),
            run_id=identity.run_id,
            ingested_run_id=identity.ingested_run_id,
            raw_audit_reference=reference,
            error_message=error_message,
        )

    def _commit_fetch_failure(
        self,
        *,
        config: ProviderConfig,
        provider_name: str,
        request_params: Mapping[str, object],
        started_at: datetime,
        error: BaseException,
    ) -> None:
        """Commit one failed fetch and its provider-health evidence before reraising."""

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
            _require_reference_identity(reference.run_id, identity.run_id, "run_id")
            _require_reference_identity(
                reference.ingested_run_id,
                identity.ingested_run_id,
                "ingested_run_id",
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


def _require_reference_identity(actual: str, expected: str, field_name: str) -> None:
    """Reject a persisted RawAudit reference bound to another sync identity."""

    if actual != expected:
        raise ValueError(f"RawAudit {field_name} does not match the issued sync identity")


__all__ = ["SyncCurrentValuationBatchUseCase"]
