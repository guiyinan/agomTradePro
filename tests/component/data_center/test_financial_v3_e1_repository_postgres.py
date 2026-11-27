"""PostgreSQL source tests for v3 date-only repository guards.

The accepted verifier below is an explicit synthetic test double used only to
exercise repository SQL and plumbing. It does not qualify C2, a numeric body,
or production data. Formal E1 qualification still requires the real composed
verifier and independent capture evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import NoReturn
from uuid import UUID, uuid4

import pytest
from django.db import DEFAULT_DB_ALIAS, connection, transaction
from django.utils import timezone

from apps.audit.application.data_fetch_audit import AppendDataFetchAuditObservationUseCase
from apps.audit.domain.system_audit_event import AuditScopeRef, SystemAuditEvent
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_outbox_repository import (
    DjangoSystemAuditOutboxRepository,
)
from apps.data_center.application.financial_e1_capture_use_case import (
    FinancialE1NativeRowIdentity,
)
from apps.data_center.application.financial_e1_discovery_runner import (
    FinancialE1FactWriteCandidate,
)
from apps.data_center.application.financial_numeric_qualification import (
    FinancialNumericVerificationPurpose,
)
from apps.data_center.application.financial_v3_e1_verification import (
    FinancialV3FactVerificationRequest,
)
from apps.data_center.domain.control_plane import SyncRun, SyncRunStatus
from apps.data_center.domain.entities import FinancialFact, RawAudit
from apps.data_center.domain.financial_next_session_witness import (
    FinancialNativeRowBinding,
    FinancialNextSessionSourceTimeWitnessV3,
)
from apps.data_center.domain.financial_numeric_evidence import (
    FinancialMetricSourceContract,
    NativeFinancialMetricObservation,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceContextRequirement,
    FinancialNumericSourceDocumentCaptureReference,
    FinancialNumericSourceQualification,
)
from apps.data_center.domain.financial_source_evidence import (
    FINANCIAL_FACT_DATASET_KEY,
    FinancialFactDecisionEvidence,
    FinancialFactSourceEvidence,
)
from apps.data_center.infrastructure.audited_sync_runtime import (
    DjangoDataCenterSyncUnitOfWork,
)
from apps.data_center.infrastructure.control_plane_repositories import SyncRunRepository
from apps.data_center.infrastructure.financial_e1_discovery_v3_writer import (
    FinancialE1V3FactWriterReadback,
)
from apps.data_center.infrastructure.financial_fact_repository import FinancialFactRepository
from apps.data_center.infrastructure.financial_fact_write_guard import (
    FinancialFactProvenanceConflictError,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_verifier import (
    AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
)
from apps.data_center.infrastructure.models import FinancialFactModel, RawAuditModel, SyncRunModel
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from tests.support.native_postgres_database import assert_native_postgres_test_database
from tests.unit.data_center.test_financial_next_session_witness import _witness

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=["apps.data_center"],
)


@pytest.fixture(autouse=True)
def _require_native_test_database(
    transactional_db: None,
    request: pytest.FixtureRequest,
) -> None:
    """Require applied migrations and the explicit isolated native test database."""

    del transactional_db
    if request.config.getoption("nomigrations", default=False):
        pytest.fail("v3 repository contracts require actual migrations")
    assert_native_postgres_test_database()


class _AcceptSyntheticV3:
    """Accept only as a test double to exercise repository storage and selection."""

    def __init__(self) -> None:
        self.requests: list[FinancialV3FactVerificationRequest] = []

    def verify(
        self,
        fact: FinancialFact,
        request: FinancialV3FactVerificationRequest,
    ) -> bool:
        """Record the request without claiming real evidence qualification."""

        assert fact.numeric_schema == "native-decimal-v2"
        self.requests.append(request)
        return True


def _synthetic_v3_fact() -> FinancialFact:
    """Build one locally valid synthetic date-only v3 fact without external fixtures."""

    from apps.data_center.infrastructure.financial_response_body_store import _location_for

    witness = _witness()
    original = witness.financial_row
    artifact = replace(
        original.artifact_reference, location=_location_for(original.artifact_reference.capture_id)
    )
    row = replace(original, artifact_reference=artifact)
    unique_metric = f"e1.synthetic.{uuid4().hex}"
    unique_row_id = f"synthetic-row-{uuid4().hex}"
    row = replace(row, metric_code=unique_metric, native_row_id=unique_row_id)
    witness = replace(witness, financial_row=row)
    artifact = row.artifact_reference
    unit = "synthetic-unit"
    contract = FinancialMetricSourceContract(
        provider=artifact.evidence.request_scope.provider_name,
        dataset_key=FINANCIAL_FACT_DATASET_KEY,
        metric_code=unique_metric,
        source_field="synthetic_source_value",
        source_unit=unit,
        canonical_unit=unit,
        scale_numerator=1,
        scale_denominator=1,
        contract_version="synthetic-e1-v3.v1",
        origin="native",
    )
    observation = NativeFinancialMetricObservation.from_raw_value(
        contract=contract,
        raw_value=Decimal("1.25"),
        source_field=contract.source_field,
        body_sha256=artifact.evidence.body_sha256,
        native_row_id=unique_row_id,
    )
    fact = FinancialFact(
        asset_code=row.asset_code,
        period_end=row.period_end,
        period_type=row.period_type,
        metric_code=unique_metric,
        value=Decimal(observation.canonical_value),
        unit=unit,
        source=contract.provider,
        report_date=row.period_end,
        available_at=witness.available_at,
        fetched_at=artifact.evidence.response_completed_at + timedelta(seconds=1),
        source_evidence=FinancialFactSourceEvidence(
            announced_at=None,
            source_record_id=unique_row_id,
            raw_payload_hash=artifact.evidence.body_sha256,
        ),
        decision_evidence=FinancialFactDecisionEvidence(
            artifact_reference=artifact,
            native_asset_code=row.asset_code,
            native_period_end=row.period_end,
            native_row_id=unique_row_id,
            source_time_witness_v3=witness,
        ),
        numeric_schema="native-decimal-v2",
        numeric_evidence=observation,
    )
    fact.__post_init__()
    return fact


def _new_synthetic_capture_version(fact: FinancialFact) -> FinancialFact:
    """Build a new-body synthetic proof over the same date-only natural key."""

    decision = fact.decision_evidence
    source = fact.source_evidence
    observation = fact.numeric_evidence
    assert decision is not None
    assert source is not None
    assert observation is not None
    witness = decision.source_time_witness_v3
    assert witness is not None
    body_sha256 = "f" * 64
    artifact = replace(
        decision.artifact_reference,
        capture_id=uuid4(),
        evidence=replace(
            decision.artifact_reference.evidence,
            body_sha256=body_sha256,
        ),
    )
    row = replace(
        witness.financial_row,
        artifact_reference=artifact,
        row_projection_sha256="e" * 64,
    )
    next_witness = replace(witness, financial_row=row)
    next_fact = replace(
        fact,
        source_evidence=replace(source, raw_payload_hash=body_sha256),
        decision_evidence=replace(
            decision,
            artifact_reference=artifact,
            source_time_witness_v3=next_witness,
        ),
        numeric_evidence=replace(observation, body_sha256=body_sha256),
    )
    next_fact.__post_init__()
    return next_fact


def _request(
    purpose: FinancialNumericVerificationPurpose,
    *,
    known_at: datetime | None = None,
) -> FinancialV3FactVerificationRequest:
    """Build an exact current or explicit point-in-time verifier request."""

    return FinancialV3FactVerificationRequest(purpose=purpose, known_at=known_at)


def _require_postgres() -> None:
    """Keep this source explicit when run under SQLite developer settings."""

    if connection.vendor != "postgresql":
        pytest.skip("v3 current UOW and repository contract requires PostgreSQL")


def test_v3_write_without_qualified_verifier_blocks_before_any_fact_insert() -> None:
    """Date-only ANN absence is never a substitute for the current full verifier."""

    _require_postgres()
    fact = _synthetic_v3_fact()
    assert fact.source_evidence is not None and fact.source_evidence.announced_at is None
    request = _request(FinancialNumericVerificationPurpose.CURRENT_WRITE)
    before = (
        FinancialFactModel._default_manager.using(DEFAULT_DB_ALIAS)
        .filter(metric_code=fact.metric_code)
        .count()
    )
    repository = FinancialFactRepository()

    with pytest.raises(FinancialFactProvenanceConflictError):
        repository.bulk_upsert([fact], verification_request=request)

    after = (
        FinancialFactModel._default_manager.using(DEFAULT_DB_ALIAS)
        .filter(metric_code=fact.metric_code)
        .count()
    )
    assert after == before == 0


def test_v3_readback_pit_selector_and_publication_guard_are_explicit() -> None:
    """A stored ANN-null row is selected for PIT and still needs its real verifier."""

    _require_postgres()
    fact = _synthetic_v3_fact()
    witness = fact.decision_evidence.source_time_witness_v3
    assert witness is not None
    assert fact.source_evidence is not None and fact.source_evidence.announced_at is None
    synthetic = _AcceptSyntheticV3()
    writer = FinancialFactRepository(v3_evidence_verifier=synthetic)
    assert (
        writer.bulk_upsert(
            [fact],
            verification_request=_request(FinancialNumericVerificationPurpose.CURRENT_WRITE),
        )
        == 1
    )
    stored = FinancialFactModel._default_manager.using(DEFAULT_DB_ALIAS).get(
        metric_code=fact.metric_code
    )
    assert stored.announced_at is None
    assert stored.source_record_id == fact.source_evidence.source_record_id
    assert stored.raw_payload_hash == fact.decision_evidence.artifact_reference.evidence.body_sha256

    unverified = FinancialFactRepository()
    with pytest.raises(FinancialFactProvenanceConflictError):
        unverified.get_facts(
            fact.asset_code,
            fact_pks=(str(stored.pk),),
            limit=1,
            verification_request=_request(FinancialNumericVerificationPurpose.CURRENT_READ),
        )
    current_readback = writer.get_facts(
        fact.asset_code,
        fact_pks=(str(stored.pk),),
        limit=1,
        verification_request=_request(FinancialNumericVerificationPurpose.CURRENT_READ),
    )
    assert len(current_readback) == 1
    assert current_readback[0].source_evidence is not None
    assert current_readback[0].source_evidence.announced_at is None

    pit_cutoff = max(
        witness.earliest_temporal_usability_at + timedelta(seconds=2),
        timezone.now() + timedelta(minutes=5),
    )
    pit_request = _request(
        FinancialNumericVerificationPurpose.POINT_IN_TIME_READ,
        known_at=pit_cutoff,
    )
    with pytest.raises(FinancialFactProvenanceConflictError):
        unverified.get_facts(
            fact.asset_code,
            fact_pks=(str(stored.pk),),
            limit=10,
            knowledge_cutoff=pit_cutoff,
            verification_request=pit_request,
        )

    readback = writer.get_facts(
        fact.asset_code,
        fact_pks=(str(stored.pk),),
        limit=10,
        knowledge_cutoff=pit_cutoff,
        verification_request=pit_request,
    )
    assert len(readback) == 1
    persisted_witness = readback[0].decision_evidence.source_time_witness_v3
    assert persisted_witness is not None
    assert persisted_witness.known_at == witness.known_at
    assert readback[0].source_evidence is not None
    assert readback[0].source_evidence.announced_at is None
    assert synthetic.requests[-1] == pit_request

    publication_request = _request(FinancialNumericVerificationPurpose.CURRENT_PUBLICATION)
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        assert connection.alias == DEFAULT_DB_ALIAS
        assert len(connection.atomic_blocks) == 1
        with pytest.raises(FinancialFactProvenanceConflictError):
            unverified.list_publication_candidates(
                (fact,),
                verification_request=publication_request,
            )


def test_verified_v3_ann_null_replacement_appends_a_new_fact_revision() -> None:
    """Only an exact CURRENT_WRITE verifier permits date-only source replacement."""

    _require_postgres()
    first = _synthetic_v3_fact()
    second = _new_synthetic_capture_version(first)
    assert first.source_evidence is not None and first.source_evidence.announced_at is None
    assert second.source_evidence is not None and second.source_evidence.announced_at is None
    assert first.source_evidence.raw_payload_hash != second.source_evidence.raw_payload_hash
    verifier = _AcceptSyntheticV3()
    repository = FinancialFactRepository(v3_evidence_verifier=verifier)
    request = _request(FinancialNumericVerificationPurpose.CURRENT_WRITE)

    assert repository.bulk_upsert([first], verification_request=request) == 1
    assert repository.bulk_upsert([second], verification_request=request) == 1
    rows = tuple(
        FinancialFactModel._default_manager.using(DEFAULT_DB_ALIAS)
        .filter(metric_code=first.metric_code)
        .order_by("revision_number")
    )
    assert len(rows) == 2
    assert rows[0].announced_at is None and rows[1].announced_at is None
    assert rows[1].raw_payload_hash == second.source_evidence.raw_payload_hash
    assert rows[1].revision_number == rows[0].revision_number + 1


class _SyntheticC2Port:
    """Expose only the alias shape; the writer receives a synthetic witness builder."""

    database_alias = DEFAULT_DB_ALIAS


class _SyntheticAuthorityGuard:
    """Allow only this mechanics test; this is not the production auth composition."""

    def assert_current(self) -> None:
        """Accept the synthetic in-process test caller."""


class _SyntheticScopeProvider:
    """Supply a fixed test scope to the canonical DataFetch Audit use case."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Return the explicit test-only scope at the requested aware instant."""

        assert as_of.tzinfo is not None and as_of.utcoffset() is not None
        return AuditScopeRef(tenant_id="tenant:e1-mechanics-test", owner_id="owner:e1-test")


