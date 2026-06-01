"""Decision replay backtests for manual trade discipline review."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Callable

from apps.backtest.application.repository_provider import (
    get_backtest_repository,
    get_close_price_series_reader,
)
from apps.backtest.domain.entities import BacktestConfig
from apps.decision_rhythm.application.repository_provider import (
    get_unified_recommendation_repository,
)
from core.integration.manual_trade_sync import get_manual_trade_sync_repository


@dataclass(frozen=True)
class DecisionReplayBacktestRequest:
    user_id: int
    portfolio_id: int
    start_date: date
    end_date: date
    branch_type: str
    initial_capital: Decimal = Decimal("1000000")


@dataclass(frozen=True)
class DecisionReplayBacktestResponse:
    success: bool
    backtest_id: int | None = None
    error: str = ""


class DecisionReplayBacktestUseCase:
    """Run fixed-branch replay backtests from imported manual transactions."""

    VALID_BRANCHES = {"actual", "no_action", "system_plan", "delayed_1d"}

    def __init__(
        self,
        *,
        trade_repo=None,
        backtest_repo=None,
        recommendation_repo=None,
        price_series_reader: Callable[[str, date, date], list[tuple[date, float]]] | None = None,
    ) -> None:
        self.trade_repo = trade_repo or get_manual_trade_sync_repository()
        self.backtest_repo = backtest_repo or get_backtest_repository()
        self.recommendation_repo = recommendation_repo or get_unified_recommendation_repository()
        self.price_series_reader = price_series_reader or get_close_price_series_reader()

    def execute(self, request: DecisionReplayBacktestRequest) -> DecisionReplayBacktestResponse:
        if request.branch_type not in self.VALID_BRANCHES:
            return DecisionReplayBacktestResponse(
                success=False,
                error=f"branch_type must be one of {sorted(self.VALID_BRANCHES)}",
            )

        config = BacktestConfig(
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=float(request.initial_capital),
            rebalance_frequency="monthly",
            use_pit_data=True,
            transaction_cost_bps=0,
        )
        model = self.backtest_repo.create_backtest(
            name=f"Decision replay {request.branch_type} {request.start_date}..{request.end_date}",
            config=config,
        )
        model.user_id = request.user_id
        model.save(update_fields=["user"])

        transactions = self.trade_repo.list_imported_transactions_for_portfolio(
            user_id=request.user_id,
            portfolio_id=request.portfolio_id,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        try:
            result_payload = self._simulate(
                transactions=transactions,
                branch_type=request.branch_type,
                initial_capital=request.initial_capital,
                start_date=request.start_date,
                end_date=request.end_date,
            )
            model.mark_completed(result_payload["final_capital"], result_payload)
            return DecisionReplayBacktestResponse(success=True, backtest_id=model.id)
        except Exception as exc:
            model.mark_failed(str(exc))
            return DecisionReplayBacktestResponse(success=False, backtest_id=model.id, error=str(exc))

    def _simulate(
        self,
        *,
        transactions: list[Any],
        branch_type: str,
        initial_capital: Decimal,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        cash = initial_capital
        positions: dict[str, Decimal] = {}
        last_price: dict[str, Decimal] = {}
        trades: list[dict[str, Any]] = []
        equity_curve: list[dict[str, Any]] = []
        warnings: list[str] = []
        market_prices = self._load_market_prices(
            transactions=transactions,
            start_date=start_date,
            end_date=end_date,
            warnings=warnings,
        )
        trades_by_date = self._build_branch_trades(
            transactions=transactions,
            branch_type=branch_type,
            end_date=end_date,
            warnings=warnings,
        )

        current_date = start_date
        while current_date <= end_date:
            self._refresh_market_prices(
                positions=positions,
                last_price=last_price,
                market_prices=market_prices,
                as_of_date=current_date,
            )
            for trade in trades_by_date.get(current_date, []):
                action = trade["action"]
                shares = trade["shares"]
                price = trade["price"]
                asset_code = trade["asset_code"]
                notional = shares * price
                last_price[asset_code] = price

                if action == "buy":
                    cash -= notional + trade["cost"]
                    positions[asset_code] = positions.get(asset_code, Decimal("0")) + shares
                elif action == "sell":
                    sell_shares = min(shares, positions.get(asset_code, Decimal("0")))
                    cash += sell_shares * price - trade["cost"]
                    positions[asset_code] = positions.get(asset_code, Decimal("0")) - sell_shares
                trades.append(
                    {
                        "trade_date": current_date.isoformat(),
                        "asset_class": asset_code,
                        "action": action,
                        "shares": float(shares),
                        "price": float(price),
                        "notional": float(notional),
                        "cost": float(trade["cost"]),
                        "branch_type": branch_type,
                        "source_transaction_id": trade["source_transaction_id"],
                        "recommendation_id": trade["recommendation_id"],
                        "price_source": trade["price_source"],
                    }
                )
            equity_curve.append(
                {
                    "date": current_date.isoformat(),
                    "value": float(self._portfolio_value(cash, positions, last_price)),
                }
            )
            current_date += timedelta(days=1)

        final_capital = self._portfolio_value(cash, positions, last_price)
        total_return = (
            float((final_capital - initial_capital) / initial_capital)
            if initial_capital
            else 0.0
        )
        equity_values = [Decimal(str(point["value"])) for point in equity_curve]
        max_drawdown = self._max_drawdown(equity_values)
        return {
            "final_capital": float(final_capital),
            "total_return": total_return,
            "annualized_return": total_return,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": None,
            "equity_curve": equity_curve,
            "regime_history": [],
            "trades": trades,
            "warnings": warnings,
        }

    def _load_market_prices(
        self,
        *,
        transactions: list[Any],
        start_date: date,
        end_date: date,
        warnings: list[str],
    ) -> dict[str, dict[date, Decimal]]:
        prices: dict[str, dict[date, Decimal]] = {}
        for asset_code in sorted({tx.asset_code for tx in transactions}):
            rows = self.price_series_reader(asset_code, start_date, end_date) or []
            if not rows:
                warnings.append(
                    f"{asset_code} has no data_center close prices for {start_date}..{end_date}; "
                    "valuation falls back to execution prices."
                )
                prices[asset_code] = {}
                continue
            prices[asset_code] = {
                row_date: Decimal(str(close_price))
                for row_date, close_price in rows
                if start_date <= row_date <= end_date
            }
        return prices

    def _build_branch_trades(
        self,
        *,
        transactions: list[Any],
        branch_type: str,
        end_date: date,
        warnings: list[str],
    ) -> dict[date, list[dict[str, Any]]]:
        trades_by_date: dict[date, list[dict[str, Any]]] = {}
        if branch_type == "no_action":
            return trades_by_date

        for tx in transactions:
            trade_date = tx.traded_at.date()
            if branch_type == "delayed_1d":
                trade_date = min(trade_date + timedelta(days=1), end_date)
            shares = Decimal(str(tx.shares))
            price = Decimal(str(tx.price))
            recommendation_id = ""
            price_source = "imported_execution"
            if branch_type == "system_plan":
                plan = self.recommendation_repo.get_execution_plan_for_transaction(tx.id)
                if plan is None:
                    warnings.append(
                        f"{tx.asset_code} transaction {tx.id} has no matched recommendation; "
                        "system_plan fell back to actual execution."
                    )
                else:
                    recommendation_id = plan["recommendation_id"]
                    if int(plan["suggested_quantity"] or 0) > 0:
                        shares = Decimal(str(plan["suggested_quantity"]))
                    if tx.action == "buy":
                        price = Decimal(str(plan["entry_price_high"] or tx.price))
                    else:
                        price = Decimal(str(plan["target_price_low"] or tx.price))
                    price_source = "system_recommendation_plan"
            trades_by_date.setdefault(trade_date, []).append(
                {
                    "asset_code": tx.asset_code,
                    "action": tx.action,
                    "shares": shares,
                    "price": price,
                    "cost": Decimal(str(tx.commission or 0)),
                    "source_transaction_id": tx.id,
                    "recommendation_id": recommendation_id,
                    "price_source": price_source,
                }
            )
        return trades_by_date

    @staticmethod
    def _refresh_market_prices(
        *,
        positions: dict[str, Decimal],
        last_price: dict[str, Decimal],
        market_prices: dict[str, dict[date, Decimal]],
        as_of_date: date,
    ) -> None:
        for asset_code, shares in positions.items():
            if shares <= 0:
                continue
            close_price = market_prices.get(asset_code, {}).get(as_of_date)
            if close_price is not None and close_price > 0:
                last_price[asset_code] = close_price

    @staticmethod
    def _portfolio_value(
        cash: Decimal,
        positions: dict[str, Decimal],
        last_price: dict[str, Decimal],
    ) -> Decimal:
        value = cash
        for asset_code, shares in positions.items():
            value += shares * last_price.get(asset_code, Decimal("0"))
        return value

    @staticmethod
    def _max_drawdown(values: list[Decimal]) -> float:
        peak = Decimal("0")
        max_dd = Decimal("0")
        for value in values:
            peak = max(peak, value)
            if peak > 0:
                max_dd = min(max_dd, (value - peak) / peak)
        return float(abs(max_dd))
