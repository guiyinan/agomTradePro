"""SQLite integration coverage for formal exchange-calendar publication rows."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from django.db import transaction

from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationRequest,
    CalendarPublicationAuditPair,
    ReadCurrentExchangeCalendarPublicationQuery,
)
from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.contracts import DatasetKey
from apps.data_center.domain.control_plane import (
    CalendarNullableMemberCodecVersion,
    CalendarPublicationMemberReference,
    PublicationMember,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarSnapshot,
    ExchangeCalendarSnapshotCandidate,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarPublicationPointerExpectation,
    create_calendar_formal_publication_seal,
)
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
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
    _bounded_pg_lock_timeout_ms,
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
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from apps.data_center.infrastructure.tushare_client import TushareResponseEvidence
from apps.data_center.infrastructure.tushare_exchange_calendar_source import (
    TushareExchangeCalendarSource,
)
from core.exceptions import DataFetchError, ExternalServiceError
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])

_DATASET = DatasetKey("test.exchange_calendar", "contract-1", "schema-1")
_EXCHANGE = "SSE"
_START = date(2026, 10, 15)
_END = date(2026, 10, 18)
_FIELDS = "exchange,cal_date,is_open,pretrade_date"
_PROVIDER_ROWS: list[list[object]] = [
    ["SSE", "20261015", 1, "20261014"],
    ["SSE", "20261016", 1, "20261015"],
    ["SSE", "20261017", 0, "20261016"],
    ["SSE", "20261018", 0, "20261016"],
]
_SCHEMA_MODELS = (
    RawPayloadModel,
    ExchangeCalendarSnapshotFactModel,
    DatasetContractModel,
    DatasetPublicationPolicyModel,
    CanonicalPublicationModel,
    PublicationMemberModel,
    CoverageSnapshotModel,
    CanonicalPublicationPointerModel,
)


@pytest.fixture(autouse=True)
def _publication_schema(django_db_blocker: object) -> Iterator[None]:
    """Create or clear only the source, catalog, and publication tables under test."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(_SCHEMA_MODELS):
            yield


class _CapturedFrame:
    """Expose the real transport response witness expected by the Tushare source."""

    def __init__(self, evidence: TushareResponseEvidence) -> None:
        self.response_evidence = evidence


class _CapturedClient:
    """Return one local test response without opening a provider connection."""

    def __init__(self, evidence: TushareResponseEvidence) -> None:
        self._evidence = evidence

    def trade_cal(self, **kwargs: object) -> _CapturedFrame:
        """Return the prepared evidence for the requested complete calendar range."""

        del kwargs
        return _CapturedFrame(self._evidence)


class _Clock:
    """Deterministic, manually advanced UTC clock injected into the repository."""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        """Return the current configured UTC instant without auto-adjusting it."""

        return self.value


class _Principal:
    """Test lease matching the exact public publisher principal contract."""

    actor_type = "django_user"
    actor_id = "django-user:27"
    permission_codename = "publish_exchange_calendar"
    database_alias = "default"
    user_id = 27
    permission_id = 91

    def __init__(self, verified_at: datetime) -> None:
        self.verified_at = verified_at
        self.live = True

    def assert_live(self) -> None:
        """Fail after the test invalidates the authority lease."""

        if not self.live:
            raise ExternalServiceError(
                "test principal lease expired", code="CALENDAR_PUBLISHER_LEASE_EXPIRED"
            )


