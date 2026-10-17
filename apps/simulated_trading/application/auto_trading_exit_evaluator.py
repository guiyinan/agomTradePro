"""Exit and price evaluation helpers for the auto-trading application service."""

import logging
from collections.abc import Mapping
from datetime import date
from typing import Protocol

from apps.simulated_trading.application.ports import (
    AssetPoolServiceProtocol,
    PositionExitAdvice,
    PositionExitAdvisorProtocol,
    PriceProviderProtocol,
    SignalServiceProtocol,
)
from apps.simulated_trading.domain.auto_trading_outcomes import AutoTradingIssueKind
from apps.simulated_trading.domain.entities import Position, SimulatedAccount
from shared.numeric import safe_float


class IssueSink(Protocol):
    """Accept stable issues without coupling evaluation to engine state."""

    def add_issue(
        self,
        *,
        kind: AutoTradingIssueKind,
        stage: str,
        code: str,
        asset_code: str | None = None,
        effects_indeterminate: bool = False,
    ) -> None:
        """Append one issue to the account outcome being assembled."""
        ...


class FloatPicker(Protocol):
    """Callback preserving the engine's overridable float extraction seam."""

    def __call__(self, payload: Mapping[str, object], *keys: str) -> float | None:
        """Return the first valid positive float under the supplied keys."""
        ...


class PriceTrigger(Protocol):
    """Callback preserving the engine's overridable price-trigger seam."""

    def __call__(
        self,
        *,
        action: str,
        price: float,
        payload: Mapping[str, object],
    ) -> bool:
        """Evaluate a price against optional execution bands."""
        ...


