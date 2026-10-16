"""SQLite coverage for the exact trusted calendar-preparation repository read."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from django.db import transaction

from apps.data_center.domain.exchange_calendar import make_exchange_calendar_snapshot
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.exchange_calendar_repository import (
    DjangoExchangeCalendarSnapshotRepository,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    ExchangeCalendarSnapshotFactModel,
    RawPayloadModel,
)
from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
    DjangoFormalExchangeCalendarPublicationRepository,
)
from apps.data_center.infrastructure.publication_fact_evidence import (
    canonical_fact_content_hash,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)
from core.exceptions import DataFetchError
from tests.component.data_center import (
    test_formal_exchange_calendar_publication_repository as fixtures,
)
from tests.component.data_center.test_formal_exchange_calendar_publication_repository import (
    _publication_schema,
)

__all__ = ["_publication_schema"]
pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])


def test_load_exact_returns_the_locked_source_catalog_and_absent_pointer() -> None:
    """Resolve exact persisted source and catalog without creating publication rows."""

    snapshot, audit, clock, _principal, _request = fixtures._ready()
    raw_row_before = (
        RawPayloadModel.objects.filter(payload_id=snapshot.raw_reference.payload_id).values().get()
    )
    fact_row_before = (
        ExchangeCalendarSnapshotFactModel.objects.filter(snapshot_id=snapshot.snapshot_id)
        .values()
        .get()
    )
    contract_row_before = (
        DatasetContractModel.objects.filter(dataset_key=fixtures._DATASET.value).values().get()
    )
    policy_row_before = (
        DatasetPublicationPolicyModel.objects.filter(dataset_key=fixtures._DATASET.value)
        .values()
        .get()
    )
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit,
        using="default",
        clock=clock.now,
    )
    known_at: datetime = clock.now()

    with transaction.atomic(using="default"):
        context = repository.load_exact(snapshot.reference(), known_at=known_at)

    assert context.snapshot == snapshot
    assert context.contract.key == fixtures._DATASET
    assert context.contract_recorded_at <= known_at
    assert context.policy.dataset == fixtures._DATASET
    assert context.policy_recorded_at <= known_at
    assert context.member_reference.member.source_record_id == snapshot.snapshot_id
    fact = ExchangeCalendarSnapshotFactModel.objects.get(snapshot_id=snapshot.snapshot_id)
    assert context.member_reference.member.fact_content_hash == canonical_fact_content_hash(fact)
    assert context.current_pointer.is_absent is True
    assert (
        RawPayloadModel.objects.filter(payload_id=snapshot.raw_reference.payload_id).values().get()
        == raw_row_before
    )
    assert (
        ExchangeCalendarSnapshotFactModel.objects.filter(snapshot_id=snapshot.snapshot_id)
        .values()
        .get()
        == fact_row_before
    )
    assert (
        DatasetContractModel.objects.filter(dataset_key=fixtures._DATASET.value).values().get()
        == contract_row_before
    )
    assert (
        DatasetPublicationPolicyModel.objects.filter(dataset_key=fixtures._DATASET.value)
        .values()
        .get()
        == policy_row_before
    )
    assert CanonicalPublicationModel.objects.count() == 0
    assert PublicationMemberModel.objects.count() == 0
    assert CoverageSnapshotModel.objects.count() == 0
    assert CanonicalPublicationPointerModel.objects.count() == 0


def test_load_exact_returns_none_for_missing_or_mismatched_exact_source() -> None:
    """Never substitute another snapshot when an exact reference does not match."""

    snapshot, audit, clock, _principal, _request = fixtures._ready()
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit,
        using="default",
        clock=clock.now,
    )
    missing = replace(snapshot.reference(), snapshot_id=str(uuid4()))
    altered = replace(snapshot.reference(), content_hash=f"sha256:{'0' * 64}")

    with transaction.atomic(using="default"):
        assert repository.load_exact(missing, known_at=clock.now()) is None
        assert repository.load_exact(altered, known_at=clock.now()) is None


def test_load_exact_blocks_before_database_access_without_owned_outer_transaction() -> None:
    """Preparation joins a caller-owned transaction instead of opening its own."""

    snapshot, audit, clock, _principal, _request = fixtures._ready()
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit,
        using="default",
        clock=clock.now,
    )

    with pytest.raises(DataFetchError) as caught:
        repository.load_exact(snapshot.reference(), known_at=clock.now())

    assert caught.value.code == "CALENDAR_FORMAL_PREPARATION_TRANSACTION_OWNER_INVALID"


def test_load_exact_does_not_expose_a_snapshot_recorded_after_the_cutoff() -> None:
    """Exact facts recorded after the caller's cutoff are not visible yet."""

    snapshot, audit, clock, _principal, _request = fixtures._ready()
    known_at = max(snapshot.recorded_at, clock.now())
    future_record = make_exchange_calendar_snapshot(
        snapshot.candidate,
        snapshot_id=snapshot.snapshot_id,
        recorded_at=known_at + timedelta(seconds=1),
    )
    ExchangeCalendarSnapshotFactModel.objects.filter(snapshot_id=snapshot.snapshot_id).update(
        recorded_at=future_record.recorded_at,
        record_digest=future_record.record_digest,
    )
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit,
        using="default",
        clock=clock.now,
    )

    with transaction.atomic(using="default"):
        context = repository.load_exact(future_record.reference(), known_at=known_at)

    assert context is None


