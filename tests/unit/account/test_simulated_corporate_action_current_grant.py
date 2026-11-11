"""Unit contracts for locked current Account grant reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from apps.account import simulated_corporate_action_current_grant_composition as current_grant
from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantBinding,
    SimulatedCorporateActionWriteGrantCurrent,
    SimulatedCorporateActionWriteGrantRevocation,
    SimulatedCorporateActionWriteGrantSelector,
)

_AT = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
_A = "a" * 64
_B = "b" * 64
_C = "c" * 64


def _binding(**changes: object) -> SimulatedCorporateActionWriteGrantBinding:
    """Build one valid canonical account, owner, source and policy binding."""

    facts: dict[str, object] = {
        "account_namespace": "simulated",
        "account_id": "account-1",
        "owner_user_id": 81,
        "tenant_id": "tenant-1",
        "owner_id": "owner-81",
        "account_source_id": "source-1",
        "account_source_version": "1",
        "account_source_content_hash": _A,
        "policy_id": "policy-1",
        "policy_version": "1",
        "policy_content_hash": _B,
    }
    facts.update(changes)
    return SimulatedCorporateActionWriteGrantBinding(**facts)  # type: ignore[arg-type]


def _grant(
    *,
    binding: SimulatedCorporateActionWriteGrantBinding | None = None,
    grant_version: str = "1",
    recorded_at: datetime = _AT,
    valid_until: datetime = _AT + timedelta(hours=1),
    supersedes_content_hash: str | None = None,
    issuer_hash: str = _C,
) -> SimulatedCorporateActionWriteGrant:
    """Build one exact grant whose MAC acceptance is controlled by the test seal."""

    return SimulatedCorporateActionWriteGrant(
        grant_id="grant-1",
        grant_version=grant_version,
        binding=binding or _binding(),
        consent_evidence_id="consent-1",
        consent_evidence_version="1",
        consent_evidence_hash=_A,
        issuer_evidence_id="issuer-1",
        issuer_evidence_version="1",
        issuer_evidence_hash=issuer_hash,
        consented_at=recorded_at - timedelta(minutes=2),
        issued_at=recorded_at - timedelta(minutes=1),
        recorded_at=recorded_at,
        valid_until=valid_until,
        supersedes_content_hash=supersedes_content_hash,
    )


def _selector(
    grant: SimulatedCorporateActionWriteGrant,
) -> SimulatedCorporateActionWriteGrantSelector:
    """Select one exact grant version and binding."""

    return SimulatedCorporateActionWriteGrantSelector(
        grant_id=grant.grant_id,
        grant_version=grant.grant_version,
        identity_hash=grant.identity_hash,
        content_hash=grant.content_hash,
        binding=grant.binding,
    )


def _revocation(
    grant: SimulatedCorporateActionWriteGrant,
) -> SimulatedCorporateActionWriteGrantRevocation:
    """Build a valid revocation that targets exactly one grant."""

    recorded_at = _AT + timedelta(minutes=2)
    return SimulatedCorporateActionWriteGrantRevocation(
        revocation_id="revoke-1",
        revocation_version="1",
        grant_id=grant.grant_id,
        grant_version=grant.grant_version,
        grant_identity_hash=grant.identity_hash,
        grant_content_hash=grant.content_hash,
        revocation_evidence_id="owner-revocation-1",
        revocation_evidence_version="1",
        revocation_evidence_hash=_A,
        issuer_evidence_id="issuer-1",
        issuer_evidence_version="1",
        issuer_evidence_hash=_B,
        revoked_at=recorded_at - timedelta(seconds=1),
        recorded_at=recorded_at,
    )


class _Cursor:
    """Capture the SQL needed to prove that locks precede repository reads."""

    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        self.connection.sql.append(sql)

    def fetchone(self) -> tuple[str, ...]:
        return ("read committed",)


class _Connection:
    """Small exact-transaction stand-in; these tests never connect to a database."""

    vendor = "postgresql"
    in_atomic_block = True
    _autocommit = False

    class _Ops:
        def quote_name(self, name: str) -> str:
            return f'"{name}"'

    ops = _Ops()

    def __init__(self) -> None:
        self.sql: list[str] = []

    def get_autocommit(self) -> bool:
        return self._autocommit

    def cursor(self) -> _Cursor:
        return _Cursor(self)


@dataclass
class _Snapshot:
    heads: tuple[SimulatedCorporateActionWriteGrant, ...]
    current: SimulatedCorporateActionWriteGrantCurrent | None


class _Repository:
    """Expose ordered current-head snapshots and verify table locks came first."""

    def __init__(self, connection: _Connection, snapshots: tuple[_Snapshot, ...]) -> None:
        self.connection = connection
        self.snapshots = snapshots
        self.round = 0
        self.scope_calls: list[tuple[str, str, datetime]] = []
        self.exact_calls: list[tuple[SimulatedCorporateActionWriteGrantSelector, datetime]] = []

    def _snapshot(self) -> _Snapshot:
        locks = tuple(sql for sql in self.connection.sql if sql.startswith("LOCK TABLE"))
        assert len(locks) == 2
        return self.snapshots[min(self.round, len(self.snapshots) - 1)]

    def get_current_for_scope(
        self, account_namespace: str, account_id: str, *, as_of: datetime
    ) -> tuple[SimulatedCorporateActionWriteGrant, ...]:
        self.scope_calls.append((account_namespace, account_id, as_of))
        return self._snapshot().heads

    def get_current_grant(
        self, *, selector: SimulatedCorporateActionWriteGrantSelector, as_of: datetime
    ) -> SimulatedCorporateActionWriteGrantCurrent | None:
        self.exact_calls.append((selector, as_of))
        snapshot = self._snapshot()
        self.round += 1
        return snapshot.current


class _Seal:
    """Represent server MAC verification without depending on process secrets."""

    def verify(self, grant: SimulatedCorporateActionWriteGrant) -> bool:
        return grant.issuer_evidence_hash == _C


@pytest.fixture
def current_world(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_Connection, _Repository, SimulatedCorporateActionWriteGrant]:
    """Install a synthetic PostgreSQL UOW and exact current grant reader."""

    connection = _Connection()
    grant = _grant()
    repository = _Repository(
        connection,
        (_Snapshot((grant,), SimulatedCorporateActionWriteGrantCurrent(grant)),),
    )
    monkeypatch.setattr(current_grant, "connections", {"default": connection})
    monkeypatch.setattr(
        current_grant,
        "DjangoSimulatedCorporateActionWriteGrantRepository",
        lambda *, using: repository,
    )
    monkeypatch.setattr(current_grant, "SimulatedCorporateActionWriteGrantSeal", _Seal)
    monkeypatch.setattr(current_grant.timezone, "now", lambda: _AT + timedelta(minutes=1))
    return connection, repository, grant


def test_current_scope_grant_is_mac_verified_under_both_ledger_table_locks(
    current_world: tuple[_Connection, _Repository, SimulatedCorporateActionWriteGrant],
) -> None:
    connection, repository, grant = current_world

    with current_grant.locked_current_simulated_corporate_action_write_grant(
        selector=_selector(grant), using="default"
    ) as observed:
        assert observed is grant
        assert tuple(sql for sql in connection.sql if sql.startswith("LOCK TABLE")) == (
            'LOCK TABLE "account_sim_corp_action_write_grant_ledger" IN SHARE MODE NOWAIT',
            'LOCK TABLE "account_sim_corp_action_write_grant_revocation_ledger" IN SHARE MODE NOWAIT',
        )

    assert repository.scope_calls[0][:2] == ("simulated", "account-1")
    assert len(repository.scope_calls) == 2
    assert len(repository.exact_calls) == 2


@pytest.mark.parametrize(
    "snapshot",
    [
        _Snapshot((), None),
        _Snapshot(
            (),
            SimulatedCorporateActionWriteGrantCurrent(
                grant=_grant(), revocation=_revocation(_grant())
            ),
        ),
    ],
)
def test_missing_or_revoked_current_grant_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    current_world: tuple[_Connection, _Repository, SimulatedCorporateActionWriteGrant],
    snapshot: _Snapshot,
) -> None:
    connection, _, grant = current_world
    repository = _Repository(connection, (snapshot,))
    monkeypatch.setattr(
        current_grant,
        "DjangoSimulatedCorporateActionWriteGrantRepository",
        lambda *, using: repository,
    )

    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        with current_grant.locked_current_simulated_corporate_action_write_grant(
            selector=_selector(grant), using="default"
        ):
            pytest.fail("an absent or revoked grant must not be yielded")


def test_unsigned_or_changed_owner_grant_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    current_world: tuple[_Connection, _Repository, SimulatedCorporateActionWriteGrant],
) -> None:
    connection, _, grant = current_world
    changed = _grant(binding=_binding(owner_user_id=82))
    for candidate in (_grant(issuer_hash="0" * 64), changed):
        connection.sql.clear()
        repository = _Repository(
            connection,
            (_Snapshot((candidate,), SimulatedCorporateActionWriteGrantCurrent(candidate)),),
        )
        monkeypatch.setattr(
            current_grant,
            "DjangoSimulatedCorporateActionWriteGrantRepository",
            lambda *, using, selected=repository: selected,
        )
        with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
            with current_grant.locked_current_simulated_corporate_action_write_grant(
                selector=_selector(grant), using="default"
            ):
                pytest.fail("an unsigned or owner-substituted grant must not be yielded")


def test_expiry_at_half_open_boundary_and_current_head_change_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    current_world: tuple[_Connection, _Repository, SimulatedCorporateActionWriteGrant],
) -> None:
    connection, _, grant = current_world
    repository = _Repository(
        connection,
        (
            _Snapshot((grant,), SimulatedCorporateActionWriteGrantCurrent(grant)),
            _Snapshot((), None),
        ),
    )
    monkeypatch.setattr(
        current_grant,
        "DjangoSimulatedCorporateActionWriteGrantRepository",
        lambda *, using: repository,
    )
    times = iter((_AT + timedelta(minutes=1), _AT + timedelta(minutes=1)))
    monkeypatch.setattr(current_grant.timezone, "now", lambda: next(times))

    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        with current_grant.locked_current_simulated_corporate_action_write_grant(
            selector=_selector(grant), using="default"
        ):
            pass

    expired_repo = _Repository(
        connection,
        (_Snapshot((grant,), SimulatedCorporateActionWriteGrantCurrent(grant)),),
    )
    connection.sql.clear()
    monkeypatch.setattr(
        current_grant,
        "DjangoSimulatedCorporateActionWriteGrantRepository",
        lambda *, using: expired_repo,
    )
    monkeypatch.setattr(current_grant.timezone, "now", lambda: grant.valid_until)
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        with current_grant.locked_current_simulated_corporate_action_write_grant(
            selector=_selector(grant), using="default"
        ):
            pytest.fail("grant expiry is half-open")


@pytest.mark.parametrize(
    ("vendor", "in_atomic_block", "autocommit"),
    [("sqlite", True, False), ("postgresql", False, True), ("postgresql", True, True)],
)
def test_alias_requires_active_postgresql_uow(
    monkeypatch: pytest.MonkeyPatch,
    vendor: str,
    in_atomic_block: bool,
    autocommit: bool,
) -> None:
    connection = _Connection()
    connection.vendor = vendor
    connection.in_atomic_block = in_atomic_block
    connection._autocommit = autocommit
    monkeypatch.setattr(current_grant, "connections", {"default": connection})
    grant = _grant()

    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        with current_grant.locked_current_simulated_corporate_action_write_grant(
            selector=_selector(grant), using="default"
        ):
            pytest.fail("an unprotected alias or transaction must not yield a grant")


def test_invalid_alias_is_rejected_before_opening_a_database_connection() -> None:
    grant = _grant()

    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        with current_grant.locked_current_simulated_corporate_action_write_grant(
            selector=_selector(grant), using=" default"
        ):
            pytest.fail("an invalid alias must not yield a grant")
