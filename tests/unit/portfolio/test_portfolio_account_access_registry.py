"""Tests for the app-neutral Portfolio account-access registry."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from core.integration import portfolio_account_access


@dataclass(frozen=True, slots=True)
class _Result:
    error: str | None
    status_code: int | None


def test_registry_forwards_the_exact_actor_account_and_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[tuple[object, int, str]] = []
    actor = object()

    def checker(user: object, account_id: int, action: str) -> _Result:
        received.append((user, account_id, action))
        return _Result(error=None, status_code=None)

    monkeypatch.setattr(portfolio_account_access, "_account_access_checker", None)
    portfolio_account_access.register_portfolio_account_access_checker(checker)

    result = portfolio_account_access.check_portfolio_account_access(actor, 7, "查看计划")

    assert result.error is None
    assert received == [(actor, 7, "查看计划")]


def test_registry_fails_closed_when_the_owner_checker_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(portfolio_account_access, "_account_access_checker", None)

    with pytest.raises(RuntimeError, match="unavailable"):
        portfolio_account_access.check_portfolio_account_access(object(), 7, "查看计划")