class _AuditPort:
    """Same-transaction Audit contract fake with commit-aware test receipts."""

    database_alias = "default"

    def __init__(self) -> None:
        self.pairs: dict[str, CalendarPublicationAuditPair] = {}
        self.fail_writes = False
        self.after_record: Callable[[], None] | None = None

    def record_published(
        self,
        record: object,
        *,
        principal: _Principal,
    ) -> CalendarPublicationAuditPair:
        """Stage one exact receipt for commit and optionally simulate Audit failure."""

        if self.fail_writes:
            raise DataFetchError("test Audit append failure", code="AUDIT_APPEND_FAILED")
        typed_record = record
        event_id = f"calendar-published:{typed_record.publication_id}"
        pair = _audit_pair(typed_record, event_id=event_id, actor_user_id=principal.user_id)
        transaction.on_commit(
            lambda: self.pairs.__setitem__(typed_record.publication_id, pair),
            using=self.database_alias,
        )
        if self.after_record is not None:
            self.after_record()
        return pair

    def verify_current_replay(
        self,
        record: object,
        *,
        principal: _Principal,
    ) -> CalendarPublicationAuditPair:
        """Require the original full receipt and same currently authorized actor."""

        pair = self.pairs.get(record.publication_id)
        if pair is None or pair.actor_user_id != principal.user_id:
            raise DataFetchError("exact Audit replay is missing", code="AUDIT_REPLAY_MISSING")
        _assert_pair_binds_record(pair, record)
        return pair

    def verify_published_integrity(
        self,
        record: object,
        *,
        as_of: datetime,
    ) -> CalendarPublicationAuditPair:
        """Verify the committed receipt at a cutoff without granting Audit read access."""

        pair = self.pairs.get(record.publication_id)
        if pair is None or pair.recorded_at > as_of:
            raise DataFetchError("published Audit pair is unavailable", code="AUDIT_PAIR_MISSING")
        _assert_pair_binds_record(pair, record)
        return pair


def _audit_pair(
    record: object, *, event_id: str, actor_user_id: int
) -> CalendarPublicationAuditPair:
    """Build a complete application-level pair bound to one formal record."""

    content = json.dumps(record.seal.to_payload(), sort_keys=True, separators=(",", ":"))
    return CalendarPublicationAuditPair(
        database_alias="default",
        dataset_key=record.seal.dataset.value,
        exchange=record.seal.exchange,
        publication_id=record.publication_id,
        publication_hash=record.seal.publication_hash,
        event_id=event_id,
        event_content_hash=sha256(content.encode("utf-8")).hexdigest(),
        actor_user_id=actor_user_id,
        outbox_id=uuid4(),
        idempotency_key=event_id,
        recorded_at=record.published_at,
    )


def _assert_pair_binds_record(pair: CalendarPublicationAuditPair, record: object) -> None:
    """Assert the fake persisted receipt retains every publication identity field."""

    assert pair.database_alias == "default"
    assert pair.dataset_key == record.seal.dataset.value
    assert pair.exchange == record.seal.exchange
    assert pair.publication_id == record.publication_id
    assert pair.publication_hash == record.seal.publication_hash
    assert pair.recorded_at == record.published_at


def _candidate() -> ExchangeCalendarSnapshotCandidate:
    """Persist exact local response bytes and parse them through the real source path."""

    body = json.dumps(
        {
            "code": 0,
            "msg": None,
            "data": {"fields": _FIELDS.split(","), "items": _PROVIDER_ROWS},
        },
        separators=(",", ":"),
    ).encode("utf-8")
    completed_at = datetime.now(UTC)
    capture = ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=completed_at,
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.DIRECT,
    )
    request_params: dict[str, object] = {
        "api_name": "trade_cal",
        "fields": _FIELDS,
        "params": {
            "exchange": _EXCHANGE,
            "start_date": _START.strftime("%Y%m%d"),
            "end_date": _END.strftime("%Y%m%d"),
        },
    }
    raw_reference = RetainProviderResponsePayloadUseCase(RawLandingRepository()).execute(
        capture,
        provider_name="tushare",
        dataset_key=_DATASET.value,
        api_name="trade_cal",
        request_params=request_params,
    )
    evidence = TushareResponseEvidence(
        body_sha256=capture.body_sha256,
        response_completed_at=completed_at,
        raw_payload_reference=raw_reference,
    )
    source = TushareExchangeCalendarSource(
        _CapturedClient(evidence),  # type: ignore[arg-type]
        RawLandingRepository(),
        dataset_key=_DATASET.value,
    )
    return source.fetch_candidate(_EXCHANGE, _START, _END)