class AutoTradingExitEvaluator:
    """Evaluate held-position exits and optional price bands.

    Ports, callbacks, issue sinks, and the logger are supplied on each call so
    the engine's current collaborators and its established override seams stay
    observable without retaining stale dependencies here.
    """

    def build_exit_advice_map(
        self,
        account_id: int,
        positions: list[Position],
        trade_date: date,
        *,
        exit_advisor: PositionExitAdvisorProtocol | None,
        state: IssueSink,
        logger: logging.Logger,
    ) -> dict[str, PositionExitAdvice]:
        """Load and normalize exit advice, preserving legacy fallback behavior."""
        if exit_advisor is None:
            return {}

        try:
            position_objects: list[object] = list(positions)
            advices = exit_advisor.get_exit_advices(
                account_id,
                position_objects,
                trade_date,
            )
        except Exception:
            logger.warning("exit_advisor 执行失败，回退旧卖出逻辑: account_id=%s", account_id)
            state.add_issue(
                kind=AutoTradingIssueKind.FAILED,
                stage="exit_advisor",
                code="EXIT_ADVISOR_UNAVAILABLE",
            )
            return {}

        return {
            advice.asset_code.strip().upper(): advice
            for advice in advices
            if advice.asset_code.strip()
        }

    def get_position_exit_advice(
        self,
        position: Position,
        account: SimulatedAccount,
        trade_date: date,
        advisor_map: dict[str, PositionExitAdvice] | None,
        *,
        signal_service: SignalServiceProtocol | None,
        asset_pool_service: AssetPoolServiceProtocol | None,
        logger: logging.Logger,
    ) -> PositionExitAdvice | None:
        """Apply the existing ordered exit checks to one position."""
        if position.is_invalidated:
            logger.info(f"    持仓 {position.asset_code} 已证伪,准备卖出")
            return PositionExitAdvice(
                asset_code=position.asset_code,
                should_exit=True,
                quantity=int(position.quantity),
                reason_code="POSITION_INVALIDATED",
                reason_text=position.invalidation_reason or "持仓已证伪",
                source="simulated_trading.position_invalidation",
            )

        advisor_advice = (advisor_map or {}).get(position.asset_code.strip().upper())
        if advisor_advice and (advisor_advice.should_exit or advisor_advice.should_reduce):
            action = "清仓" if advisor_advice.should_exit else "减仓"
            logger.info(
                "    持仓 %s 命中决策层%s建议,来源=%s",
                position.asset_code,
                action,
                advisor_advice.source,
            )
            return advisor_advice

        # 1. 检查信号是否仍然有效
        signal_valid = True
        if position.signal_id:
            if signal_service:
                signal = signal_service.get_signal_snapshot(position.signal_id)
                signal_valid = bool(signal and signal.get("is_valid", False))
            else:
                logger.warning("signal_service 未配置，跳过信号有效性校验: %s", position.signal_id)
                signal_valid = True

        if not signal_valid:
            logger.info(f"    持仓 {position.asset_code} 信号失效,准备卖出")
            return PositionExitAdvice(
                asset_code=position.asset_code,
                should_exit=True,
                quantity=int(position.quantity),
                reason_code="SIGNAL_INVALID",
                reason_text="信号失效卖出",
                source="simulated_trading.signal_validation",
            )

        # 2. 检查是否仍在可投池
        if asset_pool_service:
            pool_type = asset_pool_service.get_asset_pool_type(position.asset_code)
            if pool_type == "prohibited":
                logger.info(f"    持仓 {position.asset_code} 进入禁投池,准备卖出")
                return PositionExitAdvice(
                    asset_code=position.asset_code,
                    should_exit=True,
                    quantity=int(position.quantity),
                    reason_code="PROHIBITED_POOL",
                    reason_text="资产进入禁投池",
                    source="simulated_trading.asset_pool",
                )

        # 3. 检查是否触发止损
        if account.stop_loss_pct and position.unrealized_pnl_pct < -account.stop_loss_pct:
            logger.info(
                f"    持仓 {position.asset_code} 触发止损 "
                f"(浮亏{position.unrealized_pnl_pct:.2f}% > 止损线{account.stop_loss_pct}%),准备卖出"
            )
            return PositionExitAdvice(
                asset_code=position.asset_code,
                should_exit=True,
                quantity=int(position.quantity),
                reason_code="ACCOUNT_STOP_LOSS",
                reason_text=f"止损卖出(浮亏{position.unrealized_pnl_pct:.2f}%)",
                source="simulated_trading.account_risk",
            )

        return None

    def resolve_exit_quantity(self, position: Position, advice: PositionExitAdvice) -> int:
        """Return the existing full-exit or clamped reduction quantity."""
        position_quantity = max(int(position.quantity), 0)
        if advice.should_exit:
            return position_quantity
        if not advice.should_reduce or advice.quantity is None:
            return 0

        requested_quantity = int(advice.quantity)
        if requested_quantity <= 0:
            return 0
        return min(requested_quantity, position_quantity)

    def get_sell_reason(
        self,
        position: Position,
        advice: PositionExitAdvice | None = None,
    ) -> str:
        """Return the existing advisory, stop-loss, or signal-change reason."""
        if advice and advice.reason_text:
            return str(advice.reason_text)
        if position.unrealized_pnl_pct < 0:
            return f"止损卖出(浮亏{position.unrealized_pnl_pct:.2f}%)"
        else:
            return "信号变化卖出"

    def get_current_price(
        self,
        asset_code: str,
        trade_date: date,
        *,
        price_provider: PriceProviderProtocol | None,
    ) -> float | None:
        """Read the optional price, then require it when the first read fails."""
        if price_provider:
            price: float | None = safe_float(price_provider.get_price(asset_code, trade_date))
            if price is not None and price > 0:
                return price

            required_price: float | None = safe_float(
                price_provider.require_price(asset_code, trade_date)
            )
            if required_price is not None and required_price > 0:
                return required_price
        return None

    def is_exit_advice_price_triggered(
        self,
        advice: PositionExitAdvice,
        price: float,
        *,
        price_trigger: PriceTrigger,
    ) -> bool:
        """Evaluate an exit advice using the engine's current trigger callback."""
        payload = {
            "target_price_low": advice.target_price_low,
            "target_price_high": advice.target_price_high,
            "stop_loss_price": advice.stop_loss_price,
        }
        return price_trigger(action="sell", price=price, payload=payload)

    def is_price_triggered(
        self,
        *,
        action: str,
        price: float,
        payload: Mapping[str, object],
        pick_float: FloatPicker,
    ) -> bool:
        """Return whether current price satisfies optional execution bands."""
        if not payload:
            return True

        normalized_action = str(action or "").lower()
        if normalized_action == "sell":
            stop_loss_price = pick_float(payload, "stop_loss_price", "stop_loss")
            if stop_loss_price is not None and price <= stop_loss_price:
                return True
            low = pick_float(payload, "target_price_low", "sell_price_low", "exit_price_low")
            high = pick_float(payload, "target_price_high", "sell_price_high", "exit_price_high")
        else:
            low = pick_float(payload, "entry_price_low", "buy_price_low", "price_band_low")
            high = pick_float(payload, "entry_price_high", "buy_price_high", "price_band_high")

        if low is None and high is None:
            single_price = pick_float(
                payload,
                "entry_price",
                "buy_price",
                "target_price",
                "sell_price",
                "limit_price",
            )
            if single_price is None:
                return True
            if normalized_action == "sell":
                low = single_price
            else:
                high = single_price

        if low is not None and price < low:
            return False
        if high is not None and price > high:
            return False
        return True

    @staticmethod
    def pick_float(payload: Mapping[str, object], *keys: str) -> float | None:
        """Return the first positive numeric value under the supplied keys."""
        for key in keys:
            parsed: float | None = safe_float(payload.get(key))
            if parsed is None or parsed <= 0:
                continue
            return parsed
        return None