class _SyntheticWitnessBuilder:
    """Rebind the existing synthetic v3 fixture to the candidate row."""

    def __init__(self, witness: FinancialNextSessionSourceTimeWitnessV3) -> None:
        self._witness = witness

    def __call__(
        self,
        financial_row: FinancialNativeRowBinding,
        *,
        exchange: str,
        calendar_dataset_key: str,
    ) -> FinancialNextSessionSourceTimeWitnessV3:
        """Return a same-row witness without querying or qualifying real C2 records."""

        assert exchange == "SZSE"
        assert calendar_dataset_key == "equity.trading_calendar"
        return replace(self._witness, financial_row=financial_row)


@dataclass(frozen=True, slots=True)
class _WriterSetup:
    """One unique run, one synthetic candidate, and two pre-retained RawAudits."""

    writer: FinancialE1V3FactWriterReadback
    run: SyncRun
    candidate: FinancialE1FactWriteCandidate
    main_audit: RawAudit
    balance_audit: RawAudit
    main_audit_id: str
    balance_audit_id: str


def _build_setup(review_sha256: str | None = None) -> _WriterSetup:
    """Persist run/capture metadata before constructing the transaction writer."""

    base_fact = _synthetic_v3_fact()
    observation = base_fact.numeric_evidence
    decision = base_fact.decision_evidence
    assert observation is not None
    assert decision is not None
    witness = decision.source_time_witness_v3
    assert witness is not None
    source_row = witness.financial_row
    contract = observation.contract
    endpoint = AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
    now = timezone.now()

    document_capture = FinancialNumericSourceDocumentCaptureReference(
        capture_id=uuid4(),
        document_id="synthetic-e1-writer-transaction-test",
        issuer="Synthetic test source",
        canonical_url="https://example.test/financial-contract",
        body_sha256="b" * 64,
        body_size_bytes=64,
        captured_at=datetime(2026, 10, 1, tzinfo=UTC),
        content_type="text/html; charset=utf-8",
    )
    qualification = FinancialNumericSourceQualification(
        contract=contract,
        endpoint=endpoint,
        source_applicability="synthetic-e1-writer-mechanics-only",
        document_capture=document_capture,
        context_requirements=(
            FinancialNumericSourceContextRequirement(
                field_name="REPORT_DATE",
                expected_value=source_row.period_end.isoformat(),
            ),
        ),
        effective_from=document_capture.captured_at,
        effective_until=None,
    )
    row = FinancialE1NativeRowIdentity(
        artifact_reference=source_row.artifact_reference,
        provider_name=contract.provider,
        dataset_key=contract.dataset_key,
        endpoint=endpoint,
        asset_code=source_row.asset_code,
        period_end=source_row.period_end,
        period_type=source_row.period_type,
        notice_date=source_row.notice_date,
        native_row_id=source_row.native_row_id,
        row_projection_sha256=source_row.row_projection_sha256,
        matched_row_count=source_row.matched_row_count,
    )
    candidate = FinancialE1FactWriteCandidate(
        qualification=qualification,
        row=row,
        observation=observation,
    )

    run_id = str(uuid4())
    run = SyncRun(
        run_id=run_id,
        dataset_key=FINANCIAL_FACT_DATASET_KEY,
        trigger="financial_e1_discovery",
        status=SyncRunStatus.REQUESTED,
        outcome="blocked",
        requested=1,
        provider_name=contract.provider,
        contract_version="financial-e1-discovery.v2",
        config_snapshot_hash="c" * 64,
        started_at=now - timedelta(minutes=1),
    )
    run_repository = SyncRunRepository()
    assert run_repository.save(run) == run

    raw_audit_repository = RawAuditRepository()
    main_audit = raw_audit_repository.log(
        RawAudit(
            provider_name=contract.provider,
            capability="financial",
            request_params={"endpoint": endpoint, "synthetic_capture": "main"},
            status="ok",
            row_count=1,
            fetched_at=now - timedelta(seconds=20),
            extra={
                "financial_response_artifact": {
                    "schema": "financial-response-artifact-link.v1",
                    **row.artifact_reference.to_dict(),
                    "provider_id": 77,
                }
            },
            response_payload_hash=row.artifact_reference.body_sha256,
            parser_version="synthetic-e1-mechanics.v1",
            payload_size_bytes=row.artifact_reference.body_size_bytes,
            run_id=run_id,
            ingested_run_id=run_id,
        )
    )
    from apps.data_center.infrastructure.financial_response_body_store import _location_for

    balance_capture = uuid4()
    balance_audit = raw_audit_repository.log(
        RawAudit(
            provider_name=contract.provider,
            capability="financial",
            request_params={
                "endpoint": AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
                "synthetic_capture": "balance",
            },
            status="ok",
            row_count=1,
            fetched_at=now - timedelta(seconds=15),
            extra={
                "financial_response_artifact": {
                    "schema": "financial-response-artifact-link.v1",
                    **replace(
                        row.artifact_reference,
                        capture_id=balance_capture,
                        location=_location_for(balance_capture),
                        evidence=replace(row.artifact_reference.evidence, body_sha256="d" * 64),
                    ).to_dict(),
                    "provider_id": 77,
                }
            },
            response_payload_hash="d" * 64,
            parser_version="synthetic-e1-mechanics.v1",
            payload_size_bytes=80,
            run_id=run_id,
            ingested_run_id=run_id,
        )
    )

    data_fetch_writer = AppendDataFetchAuditObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(using=DEFAULT_DB_ALIAS),
        _SyntheticScopeProvider(),
    )
    writer = FinancialE1V3FactWriterReadback(
        repository=FinancialFactRepository(v3_evidence_verifier=_AcceptSyntheticV3()),
        witness_builder=_SyntheticWitnessBuilder(witness),
        records=_SyntheticC2Port(),
        owner_events=_SyntheticC2Port(),
        source_reader=_SyntheticC2Port(),
        sync_unit_of_work=DjangoDataCenterSyncUnitOfWork(
            (raw_audit_repository,),
            data_fetch_writer,
            using=DEFAULT_DB_ALIAS,
        ),
        data_fetch_audit_writer=data_fetch_writer,
        run_repository=run_repository,
        authority_guard=_SyntheticAuthorityGuard(),
        review_sha256=review_sha256,
        using=DEFAULT_DB_ALIAS,
    )
    return _WriterSetup(
        writer=writer,
        run=run,
        candidate=candidate,
        main_audit=main_audit,
        balance_audit=balance_audit,
        main_audit_id=main_audit.raw_audit_id,
        balance_audit_id=balance_audit.raw_audit_id,
    )


