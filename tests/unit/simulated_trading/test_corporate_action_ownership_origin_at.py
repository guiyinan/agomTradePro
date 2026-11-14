"""Calendar-independent reads preserve the full immutable account-origin check."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.simulated_trading.infrastructure import (
    corporate_action_ownership_history_repository as repo,
)
from core.exceptions import BusinessLogicError

_NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)


class _Query:
    """Apply the repository's exact filters to one in-memory retained row."""

    def __init__(self, row: object | None) -> None:
        self._row = row
        self._filters: dict[str, object] = {}

    def using(self, alias: str) -> _Query:
        assert alias == "default"
        return self

    def filter(self, **filters: object) -> _Query:
        self._filters = filters
        return self

    def first(self) -> object | None:
        if self._row is None:
            return None
        for name, expected in self._filters.items():
            if name.endswith("__lte"):
                field_name = name.removesuffix("__lte")
                if getattr(self._row, field_name) > expected:
                    return None
            elif getattr(self._row, name) != expected:
                return None
        return self._row


class _Manager:
    """Expose one fixture row using the repository's manager query chain."""

    def __init__(self, row: object | None) -> None:
        self._row = row

    def using(self, alias: str) -> _Manager:
        assert alias == "default"
        return self

    def filter(self, **filters: object) -> _Query:
        return _Query(self._row).filter(**filters)


def _fixture(*, account_created_at: datetime | None = None) -> tuple[object, object]:
    """Build an exact account row and a matching sealed zero-origin anchor."""

    created_at = account_created_at or (_NOW - timedelta(days=5))
    account = SimpleNamespace(
        pk=7,
        user_id=29,
        account_type="simulated",
        created_at=created_at,
    )
    anchor_created_at = created_at + timedelta(seconds=1)
    anchor_id = "simulated-account-zero-origin.v1:7"
    anchor_kind = "zero_origin"
    quantity = Decimal("0.000000")
    anchor = SimpleNamespace(
        account_id=7,
        owner_user_id=29,
        anchor_id=anchor_id,
        anchor_kind=anchor_kind,
        quantity=quantity,
        account_created_at=created_at,
        created_at=anchor_created_at,
        evidence_sha256=repo.simulated_account_ownership_anchor_sha256(
            account_id=7,
            owner_user_id=29,
            anchor_id=anchor_id,
            account_created_at=created_at,
            observed_at=anchor_created_at,
            anchor_kind=anchor_kind,
            quantity=quantity,
        ),
    )
    return account, anchor


def _reader(monkeypatch: pytest.MonkeyPatch, account: object, anchor: object | None):
    """Install in-memory ORM boundaries without opening a database connection."""

    class AnchorModelStub:
        ZERO_ORIGIN = "zero_origin"
        _base_manager = _Manager(anchor)

    monkeypatch.setattr(
        repo,
        "SimulatedAccountModel",
        SimpleNamespace(_base_manager=_Manager(account)),
    )
    monkeypatch.setattr(repo, "SimulatedAccountOwnershipAnchorModel", AnchorModelStub)
    monkeypatch.setattr(repo.transaction, "atomic", lambda **kwargs: nullcontext())
    return repo.DjangoCorporateActionOwnershipHistoryRepository(
        exchange_timezone_policy_reader=SimpleNamespace(
            read_exchange_timezone_policy=lambda **kwargs: pytest.fail(
                "the origin-only query must not read a market calendar"
            )
        )
    )


def test_verified_origin_at_returns_account_clock_without_calendar(monkeypatch):
    account, anchor = _fixture()
    reader = _reader(monkeypatch, account, anchor)

    result = reader.read_verified_zero_origin_at(
        account_id=7,
        owner_user_id=29,
        as_of=_NOW,
    )

    assert result is account.created_at


@pytest.mark.parametrize("anchor_state", ["missing", "bad_digest"])
def test_verified_origin_at_requires_the_exact_immutable_anchor(monkeypatch, anchor_state):
    account, anchor = _fixture()
    selected_anchor = None if anchor_state == "missing" else anchor
    if selected_anchor is not None:
        selected_anchor.evidence_sha256 = "0" * 64
    reader = _reader(monkeypatch, account, selected_anchor)

    with pytest.raises(BusinessLogicError) as error:
        reader.read_verified_zero_origin_at(account_id=7, owner_user_id=29, as_of=_NOW)

    assert error.value.code == "CORPORATE_ACTION_OWNERSHIP_ANCHOR_UNAVAILABLE"


@pytest.mark.parametrize("defect", ["wrong_owner", "future_account", "naive_cutoff"])
def test_verified_origin_at_rejects_wrong_scope_or_unknown_cutoff(monkeypatch, defect):
    account, anchor = _fixture(
        account_created_at=_NOW + timedelta(seconds=1) if defect == "future_account" else None
    )
    if defect == "wrong_owner":
        account.user_id = 30
    reader = _reader(monkeypatch, account, anchor)
    cutoff = _NOW.replace(tzinfo=None) if defect == "naive_cutoff" else _NOW

    with pytest.raises(BusinessLogicError) as error:
        reader.read_verified_zero_origin_at(account_id=7, owner_user_id=29, as_of=cutoff)

    expected = (
        "CORPORATE_ACTION_OWNERSHIP_INPUT_INVALID"
        if defect == "naive_cutoff"
        else "CORPORATE_ACTION_OWNERSHIP_SCOPE_INVALID"
    )
    assert error.value.code == expected


def test_calendar_read_delegates_to_verified_origin_at(monkeypatch):
    account, anchor = _fixture()
    timezone_policy = repo.QualifiedExchangeTimezone(
        exchange="SZSE",
        timezone_name="Asia/Shanghai",
        policy_id="fixture-policy",
        policy_sha256="a" * 64,
    )
    reader = repo.DjangoCorporateActionOwnershipHistoryRepository(
        exchange_timezone_policy_reader=SimpleNamespace(
            read_exchange_timezone_policy=lambda **kwargs: timezone_policy
        )
    )
    origin_at = account.created_at
    calls: list[dict[str, object]] = []

    def read_origin(**kwargs: object) -> datetime:
        calls.append(kwargs)
        return origin_at

    monkeypatch.setattr(reader, "read_verified_zero_origin_at", read_origin)

    result = reader.read_verified_zero_origin_calendar(
        account_id=7,
        owner_user_id=29,
        exchange="SZSE",
        as_of=_NOW,
    )

    assert calls == [{"account_id": 7, "owner_user_id": 29, "as_of": _NOW}]
    assert result.origin_on == origin_at.date()
    assert result.decision_on == _NOW.date()
    assert result.timezone_policy == timezone_policy
