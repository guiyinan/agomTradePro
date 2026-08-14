"""Pure Application coverage for Account-owned identity snapshot issuance."""

from __future__ import annotations

import ast
from contextlib import AbstractContextManager, nullcontext
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.account.application.account_identity_snapshot import (
    AccountIdentitySnapshotActor,
    AccountIdentitySnapshotConflict,
    AccountIdentitySnapshotCorruption,
    AccountIdentitySnapshotRepository,
    AccountIdentitySnapshotUnavailable,
    GetCurrentAccountIdentitySnapshot,
    GetCurrentAccountIdentitySnapshotCommand,
    GetExactAccountIdentitySnapshot,
    GetExactAccountIdentitySnapshotCommand,
    IssueAccountIdentitySnapshot,
    IssueAccountIdentitySnapshotCommand,
    ManualAccountOwnerReclaimReceipt,
    PersistedAccountIdentitySnapshot,
    ReclaimLegacyAccountIdentitySnapshot,
    ReclaimLegacyAccountIdentitySnapshotCommand,
    TrustedRawAccountIdentitySource,
)
from apps.account.domain.account_identity_snapshot import AccountIdentitySnapshot

NOW = datetime(2026, 8, 13, 9, tzinfo=UTC)


def _actor(**changes: object) -> AccountIdentitySnapshotActor:
    values: dict[str, object] = {
        "actor_id": "user:19",
        "user_id": 19,
        "role": "account_identity_issuer",
    }
    values.update(changes)
    return AccountIdentitySnapshotActor(**values)  # type: ignore[arg-type]


def _raw(**changes: object) -> TrustedRawAccountIdentitySource:
    values: dict[str, object] = {
        "source_id": "simulated-account-row-7",
        "source_version": "simulated-account-row.v17",
        "content_hash": "7" * 64,
        "account_namespace": "portfolio.transition_plan_account",
        "account_id": "portfolio-account-7",
        "underlying_unified_account_namespace": "simulated_trading.unified_account",
        "underlying_unified_account_id": 7,
        "owner_user_id": 19,
        "account_type": "real",
        "is_active": True,
        "legacy_default_user_assignment": False,
        "recorded_at": NOW - timedelta(minutes=5),
        "valid_until": NOW + timedelta(hours=2),
    }
    values.update(changes)
    return TrustedRawAccountIdentitySource(**values)  # type: ignore[arg-type]


def _receipt(**changes: object) -> ManualAccountOwnerReclaimReceipt:
    values: dict[str, object] = {
        "receipt_id": "account-owner-reclaim-7",
        "receipt_version": "account-owner-reclaim.v1",
        "content_hash": "a" * 64,
        "raw_source_id": "simulated-account-row-7",
        "raw_source_version": "simulated-account-row.v17",
        "raw_source_content_hash": "7" * 64,
        "account_namespace": "portfolio.transition_plan_account",
        "account_id": "portfolio-account-7",
        "underlying_unified_account_namespace": "simulated_trading.unified_account",
        "underlying_unified_account_id": 7,
        "reclaimed_owner_user_id": 19,
        "approved_by": _actor(),
        "recorded_at": NOW - timedelta(minutes=2),
        "valid_until": NOW + timedelta(minutes=30),
    }
    values.update(changes)
    return ManualAccountOwnerReclaimReceipt(**values)  # type: ignore[arg-type]


def _issue_command(
    *, source_version: str = "account-identity-source.v1"
) -> IssueAccountIdentitySnapshotCommand:
    return IssueAccountIdentitySnapshotCommand(
        source_id="account-identity-source-7",
        source_version=source_version,
        raw_source_id="simulated-account-row-7",
        raw_source_version="simulated-account-row.v17",
    )


def _reclaim_command() -> ReclaimLegacyAccountIdentitySnapshotCommand:
    return ReclaimLegacyAccountIdentitySnapshotCommand(
        source_id="account-identity-source-7",
        source_version="account-identity-source.v1",
        raw_source_id="simulated-account-row-7",
        raw_source_version="simulated-account-row.v17",
        reclaim_receipt_id="account-owner-reclaim-7",
        reclaim_receipt_version="account-owner-reclaim.v1",
    )