def _write(setup: _WriterSetup) -> tuple[FinancialFact, ...]:
    """Execute the canonical writer with a one-metric synthetic mechanics batch."""

    return setup.writer.write_and_read_back(
        (setup.candidate,),
        exchange="SZSE",
        calendar_dataset_key="equity.trading_calendar",
        run=setup.run,
        main_raw_audit=setup.main_audit,
        balance_raw_audit=setup.balance_audit,
    )


@pytest.mark.django_db(transaction=True, available_apps=["apps.data_center", "apps.audit"])
def test_retained_review_binds_operator_and_exact_material_to_native_forecast(
    tmp_path: Path,
) -> None:
    """Read the independent review, compare the original capture and reject changed material."""
    from apps.data_center.infrastructure.financial_e1_recovery_binding import RetainedWriteReview

    _require_postgres()
    setup = _build_setup()
    source = UUID(setup.run.run_id)
    plan_hash = setup.run.config_snapshot_hash
    predicted = setup.writer.preview_recovery(
        (setup.candidate,), exchange="SZSE", calendar_dataset_key="equity.trading_calendar"
    )
    (fact,) = predicted
    artifact = setup.candidate.row.artifact_reference
    material = {
        "schema": "retained-e1-material-review.v1",
        "source_run": str(source),
        "plan_sha256": plan_hash,
        "asset": setup.candidate.row.asset_code,
        "period": setup.candidate.row.period_end.isoformat(),
        "fields": {
            setup.candidate.observation.contract.metric_code: {
                "capture": str(artifact.capture_id),
                "raw": setup.candidate.observation.canonical_value,
                "unit": setup.candidate.observation.contract.canonical_unit,
            }
        },
    }
    material_path = tmp_path / "material.json"
    material_path.write_text(json.dumps(material), encoding="utf-8")
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "schema": "retained-e1-split-review.v1",
                "source_run": str(source),
                "plan_sha256": plan_hash,
                "owner_id": 7,
                "qualifications": [setup.candidate.qualification.identity],
                "material_sha256": hashlib.sha256(material_path.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    digest = hashlib.sha256(review_path.read_bytes()).hexdigest()
    inputs = {
        "source": source,
        "plan_hash": plan_hash,
        "main": setup.main_audit,
        "balance": setup.balance_audit,
    }
    review = RetainedWriteReview.load(review_path, digest, operator="django-user:7", **inputs)
    assert review.owner_id == 7 and review.captures[0] == artifact.capture_id
    assert review.qualification_ids == (setup.candidate.qualification.identity,)
    assert fact.value == Decimal(setup.candidate.observation.canonical_value)
    review.verify_material_forecast(
        material_path, facts=predicted, plan_hash=plan_hash, source=source
    )
    with pytest.raises(ValueError, match="scope differs"):
        review.verify_material_forecast(material_path, facts=(), plan_hash=plan_hash, source=source)
    with pytest.raises(ValueError, match="identity or scope mismatch"):
        RetainedWriteReview.load(review_path, digest, operator="django-user:8", **inputs)
    material_path.write_text(json.dumps({**material, "asset": "000002.SZ"}), encoding="utf-8")
    with pytest.raises(ValueError, match="material bytes differ"):
        review.verify_material_forecast(
            material_path, facts=predicted, plan_hash=plan_hash, source=source
        )
    assert not FinancialFactModel.objects.filter(ingested_run_id=source).exists()


@pytest.mark.django_db(transaction=True, available_apps=["apps.data_center", "apps.audit"])
def test_e1_v3_writer_commits_fact_run_and_canonical_fetch_audit_pair() -> None:
    """Persist one synthetic fact and one exact DataFetch event/outbox pair."""

    if connection.vendor != "postgresql":
        pytest.skip("E1 writer transaction contract requires PostgreSQL")
    setup = _build_setup()
    result = _write(setup)

    assert len(result) == 1
    fact_row = FinancialFactModel._default_manager.using(DEFAULT_DB_ALIAS).get(
        metric_code=setup.candidate.observation.contract.metric_code
    )
    assert fact_row.numeric_schema == "native-decimal-v2"
    assert fact_row.ingested_run_id == UUID(setup.run.run_id)
    assert fact_row.announced_at is None
    assert fact_row.raw_payload_hash == setup.candidate.row.artifact_reference.body_sha256

    run_row = SyncRunModel._default_manager.using(DEFAULT_DB_ALIAS).get(
        run_id=UUID(setup.run.run_id)
    )
    assert run_row.status == SyncRunStatus.STORED.value
    assert run_row.outcome == "success"
    assert run_row.fetched == 2
    assert run_row.validated == run_row.succeeded == run_row.stored == 1
    assert run_row.failed == 0
    assert run_row.finished_at is not None

    events = SystemAuditEventModel._default_manager.using(DEFAULT_DB_ALIAS).filter(
        correlations__run_id=setup.run.run_id
    )
    assert events.count() == 1
    event = events.get()
    assert event.event_type == "data.fetch.completed"
    assert event.outcome == "success"
    assert event.dataset_key == setup.run.dataset_key
    assert event.provider_key == setup.run.provider_name
    assert event.capability == "financial"
    assert event.detail["row_count"] == 1
    assert event.resource_id == setup.main_audit_id
    assert event.evidence_refs[0]["artifact_id"] == setup.main_audit_id
    assert event.evidence_refs[0]["content_hash"] == setup.main_audit.content_hash
    assert event.scope_tenant_id == "tenant:e1-mechanics-test"
    assert event.scope_owner_id == "owner:e1-test"

    outbox = SystemAuditOutboxModel._default_manager.using(DEFAULT_DB_ALIAS).get(
        event_id=event.event_id
    )
    assert outbox.payload_hash == event.content_hash
    assert outbox.status == SystemAuditOutboxModel.STATUS_PENDING
    persisted_raw_ids = set(
        RawAuditModel._default_manager.using(DEFAULT_DB_ALIAS)
        .filter(run_id=UUID(setup.run.run_id))
        .values_list("pk", flat=True)
    )
    assert persisted_raw_ids == {int(setup.main_audit_id), int(setup.balance_audit_id)}


@pytest.mark.django_db(transaction=True, available_apps=["apps.data_center", "apps.audit"])
def test_e1_audit_outbox_failure_rolls_back_fact_and_success_run_but_keeps_raw_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rollback all final writes after canonical audit fails following event append."""

    if connection.vendor != "postgresql":
        pytest.skip("E1 writer transaction contract requires PostgreSQL")
    setup = _build_setup()
    run_uuid = UUID(setup.run.run_id)
    retained_ids_before = set(
        RawAuditModel._default_manager.using(DEFAULT_DB_ALIAS)
        .filter(run_id=run_uuid)
        .values_list("pk", flat=True)
    )
    assert len(retained_ids_before) == 2
    original_enqueue = DjangoSystemAuditOutboxRepository.enqueue

    def enqueue_then_fail(
        repository: DjangoSystemAuditOutboxRepository,
        event: SystemAuditEvent,
        *,
        available_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> NoReturn:
        """Create the real outbox row, then fail inside Audit's atomic pair."""

        original_enqueue(
            repository,
            event,
            available_at=available_at,
            created_at=created_at,
        )
        raise RuntimeError("injected E1 DataFetch outbox failure")

    monkeypatch.setattr(DjangoSystemAuditOutboxRepository, "enqueue", enqueue_then_fail)
    with pytest.raises(RuntimeError, match="injected E1 DataFetch outbox failure"):
        _write(setup)

    assert (
        not FinancialFactModel._default_manager.using(DEFAULT_DB_ALIAS)
        .filter(metric_code=setup.candidate.observation.contract.metric_code)
        .exists()
    )
    run_row = SyncRunModel._default_manager.using(DEFAULT_DB_ALIAS).get(run_id=run_uuid)
    assert run_row.status == SyncRunStatus.REQUESTED.value
    assert run_row.outcome == "blocked"
    assert run_row.finished_at is None
    assert run_row.fetched == run_row.stored == 0
    assert (
        set(
            RawAuditModel._default_manager.using(DEFAULT_DB_ALIAS)
            .filter(run_id=run_uuid)
            .values_list("pk", flat=True)
        )
        == retained_ids_before
    )
    assert (
        not SystemAuditEventModel._default_manager.using(DEFAULT_DB_ALIAS)
        .filter(correlations__run_id=setup.run.run_id)
        .exists()
    )
    assert (
        not SystemAuditOutboxModel._default_manager.using(DEFAULT_DB_ALIAS)
        .filter(idempotency_key__contains=setup.run.run_id)
        .exists()
    )


@pytest.mark.django_db(transaction=True, available_apps=["apps.data_center", "apps.audit"])
@pytest.mark.parametrize("fail_outbox", [False, True])
def test_retained_recovery_preserves_failed_parent_and_binds_both_audits(
    fail_outbox: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A distinct single-use recovery either commits its linked evidence or rolls back."""
    from apps.data_center.infrastructure.financial_e1_recovery_binding import (
        claim_recovery,
        forecast_digest,
    )
    from core.exceptions import DataValidationError

    _require_postgres()
    review_digest = "c" * 64
    setup = _build_setup(review_digest)
    parent = SyncRunRepository().save(
        replace(
            setup.run,
            status=SyncRunStatus.FAILED,
            outcome="failed",
            fetched=2,
            failed=1,
            finished_at=timezone.now(),
            error_code="FINANCIAL_FACT_PROVENANCE_CONFLICT",
        )
    )
    predicted = setup.writer.preview_recovery(
        (setup.candidate,), exchange="SZSE", calendar_dataset_key="equity.trading_calendar"
    )
    args = (
        UUID(parent.run_id),
        parent.config_snapshot_hash,
        setup.main_audit,
        setup.balance_audit,
        forecast_digest(predicted, review_digest),
    )
    assert forecast_digest(predicted) != args[-1]
    child = claim_recovery(*args)
    assert child.run_id != parent.run_id
    with pytest.raises(DataValidationError, match="already has"):
        claim_recovery(*args)
    if fail_outbox:

        def fail(*args: object, **kwargs: object) -> NoReturn:
            raise RuntimeError("injected recovery outbox failure")

        monkeypatch.setattr(DjangoSystemAuditOutboxRepository, "enqueue", fail)
        with pytest.raises(RuntimeError, match="injected recovery outbox failure"):
            _write(replace(setup, run=child))
        assert not FinancialFactModel.objects.filter(ingested_run_id=child.run_id).exists()
        assert SyncRunRepository().get(child.run_id) == child
    else:
        facts = _write(replace(setup, run=child))
        assert len(facts) == 1
        assert FinancialFactModel.objects.filter(ingested_run_id=child.run_id).count() == 1
        saved = SyncRunRepository().get(child.run_id)
        assert saved and saved.fetched == 0 and saved.stored == 1
        event = SystemAuditEventModel.objects.get(
            correlations__run_id=parent.run_id, correlations__ingested_run_id=child.run_id
        )
        assert {ref["artifact_id"] for ref in event.evidence_refs} == {
            setup.main_audit_id,
            setup.balance_audit_id,
        }
    assert SyncRunRepository().get(parent.run_id) == parent
    assert {audit.content_hash for audit in (setup.main_audit, setup.balance_audit)} == set(
        RawAuditModel.objects.filter(run_id=parent.run_id).values_list("content_hash", flat=True)
    )
