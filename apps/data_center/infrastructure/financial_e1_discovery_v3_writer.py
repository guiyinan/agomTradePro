"""Same-UOW v3 witness building, native fact writes, and exact readback.

This is an isolated E1 preparation adapter. It uses the canonical repository
API but does not install a verifier or infer any source, metric, unit, or
calendar authority. A caller must inject the real witness builder and a
repository constructed with both numeric and v3 evidence verifiers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections
from django.utils import timezone

from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilityGovernanceRepositoryPort,
    FinancialAvailabilityOwnerEventRepositoryPort,
    FinancialAvailabilitySourceReaderPort,
)
from apps.data_center.application.financial_e1_discovery_runner import (
    FinancialE1ExecutionAuthorityPort,
    FinancialE1FactWriteCandidate,
)
from apps.data_center.application.financial_numeric_qualification import (
    FinancialNumericVerificationPurpose,
)
from apps.data_center.application.financial_v3_e1_verification import (
    FinancialV3FactVerificationRequest,
)
from apps.data_center.application.sync_transaction import (
    DataCenterSyncUnitOfWork,
    DataFetchAuditWriter,
)
from apps.data_center.domain.control_plane import SyncRun, SyncRunStatus
from apps.data_center.domain.entities import FinancialFact, RawAudit
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_next_session_witness import (
    FinancialNativeRowBinding,
    FinancialNextSessionSourceTimeWitnessV3,
)
from apps.data_center.domain.financial_source_evidence import (
    FinancialFactDecisionEvidence,
    FinancialFactSourceEvidence,
)
from apps.data_center.infrastructure.financial_e1_recovery_binding import (
    RECOVERY_TRIGGER,
    validate_recovery_commit,
)
from apps.data_center.infrastructure.financial_fact_models import FinancialFactModel
from apps.data_center.infrastructure.financial_numeric_qualification.balance_verifier import (
    AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
)
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    reference_from_audit,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
)
from apps.data_center.infrastructure.financial_v3_current_uow import (
    financial_v3_current_operation_uow,
)
from apps.data_center.infrastructure.publication_fact_write_lock import publication_fact_write_lock
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationPointerModel,
)
from core.exceptions import DataValidationError
from core.integration.data_center_audit import (
    AuditEvidenceRef,
    AuditOutcome,
    DataFetchAuditObservation,
)


class FinancialE1WitnessBuilderPort(Protocol):
    """Build the reference-only C2 v3 witness from one replayed native row."""

    def __call__(
        self,
        financial_row: FinancialNativeRowBinding,
        *,
        exchange: str,
        calendar_dataset_key: str,
    ) -> FinancialNextSessionSourceTimeWitnessV3:
        """Resolve real current C2 records in the caller-owned transaction."""


class FinancialE1FactRepositoryPort(Protocol):
    """The canonical write/read methods needed for one E1 finite batch."""

    def verify_recovery_fact(
        self, fact: FinancialFact, request: FinancialV3FactVerificationRequest
    ) -> bool:
        """Check the proposed v3 fact using the same verifier as a current write."""
        ...

    def bulk_upsert(
        self,
        facts: list[FinancialFact],
        *,
        ingested_run_id: UUID,
        verification_request: FinancialV3FactVerificationRequest,
    ) -> int:
        """Write exact facts only after the configured verifier accepts them."""

    def get_facts(
        self,
        asset_code: str,
        period_type: FinancialPeriodType | None = None,
        limit: int = 20,
        end: date | None = None,
        fact_pks: Sequence[str] | None = None,
        knowledge_cutoff: datetime | None = None,
        *,
        verification_request: FinancialV3FactVerificationRequest,
    ) -> list[FinancialFact]:
        """Return each requested revision after current same-UOW verification."""


class FinancialE1RunRepositoryPort(Protocol):
    """Persist a terminal lifecycle update for the existing E1 SyncRun."""

    def save(self, run: SyncRun) -> SyncRun:
        """Persist one exact run state without replacing its identity."""


class FinancialE1V3FactWriterReadback:
    """Build, write, and independently reread the exact selected native facts."""

    def __init__(
        self,
        *,
        repository: FinancialE1FactRepositoryPort,
        witness_builder: FinancialE1WitnessBuilderPort,
        records: FinancialAvailabilityGovernanceRepositoryPort,
        owner_events: FinancialAvailabilityOwnerEventRepositoryPort,
        source_reader: FinancialAvailabilitySourceReaderPort,
        sync_unit_of_work: DataCenterSyncUnitOfWork,
        data_fetch_audit_writer: DataFetchAuditWriter,
        run_repository: FinancialE1RunRepositoryPort,
        authority_guard: FinancialE1ExecutionAuthorityPort,
        using: str = DEFAULT_DB_ALIAS,
        review_sha256: str | None = None,
    ) -> None:
        """Require the real repositories and all C2 builders to share default DB."""

        if type(using) is not str or using != DEFAULT_DB_ALIAS:
            raise ValueError("E1 v3 fact writing requires the default database alias")
        if not callable(witness_builder):
            raise TypeError("the C2 v3 witness builder must be explicitly injected")
        aliases = tuple(
            getattr(value, "database_alias", None)
            for value in (records, owner_events, source_reader)
        )
        if any(type(alias) is not str or alias != using for alias in aliases):
            raise ValueError("E1 C2 repositories must share the exact default alias")
        if repository is None:
            raise TypeError("the canonical FinancialFactRepository is required")
        if sync_unit_of_work.unit_of_work_key != f"django:{using}":
            raise ValueError("E1 fact/audit unit of work must use the exact default alias")
        if data_fetch_audit_writer.database_alias != using:
            raise ValueError("E1 fetch audit writer must use the exact default alias")
        self._repository = repository
        self._witness_builder = witness_builder
        self._records = records
        self._owner_events = owner_events
        self._source_reader = source_reader
        self._sync_unit_of_work = sync_unit_of_work
        self._data_fetch_audit_writer = data_fetch_audit_writer
        self._run_repository = run_repository
        self._authority_guard = authority_guard
        self._review_sha256 = review_sha256
        self._using = using

    def preview_recovery(
        self,
        candidates: tuple[FinancialE1FactWriteCandidate, ...],
        *,
        exchange: str,
        calendar_dataset_key: str,
    ) -> tuple[FinancialFact, ...]:
        """Build and verify each forecast row with current authorities before accepting a write."""
        self._authority_guard.assert_current()
        with financial_v3_current_operation_uow(using=self._using):
            _require_empty_recovery_target(candidates)
            facts = tuple(
                self._build_fact(c, exchange=exchange, calendar_dataset_key=calendar_dataset_key)
                for c in candidates
            )
            request = FinancialV3FactVerificationRequest(
                FinancialNumericVerificationPurpose.CURRENT_WRITE
            )
            if not all(self._repository.verify_recovery_fact(fact, request) for fact in facts):
                raise DataValidationError(
                    "Retained recovery forecast failed current v3 verification."
                )
            self._authority_guard.assert_current()
            return facts

    def write_and_read_back(
        self,
        candidates: tuple[FinancialE1FactWriteCandidate, ...],
        *,
        exchange: str,
        calendar_dataset_key: str,
        run: SyncRun,
        main_raw_audit: RawAudit,
        balance_raw_audit: RawAudit,
    ) -> tuple[FinancialFact, ...]:
        """Commit exact facts, one aggregate fetch event, and run status in one UOW."""

        if type(candidates) is not tuple or not candidates:
            raise ValueError("E1 writer requires the exact non-empty finite candidate tuple")
        if (
            type(exchange) is not str
            or not exchange
            or exchange != exchange.strip()
            or type(calendar_dataset_key) is not str
            or not calendar_dataset_key
            or calendar_dataset_key != calendar_dataset_key.strip()
        ):
            raise ValueError("E1 exchange and calendar dataset must be explicit plan values")
        if connections[self._using].vendor != "postgresql":
            raise DataValidationError(
                "E1 v3 write/readback requires PostgreSQL READ COMMITTED.",
                code="FINANCIAL_V3_CURRENT_UOW_INVALID",
            )
        run_uuid = _validated_run_and_audits(
            run=run,
            candidates=candidates,
            main_raw_audit=main_raw_audit,
            balance_raw_audit=balance_raw_audit,
        )
        write_request = FinancialV3FactVerificationRequest(
            FinancialNumericVerificationPurpose.CURRENT_WRITE
        )
        read_request = FinancialV3FactVerificationRequest(
            FinancialNumericVerificationPurpose.CURRENT_READ
        )
        with self._sync_unit_of_work.atomic():
            with financial_v3_current_operation_uow(using=self._using):
                if run.trigger == RECOVERY_TRIGGER:
                    originals = {
                        audit.request_params["endpoint"]: reference_from_audit(audit)
                        for audit in (main_raw_audit, balance_raw_audit)
                    }
                    if any(
                        originals.get(c.row.endpoint) != c.row.artifact_reference
                        for c in candidates
                    ):
                        raise DataValidationError(
                            "Recovery fact is not bound to its source endpoint capture."
                        )
                    _require_empty_recovery_target(candidates)
                facts = [
                    self._build_fact(
                        candidate,
                        exchange=exchange,
                        calendar_dataset_key=calendar_dataset_key,
                    )
                    for candidate in candidates
                ]
                self._authority_guard.assert_current()
                if run.trigger == RECOVERY_TRIGGER:
                    validate_recovery_commit(
                        run, main_raw_audit, balance_raw_audit, tuple(facts), self._review_sha256
                    )
                self._repository.bulk_upsert(
                    facts,
                    ingested_run_id=run_uuid,
                    verification_request=write_request,
                )
                readbacks: list[FinancialFact] = []
                for candidate, expected in zip(candidates, facts, strict=True):
                    row = self._latest_model_row(expected, ingested_run_id=run_uuid)
                    if row is None:
                        raise DataValidationError(
                            "E1 fact write did not create a readable exact revision.",
                            code="FINANCIAL_E1_READBACK_MISSING",
                        )
                    actual = self._repository.get_facts(
                        expected.asset_code,
                        period_type=expected.period_type,
                        fact_pks=[str(row.pk)],
                        verification_request=read_request,
                    )
                    if len(actual) != 1:
                        raise DataValidationError(
                            "E1 exact fact revision failed current verified readback.",
                            code="FINANCIAL_E1_READBACK_INVALID",
                        )
                    restored = actual[0]
                    if not _same_fact_revision(candidate, expected, restored):
                        raise DataValidationError(
                            "E1 readback differs from its exact native candidate.",
                            code="FINANCIAL_E1_READBACK_MISMATCH",
                        )
                    readbacks.append(restored)

                recorded_at = timezone.now()
                if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
                    raise DataValidationError(
                        "E1 fetch audit clock is not timezone-aware.",
                        code="FINANCIAL_E1_AUDIT_CLOCK_INVALID",
                    )
                occurred_at = max(main_raw_audit.fetched_at, balance_raw_audit.fetched_at)
                primary_reference = main_raw_audit.exact_reference()
                secondary = balance_raw_audit.exact_reference()
                observation = DataFetchAuditObservation(
                    secondary_raw_audit=(
                        AuditEvidenceRef(
                            "data_center",
                            "raw_audit",
                            secondary.raw_audit_id,
                            secondary.version,
                            secondary.content_hash,
                        )
                        if run.trigger == RECOVERY_TRIGGER
                        else None
                    ),
                    provider_key=run.provider_name,
                    capability="financial",
                    dataset_key=run.dataset_key,
                    run_id=primary_reference.run_id,
                    ingested_run_id=str(run_uuid),
                    raw_audit_id=primary_reference.raw_audit_id,
                    raw_audit_version=primary_reference.version,
                    raw_audit_content_hash=primary_reference.content_hash,
                    outcome=AuditOutcome.SUCCESS,
                    row_count=len(readbacks),
                    occurred_at=occurred_at,
                    recorded_at=recorded_at,
                )
                self._authority_guard.assert_current()
                self._data_fetch_audit_writer.write(observation)

                terminal_run = replace(
                    run,
                    status=SyncRunStatus.STORED,
                    outcome="success",
                    fetched=0 if run.trigger == RECOVERY_TRIGGER else 2,
                    validated=len(candidates),
                    succeeded=len(readbacks),
                    failed=0,
                    stored=len(readbacks),
                    finished_at=recorded_at,
                    error_code="",
                    error_message="",
                )
                self._authority_guard.assert_current()
                persisted_run = self._run_repository.save(terminal_run)
                if persisted_run != terminal_run:
                    raise DataValidationError(
                        "E1 terminal SyncRun changed during persistence.",
                        code="FINANCIAL_E1_RUN_FINALIZATION_INVALID",
                    )
                return tuple(readbacks)

    def _build_fact(
        self,
        candidate: FinancialE1FactWriteCandidate,
        *,
        exchange: str,
        calendar_dataset_key: str,
    ) -> FinancialFact:
        """Use source response dates and exact Decimal without synthesizing ANN."""

        if type(candidate) is not FinancialE1FactWriteCandidate:
            raise TypeError("candidate must be an exact selected native fact write candidate")
        row = candidate.row
        observation = candidate.observation
        contract = candidate.qualification.contract
        if (
            contract != observation.contract
            or row.endpoint != candidate.qualification.endpoint
            or row.native_row_id != observation.native_row_id
        ):
            raise ValueError("fact write candidate differs from its persisted qualification")
        financial_row = row.financial_row(contract.metric_code)
        witness = self._witness_builder(
            financial_row,
            exchange=exchange,
            calendar_dataset_key=calendar_dataset_key,
        )
        if (
            type(witness) is not FinancialNextSessionSourceTimeWitnessV3
            or witness.financial_row != financial_row
            or witness.financial_row.artifact_reference != row.artifact_reference
            or witness.financial_row.notice_date != row.notice_date
            or witness.financial_row.native_row_id != row.native_row_id
        ):
            raise ValueError("C2 builder returned a different raw financial row binding")
        completed_at = row.artifact_reference.evidence.response_completed_at
        if completed_at > witness.known_at:
            raise ValueError("witness knowledge clock predates the raw response")
        return FinancialFact(
            asset_code=row.asset_code,
            period_end=row.period_end,
            period_type=row.period_type,
            metric_code=contract.metric_code,
            value=Decimal(observation.canonical_value),
            unit=contract.canonical_unit,
            source=contract.provider,
            report_date=row.notice_date,
            available_at=witness.available_at,
            fetched_at=completed_at,
            extra={},
            source_evidence=FinancialFactSourceEvidence(
                announced_at=None,
                source_record_id=row.native_row_id,
                raw_payload_hash=row.artifact_reference.body_sha256,
            ),
            decision_evidence=FinancialFactDecisionEvidence(
                artifact_reference=row.artifact_reference,
                native_asset_code=row.asset_code,
                native_period_end=row.period_end,
                native_row_id=row.native_row_id,
                source_time_witness_v3=witness,
            ),
            numeric_schema="native-decimal-v2",
            numeric_evidence=observation,
        )

    def _latest_model_row(
        self,
        fact: FinancialFact,
        *,
        ingested_run_id: UUID,
    ) -> FinancialFactModel | None:
        """Select the greatest revision for one exact natural key and require v2."""

        numeric_evidence = fact.numeric_evidence
        source_evidence = fact.source_evidence
        if numeric_evidence is None or source_evidence is None:
            return None
        try:
            row = (
                FinancialFactModel._default_manager.using(self._using)
                .filter(
                    asset_code=fact.asset_code,
                    period_end=fact.period_end,
                    period_type=fact.period_type.value,
                    metric_code=fact.metric_code,
                    source=fact.source,
                )
                .order_by("-revision_number", "-pk")
                .first()
            )
        except DatabaseError as error:
            raise DataValidationError(
                "E1 fact revision selector is unavailable.",
                code="FINANCIAL_E1_READBACK_UNAVAILABLE",
            ) from error
        if (
            row is None
            or row.numeric_schema != "native-decimal-v2"
            or row.exact_value_text != numeric_evidence.canonical_value
            or row.numeric_evidence != numeric_evidence.to_dict()
            or row.ingested_run_id != ingested_run_id
            or row.announced_at is not None
            or row.report_date != fact.report_date
            or row.available_at != fact.available_at
            or row.source_record_id != source_evidence.source_record_id
            or row.raw_payload_hash != source_evidence.raw_payload_hash
        ):
            return None
        return row


def _validated_run_and_audits(
    *,
    run: SyncRun,
    candidates: tuple[FinancialE1FactWriteCandidate, ...],
    main_raw_audit: RawAudit,
    balance_raw_audit: RawAudit,
) -> UUID:
    """Bind both retained captures and every metric to one persisted SyncRun."""

    if type(run) is not SyncRun or type(main_raw_audit) is not RawAudit:
        raise TypeError("E1 commit requires a typed persisted run and Main RawAudit")
    if type(balance_raw_audit) is not RawAudit:
        raise TypeError("E1 commit requires the independent Balance RawAudit")
    try:
        run_uuid = UUID(run.run_id)
    except (TypeError, ValueError) as error:
        raise ValueError("E1 SyncRun identifier must be a canonical UUID") from error
    if (
        str(run_uuid) != run.run_id.lower()
        or run.finished_at is not None
        or run.status not in {SyncRunStatus.REQUESTED, SyncRunStatus.FETCHING}
        or run.outcome != "blocked"
        or run.requested != len(candidates)
    ):
        raise ValueError("E1 SyncRun state does not match the exact unfinished selection")

    main_reference = main_raw_audit.exact_reference()
    balance_reference = balance_raw_audit.exact_reference()
    source_id = main_raw_audit.run_id if run.trigger == RECOVERY_TRIGGER else run.run_id
    if (
        main_raw_audit.status != "ok"
        or balance_raw_audit.status != "ok"
        or main_raw_audit.capability != "financial"
        or balance_raw_audit.capability != "financial"
        or main_raw_audit.provider_name != run.provider_name
        or balance_raw_audit.provider_name != run.provider_name
        or main_raw_audit.row_count <= 0
        or balance_raw_audit.row_count <= 0
        or main_reference.run_id != source_id
        or main_reference.ingested_run_id != source_id
        or balance_reference.run_id != source_id
        or balance_reference.ingested_run_id != source_id
        or main_reference.raw_audit_id == balance_reference.raw_audit_id
        or main_reference.content_hash == balance_reference.content_hash
        or main_raw_audit.request_params.get("endpoint") != AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
        or balance_raw_audit.request_params.get("endpoint")
        != AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT
    ):
        raise ValueError("E1 RawAudit rows do not independently match the persisted run")
    if any(
        item.qualification.contract.provider != run.provider_name
        or item.qualification.contract.dataset_key != run.dataset_key
        for item in candidates
    ):
        raise ValueError("E1 native candidates differ from the persisted run dataset/provider")
    return run_uuid


def _require_empty_recovery_target(candidates: tuple[FinancialE1FactWriteCandidate, ...]) -> None:
    """Serialize the forecast natural keys and reject an already populated target."""

    first = candidates[0].row
    metrics = [item.qualification.contract.metric_code for item in candidates]
    tokens = [
        ":".join(
            (
                item.row.asset_code,
                item.row.period_end.isoformat(),
                item.row.period_type.value,
                item.qualification.contract.metric_code,
                item.qualification.contract.provider,
            )
        )
        for item in candidates
    ]
    with publication_fact_write_lock(FinancialFactModel, natural_key_tokens=tokens):
        if CanonicalPublicationPointerModel.objects.filter(dataset_key=first.dataset_key).exists():
            raise DataValidationError("Recovery forecast requires inactive financial Publication.")
        if FinancialFactModel.objects.filter(
            asset_code=first.asset_code,
            period_end=first.period_end,
            period_type=first.period_type.value,
            source=first.provider_name,
            metric_code__in=metrics,
        ).exists():
            raise DataValidationError(
                "Retained recovery forecast requires zero existing financial facts."
            )


def _same_fact_revision(
    candidate: FinancialE1FactWriteCandidate,
    expected: FinancialFact,
    actual: FinancialFact,
) -> bool:
    """Compare readback to exact raw contract, decimal, and endpoint witness."""

    decision = actual.decision_evidence
    expected_decision = expected.decision_evidence
    return (
        type(actual) is FinancialFact
        and type(actual.value) is Decimal
        and actual.asset_code == expected.asset_code
        and actual.period_end == expected.period_end
        and actual.period_type is expected.period_type
        and actual.metric_code == expected.metric_code
        and actual.value == expected.value
        and actual.unit == expected.unit
        and actual.source == expected.source
        and actual.report_date == expected.report_date
        and actual.available_at == expected.available_at
        and actual.numeric_schema == "native-decimal-v2"
        and actual.numeric_evidence == candidate.observation
        and actual.source_evidence == expected.source_evidence
        and decision is not None
        and expected_decision is not None
        and decision.artifact_reference == candidate.row.artifact_reference
        and decision.native_row_id == candidate.row.native_row_id
        and decision.source_time_witness_v3 is not None
        and expected_decision.source_time_witness_v3 is not None
        and decision.source_time_witness_v3 == expected_decision.source_time_witness_v3
        and decision.source_time_witness is None
    )


__all__ = [
    "FinancialE1FactRepositoryPort",
    "FinancialE1V3FactWriterReadback",
    "FinancialE1WitnessBuilderPort",
]