def _catalog(
    *, ttl: int | None = 3600
) -> tuple[DatasetContractModel, DatasetPublicationPolicyModel]:
    """Insert explicit active config rows without implying official production values."""

    contract = DatasetContractModel._default_manager.create(
        dataset_key=_DATASET.value,
        contract_version=_DATASET.contract_version,
        schema_version=_DATASET.schema_version,
        owner="test-owner",
        frequency="reference",
        decision_critical=True,
        fields=[
            {
                "name": "sessions",
                "value_type": "json",
                "nullable": False,
                "zero_allowed": False,
            }
        ],
        calendar_response_max_age_seconds=ttl,
        active=True,
    )
    policy = DatasetPublicationPolicyModel._default_manager.create(
        dataset_key=_DATASET.value,
        contract_version=_DATASET.contract_version,
        schema_version=_DATASET.schema_version,
        policy_version="calendar-policy-v1",
        member_codec_version=CalendarNullableMemberCodecVersion.V1.value,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=["source", "fact_content_hash"],
        retention_days=30,
        active=True,
    )
    return contract, policy


def _request(
    snapshot: ExchangeCalendarSnapshot,
    contract: DatasetContractModel,
    policy: DatasetPublicationPolicyModel,
    *,
    expected_pointer: CalendarPublicationPointerExpectation | None = None,
    activation_id: str = "calendar-activation-1",
) -> CalendarFormalPublicationRequest:
    """Build a typed proposal using the exact stored source-row fact hash."""

    fact_row = ExchangeCalendarSnapshotFactModel._default_manager.get(
        snapshot_id=UUID(snapshot.snapshot_id)
    )
    member = PublicationMember(
        member_id=str(uuid4()),
        publication_id=str(uuid4()),
        dataset_key=_DATASET.value,
        natural_key=f"{_EXCHANGE}:{_START.isoformat()}:{_END.isoformat()}",
        source=snapshot.provider_name,
        source_record_id=snapshot.snapshot_id,
        fact_table=ExchangeCalendarSnapshotFactModel._meta.db_table,
        fact_pk=snapshot.snapshot_id,
        observed_at=None,
        raw_payload_hash=snapshot.raw_reference.payload_hash,
        quality_status="accepted",
        revision_number=1,
        available_at=None,
        fetched_at=snapshot.first_seen_at,
        source_published_at=None,
        raw_payload_scope="record_response_body",
        fact_content_hash=canonical_fact_content_hash(fact_row),
    )
    member_reference = CalendarPublicationMemberReference(
        member=member,
        snapshot_content_hash=snapshot.content_hash,
        snapshot_record_digest=snapshot.record_digest,
        codec_version=CalendarNullableMemberCodecVersion.V1,
    )
    seal = create_calendar_formal_publication_seal(
        dataset=_DATASET,
        exchange=snapshot.exchange,
        calendar_response_max_age_seconds=int(contract.calendar_response_max_age_seconds or 0),
        contract_recorded_at=contract.created_at,
        policy=policy.to_domain(),
        policy_recorded_at=policy.created_at,
        snapshot=snapshot,
        member_reference=member_reference,
    )
    pointer = expected_pointer or CalendarPublicationPointerExpectation(
        dataset_key=_DATASET.value,
        publication_key=seal.publication_key,
        pointer_id=None,
        publication_id=None,
        publication_hash=None,
        activation_id=None,
        updated_at=None,
    )
    return CalendarFormalPublicationRequest(
        proposed_seal=seal,
        expected_pointer=pointer,
        activation_id=activation_id,
    )


