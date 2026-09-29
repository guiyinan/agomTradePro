from __future__ import annotations

from datetime import timedelta

import pytest

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    CurrentOwnerTenantAuthorityV3,
)
from apps.account.infrastructure import account_authority_shadow_scanner as shadow_module
from apps.account.infrastructure.account_authority_generation import (
    AccountAuthorityGenerationProof,
    AccountAuthorityGenerationUnavailable,
)
from apps.account.infrastructure.account_authority_shadow_scanner import (
    AccountAuthorityShadowScannerV3,
    DjangoAccountAuthorityNoLockSnapshotBundleProviderV3,
)
from tests.unit.audit.test_system_audit_authority_v3_reader import (
    _authority,
    _authority_source,
    _PhysicalProvider,
)


class _Cursor:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection
        self.statements: list[str] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def fetchone(self) -> tuple[str, str]:
        return (self.connection.isolation, self.connection.read_only)


class _Connection:
    def __init__(
        self,
        *,
        alias: str = "default",
        vendor: str = "postgresql",
        isolation: str = "repeatable read",
        read_only: str = "on",
        in_atomic_block: bool = True,
        autocommit: bool = False,
    ) -> None:
        self.alias = alias
        self.vendor = vendor
        self.isolation = isolation
        self.read_only = read_only
        self.in_atomic_block = in_atomic_block
        self.autocommit = autocommit
        self.cursor_value = _Cursor(self)

    def get_autocommit(self) -> bool:
        return self.autocommit

    def cursor(self) -> _Cursor:
        return self.cursor_value


class _Atomic:
    def __init__(self, connection: _Connection, events: list[str]) -> None:
        self.connection = connection
        self.events = events

    def __enter__(self) -> None:
        self.events.append("transaction.begin")
        self.connection.in_atomic_block = True
        self.connection.autocommit = False

    def __exit__(self, *args: object) -> None:
        self.events.append("transaction.end")
        self.connection.in_atomic_block = False
        self.connection.autocommit = True


def _scanner() -> AccountAuthorityShadowScannerV3:
    return AccountAuthorityShadowScannerV3(
        actor_source_id="audit-actor-v3",
        actor_source_version="v1",
        actor_content_hash="c" * 64,
        physical_row_provider=_PhysicalProvider(),
        using="default",
    )


def _legacy_current() -> CurrentOwnerTenantAuthorityV3:
    authority = _authority()
    observed_at = authority.recorded_at + timedelta(microseconds=1)
    authentication = _authority_source(
        authority.assignment,
        valid_until=authority.valid_until,
    )
    return CurrentOwnerTenantAuthorityV3(
        authority=authority,
        authentication=authentication,
        observed_at=observed_at,
        valid_until=min(
            authority.valid_until,
            authority.assignment.valid_until,
            authority.policy.valid_until,
            authentication.valid_until,
        ),
    )


def test_no_lock_actor_snapshot_requires_one_active_rr_read_only_alias() -> None:
    connection = _Connection()
    provider = DjangoAccountAuthorityNoLockSnapshotBundleProviderV3(using="default")

    with provider._snapshot(connection):  # type: ignore[arg-type]
        pass

    assert len(connection.cursor_value.statements) == 1
    statement = connection.cursor_value.statements[0].lower()
    assert "current_setting" in statement
    assert "lock table" not in statement
    assert "pg_advisory" not in statement


@pytest.mark.parametrize(
    ("connection", "error_type", "message"),
    [
        (_Connection(alias="other"), AccountActorAuthorityRawSourceV3Corruption, "alias"),
        (_Connection(vendor="sqlite"), AccountActorAuthorityRawSourceV3Unavailable, "PostgreSQL"),
        (
            _Connection(isolation="read committed"),
            AccountActorAuthorityRawSourceV3Unavailable,
            "repeatable read",
        ),
        (
            _Connection(read_only="off"),
            AccountActorAuthorityRawSourceV3Unavailable,
            "read-only",
        ),
        (
            _Connection(in_atomic_block=False, autocommit=True),
            AccountActorAuthorityRawSourceV3Unavailable,
            "active transaction",
        ),
    ],
)
def test_no_lock_actor_snapshot_fails_closed_on_alias_or_transaction_drift(
    connection: _Connection,
    error_type: type[Exception],
    message: str,
) -> None:
    provider = DjangoAccountAuthorityNoLockSnapshotBundleProviderV3(using="default")

    with pytest.raises(error_type, match=message):
        provider._snapshot(connection)  # type: ignore[arg-type]


