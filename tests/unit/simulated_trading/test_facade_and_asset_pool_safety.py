"""Safety regressions for simulated-trading application read services."""

from datetime import date
from decimal import Decimal

import pytest

from apps.simulated_trading.application.asset_pool_query_service import (
    AssetPoolQueryService,
)
from apps.simulated_trading.application.facade import SimulatedTradingFacade
from apps.simulated_trading.domain.entities import (
    AccountType,
    Position,
    SimulatedAccount,
)


def _account() -> SimulatedAccount:
    return SimulatedAccount(
        account_id=1,
        account_name="read model",
        account_type=AccountType.SIMULATED,
        initial_capital=1_000.0,
        current_cash=400.0,
        current_market_value=999.0,
        total_value=1_399.0,
    )


def _position() -> Position:
    return Position(
        account_id=1,
        asset_code="FUND.OF",
        asset_name="fractional fund",
        asset_type="fund",
        quantity=12.5,
        available_quantity=12.5,
        avg_cost=19.0,
        total_cost=237.5,
        current_price=20.0,
        market_value=250.0,
        unrealized_pnl=12.5,
        unrealized_pnl_pct=5.0,
        first_buy_date=date(2026, 1, 1),
        last_update_date=date(2026, 1, 2),
    )


class AccountRepo:
    def get_by_id(self, account_id: int) -> SimulatedAccount | None:
        return _account() if account_id == 1 else None

    def get_active_accounts(self) -> list[SimulatedAccount]:
        return [_account()]

    def user_owns_account(self, account_id: int, user_id: int) -> bool:
        return account_id == 1 and user_id == 7


class PositionRepo:
    def get_by_account(self, account_id: int) -> list[Position]:
        return [_position()]

    def get_position(self, account_id: int, asset_code: str) -> Position | None:
        return _position() if asset_code == "FUND.OF" else None


class RaisingPositionRepo(PositionRepo):
    def get_by_account(self, account_id: int) -> list[Position]:
        raise RuntimeError("position store unavailable")

    def get_position(self, account_id: int, asset_code: str) -> Position | None:
        raise RuntimeError("position store unavailable")


def test_facade_preserves_fractional_quantity_and_recomputes_market_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facade = SimulatedTradingFacade(
        account_repo=AccountRepo(),
        position_repo=PositionRepo(),
    )
    monkeypatch.setattr(facade, "_get_active_strategy_binding", lambda account_id: None)

    positions = facade.get_positions(1)
    overview = facade.get_account_overview(1)

    assert positions[0].quantity == 12.5
    assert overview is not None
    assert overview.market_value == Decimal("250.0")
    assert overview.total_value == Decimal("650.0")


def test_facade_does_not_turn_repository_failure_into_empty_portfolio() -> None:
    facade = SimulatedTradingFacade(
        account_repo=AccountRepo(),
        position_repo=RaisingPositionRepo(),
    )

    with pytest.raises(RuntimeError, match="position store unavailable"):
        facade.get_positions(1)

    with pytest.raises(RuntimeError, match="position store unavailable"):
        facade.position_exists(1, "FUND.OF")


class AssetPoolRepo:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float, int]] = []
        self.candidate: dict[str, object] = {
            "asset_code": " abc.sz ",
            "asset_name": "candidate",
            "score": 80.0,
        }

    def list_investable_assets(
        self,
        asset_type: str,
        min_score: float,
        limit: int,
    ) -> list[dict[str, object]]:
        self.calls.append((asset_type, min_score, limit))
        return [self.candidate]

    def get_latest_pool_type(self, asset_code: str) -> str | None:
        return "investable"

    def summarize_pool_counts(self, asset_type: str | None = None) -> dict[str, int]:
        return {"investable": 1}


class SignalRepo:
    def __init__(self) -> None:
        self.requested_codes: list[str] = []

    def get_valid_signal_summaries(
        self,
        asset_codes: list[str] | None = None,
    ) -> list[dict[str, object]]:
        self.requested_codes = list(asset_codes or [])
        return [
            {
                "id": 22,
                "asset_code": "ABC.SZ",
                "logic_desc": "latest",
            },
            {
                "id": 11,
                "asset_code": "abc.sz",
                "logic_desc": "older",
            },
        ]

    def get_signal_snapshot(self, signal_id: int) -> dict[str, object] | None:
        return None

    def get_signal_invalidation_payload(self, signal_id: int) -> tuple[str | None, str]:
        return None, ""


def test_asset_pool_uses_latest_signal_id_and_does_not_mutate_repository_row() -> None:
    pool_repo = AssetPoolRepo()
    signal_repo = SignalRepo()
    service = AssetPoolQueryService(pool_repo, signal_repo)

    candidates = service.get_investable_assets_with_signals(
        asset_type=" EQUITY ",
        min_score=60.0,
        limit=1_000,
    )

    assert signal_repo.requested_codes == ["ABC.SZ"]
    assert candidates[0]["asset_code"] == "ABC.SZ"
    assert candidates[0]["signal_id"] == 22
    assert candidates[0]["signal_logic"] == "latest"
    assert "signal_id" not in pool_repo.candidate
    assert pool_repo.calls == [("equity", 60.0, 500)]