def _ready() -> tuple[object, _AuditPort, _Clock, _Principal, CalendarFormalPublicationRequest]:
    """Create one persisted source, exact active config, and bounded test principal."""

    snapshot = DjangoExchangeCalendarSnapshotRepository().save(_candidate())
    contract, policy = _catalog()
    verified_at = max(snapshot.recorded_at, contract.created_at, policy.created_at)
    clock = _Clock(verified_at + timedelta(seconds=2))
    principal = _Principal(verified_at=verified_at + timedelta(seconds=1))
    audit = _AuditPort()
    request = _request(snapshot, contract, policy)
    return snapshot, audit, clock, principal, request


def test_first_publish_rebuilds_source_and_current_read_verifies_exact_audit_pair() -> None:
    """Write all existing publication rows and read only that exact current winner."""

    from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
        DjangoFormalExchangeCalendarPublicationRepository,
    )

    snapshot, audit, clock, principal, request = _ready()
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit, using="default", clock=clock.now
    )

    with transaction.atomic(using="default"):
        commit = repository.publish(request, principal=principal)

    publication = CanonicalPublicationModel._default_manager.get()
    member = PublicationMemberModel._default_manager.get()
    coverage = CoverageSnapshotModel._default_manager.get()
    pointer_model = CanonicalPublicationPointerModel._default_manager.get()
    assert commit.record.seal.snapshot_reference == snapshot.reference()
    assert commit.record.publication_id == str(publication.publication_id)
    assert member.publication_id == publication.publication_id
    assert member.fact_content_hash == canonical_fact_content_hash(
        ExchangeCalendarSnapshotFactModel._default_manager.get()
    )
    assert coverage.publication_id == publication.publication_id
    assert pointer_model.publication_id == publication.publication_id
    assert pointer_model.updated_at == commit.record.published_at
    assert commit.pointer.updated_at == commit.record.published_at
    assert len(audit.pairs) == 1

    clock.value += timedelta(seconds=2)
    query = ReadCurrentExchangeCalendarPublicationQuery(
        dataset_key=_DATASET.value,
        exchange=_EXCHANGE,
        as_of=clock.now(),
    )
    with pytest.raises(DataFetchError) as owner_error:
        repository.read_current(query)
    assert owner_error.value.code == "CALENDAR_FORMAL_READ_TRANSACTION_OWNER_INVALID"
    with transaction.atomic(using="default"):
        result = repository.read_current(query)
    assert result is not None
    assert result.record == commit.record
    assert result.pointer.updated_at == result.record.published_at
    assert result.must_not_execute is True


def test_missing_audit_integrity_pair_blocks_a_current_read() -> None:
    """A pointer and publication without the exact paired Audit receipt are unusable."""

    from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
        DjangoFormalExchangeCalendarPublicationRepository,
    )

    _snapshot, audit, clock, principal, request = _ready()
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit, using="default", clock=clock.now
    )
    with transaction.atomic(using="default"):
        repository.publish(request, principal=principal)
    audit.pairs.clear()

    query = ReadCurrentExchangeCalendarPublicationQuery(
        dataset_key=_DATASET.value,
        exchange=_EXCHANGE,
        as_of=clock.now() + timedelta(seconds=2),
    )
    with transaction.atomic(using="default"):
        with pytest.raises(DataFetchError) as caught:
            repository.read_current(query)

    assert caught.value.code == "AUDIT_PAIR_MISSING"


def test_audit_failure_rolls_back_all_formal_publication_rows() -> None:
    """An Audit append failure must not leave a publication or moved pointer."""

    from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
        DjangoFormalExchangeCalendarPublicationRepository,
    )

    _snapshot, audit, _clock, principal, request = _ready()
    audit.fail_writes = True
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit, using="default", clock=_clock.now
    )

    with pytest.raises(DataFetchError, match="test Audit append failure"):
        with transaction.atomic(using="default"):
            repository.publish(request, principal=principal)

    assert CanonicalPublicationModel._default_manager.count() == 0
    assert PublicationMemberModel._default_manager.count() == 0
    assert CoverageSnapshotModel._default_manager.count() == 0
    assert CanonicalPublicationPointerModel._default_manager.count() == 0
    assert audit.pairs == {}


