"""Shared contracts and calculation for automatic buy pre-trade risk."""

from __future__ import annotations

import logging
from typing import Protocol

from apps.risk_center.application.trade_guard import PreTradeRiskCheckResult
from apps.simulated_trading.application.use_cases import (
    PositionRepositoryProtocol,
)
from apps.simulated_trading.domain.auto_trading_outcomes import (
    AutoTradingIssue,
    AutoTradingIssueKind,
)
from apps.simulated_trading.domain.entities import Position, SimulatedAccount


class PreTradeRiskGuardProtocol(Protocol):
    """Centralized pre-trade risk guard interface."""

    def execute(
        self,
        *,
        account_id: int,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        account_equity: float,
        total_position_value: float,
        cash_balance: float | None = None,
        current_symbol_position_value: float = 0.0,
    ) -> PreTradeRiskCheckResult:
        """Evaluate whether a proposed order can be submitted."""
        ...


def build_buy_risk_issue(
    *,
    account: SimulatedAccount,
    asset_code: str,
    quantity: float,
    price: float,
    position_repo: PositionRepositoryProtocol,
    pre_trade_risk_guard: PreTradeRiskGuardProtocol,
    logger: logging.Logger,
    positions: list[Position] | None = None,
) -> AutoTradingIssue | None:
    """Return a stable issue when the centralized buy risk check blocks or fails."""
    if account.cash_known is not True:
        return AutoTradingIssue(
            AutoTradingIssueKind.BLOCKED,
            "pre_trade_risk",
            "ACCOUNT_CASH_UNKNOWN",
            asset_code,
        )

    try:
        resolved_positions = (
            positions if positions is not None else position_repo.get_by_account(account.account_id)
        )
        if any(not getattr(position, "valuation_known", True) for position in resolved_positions):
            return AutoTradingIssue(
                AutoTradingIssueKind.BLOCKED,
                "pre_trade_risk",
                "POSITION_VALUATION_UNKNOWN",
                asset_code,
            )
        normalized_asset_code = asset_code.strip().upper()
        current_symbol_position_value = sum(
            float(position.market_value)
            for position in resolved_positions
            if position.asset_code.strip().upper() == normalized_asset_code
        )
        result = pre_trade_risk_guard.execute(
            account_id=account.account_id,
            symbol=normalized_asset_code,
            side="buy",
            quantity=float(quantity),
            price=float(price),
            account_equity=float(account.total_value),
            total_position_value=float(account.current_market_value),
            cash_balance=float(account.current_cash),
            current_symbol_position_value=current_symbol_position_value,
        )
    except Exception:
        logger.error("风控中心前置检查异常: asset=%s", asset_code)
        return AutoTradingIssue(
            AutoTradingIssueKind.FAILED,
            "pre_trade_risk",
            "PRE_TRADE_RISK_UNAVAILABLE",
            asset_code,
        )

    if not result.passed:
        logger.warning("风控中心拒绝买入: asset=%s", asset_code)
        return AutoTradingIssue(
            AutoTradingIssueKind.BLOCKED,
            "pre_trade_risk",
            "PRE_TRADE_RISK_REJECTED",
            asset_code,
        )

    for warning in result.warnings:
        logger.info("    风控中心提示 %s: %s", asset_code, warning)
    return None
