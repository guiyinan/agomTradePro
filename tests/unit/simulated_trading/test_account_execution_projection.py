"""Account execution projection keeps ledger sellable quantity explicit."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.simulated_trading.application import query_services

_MISSING = object()


class _AccountRepository:
    def __init__(self, account: SimpleNamespace, owner_user_id: int) -> None:
        self.account = account
        self.owner_user_id = owner_user_id
        self.requested_user_ids: list[int] = []

    def get_by_user(self, user_id: int) -> list[SimpleNamespace]:
        self.requested_user_ids.append(user_id)
        return [self.account] if user_id == self.owner_user_id else []


class _PositionRepository:
    def __init__(self, positions: list[SimpleNamespace]) -> None:
        self.positions = positions
        self.requested_account_ids: list[int] = []

    def get_by_account(self, account_id: int) -> list[SimpleNamespace]:
        self.requested_account_ids.append(account_id)
        return self.positions


def _position(
    *,
    quantity: object = 100,
    available_quantity: object = _MISSING,
    asset_code: str = "600000.SH",
) -> SimpleNamespace:
    values: dict[str, object] = {
        "asset_code": asset_code,
        "quantity": quantity,
        "available_quantity_known": True,
        "current_price": 10.0,
        "market_value": 1000.0,
    }
    if available_quantity is not _MISSING:
        values["available_quantity"] = available_quantity
    return SimpleNamespace(**values)


def _install_repositories(
    monkeypatch: pytest.MonkeyPatch,
    *,
    positions: list[SimpleNamespace],
    account_id: int = 7,
    owner_user_id: int = 19,
) -> tuple[_AccountRepository, _PositionRepository]:
    account_repo = _AccountRepository(
        SimpleNamespace(
            account_id=account_id,
            account_type="real",
            is_active=True,
            total_value=2000.0,
            current_cash=1000.0,
            current_market_value=1000.0,
        ),
        owner_user_id=owner_user_id,
    )
    position_repo = _PositionRepository(positions)
    monkeypatch.setattr(
        query_services,
        "get_simulated_account_repository",
        lambda: account_repo,
    )
    monkeypatch.setattr(
        query_services,
        "get_simulated_position_repository",
        lambda: position_repo,
    )
    return account_repo, position_repo


@pytest.mark.parametrize("available_quantity", [Decimal("0"), Decimal("0.1"), Decimal("37.25")])
def test_execution_projection_returns_persisted_available_quantity(
    monkeypatch: pytest.MonkeyPatch,
    available_quantity: Decimal,
) -> None:
    account_repo, position_repo = _install_repositories(
        monkeypatch,
        positions=[_position(available_quantity=available_quantity)],
    )

    projection = query_services.get_account_execution_projection(user_id=19, account_id=7)

    assert projection is not None
    assert projection["positions"] == [
        {
            "asset_code": "600000.SH",
            "quantity": 100.0,
            "available_quantity": float(available_quantity),
            "current_price": 10.0,
            "market_value": 1000.0,
        }
    ]
    assert set(projection) == {
        "account_id",
        "user_id",
        "account_type",
        "is_active",
        "total_asset",
        "cash_available",
        "total_position_value",
        "positions",
    }
    assert account_repo.requested_user_ids == [19]
    assert position_repo.requested_account_ids == [7]


@pytest.mark.parametrize(
    "available_quantity",
    [
        None,
        -1,
        101,
        True,
        "not-a-number",
        float("nan"),
        float("inf"),
        float("-inf"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ],
)
def test_execution_projection_is_unavailable_for_invalid_available_quantity(
    monkeypatch: pytest.MonkeyPatch,
    available_quantity: object,
) -> None:
    _install_repositories(
        monkeypatch,
        positions=[_position(available_quantity=available_quantity)],
    )

    projection = query_services.get_account_execution_projection(user_id=19, account_id=7)

    assert projection is None


def test_execution_projection_is_unavailable_when_available_quantity_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_repositories(monkeypatch, positions=[_position()])

    projection = query_services.get_account_execution_projection(user_id=19, account_id=7)

    assert projection is None


def test_execution_projection_rejects_float_rounding_that_increases_quantity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_repositories(
        monkeypatch,
        positions=[
            _position(
                quantity=10_000_000_000_000_000,
                available_quantity=Decimal("9999999999999999"),
            )
        ],
    )

    projection = query_services.get_account_execution_projection(user_id=19, account_id=7)

    assert projection is None


@pytest.mark.parametrize("quantity", [None, -1, True, "invalid", float("nan"), float("inf")])
def test_execution_projection_is_unavailable_for_invalid_total_quantity(
    monkeypatch: pytest.MonkeyPatch,
    quantity: object,
) -> None:
    _install_repositories(
        monkeypatch,
        positions=[_position(quantity=quantity, available_quantity=0)],
    )

    projection = query_services.get_account_execution_projection(user_id=19, account_id=7)

    assert projection is None


def test_one_invalid_position_makes_the_whole_projection_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_repositories(
        monkeypatch,
        positions=[
            _position(available_quantity=25),
            _position(asset_code="000001.SZ", available_quantity=101),
        ],
    )

    projection = query_services.get_account_execution_projection(user_id=19, account_id=7)

    assert projection is None


def test_execution_projection_preserves_user_and_account_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_repo, position_repo = _install_repositories(
        monkeypatch,
        positions=[_position(available_quantity=0)],
        account_id=7,
    )

    projection = query_services.get_account_execution_projection(user_id=19, account_id=8)
    wrong_user_projection = query_services.get_account_execution_projection(
        user_id=20,
        account_id=7,
    )

    assert projection is None
    assert wrong_user_projection is None
    assert account_repo.requested_user_ids == [19, 20]
    assert position_repo.requested_account_ids == []