def test_post_audit_ttl_expiry_rolls_back_instead_of_resetting_source_age() -> None:
    """The TTL remains anchored to first_seen_at after the Audit call."""

    from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
        DjangoFormalExchangeCalendarPublicationRepository,
    )

    snapshot = DjangoExchangeCalendarSnapshotRepository().save(_candidate())
    contract, policy = _catalog(ttl=30)
    latest_known = max(snapshot.recorded_at, contract.created_at, policy.created_at)
    clock = _Clock(latest_known + timedelta(seconds=1))
    principal = _Principal(clock.now() - timedelta(microseconds=1))
    audit = _AuditPort()
    audit.after_record = lambda: setattr(
        clock, "value", snapshot.first_seen_at + timedelta(seconds=30)
    )
    request = _request(snapshot, contract, policy)
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit, using="default", clock=clock.now
    )

    with pytest.raises(DataFetchError) as caught:
        with transaction.atomic(using="default"):
            repository.publish(request, principal=principal)

    assert caught.value.code == "CALENDAR_FORMAL_TTL_EXPIRED"
    assert CanonicalPublicationModel._default_manager.count() == 0
    assert CanonicalPublicationPointerModel._default_manager.count() == 0
    assert audit.pairs == {}


def test_forward_publication_requires_a_later_pointer_clock_and_supersedes_atomically() -> None:
    """A forward switch advances pointer time and truncates only its old winner."""

    from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
        DjangoFormalExchangeCalendarPublicationRepository,
    )

    first_snapshot, audit, clock, principal, first_request = _ready()
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit, using="default", clock=clock.now
    )
    with transaction.atomic(using="default"):
        first = repository.publish(first_request, principal=principal)

    second_snapshot = DjangoExchangeCalendarSnapshotRepository().save(_candidate())
    contract = DatasetContractModel._default_manager.get(dataset_key=_DATASET.value)
    policy = DatasetPublicationPolicyModel._default_manager.get(dataset_key=_DATASET.value)
    second_request = _request(
        second_snapshot,
        contract,
        policy,
        expected_pointer=first.pointer,
        activation_id="calendar-activation-2",
    )
    clock.value = first.record.published_at
    with pytest.raises(DataFetchError) as caught:
        with transaction.atomic(using="default"):
            repository.publish(second_request, principal=principal)
    assert caught.value.code == "CALENDAR_PUBLICATION_FORWARD_TIME_INVALID"
    assert CanonicalPublicationModel._default_manager.filter(state="published").count() == 1

    clock.value = first.record.published_at + timedelta(seconds=1)
    with transaction.atomic(using="default"):
        second = repository.publish(second_request, principal=principal)

    old_row = CanonicalPublicationModel._default_manager.get(pk=UUID(first.record.publication_id))
    pointer_model = CanonicalPublicationPointerModel._default_manager.get()
    old_member = PublicationMemberModel._default_manager.get(
        publication_id=UUID(first.record.publication_id)
    )
    assert old_member.source_record_id == first_snapshot.snapshot_id
    assert old_row.state == "superseded"
    assert old_row.superseded_at == second.record.published_at
    assert pointer_model.publication_id == UUID(second.record.publication_id)
    assert pointer_model.updated_at == second.record.published_at
    assert CanonicalPublicationModel._default_manager.filter(state="published").count() == 1
    assert CanonicalPublicationModel._default_manager.count() == 2
    assert len(audit.pairs) == 2