class _RawProvider:
    def __init__(self, values: list[TrustedRawAccountIdentitySource | None]) -> None:
        self.values = values
        self.calls: list[dict[str, object]] = []

    def get_exact_current(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> TrustedRawAccountIdentitySource | None:
        self.calls.append(
            {
                "source_id": source_id,
                "source_version": source_version,
                "as_of": as_of,
            }
        )
        index = min(len(self.calls) - 1, len(self.values) - 1)
        return self.values[index]


class _ReceiptProvider:
    def __init__(self, values: list[ManualAccountOwnerReclaimReceipt | None]) -> None:
        self.values = values
        self.calls: list[dict[str, object]] = []

    def get_exact_current(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        as_of: datetime,
    ) -> ManualAccountOwnerReclaimReceipt | None:
        self.calls.append(
            {
                "receipt_id": receipt_id,
                "receipt_version": receipt_version,
                "as_of": as_of,
            }
        )
        index = min(len(self.calls) - 1, len(self.values) - 1)
        return self.values[index]


class _Repository(AccountIdentitySnapshotRepository):
    def __init__(self) -> None:
        self.clock = NOW
        self.by_identity: dict[tuple[str, str], PersistedAccountIdentitySnapshot] = {}
        self.heads: dict[tuple[str, str], PersistedAccountIdentitySnapshot] = {}
        self.append_calls: list[tuple[str | None, datetime]] = []

    def atomic(self) -> AbstractContextManager[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.clock

    def get_winner(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> PersistedAccountIdentitySnapshot | None:
        del as_of
        return self.by_identity.get((source_id, source_version))

    def get_current_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        as_of: datetime,
    ) -> PersistedAccountIdentitySnapshot | None:
        del as_of
        return self.heads.get((account_namespace, account_id))

    def append(
        self,
        record: PersistedAccountIdentitySnapshot,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountIdentitySnapshot:
        self.append_calls.append((expected_predecessor_hash, recorded_at))
        snapshot = record.snapshot
        head_key = (snapshot.account_namespace, snapshot.account_id)
        current = self.heads.get(head_key)
        actual = current.snapshot.content_hash if current else None
        if actual != expected_predecessor_hash:
            raise AccountIdentitySnapshotConflict("CAS conflict")
        identity = (snapshot.source_id, snapshot.source_version)
        winner = self.by_identity.setdefault(identity, record)
        if winner == record:
            self.heads[head_key] = record
        return winner

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountIdentitySnapshot | None:
        value = self.by_identity.get((source_id, source_version))
        if value is None or value.snapshot.content_hash != expected_content_hash:
            return None
        return value if value.snapshot.is_knowable_at(as_of) else None


def _issue(
    repository: _Repository,
    *,
    raws: list[TrustedRawAccountIdentitySource | None] | None = None,
    actor: AccountIdentitySnapshotActor | None = None,
) -> tuple[IssueAccountIdentitySnapshot, _RawProvider]:
    provider = _RawProvider(raws or [_raw()])
    return (
        IssueAccountIdentitySnapshot(
            raw_source_provider=provider,
            repository=repository,
            actor=actor or _actor(),
            validity_period=timedelta(hours=1),
        ),
        provider,
    )


def _reclaim(
    repository: _Repository,
    *,
    raws: list[TrustedRawAccountIdentitySource | None] | None = None,
    receipts: list[ManualAccountOwnerReclaimReceipt | None] | None = None,
    actor: AccountIdentitySnapshotActor | None = None,
) -> tuple[
    ReclaimLegacyAccountIdentitySnapshot,
    _RawProvider,
    _ReceiptProvider,
]:
    raw_provider = _RawProvider(
        raws
        or [
            _raw(
                owner_user_id=None,
                legacy_default_user_assignment=True,
            )
        ]
    )
    receipt_provider = _ReceiptProvider(receipts or [_receipt()])
    return (
        ReclaimLegacyAccountIdentitySnapshot(
            raw_source_provider=raw_provider,
            reclaim_receipt_provider=receipt_provider,
            repository=repository,
            actor=actor or _actor(),
            validity_period=timedelta(hours=1),
        ),
        raw_provider,
        receipt_provider,
    )


def test_issue_is_id_only_and_double_reads_raw_source_at_one_server_cutoff() -> None:
    repository = _Repository()
    use_case, provider = _issue(repository)

    snapshot = use_case.execute(_issue_command())

    assert len(provider.calls) == 2
    assert {call["as_of"] for call in provider.calls} == {NOW}
    assert snapshot.source_id == "account-identity-source-7"
    assert snapshot.source_version == "account-identity-source.v1"
    assert snapshot.account_id == "portfolio-account-7"
    assert type(snapshot.account_id) is str
    assert snapshot.underlying_unified_account_id == 7
    assert type(snapshot.underlying_unified_account_id) is int
    assert snapshot.underlying_source_id == "simulated-account-row-7"
    assert snapshot.underlying_source_version == "simulated-account-row.v17"
    assert snapshot.underlying_source_content_hash == "7" * 64
    assert snapshot.owner_user_id == 19
    assert snapshot.provenance_kind == "authoritative"
    assert snapshot.issued_at == snapshot.recorded_at == NOW
    assert snapshot.ttl_valid_until == snapshot.valid_until == NOW + timedelta(hours=1)
    assert snapshot.activation_available is False
    assert snapshot.must_not_execute is True
    assert repository.append_calls == [(None, NOW)]


def test_commands_expose_only_identity_selectors() -> None:
    issue_names = {field.name for field in fields(IssueAccountIdentitySnapshotCommand)}
    reclaim_names = {field.name for field in fields(ReclaimLegacyAccountIdentitySnapshotCommand)}

    assert issue_names == {
        "source_id",
        "source_version",
        "raw_source_id",
        "raw_source_version",
    }
    assert reclaim_names == issue_names | {
        "reclaim_receipt_id",
        "reclaim_receipt_version",
    }
    forbidden = {
        "account_id",
        "owner_user_id",
        "content_hash",
        "recorded_at",
        "valid_until",
        "permission",
        "actor",
    }
    assert not issue_names & forbidden
    assert not reclaim_names & forbidden


def test_legacy_default_user_without_reclaim_receipt_is_unavailable_and_never_written() -> None:
    repository = _Repository()
    use_case, _provider = _issue(
        repository,
        raws=[_raw(owner_user_id=1, legacy_default_user_assignment=True)],
    )

    with pytest.raises(AccountIdentitySnapshotUnavailable, match="manual reclaim"):
        use_case.execute(_issue_command())

    assert repository.append_calls == []
    assert repository.by_identity == {}


def test_manual_reclaim_uses_exact_receipt_owner_not_nullable_legacy_user() -> None:
    repository = _Repository()
    use_case, raw_provider, receipt_provider = _reclaim(repository)

    snapshot = use_case.execute(_reclaim_command())

    assert len(raw_provider.calls) == len(receipt_provider.calls) == 2
    assert {
        call["as_of"] for calls in (raw_provider.calls, receipt_provider.calls) for call in calls
    } == {NOW}
    assert snapshot.owner_user_id == 19
    assert snapshot.provenance_kind == "manual_reclaim"
    assert snapshot.legacy_default_user_assignment is True
    assert snapshot.reclaim_receipt_owner == "account"
    assert snapshot.reclaim_receipt_artifact_type == "account_owner_reclaim_receipt"
    assert snapshot.reclaim_receipt_id == "account-owner-reclaim-7"
    assert snapshot.reclaim_receipt_content_hash == "a" * 64
    assert snapshot.valid_until == NOW + timedelta(minutes=30)


def test_missing_manual_reclaim_receipt_is_unavailable_before_any_write() -> None:
    repository = _Repository()
    use_case, _raw_provider, receipt_provider = _reclaim(
        repository,
        receipts=[None],
    )

    with pytest.raises(AccountIdentitySnapshotUnavailable, match="receipt"):
        use_case.execute(_reclaim_command())

    assert len(receipt_provider.calls) == 1
    assert repository.append_calls == []
    assert repository.by_identity == {}


@pytest.mark.parametrize(  # type: ignore[misc]
    "raw_changes",
    [
        {"owner_user_id": None},
        {"account_type": "simulated"},
        {"is_active": False},
        {"source_id": "substituted-source"},
        {"valid_until": NOW},
    ],
)
def test_authoritative_raw_source_semantics_fail_closed(
    raw_changes: dict[str, object],
) -> None:
    repository = _Repository()
    use_case, _provider = _issue(repository, raws=[_raw(**raw_changes)])

    with pytest.raises((AccountIdentitySnapshotUnavailable, AccountIdentitySnapshotCorruption)):
        use_case.execute(_issue_command())

    assert repository.append_calls == []


def test_source_or_receipt_drift_during_double_read_is_corruption() -> None:
    raw_repository = _Repository()
    raw_drift, _provider = _issue(
        raw_repository,
        raws=[_raw(), _raw(content_hash="6" * 64)],
    )
    with pytest.raises(AccountIdentitySnapshotCorruption, match="changed"):
        raw_drift.execute(_issue_command())

    receipt_repository = _Repository()
    receipt_drift, _raw_provider, _receipt_provider = _reclaim(
        receipt_repository,
        receipts=[_receipt(), _receipt(content_hash="b" * 64)],
    )
    with pytest.raises(AccountIdentitySnapshotCorruption, match="changed"):
        receipt_drift.execute(_reclaim_command())

    assert raw_repository.append_calls == receipt_repository.append_calls == []


@pytest.mark.parametrize(  # type: ignore[misc]
    "receipt_changes",
    [
        {"raw_source_content_hash": "6" * 64},
        {"account_id": "portfolio-account-8"},
        {"underlying_unified_account_id": 8},
        {"approved_by": _actor(actor_id="user:20", user_id=20)},
        {"valid_until": NOW},
    ],
)
def test_reclaim_receipt_must_bind_raw_source_and_server_actor(
    receipt_changes: dict[str, object],
) -> None:
    repository = _Repository()
    use_case, _raw_provider, _receipt_provider = _reclaim(
        repository,
        receipts=[_receipt(**receipt_changes)],
    )

    with pytest.raises(
        (
            AccountIdentitySnapshotUnavailable,
            AccountIdentitySnapshotConflict,
            AccountIdentitySnapshotCorruption,
        )
    ):
        use_case.execute(_reclaim_command())

    assert repository.append_calls == []


def test_same_identity_replays_across_clock_only_for_original_actor() -> None:
    repository = _Repository()
    first_use_case, _provider = _issue(repository)
    winner = first_use_case.execute(_issue_command())
    repository.clock = NOW + timedelta(minutes=5)

    replay, _replay_provider = _issue(repository, actor=_actor())
    assert replay.execute(_issue_command()) == winner
    assert len(repository.append_calls) == 1

    other_actor, _other_provider = _issue(
        repository,
        actor=_actor(actor_id="user:20", user_id=20),
    )
    with pytest.raises(AccountIdentitySnapshotConflict, match="actor"):
        other_actor.execute(_issue_command())


def test_same_account_identity_forms_one_cas_supersession_chain() -> None:
    repository = _Repository()
    first_use_case, _provider = _issue(repository)
    first = first_use_case.execute(_issue_command())
    repository.clock = NOW + timedelta(minutes=1)
    second_use_case, _provider = _issue(repository)

    second = second_use_case.execute(_issue_command(source_version="account-identity-source.v2"))

    assert second.supersedes_content_hash == first.content_hash
    assert repository.append_calls[-1] == (first.content_hash, repository.clock)


def _current_command(
    snapshot: AccountIdentitySnapshot,
    **changes: object,
) -> GetCurrentAccountIdentitySnapshotCommand:
    values: dict[str, object] = {
        "source_id": snapshot.source_id,
        "source_version": snapshot.source_version,
        "expected_content_hash": snapshot.content_hash,
        "account_namespace": snapshot.account_namespace,
        "account_id": snapshot.account_id,
        "underlying_unified_account_namespace": (snapshot.underlying_unified_account_namespace),
        "underlying_unified_account_id": snapshot.underlying_unified_account_id,
        "owner_user_id": snapshot.owner_user_id,
        "provenance_kind": snapshot.provenance_kind,
        "legacy_default_user_assignment": snapshot.legacy_default_user_assignment,
        "underlying_source_id": snapshot.underlying_source_id,
        "underlying_source_version": snapshot.underlying_source_version,
        "underlying_source_content_hash": snapshot.underlying_source_content_hash,
        "reclaim_receipt_owner": snapshot.reclaim_receipt_owner,
        "reclaim_receipt_artifact_type": snapshot.reclaim_receipt_artifact_type,
        "reclaim_receipt_id": snapshot.reclaim_receipt_id,
        "reclaim_receipt_version": snapshot.reclaim_receipt_version,
        "reclaim_receipt_content_hash": snapshot.reclaim_receipt_content_hash,
        "account_type": snapshot.account_type,
        "is_active": snapshot.is_active,
        "as_of": NOW,
    }
    values.update(changes)
    return GetCurrentAccountIdentitySnapshotCommand(**values)  # type: ignore[arg-type]


def test_exact_pit_and_current_readers_return_only_inactive_exact_head() -> None:
    repository = _Repository()
    use_case, _provider = _issue(repository)
    snapshot = use_case.execute(_issue_command())

    exact = GetExactAccountIdentitySnapshot(repository).execute(
        GetExactAccountIdentitySnapshotCommand(
            source_id=snapshot.source_id,
            source_version=snapshot.source_version,
            expected_content_hash=snapshot.content_hash,
            as_of=NOW,
        )
    )
    current = GetCurrentAccountIdentitySnapshot(repository).execute(_current_command(snapshot))

    assert exact == current == snapshot
    assert exact is not None and exact.activation_available is False
    assert exact.must_not_execute is True
    assert (
        GetExactAccountIdentitySnapshot(repository).execute(
            GetExactAccountIdentitySnapshotCommand(
                source_id=snapshot.source_id,
                source_version=snapshot.source_version,
                expected_content_hash="0" * 64,
                as_of=NOW,
            )
        )
        is None
    )


@pytest.mark.parametrize(  # type: ignore[misc]
    ("field_name", "replacement"),
    [
        ("account_id", "portfolio-account-8"),
        ("underlying_unified_account_id", 8),
        ("owner_user_id", 20),
        ("underlying_source_content_hash", "0" * 64),
    ],
)
def test_current_reader_rejects_complete_selector_substitution(
    field_name: str,
    replacement: object,
) -> None:
    repository = _Repository()
    use_case, _provider = _issue(repository)
    snapshot = use_case.execute(_issue_command())

    with pytest.raises(AccountIdentitySnapshotCorruption, match="selector"):
        GetCurrentAccountIdentitySnapshot(repository).execute(
            _current_command(snapshot, **{field_name: replacement})
        )


@pytest.mark.parametrize(  # type: ignore[misc]
    "changes",
    [
        {"provenance_kind": "authoritative", "legacy_default_user_assignment": True},
        {"provenance_kind": "manual_reclaim", "legacy_default_user_assignment": False},
        {"account_type": "simulated"},
        {"is_active": False},
    ],
)
def test_current_selector_cannot_upgrade_or_forge_provenance(
    changes: dict[str, object],
) -> None:
    repository = _Repository()
    use_case, _provider = _issue(repository)
    snapshot = use_case.execute(_issue_command())

    with pytest.raises(ValueError):
        _current_command(snapshot, **changes)


def test_current_reader_never_resurrects_superseded_snapshot() -> None:
    repository = _Repository()
    first_use_case, _provider = _issue(repository)
    first = first_use_case.execute(_issue_command())
    repository.clock = NOW + timedelta(minutes=1)
    second_use_case, _provider = _issue(repository)
    second_use_case.execute(_issue_command(source_version="account-identity-source.v2"))

    assert (
        GetCurrentAccountIdentitySnapshot(repository).execute(
            _current_command(first, as_of=repository.clock)
        )
        is None
    )


@pytest.mark.parametrize(  # type: ignore[misc]
    "changes",
    [
        {"user_id": True},
        {"user_id": 0},
        {"actor_id": "user 19"},
        {"kind": "service"},
        {"is_staff": False},
    ],
)
def test_actor_must_be_exact_server_human_staff(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _actor(**changes)


def test_application_has_no_infrastructure_or_other_app_dependency() -> None:
    path = Path("apps/account/application/account_identity_snapshot.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not any(".infrastructure" in name for name in imported)
    assert not any(
        name.startswith("apps.")
        and not name.startswith("apps.account.domain.account_identity_snapshot")
        for name in imported
    )
