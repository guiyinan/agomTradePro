"""Deterministic contracts for deployment cache warmup."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management.base import CommandError

from core.management.commands import warmup_cache as module


class _FakeCache:
    def __init__(self, initial: dict[str, object] | None = None) -> None:
        self.data = dict(initial or {})
        self.fail_key: str | None = None
        self.raise_after_write_key: str | None = None
        self.raise_on_get_key: str | None = None

    def get(self, key: str, default: object = None) -> object:
        if key == self.raise_on_get_key:
            raise ConnectionError("redis://secret-host")
        return self.data.get(key, default)

    def set(self, key: str, value: object, timeout: int) -> None:
        assert timeout == module.CACHE_TIMEOUT_SECONDS
        if key != self.fail_key:
            self.data[key] = value
        if key == self.raise_after_write_key:
            self.raise_after_write_key = None
            raise ConnectionError("redis://secret-host")

    def delete(self, key: str) -> None:
        self.data.pop(key, None)


def test_warmup_rejects_unknown_target_before_queries(monkeypatch) -> None:
    """Typos cannot produce an empty successful warmup."""

    command = module.Command(stdout=StringIO())
    monkeypatch.setattr(command, "_prepare_target", lambda _target: pytest.fail("queried"))

    with pytest.raises(CommandError, match="unknown cache warmup target"):
        command.handle(only="regmie", allow_empty=False)


def test_warmup_empty_requires_explicit_allow_empty(monkeypatch) -> None:
    """Missing critical data fails unless an operator explicitly allows cold state."""

    command = module.Command(stdout=StringIO())
    empty = module.WarmupTargetResult("regime", (), "no regime data")
    monkeypatch.setattr(command, "_prepare_target", lambda _target: empty)

    with pytest.raises(CommandError, match="has no data"):
        command.handle(only="regime", allow_empty=False)

    command.handle(only="regime", allow_empty=True)
    assert "Cache warmup complete" in command.stdout.getvalue()


def test_warmup_prepares_every_target_before_any_cache_write(monkeypatch) -> None:
    """A later preparation failure leaves all existing cache values untouched."""

    fake_cache = _FakeCache({"regime:current": {"regime": "Recovery"}})
    monkeypatch.setattr(module, "cache", fake_cache)
    command = module.Command(stdout=StringIO())

    def _prepare(target: str) -> module.WarmupTargetResult:
        if target == "regime":
            return module.WarmupTargetResult(
                target,
                (module.CacheEntry("regime:current", {"regime": "Deflation"}),),
                "Deflation",
            )
        raise RuntimeError("token=should-not-appear")

    monkeypatch.setattr(command, "_prepare_target", _prepare)
    with pytest.raises(CommandError, match="RuntimeError") as exc_info:
        command.handle(only="regime,macro", allow_empty=False)

    assert "should-not-appear" not in str(exc_info.value)
    assert fake_cache.data["regime:current"] == {"regime": "Recovery"}


def test_warmup_rejects_duplicate_keys_before_writes(monkeypatch) -> None:
    """Multiple Alpha rows for one universe cannot silently overwrite by query order."""

    fake_cache = _FakeCache()
    monkeypatch.setattr(module, "cache", fake_cache)
    command = module.Command(stdout=StringIO())
    duplicate = module.WarmupTargetResult(
        "alpha",
        (
            module.CacheEntry("alpha:score:csi300", {"status": "old"}),
            module.CacheEntry("alpha:score:csi300", {"status": "new"}),
        ),
        "2 scores",
    )
    monkeypatch.setattr(command, "_prepare_target", lambda _target: duplicate)

    with pytest.raises(CommandError, match="duplicate cache warmup key"):
        command.handle(only="alpha", allow_empty=False)
    assert fake_cache.data == {}


def test_warmup_restores_prior_values_when_round_trip_verification_fails(monkeypatch) -> None:
    """A backend write failure restores old entries and removes new partial keys."""

    fake_cache = _FakeCache({"regime:current": {"regime": "Recovery"}})
    fake_cache.fail_key = "macro:latest:CN_CPI"
    monkeypatch.setattr(module, "cache", fake_cache)
    entries = (
        module.CacheEntry("regime:current", {"regime": "Deflation"}),
        module.CacheEntry("macro:latest:CN_CPI", {"value": 2.0}),
    )

    with pytest.raises(CommandError, match="RuntimeError"):
        module.Command._write_entries(entries)

    assert fake_cache.data == {"regime:current": {"regime": "Recovery"}}


def test_warmup_snapshot_failure_is_sanitized_before_writes(monkeypatch) -> None:
    """Snapshot errors fail closed without exposing backend connection details."""

    fake_cache = _FakeCache({"regime:current": {"regime": "Recovery"}})
    fake_cache.raise_on_get_key = "regime:current"
    monkeypatch.setattr(module, "cache", fake_cache)
    entries = (module.CacheEntry("regime:current", {"regime": "Deflation"}),)

    with pytest.raises(CommandError, match="snapshot failed: ConnectionError") as exc_info:
        module.Command._write_entries(entries)

    assert "secret-host" not in str(exc_info.value)
    assert fake_cache.data == {"regime:current": {"regime": "Recovery"}}


def test_warmup_rolls_back_when_backend_raises_after_mutation(monkeypatch) -> None:
    """The current key is restored even when a backend mutates before raising."""

    fake_cache = _FakeCache({"regime:current": {"regime": "Recovery"}})
    fake_cache.raise_after_write_key = "regime:current"
    monkeypatch.setattr(module, "cache", fake_cache)
    entries = (module.CacheEntry("regime:current", {"regime": "Deflation"}),)

    with pytest.raises(CommandError, match="write failed: ConnectionError") as exc_info:
        module.Command._write_entries(entries)

    assert "secret-host" not in str(exc_info.value)
    assert fake_cache.data == {"regime:current": {"regime": "Recovery"}}
