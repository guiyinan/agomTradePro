"""Pure boundary checks for E1 v3 current UOW acquisition and joining."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from apps.data_center.infrastructure import financial_v3_current_uow as current_uow


class _FakeConnection:
    """Minimal connection state consumed by the UOW boundary."""

    def __init__(self, *, vendor: str = "postgresql") -> None:
        self.alias = "default"
        self.vendor = vendor
        self.in_atomic_block = False
        self.autocommit = True
        self.atomic_blocks: list[object] = []

    def get_autocommit(self) -> bool:
        """Return the current synthetic autocommit setting."""

        return self.autocommit


def _fake_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    vendor: str = "postgresql",
) -> tuple[_FakeConnection, list[str]]:
    """Replace Django connection entry with state-only test doubles."""

    fake_connection = _FakeConnection(vendor=vendor)
    calls: list[str] = []

    @contextmanager
    def fake_atomic(*, using: str) -> Iterator[None]:
        assert using == "default"
        calls.append("atomic")
        marker = object()
        fake_connection.in_atomic_block = True
        fake_connection.autocommit = False
        fake_connection.atomic_blocks.append(marker)
        try:
            yield
        finally:
            fake_connection.atomic_blocks.pop()
            fake_connection.in_atomic_block = bool(fake_connection.atomic_blocks)
            fake_connection.autocommit = not fake_connection.in_atomic_block

    monkeypatch.setattr(current_uow, "connections", {"default": fake_connection})
    monkeypatch.setattr(
        current_uow,
        "transaction",
        SimpleNamespace(atomic=fake_atomic),
    )
    return fake_connection, calls


def test_current_uow_opens_once_or_joins_without_savepoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Open one outer boundary or join exactly one existing boundary."""

    fake_connection, calls = _fake_runtime(monkeypatch)
    depths: list[int] = []

    def require_one(*, using: str) -> None:
        assert using == "default"
        assert fake_connection.in_atomic_block
        assert not fake_connection.get_autocommit()
        depths.append(len(fake_connection.atomic_blocks))

    monkeypatch.setattr(current_uow, "_require_one_default_read_committed_uow", require_one)
    with current_uow.financial_v3_current_operation_uow():
        assert len(fake_connection.atomic_blocks) == 1
    assert not fake_connection.in_atomic_block

    fake_connection.in_atomic_block = True
    fake_connection.autocommit = False
    fake_connection.atomic_blocks.append(object())
    with current_uow.financial_v3_current_operation_uow():
        assert len(fake_connection.atomic_blocks) == 1
    assert len(fake_connection.atomic_blocks) == 1
    assert calls == ["atomic"]
    assert depths == [1, 1]


def test_current_uow_refuses_to_join_nested_atomic_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never treat nested transaction depth as one qualified current UOW."""

    fake_connection, _calls = _fake_runtime(monkeypatch)
    fake_connection.in_atomic_block = True
    fake_connection.autocommit = False
    fake_connection.atomic_blocks.extend((object(), object()))

    def require_one(*, using: str) -> None:
        assert using == "default"
        if len(fake_connection.atomic_blocks) != 1:
            raise current_uow.FinancialV3CurrentUowBlocked()

    monkeypatch.setattr(current_uow, "_require_one_default_read_committed_uow", require_one)
    with pytest.raises(current_uow.FinancialV3CurrentUowBlocked):
        with current_uow.financial_v3_current_operation_uow():
            pytest.fail("a nested UOW must be rejected")


def test_postgresql_current_uow_rejects_sqlite_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLite connection state cannot be labeled a PostgreSQL RC fence."""

    _fake_runtime(monkeypatch, vendor="sqlite")
    with pytest.raises(current_uow.FinancialV3CurrentUowBlocked):
        with current_uow.financial_v3_current_operation_uow():
            pytest.fail("SQLite must not satisfy the PostgreSQL current boundary")
