from __future__ import annotations

from contextlib import nullcontext

import pytest

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_bundle_provider import (
    DjangoAccountActorAuthorityInputBundleProviderV3,
)
from apps.account.infrastructure.account_system_audit_actor_authority_bundle_provider import (
    DjangoAccountSystemAuditActorAuthorityBundleProviderV3,
)


class _Ops:
    @staticmethod
    def quote_name(value: str) -> str:
        return f'"{value}"'


class _Cursor:
    def __init__(self, isolation: str = "read committed") -> None:
        self.isolation = isolation
        self.statements: list[str] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def fetchone(self) -> tuple[str]:
        return (self.isolation,)


class _Connection:
    def __init__(
        self,
        *,
        alias: str = "default",
        vendor: str = "postgresql",
        in_atomic_block: bool = True,
        autocommit: bool = False,
        isolation: str = "read committed",
    ) -> None:
        self.alias = alias
        self.vendor = vendor
        self.in_atomic_block = in_atomic_block
        self.autocommit = autocommit
        self.ops = _Ops()
        self.cursor_value = _Cursor(isolation)

    def get_autocommit(self) -> bool:
        return self.autocommit

    def cursor(self) -> _Cursor:
        return self.cursor_value


def _provider() -> DjangoAccountSystemAuditActorAuthorityBundleProviderV3:
    return DjangoAccountSystemAuditActorAuthorityBundleProviderV3(using="default")


def test_active_read_committed_transaction_locks_all_raw_authority_tables() -> None:
    connection = _Connection()

    with _provider()._snapshot(connection):  # type: ignore[arg-type]
        pass

    assert connection.cursor_value.statements[0] == "SHOW transaction_isolation"
    lock = connection.cursor_value.statements[1]
    assert lock.startswith("LOCK TABLE ")
    assert lock.endswith(" IN SHARE MODE NOWAIT")
    assert lock.count('"account_') == 6


def test_standalone_read_delegates_to_original_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(in_atomic_block=False, autocommit=True)
    calls: list[object] = []

    def snapshot(_self: object, supplied: object):
        calls.append(supplied)
        return nullcontext()

    monkeypatch.setattr(DjangoAccountActorAuthorityInputBundleProviderV3, "_snapshot", snapshot)

    with _provider()._snapshot(connection):  # type: ignore[arg-type]
        pass

    assert calls == [connection]
    assert connection.cursor_value.statements == []


@pytest.mark.parametrize(
    ("connection", "error_type", "message"),
    [
        (_Connection(alias="other"), AccountActorAuthorityRawSourceV3Corruption, "alias"),
        (_Connection(vendor="sqlite"), AccountActorAuthorityRawSourceV3Unavailable, "PostgreSQL"),
        (
            _Connection(in_atomic_block=False, autocommit=False),
            AccountActorAuthorityRawSourceV3Unavailable,
            "unavailable",
        ),
        (
            _Connection(isolation="repeatable read"),
            AccountActorAuthorityRawSourceV3Unavailable,
            "READ COMMITTED",
        ),
    ],
)
def test_invalid_caller_transaction_fails_closed(
    connection: _Connection,
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        _provider()._snapshot(connection)  # type: ignore[arg-type]
