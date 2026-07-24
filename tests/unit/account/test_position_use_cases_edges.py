"""Account position orchestration and ownership boundary contracts."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.account.application.use_cases import (
    ClosePositionUseCase,
    CreatePositionFromSignalUseCase,
    CreatePositionInput,
    CreatePositionUseCase,
    UpdatePositionPricesUseCase,
)


class _AccountRepo:
    def __init__(self, profile: object | None = None) -> None:
        self.profile = profile

    def get_by_user_id(self, user_id: int) -> object | None:
        return self.profile

    def get_or_create_default_portfolio(self, user_id: int) -> int:
        return 7


class _PositionRepo:
    def __init__(self) -> None:
        self.position = SimpleNamespace(
            user_id=1,
            shares=100,
            market_value=Decimal("1250"),
        )
        self.created: list[dict[str, object]] = []

    def create_position_legacy(self, **kwargs: object) -> object:
        self.created.append(dict(kwargs))
        return self.position

    def create_position_from_signal(self, **kwargs: object) -> object:
        return self.position

    def get_position_by_id(self, position_id: int) -> object | None:
        return self.position if position_id == 1 else None

    def close_position(self, position_id: int, shares: float | None) -> object:
        return self.position


class _AssetRepo:
    def get_or_create_asset(self, **kwargs: object) -> dict[str, str]:
        return {"asset_class": "equity", "region": "CN"}

    def update_position_prices(self, user_id: int) -> int:
        return 3


def test_create_position_requires_profile_and_price_then_persists_manual_size() -> None:
    """Position creation rejects missing identity/price and returns exact notional."""
    positions = _PositionRepo()
    missing_profile = CreatePositionUseCase(
        positions,
        _AccountRepo(),
        _AssetRepo(),
        market_price_service=SimpleNamespace(get_price_with_metadata=lambda code: None),
    )
    with pytest.raises(ValueError, match="账户配置不存在"):
        missing_profile.execute(CreatePositionInput(user_id=1, asset_code="000001.SZ"))

    missing_price = CreatePositionUseCase(
        positions,
        _AccountRepo(SimpleNamespace(initial_capital=100000, risk_tolerance="moderate")),
        _AssetRepo(),
        market_price_service=SimpleNamespace(get_price_with_metadata=lambda code: None),
    )
    with pytest.raises(ValueError, match="无法获取"):
        missing_price.execute(CreatePositionInput(user_id=1, asset_code="000001.SZ", shares=10))

    priced = CreatePositionUseCase(
        positions,
        _AccountRepo(SimpleNamespace(initial_capital=100000, risk_tolerance="moderate")),
        _AssetRepo(),
        market_price_service=SimpleNamespace(
            get_price_with_metadata=lambda code: {"price": 12.5, "source": "fake"}
        ),
    )
    output = priced.execute(CreatePositionInput(user_id=1, asset_code="000001.SZ", shares=10))
    assert output.shares == 10
    assert output.notional == Decimal("125.0")
    assert positions.created[0]["source"] == "manual"


def test_signal_position_enforces_owner_and_market_price() -> None:
    """Signal-derived positions require the same user and an auditable market price."""
    positions = _PositionRepo()
    account = _AccountRepo(SimpleNamespace())
    wrong_signal = SimpleNamespace(
        get_signal_snapshot=lambda signal_id: {"user_id": 2, "asset_code": "000001.SZ"}
    )
    use_case = CreatePositionFromSignalUseCase(
        positions,
        account,
        market_price_service=SimpleNamespace(
            get_price_with_metadata=lambda code: {"price": Decimal("12.5"), "source": "fake"}
        ),
        signal_repo=wrong_signal,
    )
    with pytest.raises(ValueError, match="无权限"):
        use_case.execute(1, 10)

    use_case.signal_repo = SimpleNamespace(
        get_signal_snapshot=lambda signal_id: {"user_id": 1, "asset_code": "000001.SZ"}
    )
    output = use_case.execute(1, 10)
    assert output.position is positions.position
    assert output.cash_required == Decimal("1250")


def test_close_position_and_price_refresh_enforce_ownership() -> None:
    """Close rejects missing/cross-user positions and refresh reports its timestamp."""
    positions = _PositionRepo()
    close = ClosePositionUseCase(positions)
    with pytest.raises(ValueError, match="不存在"):
        close.execute(99, 1)
    with pytest.raises(ValueError, match="无权限"):
        close.execute(1, 2)
    assert close.execute(1, 1, shares=50) is positions.position

    refreshed = UpdatePositionPricesUseCase(positions, _AssetRepo()).execute(1)
    assert refreshed["updated_count"] == 3
    assert refreshed["user_id"] == 1
    assert refreshed["updated_at"].tzinfo is not None