def test_load_exact_blocks_when_active_configuration_is_missing_or_ambiguous() -> None:
    """Never synthesize a contract or choose one of multiple active versions."""

    snapshot = DjangoExchangeCalendarSnapshotRepository().save(fixtures._candidate())
    now = datetime.now(UTC) + timedelta(seconds=1)
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=fixtures._AuditPort(),
        using="default",
        clock=lambda: now,
    )

    with transaction.atomic(using="default"):
        with pytest.raises(DataFetchError) as missing:
            repository.load_exact(snapshot.reference(), known_at=now)
    assert missing.value.code == "CALENDAR_FORMAL_CONTRACT_MISSING"

    _snapshot, audit, clock, _principal, _request = fixtures._ready()
    DatasetContractModel.objects.create(
        dataset_key=fixtures._DATASET.value,
        contract_version="contract-2",
        schema_version=fixtures._DATASET.schema_version,
        owner="test-owner-2",
        frequency="reference",
        decision_critical=True,
        fields=[{"name": "sessions", "value_type": "json"}],
        calendar_response_max_age_seconds=3600,
        active=True,
    )
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit,
        using="default",
        clock=clock.now,
    )
    with transaction.atomic(using="default"):
        with pytest.raises(DataFetchError) as ambiguous:
            repository.load_exact(_snapshot.reference(), known_at=clock.now())
    assert ambiguous.value.code == "CALENDAR_FORMAL_CONTRACT_AMBIGUOUS"


def test_load_exact_blocks_when_active_policy_is_missing_or_only_inactive() -> None:
    """Never use an absent or inactive policy as a default."""

    snapshot, audit, clock, _principal, _request = fixtures._ready()
    DatasetPublicationPolicyModel.objects.all().delete()
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit,
        using="default",
        clock=clock.now,
    )
    with transaction.atomic(using="default"):
        with pytest.raises(DataFetchError) as missing:
            repository.load_exact(snapshot.reference(), known_at=clock.now())
    assert missing.value.code == "CALENDAR_FORMAL_POLICY_MISSING"

    DatasetPublicationPolicyModel.objects.create(
        dataset_key=fixtures._DATASET.value,
        contract_version=fixtures._DATASET.contract_version,
        schema_version=fixtures._DATASET.schema_version,
        policy_version="calendar-policy-v1",
        member_codec_version="calendar-nullable-member-v1",
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=["source", "fact_content_hash"],
        retention_days=30,
        active=False,
    )
    with transaction.atomic(using="default"):
        with pytest.raises(DataFetchError) as inactive:
            repository.load_exact(snapshot.reference(), known_at=clock.now())
    assert inactive.value.code == "CALENDAR_FORMAL_POLICY_MISSING"


def test_load_exact_blocks_when_catalog_knowledge_is_after_cutoff() -> None:
    """An active row updated after the cutoff cannot be reported as known then."""

    snapshot, audit, clock, _principal, _request = fixtures._ready()
    DatasetPublicationPolicyModel.objects.filter(dataset_key=fixtures._DATASET.value).update(
        updated_at=clock.now() + timedelta(seconds=5)
    )
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit,
        using="default",
        clock=clock.now,
    )

    with transaction.atomic(using="default"):
        with pytest.raises(DataFetchError) as caught:
            repository.load_exact(snapshot.reference(), known_at=clock.now())

    assert caught.value.code == "CALENDAR_FORMAL_CONFIGURATION_NOT_KNOWN"


def test_load_exact_blocks_when_active_contract_has_no_explicit_ttl() -> None:
    """The preparation reader never invents a calendar response-age budget."""

    snapshot = DjangoExchangeCalendarSnapshotRepository().save(fixtures._candidate())
    contract, _policy = fixtures._catalog(ttl=None)
    known_at = max(snapshot.recorded_at, contract.created_at) + timedelta(seconds=1)
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=fixtures._AuditPort(),
        using="default",
        clock=lambda: known_at,
    )

    with transaction.atomic(using="default"):
        with pytest.raises(DataFetchError) as caught:
            repository.load_exact(snapshot.reference(), known_at=known_at)

    assert caught.value.code == "CALENDAR_FORMAL_TTL_MISSING"