def test_exact_replay_requires_existing_complete_pair_same_activation_and_actor() -> None:
    """Idempotent replay verifies the old winner and does not repair or duplicate it."""

    from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
        DjangoFormalExchangeCalendarPublicationRepository,
    )

    snapshot, audit, clock, principal, first_request = _ready()
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit, using="default", clock=clock.now
    )
    with transaction.atomic(using="default"):
        first = repository.publish(first_request, principal=principal)
    replay_request = _request(
        snapshot,
        DatasetContractModel._default_manager.get(dataset_key=_DATASET.value),
        DatasetPublicationPolicyModel._default_manager.get(dataset_key=_DATASET.value),
        expected_pointer=first.pointer,
    )
    clock.value = first.record.published_at + timedelta(seconds=2)
    with transaction.atomic(using="default"):
        replay = repository.publish(replay_request, principal=principal)

    assert replay.transition.value == "exact_current_replay"
    assert replay.record.publication_id == first.record.publication_id
    assert replay.record.published_at == first.record.published_at
    assert replay.pointer == first.pointer
    assert CanonicalPublicationModel._default_manager.count() == 1
    assert PublicationMemberModel._default_manager.count() == 1
    assert CoverageSnapshotModel._default_manager.count() == 1
    assert len(audit.pairs) == 1

    audit.pairs.clear()
    with pytest.raises(DataFetchError):
        with transaction.atomic(using="default"):
            repository.publish(replay_request, principal=principal)
    assert CanonicalPublicationModel._default_manager.count() == 1
    assert CanonicalPublicationPointerModel._default_manager.get().publication_id == UUID(
        first.record.publication_id
    )


def test_ambiguous_active_contract_blocks_before_any_publication_write() -> None:
    """Multiple active contract versions are not resolved by newest-row ordering."""

    from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
        DjangoFormalExchangeCalendarPublicationRepository,
    )

    _snapshot, audit, _clock, principal, request = _ready()
    DatasetContractModel._default_manager.create(
        dataset_key=_DATASET.value,
        contract_version="contract-2",
        schema_version=_DATASET.schema_version,
        owner="test-owner-2",
        frequency="reference",
        decision_critical=True,
        fields=[{"name": "sessions", "value_type": "json"}],
        calendar_response_max_age_seconds=3600,
        active=True,
    )
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit, using="default", clock=_clock.now
    )

    with pytest.raises(DataFetchError) as caught:
        with transaction.atomic(using="default"):
            repository.publish(request, principal=principal)

    assert caught.value.code == "CALENDAR_FORMAL_CONTRACT_AMBIGUOUS"
    assert CanonicalPublicationModel._default_manager.count() == 0
    assert CanonicalPublicationPointerModel._default_manager.count() == 0


def test_publisher_principal_from_another_database_alias_is_rejected() -> None:
    """A valid user/permission lease cannot cross the repository's database alias."""

    from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
        DjangoFormalExchangeCalendarPublicationRepository,
    )

    _snapshot, audit, clock, principal, request = _ready()
    principal.database_alias = "other"
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit, using="default", clock=clock.now
    )
    with transaction.atomic(using="default"):
        with pytest.raises(DataFetchError) as caught:
            repository.publish(request, principal=principal)

    assert caught.value.code == "CALENDAR_PUBLICATION_AUTHORITY_INVALID"
    assert CanonicalPublicationModel._default_manager.count() == 0
    assert PublicationMemberModel._default_manager.count() == 0
    assert CoverageSnapshotModel._default_manager.count() == 0
    assert CanonicalPublicationPointerModel._default_manager.count() == 0


@pytest.mark.parametrize(
    ("configured_timeout", "expected_timeout"),
    [
        ("0.5ms", "0.5ms"),
        ("2s", "2s"),
        ("0", 5_000),
        ("9s", 5_000),
    ],
)
def test_postgresql_lock_timeout_preserves_stricter_submillisecond_setting(
    configured_timeout: str,
    expected_timeout: str | int,
) -> None:
    """Keep stricter transaction timeouts exact while applying the five-second cap."""

    assert _bounded_pg_lock_timeout_ms(configured_timeout) == expected_timeout