def test_shadow_proof_and_closed_world_reader_share_one_rr_transaction_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(in_atomic_block=False, autocommit=True)
    events: list[str] = []
    legacy = _legacy_current()
    legacy_before = legacy
    command = GetCurrentOwnerTenantAuthorityV3Command(
        legacy.authority.authority_id,
        legacy.authority.authority_version,
        legacy.authority.content_hash,
    )
    scanner = _scanner()
    current_reads: list[tuple[object, bool, str, str]] = []

    def proof_reader(*, using: str) -> AccountAuthorityGenerationProof:
        events.append("proof")
        assert using == "default"
        assert connection.in_atomic_block
        assert not connection.get_autocommit()
        assert connection.isolation == "repeatable read"
        assert connection.read_only == "on"
        return AccountAuthorityGenerationProof(using=using, generation=41)

    def current_reader(
        _self: AccountAuthorityShadowScannerV3,
        _command: GetCurrentOwnerTenantAuthorityV3Command,
    ) -> CurrentOwnerTenantAuthorityV3:
        events.append("scan")
        current_reads.append(
            (connection, connection.in_atomic_block, connection.isolation, connection.read_only)
        )
        return legacy

    monkeypatch.setattr(shadow_module, "_connection", lambda using: connection)
    monkeypatch.setattr(
        shadow_module.transaction,
        "atomic",
        lambda *, using: _Atomic(connection, events),
    )
    monkeypatch.setattr(shadow_module, "read_account_authority_generation_proof", proof_reader)
    monkeypatch.setattr(AccountAuthorityShadowScannerV3, "_read_shadow", current_reader)

    result = scanner.scan(command, legacy)

    assert events.index("proof") < events.index("scan")
    assert current_reads == [(connection, True, "repeatable read", "on")]
    assert result.database_alias == "default"
    assert result.proof_generation == 41
    assert result.comparison.matches is True
    assert result.comparison.differing_fields == ()
    assert legacy is legacy_before
    assert legacy == legacy_before
    forbidden = ("lock table", "pg_advisory", "insert ", "update ", "delete ", "truncate ")
    assert not any(
        token in statement.lower()
        for statement in connection.cursor_value.statements
        for token in forbidden
    )


@pytest.mark.parametrize(
    "changed_selector",
    ("authority_id", "authority_version", "content_hash"),
)
def test_shadow_rejects_legacy_authority_selector_mismatch_before_opening_transaction(
    monkeypatch: pytest.MonkeyPatch,
    changed_selector: str,
) -> None:
    legacy = _legacy_current()
    selectors = (
        legacy.authority.authority_id,
        legacy.authority.authority_version,
        legacy.authority.content_hash,
    )
    selector_values = list(selectors)
    changed_index = {
        "authority_id": 0,
        "authority_version": 1,
        "content_hash": 2,
    }[changed_selector]
    selector_values[changed_index] = (
        "different-authority"
        if changed_selector == "authority_id"
        else "different-version" if changed_selector == "authority_version" else "0" * 64
    )
    command = GetCurrentOwnerTenantAuthorityV3Command(
        selector_values[0],
        selector_values[1],
        selector_values[2],
    )

    def unexpected_connection(_using: str) -> object:
        pytest.fail("selector mismatch must fail before resolving a database connection")

    monkeypatch.setattr(shadow_module, "_connection", unexpected_connection)

    with pytest.raises(AccountAuthorityGenerationUnavailable, match="selectors"):
        _scanner().scan(command, legacy)


def test_shadow_rejects_a_proof_bound_to_another_alias_before_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(in_atomic_block=False, autocommit=True)
    events: list[str] = []
    legacy = _legacy_current()
    command = GetCurrentOwnerTenantAuthorityV3Command(
        legacy.authority.authority_id,
        legacy.authority.authority_version,
        legacy.authority.content_hash,
    )
    scanner = _scanner()
    scan_calls: list[object] = []

    monkeypatch.setattr(shadow_module, "_connection", lambda using: connection)
    monkeypatch.setattr(
        shadow_module.transaction,
        "atomic",
        lambda *, using: _Atomic(connection, events),
    )
    monkeypatch.setattr(
        shadow_module,
        "read_account_authority_generation_proof",
        lambda *, using: AccountAuthorityGenerationProof(using="other", generation=9),
    )
    monkeypatch.setattr(
        AccountAuthorityShadowScannerV3,
        "_read_shadow",
        lambda self, value: scan_calls.append(value),
    )

    with pytest.raises(AccountAuthorityGenerationUnavailable, match="alias"):
        scanner.scan(command, legacy)

    assert scan_calls == []
