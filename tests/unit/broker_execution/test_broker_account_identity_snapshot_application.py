"""Pure tests for Broker account identity snapshot Application workflow."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.broker_execution.application.broker_account_identity_snapshot import (
    AccountIdentitySourceDefinition,
    BrokerAccountIdentityIssuanceActor,
    BrokerAccountIdentitySnapshotConflict,
    BrokerAccountIdentitySnapshotCorruption,
    BrokerAccountIdentitySnapshotUnavailable,
    BrokerBindingAgentRawProjection,
    GetCurrentBrokerAccountIdentitySnapshot,
    GetCurrentBrokerAccountIdentitySnapshotCommand,
    GetExactBrokerAccountIdentitySnapshot,
    GetExactBrokerAccountIdentitySnapshotCommand,
    IssueBrokerAccountIdentitySnapshot,
    IssueBrokerAccountIdentitySnapshotCommand,
    PersistedBrokerAccountIdentitySnapshot,
)
from apps.broker_execution.domain.broker_account_identity_snapshot import (
    BrokerAccountIdentitySnapshot,
    KeyedBrokerAccountReferenceDigest,
)

NOW = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
OPAQUE_QMT_REFERENCE = b"qmt-secret-reference-must-not-leak"


def _account(**changes: object) -> AccountIdentitySourceDefinition:
    base: dict[str, object] = {
        "source_id": "account-source-1",
        "source_version": "v1",
        "content_hash": HASH_A,
        "account_namespace": "account-primary",
        "account_id": "portfolio-account-alpha",
        "owner_user_id": 7,
        "account_type": "real",
        "is_active": True,
        "recorded_at": NOW - timedelta(minutes=10),
        "valid_until": NOW + timedelta(hours=2),
    }
    base.update(changes)
    return AccountIdentitySourceDefinition(**base)  # type: ignore[arg-type]


def _broker(**changes: object) -> BrokerBindingAgentRawProjection:
    base: dict[str, object] = {
        "broker_account_namespace": "qmt-live",
        "broker_account_id": 42,
        "binding_revision": 3,
        "binding_content_hash": HASH_B,
        "binding_owner_user_id": 7,
        "agent_id": "agent-1",
        "agent_version": "v4",
        "agent_content_hash": HASH_C,
        "agent_owner_user_id": 7,
        "broker_account_category": "STOCK",
        "qmt_account_ref_opaque": OPAQUE_QMT_REFERENCE,
        "recorded_at": NOW - timedelta(minutes=5),
    }
    base.update(changes)
    return BrokerBindingAgentRawProjection(**base)  # type: ignore[arg-type]


def _command(**changes: object) -> IssueBrokerAccountIdentitySnapshotCommand:
    base: dict[str, object] = {
        "snapshot_id": "broker-account-identity-1",
        "snapshot_version": "v1",
        "account_source_id": "account-source-1",
        "account_source_version": "v1",
        "broker_account_namespace": "qmt-live",
        "broker_account_id": 42,
    }
    base.update(changes)
    return IssueBrokerAccountIdentitySnapshotCommand(**base)  # type: ignore[arg-type]


class SequenceAccountProvider:
    def __init__(self, *values: AccountIdentitySourceDefinition | None) -> None:
        self.values = list(values)
        self.calls: list[tuple[str, str, datetime]] = []

    def get_exact_current(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> AccountIdentitySourceDefinition | None:
        self.calls.append((source_id, source_version, as_of))
        return self.values.pop(0)


class SequenceBrokerProvider:
    def __init__(self, *values: BrokerBindingAgentRawProjection | None) -> None:
        self.values = list(values)
        self.calls: list[tuple[str, int, datetime]] = []

    def get_exact_current(
        self,
        *,
        broker_account_namespace: str,
        broker_account_id: int,
        as_of: datetime,
    ) -> BrokerBindingAgentRawProjection | None:
        self.calls.append((broker_account_namespace, broker_account_id, as_of))
        return self.values.pop(0)


class RecordingDigestService:
    def __init__(self) -> None:
        self.inputs: list[bytes] = []

    def digest(self, *, opaque_reference: bytes) -> KeyedBrokerAccountReferenceDigest:
        self.inputs.append(opaque_reference)
        return KeyedBrokerAccountReferenceDigest(
            algorithm="hmac-sha256", key_id="qmt-ref-key-v2", digest=HASH_C
        )


class FakeRepository:
    def __init__(self, now: datetime = NOW) -> None:
        self.clock = now
        self.by_identity: dict[tuple[str, str], PersistedBrokerAccountIdentitySnapshot] = {}
        self.heads: dict[tuple[str, int], PersistedBrokerAccountIdentitySnapshot] = {}
        self.append_result: PersistedBrokerAccountIdentitySnapshot | None = None
        self.append_calls: list[
            tuple[PersistedBrokerAccountIdentitySnapshot, str | None, datetime]
        ] = []

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.clock

    def get_identity_winner(
        self, *, snapshot_id: str, snapshot_version: str, as_of: datetime
    ) -> PersistedBrokerAccountIdentitySnapshot | None:
        value = self.by_identity.get((snapshot_id, snapshot_version))
        return value if value is not None and value.snapshot.recorded_at <= as_of else None

    def get_current_head(
        self,
        *,
        broker_account_namespace: str,
        broker_account_id: int,
        as_of: datetime,
    ) -> PersistedBrokerAccountIdentitySnapshot | None:
        value = self.heads.get((broker_account_namespace, broker_account_id))
        return value if value is not None and value.snapshot.is_knowable_at(as_of) else None

    def append(
        self,
        record: PersistedBrokerAccountIdentitySnapshot,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedBrokerAccountIdentitySnapshot:
        self.append_calls.append((record, expected_predecessor_hash, recorded_at))
        if self.append_result is not None:
            return self.append_result
        snapshot = record.snapshot
        current = self.heads.get((snapshot.broker_account_namespace, snapshot.broker_account_id))
        actual_hash = current.snapshot.content_hash if current is not None else None
        if actual_hash != expected_predecessor_hash:
            return current if current is not None else record
        self.by_identity[(snapshot.snapshot_id, snapshot.snapshot_version)] = record
        self.heads[(snapshot.broker_account_namespace, snapshot.broker_account_id)] = record
        return record

    def get_exact_by_hash(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedBrokerAccountIdentitySnapshot | None:
        value = self.by_identity.get((snapshot_id, snapshot_version))
        if value is None or value.snapshot.content_hash != expected_content_hash:
            return None
        return value if value.snapshot.is_knowable_at(as_of) else None


def _service(
    repository: FakeRepository,
    account_provider: SequenceAccountProvider | None = None,
    broker_provider: SequenceBrokerProvider | None = None,
    digest_service: RecordingDigestService | None = None,
) -> tuple[IssueBrokerAccountIdentitySnapshot, RecordingDigestService]:
    account = _account()
    broker = _broker()
    digest = digest_service or RecordingDigestService()
    return (
        IssueBrokerAccountIdentitySnapshot(
            account_provider=account_provider or SequenceAccountProvider(account, account),
            broker_provider=broker_provider or SequenceBrokerProvider(broker, broker),
            digest_service=digest,
            actor=BrokerAccountIdentityIssuanceActor(actor_id="staff-user-9", user_id=9),
            repository=repository,
            ttl=timedelta(hours=1),
        ),
        digest,
    )


def _issue(repository: FakeRepository | None = None) -> BrokerAccountIdentitySnapshot:
    repo = repository or FakeRepository()
    service, _ = _service(repo)
    return service.execute(_command())


def test_issue_uses_id_only_command_same_cutoff_and_separate_namespaces() -> None:
    repository = FakeRepository()
    account = _account()
    broker = _broker()
    account_provider = SequenceAccountProvider(account, account)
    broker_provider = SequenceBrokerProvider(broker, broker)
    service, digest = _service(repository, account_provider, broker_provider)

    snapshot = service.execute(_command())

    assert {field.name for field in fields(IssueBrokerAccountIdentitySnapshotCommand)} == {
        "snapshot_id",
        "snapshot_version",
        "account_source_id",
        "account_source_version",
        "broker_account_namespace",
        "broker_account_id",
    }
    assert [call[2] for call in account_provider.calls] == [NOW, NOW]
    assert [call[2] for call in broker_provider.calls] == [NOW, NOW]
    assert snapshot.account_source_ref.account_id == "portfolio-account-alpha"
    assert snapshot.broker_account_id == 42
    assert type(snapshot.account_source_ref.account_id) is str
    assert type(snapshot.broker_account_id) is int
    assert snapshot.permission == "inactive"
    assert snapshot.activation_available is False
    assert snapshot.must_not_execute is True
    assert digest.inputs == [OPAQUE_QMT_REFERENCE]


def test_plaintext_qmt_reference_never_enters_snapshot_payload() -> None:
    snapshot = _issue()

    payload_text = repr(snapshot.to_payload())
    assert OPAQUE_QMT_REFERENCE.decode() not in payload_text
    assert snapshot.qmt_account_ref_digest.algorithm == "hmac-sha256"
    assert snapshot.qmt_account_ref_digest.key_id == "qmt-ref-key-v2"


@pytest.mark.parametrize("missing", ["account", "broker"])  # type: ignore[misc]
def test_missing_exact_source_fails_closed(missing: str) -> None:
    repository = FakeRepository()
    account_provider = SequenceAccountProvider(None, None) if missing == "account" else None
    broker_provider = SequenceBrokerProvider(None, None) if missing == "broker" else None
    service, _ = _service(repository, account_provider, broker_provider)

    with pytest.raises(BrokerAccountIdentitySnapshotUnavailable):
        service.execute(_command())


@pytest.mark.parametrize("source", ["account", "broker"])  # type: ignore[misc]
def test_double_read_source_drift_fails_closed(source: str) -> None:
    repository = FakeRepository()
    account_provider = SequenceAccountProvider(
        _account(), _account(content_hash=HASH_B) if source == "account" else _account()
    )
    broker_provider = SequenceBrokerProvider(
        _broker(),
        _broker(agent_content_hash=HASH_A) if source == "broker" else _broker(),
    )
    service, _ = _service(repository, account_provider, broker_provider)

    with pytest.raises(BrokerAccountIdentitySnapshotCorruption, match="changed"):
        service.execute(_command())

    assert repository.append_calls == []


@pytest.mark.parametrize(  # type: ignore[misc]
    "field_name", ["binding_owner_user_id", "agent_owner_user_id"]
)
def test_broker_owner_must_match_exact_account_owner(field_name: str) -> None:
    bad_broker = _broker(**{field_name: 8})
    service, _ = _service(
        FakeRepository(),
        broker_provider=SequenceBrokerProvider(bad_broker, bad_broker),
    )

    with pytest.raises(BrokerAccountIdentitySnapshotCorruption, match="owner"):
        service.execute(_command())


def test_stock_category_cannot_substitute_for_real_account_truth() -> None:
    corrupted = _account()
    object.__setattr__(corrupted, "account_type", "simulated")
    service, _ = _service(
        FakeRepository(), account_provider=SequenceAccountProvider(corrupted, corrupted)
    )

    with pytest.raises(ValueError, match="account_type"):
        service.execute(_command())


def test_opaque_reference_requires_exact_bytes() -> None:
    with pytest.raises(TypeError, match="exact bytes"):
        _broker(qmt_account_ref_opaque="plaintext")


def test_digest_service_type_substitution_fails_closed() -> None:
    class BadDigestService:
        def digest(self, *, opaque_reference: bytes) -> object:
            return {"algorithm": "sha256", "digest": HASH_A}

    account = _account()
    broker = _broker()
    service = IssueBrokerAccountIdentitySnapshot(
        account_provider=SequenceAccountProvider(account, account),
        broker_provider=SequenceBrokerProvider(broker, broker),
        digest_service=BadDigestService(),
        actor=BrokerAccountIdentityIssuanceActor(actor_id="staff-9", user_id=9),
        repository=FakeRepository(),
        ttl=timedelta(hours=1),
    )

    with pytest.raises(BrokerAccountIdentitySnapshotCorruption, match="digest type"):
        service.execute(_command())


def test_server_clock_and_human_staff_actor_are_fail_closed() -> None:
    repository = FakeRepository(datetime(2026, 8, 13, 8, 0))
    service, _ = _service(repository)
    with pytest.raises(ValueError, match="timezone-aware"):
        service.execute(_command())

    actor = BrokerAccountIdentityIssuanceActor(actor_id="staff-9", user_id=9)
    object.__setattr__(actor, "is_staff", False)
    with pytest.raises(ValueError, match="human staff"):
        IssueBrokerAccountIdentitySnapshot(
            account_provider=SequenceAccountProvider(_account(), _account()),
            broker_provider=SequenceBrokerProvider(_broker(), _broker()),
            digest_service=RecordingDigestService(),
            actor=actor,
            repository=FakeRepository(),
            ttl=timedelta(hours=1),
        )


def test_exact_current_identity_winner_replays_without_duplicate_append() -> None:
    repository = FakeRepository()
    winner = _issue(repository)
    service, digest = _service(repository)

    replay = service.execute(_command())

    assert replay == winner
    assert len(repository.append_calls) == 1
    assert digest.inputs == [OPAQUE_QMT_REFERENCE]


def test_identity_winner_is_bound_to_original_server_actor() -> None:
    repository = FakeRepository()
    _issue(repository)
    account = _account()
    broker = _broker()
    service = IssueBrokerAccountIdentitySnapshot(
        account_provider=SequenceAccountProvider(account, account),
        broker_provider=SequenceBrokerProvider(broker, broker),
        digest_service=RecordingDigestService(),
        actor=BrokerAccountIdentityIssuanceActor(actor_id="staff-user-10", user_id=10),
        repository=repository,
        ttl=timedelta(hours=1),
    )

    with pytest.raises(BrokerAccountIdentitySnapshotConflict, match="another server actor"):
        service.execute(_command())


def test_identity_winner_that_is_not_current_head_is_rejected() -> None:
    repository = FakeRepository()
    old = _issue(repository)
    repository.clock = NOW + timedelta(minutes=1)
    next_account = _account(content_hash=HASH_B)
    next_broker = _broker(binding_revision=4)
    service, _ = _service(
        repository,
        SequenceAccountProvider(next_account, next_account),
        SequenceBrokerProvider(next_broker, next_broker),
    )
    successor = service.execute(
        _command(snapshot_id="broker-account-identity-2", snapshot_version="v1")
    )
    assert successor.supersedes_snapshot_hash == old.content_hash

    replay, _ = _service(repository)
    with pytest.raises(BrokerAccountIdentitySnapshotConflict, match="current head"):
        replay.execute(_command())


def test_repository_substituted_first_winner_is_rejected() -> None:
    repository = FakeRepository()
    other = _issue()
    repository.append_result = PersistedBrokerAccountIdentitySnapshot(
        replace(
            other,
            snapshot_id="other-snapshot",
            identity_hash="",
            content_hash="",
        ),
        BrokerAccountIdentityIssuanceActor(actor_id="staff-user-9", user_id=9),
    )
    service, _ = _service(repository)

    with pytest.raises(BrokerAccountIdentitySnapshotConflict, match="first winner"):
        service.execute(_command())


def test_successor_uses_repository_head_and_requires_advanced_binding() -> None:
    repository = FakeRepository()
    previous = _issue(repository)
    repository.clock = NOW + timedelta(minutes=1)
    account = _account(content_hash=HASH_B)
    unchanged_broker = _broker()
    service, _ = _service(
        repository,
        SequenceAccountProvider(account, account),
        SequenceBrokerProvider(unchanged_broker, unchanged_broker),
    )

    with pytest.raises(BrokerAccountIdentitySnapshotCorruption, match="successor"):
        service.execute(_command(snapshot_id="snapshot-next"))

    assert repository.heads[("qmt-live", 42)].snapshot == previous


def test_exact_reader_enforces_identity_hash_pit_and_inactive_authority() -> None:
    repository = FakeRepository()
    snapshot = _issue(repository)
    reader = GetExactBrokerAccountIdentitySnapshot(repository)

    assert (
        reader.execute(
            GetExactBrokerAccountIdentitySnapshotCommand(
                snapshot_id=snapshot.snapshot_id,
                snapshot_version=snapshot.snapshot_version,
                expected_content_hash=snapshot.content_hash,
                as_of=NOW,
            )
        )
        == snapshot
    )
    assert (
        reader.execute(
            GetExactBrokerAccountIdentitySnapshotCommand(
                snapshot_id=snapshot.snapshot_id,
                snapshot_version=snapshot.snapshot_version,
                expected_content_hash=snapshot.content_hash,
                as_of=NOW - timedelta(seconds=1),
            )
        )
        is None
    )
    assert snapshot.permission == "inactive" and snapshot.must_not_execute


def test_current_reader_uses_closed_selector_and_rejects_historical_head() -> None:
    repository = FakeRepository()
    old = _issue(repository)
    command = GetCurrentBrokerAccountIdentitySnapshotCommand(
        snapshot_id=old.snapshot_id,
        snapshot_version=old.snapshot_version,
        expected_content_hash=old.content_hash,
        broker_account_namespace=old.broker_account_namespace,
        broker_account_id=old.broker_account_id,
        account_source_id=old.account_source_ref.source_id,
        account_source_version=old.account_source_ref.source_version,
        account_source_content_hash=old.account_source_ref.content_hash,
        account_namespace=old.account_source_ref.account_namespace,
        account_id=old.account_source_ref.account_id,
        owner_user_id=old.owner_user_id,
        account_type="real",
        is_active=True,
        as_of=NOW,
    )
    reader = GetCurrentBrokerAccountIdentitySnapshot(repository)
    assert reader.execute(command) == old

    with pytest.raises(BrokerAccountIdentitySnapshotCorruption, match="selector"):
        reader.execute(replace(command, account_source_content_hash=HASH_B))
    with pytest.raises(BrokerAccountIdentitySnapshotCorruption, match="selector"):
        reader.execute(replace(command, account_id="another-account"))

    repository.clock = NOW + timedelta(minutes=1)
    account = _account(content_hash=HASH_B)
    broker = _broker(binding_revision=4)
    service, _ = _service(
        repository,
        SequenceAccountProvider(account, account),
        SequenceBrokerProvider(broker, broker),
    )
    service.execute(_command(snapshot_id="new-head"))
    assert reader.execute(replace(command, as_of=repository.clock)) is None


def test_application_has_no_cross_app_or_infrastructure_imports() -> None:
    source = Path(
        "apps/broker_execution/application/broker_account_identity_snapshot.py"
    ).read_text(encoding="utf-8")

    assert "from apps.account" not in source
    assert ".infrastructure" not in source
    assert ".objects" not in source