def test_load_exact_rejects_a_tampered_fact_instead_of_returning_its_reference() -> None:
    """A fact row whose stored calendar differs from retained source bytes is blocked."""

    snapshot, audit, clock, _principal, _request = fixtures._ready()
    fact = ExchangeCalendarSnapshotFactModel.objects.get(snapshot_id=snapshot.snapshot_id)
    stored_days = list(fact.days)
    stored_days[0] = {**stored_days[0], "is_open": not stored_days[0]["is_open"]}
    ExchangeCalendarSnapshotFactModel.objects.filter(snapshot_id=snapshot.snapshot_id).update(
        days=stored_days
    )
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit,
        using="default",
        clock=clock.now,
    )

    with transaction.atomic(using="default"):
        with pytest.raises(DataFetchError) as caught:
            repository.load_exact(snapshot.reference(), known_at=clock.now())

    assert caught.value.code == "EXCHANGE_CALENDAR_SNAPSHOT_CORRUPT"


def test_load_exact_reparses_locked_raw_payload_instead_of_trusting_fact_json() -> None:
    """An altered retained response invalidates even a still matching fact row."""

    snapshot, audit, clock, _principal, _request = fixtures._ready()
    RawPayloadModel.objects.filter(payload_id=snapshot.raw_reference.payload_id).update(
        payload={"exact_original_utf8_json": "{}"}
    )
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit,
        using="default",
        clock=clock.now,
    )

    with transaction.atomic(using="default"):
        with pytest.raises(DataFetchError) as caught:
            repository.load_exact(snapshot.reference(), known_at=clock.now())

    assert caught.value.code == "EXCHANGE_CALENDAR_RAW_REFERENCE_MISMATCH"


def test_load_exact_verifies_old_current_audit_and_does_not_repair_it() -> None:
    """The current pointer is unusable for preparation when its Audit pair is absent."""

    _snapshot, audit, clock, principal, request = fixtures._ready()
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit,
        using="default",
        clock=clock.now,
    )
    with transaction.atomic(using="default"):
        current = repository.publish(request, principal=principal)
    audit.pairs.clear()
    successor = DjangoExchangeCalendarSnapshotRepository().save(fixtures._candidate())
    known_at = max(clock.now(), successor.recorded_at) + timedelta(seconds=1)

    with transaction.atomic(using="default"):
        with pytest.raises(DataFetchError) as caught:
            repository.load_exact(successor.reference(), known_at=known_at)

    assert caught.value.code == "AUDIT_PAIR_MISSING"
    assert CanonicalPublicationModel.objects.count() == 1
    assert CanonicalPublicationModel.objects.get().publication_id == UUID(
        current.record.publication_id
    )
    assert CanonicalPublicationPointerModel.objects.get().publication_id == UUID(
        current.record.publication_id
    )
    assert audit.pairs == {}


def test_load_exact_blocks_publication_history_when_current_pointer_is_missing() -> None:
    """An orphaned publication history cannot be mistaken for a first publish."""

    _snapshot, audit, clock, principal, request = fixtures._ready()
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit,
        using="default",
        clock=clock.now,
    )
    with transaction.atomic(using="default"):
        current = repository.publish(request, principal=principal)
    CanonicalPublicationPointerModel.objects.all().delete()
    successor = DjangoExchangeCalendarSnapshotRepository().save(fixtures._candidate())
    known_at = max(clock.now(), successor.recorded_at) + timedelta(seconds=1)

    with transaction.atomic(using="default"):
        with pytest.raises(DataFetchError) as caught:
            repository.load_exact(successor.reference(), known_at=known_at)

    assert caught.value.code == "CALENDAR_FORMAL_POINTER_MISSING"
    assert CanonicalPublicationModel.objects.count() == 1
    assert CanonicalPublicationModel.objects.get().publication_id == UUID(
        current.record.publication_id
    )
    assert CanonicalPublicationPointerModel.objects.count() == 0
    assert len(audit.pairs) == 1


def test_load_exact_allows_expired_old_current_when_the_exact_new_source_is_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old TTL expiry does not hide its exact pointer from new-source preparation."""

    class EarlierCaptureClock:
        @staticmethod
        def now(tz: object = None) -> datetime:
            return datetime.now(UTC) - timedelta(seconds=3550)

    with monkeypatch.context() as patcher:
        patcher.setattr(fixtures, "datetime", EarlierCaptureClock)
        old_snapshot, audit, clock, principal, old_request = fixtures._ready()

    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit,
        using="default",
        clock=clock.now,
    )
    with transaction.atomic(using="default"):
        old = repository.publish(old_request, principal=principal)

    fresh_snapshot = DjangoExchangeCalendarSnapshotRepository().save(fixtures._candidate())
    known_at = old_snapshot.first_seen_at + timedelta(seconds=3601)
    assert not old.record.is_effective_at(known_at)

    with transaction.atomic(using="default"):
        context = repository.load_exact(fresh_snapshot.reference(), known_at=known_at)

    assert context.current_pointer == old.pointer
    assert context.snapshot.snapshot_id == fresh_snapshot.snapshot_id
    assert CanonicalPublicationModel.objects.count() == 1
    assert CanonicalPublicationPointerModel.objects.get().publication_id == UUID(
        old.record.publication_id
    )
