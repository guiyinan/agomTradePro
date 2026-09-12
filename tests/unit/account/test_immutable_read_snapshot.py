"""Tests for caller-stabilized immutable ledger read reuse."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.account.infrastructure.immutable_read_snapshot import (
    immutable_read_snapshot,
    reuse_immutable_read,
)


class _Reader:
    def __init__(self) -> None:
        self.calls = 0

    @reuse_immutable_read("test-ledger-world")
    def read(self, *, as_of: datetime) -> object:
        self.calls += 1
        return object()


def test_read_reuse_requires_an_active_snapshot_and_exact_arguments() -> None:
    reader = _Reader()
    cutoff = datetime(2026, 9, 13, tzinfo=UTC)

    outside_first = reader.read(as_of=cutoff)
    outside_second = reader.read(as_of=cutoff)
    assert outside_first is not outside_second
    assert reader.calls == 2

    with immutable_read_snapshot():
        first = reader.read(as_of=cutoff)
        second = reader.read(as_of=cutoff)
        later = reader.read(as_of=cutoff + timedelta(microseconds=1))

    assert first is second
    assert later is not first
    assert reader.calls == 4


def test_read_reuse_isolated_by_repository_instance_and_operation() -> None:
    first_reader = _Reader()
    second_reader = _Reader()
    cutoff = datetime(2026, 9, 13, tzinfo=UTC)

    with immutable_read_snapshot():
        first = first_reader.read(as_of=cutoff)
        second = second_reader.read(as_of=cutoff)

    assert first is not second
    assert first_reader.calls == 1
    assert second_reader.calls == 1

    with immutable_read_snapshot():
        assert first_reader.read(as_of=cutoff) is not first
    assert first_reader.calls == 2


def test_failed_read_is_not_cached() -> None:
    calls = 0

    @reuse_immutable_read("test-failed-ledger-read")
    def read(_repository: object) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("read failed")
        return "ok"

    repository = object()
    with immutable_read_snapshot():
        with pytest.raises(RuntimeError, match="read failed"):
            read(repository)
        assert read(repository) == "ok"
        assert read(repository) == "ok"

    assert calls == 2
