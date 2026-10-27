"""
Account Application - Stop Loss Use Cases

自动止损止盈条件评估；通知由任务层按持仓所有者发送。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol, cast

from apps.account.application.market_price_contracts import MarketPriceServiceProtocol
from apps.account.application.repository_provider import (
    PositionRepository,
    StopLossRepository,
    TakeProfitRepository,
    build_market_price_service,
)
from apps.account.domain.interfaces import (
    PositionRepositoryProtocol,
    StopLossPeakObservation,
    StopLossRepositoryProtocol,
    TakeProfitRepositoryProtocol,
)
from apps.account.domain.observed_position_pnl import (
    calculate_observed_unrealized_pnl,
)
from apps.account.domain.services import (
    StopLossCheckResult,
    StopLossService,
    TakeProfitCheckResult,
    TakeProfitService,
)
from shared.numeric import safe_float

logger = logging.getLogger(__name__)


class RiskPolicyProviderProtocol(Protocol):
    """Risk-policy lookup required by stop-loss and take-profit checks."""

    def get_effective_parameters(self, account_id: int) -> dict[str, Any]: ...


class _RiskCenterPolicyProvider:
    """Read effective risk parameters without coupling account to risk-center ORM."""

    def get_effective_parameters(self, account_id: int) -> dict[str, Any]:
        from apps.risk_center.application.use_cases import (
            ResolveEffectiveRiskPolicyForAccountUseCase,
        )

        payload = ResolveEffectiveRiskPolicyForAccountUseCase().execute(account_id=account_id)
        parameters: object = payload.get("parameters", {})
        if not isinstance(parameters, dict):
            return {}
        return {str(key): value for key, value in parameters.items()}


def MarketPriceService() -> MarketPriceServiceProtocol:
    """Build the Account market-price boundary with provenance metadata."""

    return cast(MarketPriceServiceProtocol, build_market_price_service())


ExitCheckStatus = Literal["evaluated", "unavailable"]
ExitExecutionStatus = Literal["not_triggered", "blocked", "unknown", "confirmed"]
_LEGACY_EXIT_BLOCKED_REASON = "legacy_automatic_exit_not_qualified"
_CHECK_UNAVAILABLE_REASON = "automatic_exit_check_unavailable"


def is_valid_exit_user_id(user_id: object) -> bool:
    """Return whether an optional task owner id is a positive, exact integer."""

    return user_id is None or (type(user_id) is int and user_id > 0)


@dataclass(frozen=True)
class StopLossCheckOutput:
    """Separate a stop-loss trigger observation from any confirmed execution."""

    position_id: int | None
    asset_code: str | None
    triggered: bool
    check_status: ExitCheckStatus
    execution_status: ExitExecutionStatus
    reason_code: str | None
    check_result: StopLossCheckResult | None
    current_price: float | None
    unrealized_pnl: Decimal | None
    unrealized_pnl_pct: float | None
    execution_receipt_id: str | None = None
    price_source: str | None = None
    price_observed_at: datetime | None = None
    price_freshness: str | None = None
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True


@dataclass(frozen=True)
class TakeProfitCheckOutput:
    """Separate a take-profit trigger observation from any confirmed execution."""

    position_id: int | None
    asset_code: str | None
    triggered: bool
    check_status: ExitCheckStatus
    execution_status: ExitExecutionStatus
    reason_code: str | None
    check_result: TakeProfitCheckResult | None
    current_price: float | None
    unrealized_pnl: Decimal | None
    unrealized_pnl_pct: float | None
    partial_level: int | None = None
    execution_receipt_id: str | None = None
    price_source: str | None = None
    price_observed_at: datetime | None = None
    price_freshness: str | None = None
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True


@dataclass(frozen=True)
class _MarketPriceObservation:
    """A realtime price observation retained only for blocked diagnostics."""

    price: float
    exact_price: Decimal
    source: str
    observed_at: datetime
    freshness: str


def _read_realtime_price_observation(
    market_price_service: MarketPriceServiceProtocol,
    asset_code: str,
    evaluation_time: datetime,
) -> _MarketPriceObservation | None:
    """Read only exact, non-fallback realtime prices with valid source clocks."""

    try:
        metadata = market_price_service.get_price_with_metadata(asset_code)
    except Exception as exc:
        logger.warning("Market price lookup failed: error_type=%s", type(exc).__name__)
        return None
    if not isinstance(metadata, dict):
        return None
    raw_code: object = metadata.get("asset_code")
    raw_price: object = metadata.get("price")
    source: object = metadata.get("source")
    freshness: object = metadata.get("freshness")
    is_fallback: object = metadata.get("is_fallback")
    observed_at: object = metadata.get("observed_at")
    if (
        not isinstance(raw_code, str)
        or raw_code != asset_code.strip().upper()
        or freshness != "realtime"
        or is_fallback is not False
        or not isinstance(source, str)
        or not source.strip()
        or not isinstance(observed_at, datetime)
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
        or observed_at > evaluation_time
        or isinstance(raw_price, bool)
    ):
        return None
    price = safe_float(raw_price)
    if price is None or not math.isfinite(price) or price <= 0:
        return None
    try:
        exact_price = raw_price if isinstance(raw_price, Decimal) else Decimal(str(raw_price))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not exact_price.is_finite() or exact_price <= 0:
        return None
    return _MarketPriceObservation(
        price=price,
        exact_price=exact_price,
        source=source.strip(),
        observed_at=observed_at,
        freshness="realtime",
    )


def _positive_integer(value: object) -> int | None:
    """Narrow a repository value to a positive integer without accepting booleans."""

    if type(value) is int and value > 0:
        return value
    return None


def _decimal_value(value: object) -> Decimal | None:
    """Return an exact finite Decimal for persisted monetary values."""

    if isinstance(value, bool) or value is None:
        return None
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _stop_price_for_storage(value: Decimal) -> Decimal | None:
    """Normalize only prices exactly representable by decimal(20, 4)."""

    if not value.is_finite() or value <= 0:
        return None
    try:
        normalized = value.quantize(Decimal("0.0001"))
    except ArithmeticError:
        return None
    if normalized != value or len(normalized.as_tuple().digits) > 20:
        return None
    return normalized


def _position_identity(config: dict[str, Any]) -> tuple[int | None, str | None]:
    """Return only position identity fields that are independently validated."""

    position_value: object = config.get("position")
    if not isinstance(position_value, dict):
        return None, None
    position = cast(dict[str, Any], position_value)
    position_id = _positive_integer(position.get("id"))
    asset_code_value: object = position.get("asset_code")
    asset_code = (
        asset_code_value.strip()
        if isinstance(asset_code_value, str) and asset_code_value.strip()
        else None
    )
    return position_id, asset_code


def _position_fields(config: dict[str, Any]) -> tuple[int, str, float, float, int | None] | None:
    """Narrow the legacy repository payload needed for one exit check."""

    position_value: object = config.get("position")
    if not isinstance(position_value, dict):
        return None
    position = cast(dict[str, Any], position_value)
    position_id, asset_code = _position_identity(config)
    entry_price = safe_float(position.get("avg_cost"))
    shares = safe_float(position.get("shares"))
    portfolio_id = _positive_integer(position.get("portfolio_id"))
    if (
        position_id is None
        or asset_code is None
        or entry_price is None
        or entry_price <= 0
        or shares is None
        or shares <= 0
    ):
        return None
    return position_id, asset_code, entry_price, shares, portfolio_id


def _unavailable_stop_loss(
    *,
    position_id: int | None,
    asset_code: str | None,
    reason_code: str = _CHECK_UNAVAILABLE_REASON,
    observation: _MarketPriceObservation | None = None,
) -> StopLossCheckOutput:
    """Build an unavailable stop result without synthesizing price or P&L values."""

    return StopLossCheckOutput(
        position_id=position_id,
        asset_code=asset_code,
        triggered=False,
        check_status="unavailable",
        execution_status="not_triggered",
        reason_code=reason_code,
        check_result=None,
        current_price=observation.price if observation is not None else None,
        unrealized_pnl=None,
        unrealized_pnl_pct=None,
        price_source=observation.source if observation is not None else None,
        price_observed_at=observation.observed_at if observation is not None else None,
        price_freshness=observation.freshness if observation is not None else None,
        must_not_use_for_decision=True,
        must_not_execute=True,
    )


def _unavailable_take_profit(
    *,
    position_id: int | None,
    asset_code: str | None,
    reason_code: str = _CHECK_UNAVAILABLE_REASON,
    observation: _MarketPriceObservation | None = None,
) -> TakeProfitCheckOutput:
    """Build an unavailable take-profit result without synthetic financial values."""

    return TakeProfitCheckOutput(
        position_id=position_id,
        asset_code=asset_code,
        triggered=False,
        check_status="unavailable",
        execution_status="not_triggered",
        reason_code=reason_code,
        check_result=None,
        current_price=observation.price if observation is not None else None,
        unrealized_pnl=None,
        unrealized_pnl_pct=None,
        price_source=observation.source if observation is not None else None,
        price_observed_at=observation.observed_at if observation is not None else None,
        price_freshness=observation.freshness if observation is not None else None,
        must_not_use_for_decision=True,
        must_not_execute=True,
    )


class AutoStopLossUseCase:
    """Observe stop-loss conditions and block unqualified legacy automatic exits."""

    def __init__(
        self,
        market_data_service: MarketPriceServiceProtocol | None = None,
        stop_loss_repo: StopLossRepositoryProtocol | None = None,
        risk_policy_provider: RiskPolicyProviderProtocol | None = None,
    ) -> None:
        """Initialize the read/evaluation path and its monotonic peak observer."""

        self.market_data_service = market_data_service or MarketPriceService()
        self.stop_loss_repo = stop_loss_repo or StopLossRepository()
        self.risk_policy_provider = risk_policy_provider or _RiskCenterPolicyProvider()

    def check_and_execute_stop_loss(self, user_id: int | None = None) -> list[StopLossCheckOutput]:
        """Evaluate every active rule and report trigger intent without legacy settlement."""

        if not is_valid_exit_user_id(user_id):
            raise ValueError("invalid_exit_user_id")
        active_configs = self.stop_loss_repo.get_active_stop_loss_configs(user_id=user_id)
        return [self._check_single_position(config) for config in active_configs]

    def _check_single_position(self, config: dict[str, Any]) -> StopLossCheckOutput:
        """Evaluate one stop-loss rule, preserving missing market values as unavailable."""

        fields = _position_fields(config)
        if fields is None:
            logger.warning("Stop-loss check skipped malformed legacy position context")
            position_id, asset_code = _position_identity(config)
            return _unavailable_stop_loss(position_id=position_id, asset_code=asset_code)
        position_id, asset_code, entry_price, shares, portfolio_id = fields
        evaluation_time = datetime.now(UTC)
        observation = self._get_price_observation(asset_code, evaluation_time=evaluation_time)
        if observation is None:
            logger.warning("Stop-loss price unavailable for asset %s", asset_code)
            return _unavailable_stop_loss(
                position_id=position_id,
                asset_code=asset_code,
                reason_code="market_price_unavailable",
            )
        current_price = observation.price

        stop_type_value: object = config.get("stop_loss_type")
        stop_type = stop_type_value if isinstance(stop_type_value, str) else ""
        stop_loss_pct = self._resolve_stop_loss_pct(config, portfolio_id)
        if stop_loss_pct is None:
            return _unavailable_stop_loss(
                position_id=position_id,
                asset_code=asset_code,
                reason_code="stop_loss_configuration_unavailable",
                observation=observation,
            )
        position_payload_value: object = config.get("position")
        if not isinstance(position_payload_value, dict):
            return _unavailable_stop_loss(
                position_id=position_id,
                asset_code=asset_code,
                reason_code="stop_loss_configuration_unavailable",
                observation=observation,
            )
        position_payload = cast(dict[str, Any], position_payload_value)
        average_cost = _decimal_value(position_payload.get("avg_cost"))
        stored_high_value: object = config.get("highest_price")
        stored_highest = None if stored_high_value is None else _decimal_value(stored_high_value)
        if (
            average_cost is None
            or average_cost <= 0
            or (stored_high_value is not None and stored_highest is None)
        ):
            return _unavailable_stop_loss(
                position_id=position_id,
                asset_code=asset_code,
                reason_code="stop_loss_configuration_unavailable",
                observation=observation,
            )
        peak_baseline = stored_highest if stored_highest is not None else average_cost
        highest_price = safe_float(peak_baseline)
        if highest_price is None or highest_price <= 0:
            return _unavailable_stop_loss(
                position_id=position_id,
                asset_code=asset_code,
                reason_code="stop_loss_configuration_unavailable",
                observation=observation,
            )
        expected_peak_time_value: object = config.get("highest_price_updated_at")
        expected_peak_time = (
            expected_peak_time_value if isinstance(expected_peak_time_value, datetime) else None
        )
        if expected_peak_time_value is not None and (
            expected_peak_time is None or expected_peak_time.tzinfo is None
        ):
            return _unavailable_stop_loss(
                position_id=position_id,
                asset_code=asset_code,
                reason_code="stop_loss_configuration_unavailable",
                observation=observation,
            )
        if (
            stop_type == "trailing"
            and expected_peak_time is not None
            and observation.observed_at < expected_peak_time
        ):
            return _unavailable_stop_loss(
                position_id=position_id,
                asset_code=asset_code,
                reason_code="stop_loss_source_time_regressed",
                observation=observation,
            )

        try:
            if stop_type in {"fixed", "trailing"}:
                trailing_pct = safe_float(config.get("trailing_stop_pct"))
                check_result = StopLossService.check_stop_loss(
                    entry_price=entry_price,
                    current_price=current_price,
                    highest_price=highest_price,
                    stop_loss_pct=stop_loss_pct,
                    stop_loss_type=stop_type,
                    trailing_stop_pct=trailing_pct,
                )
            elif stop_type == "time_based":
                position = cast(dict[str, Any], config["position"])
                opened_at_value: object = position.get("opened_at")
                max_holding_days = _positive_integer(config.get("max_holding_days"))
                if (
                    not isinstance(opened_at_value, datetime)
                    or opened_at_value.tzinfo is None
                    or opened_at_value.utcoffset() is None
                    or max_holding_days is None
                ):
                    return _unavailable_stop_loss(
                        position_id=position_id,
                        asset_code=asset_code,
                        reason_code="stop_loss_configuration_unavailable",
                        observation=observation,
                    )
                check_result = StopLossService.check_time_stop_loss(
                    opened_at=opened_at_value,
                    current_time=evaluation_time,
                    max_holding_days=max_holding_days,
                )
            else:
                return _unavailable_stop_loss(
                    position_id=position_id,
                    asset_code=asset_code,
                    reason_code="stop_loss_configuration_unavailable",
                    observation=observation,
                )
        except (TypeError, ValueError, ArithmeticError) as exc:
            logger.warning("Stop-loss rule unavailable: error_type=%s", type(exc).__name__)
            return _unavailable_stop_loss(
                position_id=position_id,
                asset_code=asset_code,
                reason_code="stop_loss_configuration_unavailable",
                observation=observation,
            )

        if stop_type == "trailing":
            if observation.exact_price > peak_baseline:
                exact_price_for_storage = _stop_price_for_storage(observation.exact_price)
                if exact_price_for_storage is None:
                    return _unavailable_stop_loss(
                        position_id=position_id,
                        asset_code=asset_code,
                        reason_code="stop_loss_peak_price_precision_unsupported",
                        observation=observation,
                    )
                config_id = _positive_integer(config.get("id"))
                portfolio_id = _positive_integer(position_payload.get("portfolio_id"))
                owner_user_id = _positive_integer(position_payload.get("user_id"))
                position_shares = safe_float(position_payload.get("shares"))
                stop_loss_pct_value = safe_float(config.get("stop_loss_pct"))
                trailing_pct_value: object = config.get("trailing_stop_pct")
                trailing_stop_pct = (
                    None if trailing_pct_value is None else safe_float(trailing_pct_value)
                )
                max_holding_value: object = config.get("max_holding_days")
                max_holding_days = max_holding_value if type(max_holding_value) is int else None
                config_updated_value: object = config.get("updated_at")
                if (
                    config_id is None
                    or portfolio_id is None
                    or owner_user_id is None
                    or position_shares is None
                    or position_shares <= 0
                    or stop_loss_pct_value is None
                    or (trailing_pct_value is not None and trailing_stop_pct is None)
                    or (max_holding_value is not None and max_holding_days is None)
                    or not isinstance(config_updated_value, datetime)
                    or config_updated_value.tzinfo is None
                    or not isinstance(average_cost, Decimal)
                    or (stored_high_value is not None and not isinstance(stored_highest, Decimal))
                ):
                    return _unavailable_stop_loss(
                        position_id=position_id,
                        asset_code=asset_code,
                        reason_code="stop_loss_configuration_unavailable",
                        observation=observation,
                    )
                peak_observation = StopLossPeakObservation(
                    config_id=config_id,
                    position_id=position_id,
                    portfolio_id=portfolio_id,
                    owner_user_id=owner_user_id,
                    asset_code=asset_code,
                    position_shares=position_shares,
                    average_cost=average_cost,
                    stop_loss_pct=stop_loss_pct_value,
                    trailing_stop_pct=trailing_stop_pct,
                    max_holding_days=max_holding_days,
                    config_updated_at=config_updated_value,
                    expected_highest_price=stored_highest,
                    expected_highest_price_updated_at=expected_peak_time,
                    exact_price=exact_price_for_storage,
                    observed_at=observation.observed_at,
                )
                if (
                    self.stop_loss_repo.record_trailing_stop_peak_observation(peak_observation)
                    is not True
                ):
                    return _unavailable_stop_loss(
                        position_id=position_id,
                        asset_code=asset_code,
                        reason_code="stop_loss_peak_observation_changed",
                        observation=observation,
                    )
                config["highest_price"] = exact_price_for_storage
                config["highest_price_updated_at"] = observation.observed_at

        unrealized_pnl, unrealized_pnl_pct = calculate_observed_unrealized_pnl(
            entry_price, shares, current_price
        )
        triggered = check_result.should_trigger
        return StopLossCheckOutput(
            position_id=position_id,
            asset_code=asset_code,
            triggered=triggered,
            check_status="evaluated",
            execution_status="blocked" if triggered else "not_triggered",
            reason_code=_LEGACY_EXIT_BLOCKED_REASON if triggered else None,
            check_result=check_result,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            price_source=observation.source,
            price_observed_at=observation.observed_at,
            price_freshness=observation.freshness,
            must_not_use_for_decision=True,
            must_not_execute=True,
        )

    def _resolve_stop_loss_pct(
        self, config: dict[str, Any], portfolio_id: int | None
    ) -> float | None:
        """Resolve the configured stop bound, retaining the existing policy fallback."""

        configured_pct = safe_float(config.get("stop_loss_pct"))
        if configured_pct is None or configured_pct < 0 or configured_pct > 1:
            return None
        if portfolio_id is None:
            return configured_pct
        try:
            parameters = self.risk_policy_provider.get_effective_parameters(portfolio_id)
        except Exception as exc:
            logger.warning("Risk policy lookup failed; configured stop bound retained: %s", exc)
            return configured_pct
        if not isinstance(parameters, dict):
            return configured_pct
        maximum = safe_float(parameters.get("max_stop_loss_pct"))
        if maximum is None:
            return configured_pct
        if maximum < 0 or maximum > 1:
            return None
        return min(configured_pct, maximum)

    def _get_price_observation(
        self,
        asset_code: str,
        *,
        evaluation_time: datetime,
    ) -> _MarketPriceObservation | None:
        """Read one source observation without discarding its provenance."""

        return _read_realtime_price_observation(
            self.market_data_service,
            asset_code,
            evaluation_time,
        )


class AutoTakeProfitUseCase:
    """Observe take-profit conditions and block unqualified legacy automatic exits."""

    def __init__(
        self,
        market_data_service: MarketPriceServiceProtocol | None = None,
        take_profit_repo: TakeProfitRepositoryProtocol | None = None,
        risk_policy_provider: RiskPolicyProviderProtocol | None = None,
    ) -> None:
        """Initialize the read/evaluation path without a legacy SELL writer."""

        self.market_data_service = market_data_service or MarketPriceService()
        self.take_profit_repo = take_profit_repo or TakeProfitRepository()
        self.risk_policy_provider = risk_policy_provider or _RiskCenterPolicyProvider()

    def check_and_execute_take_profit(
        self, user_id: int | None = None
    ) -> list[TakeProfitCheckOutput]:
        """Evaluate every active rule and report trigger intent without consuming levels."""

        if not is_valid_exit_user_id(user_id):
            raise ValueError("invalid_exit_user_id")
        active_configs = self.take_profit_repo.get_active_take_profit_configs(user_id=user_id)
        return [self._check_single_position(config) for config in active_configs]

    def _check_single_position(self, config: dict[str, Any]) -> TakeProfitCheckOutput:
        """Evaluate one take-profit rule, preserving missing market values as unavailable."""

        fields = _position_fields(config)
        if fields is None:
            logger.warning("Take-profit check skipped malformed legacy position context")
            position_id, asset_code = _position_identity(config)
            return _unavailable_take_profit(position_id=position_id, asset_code=asset_code)
        position_id, asset_code, entry_price, shares, portfolio_id = fields
        evaluation_time = datetime.now(UTC)
        observation = self._get_price_observation(asset_code, evaluation_time=evaluation_time)
        if observation is None:
            logger.warning("Take-profit price unavailable for asset %s", asset_code)
            return _unavailable_take_profit(
                position_id=position_id,
                asset_code=asset_code,
                reason_code="market_price_unavailable",
            )
        current_price = observation.price
        take_profit_pct = self._resolve_take_profit_pct(config, portfolio_id)
        if take_profit_pct is None:
            return _unavailable_take_profit(
                position_id=position_id,
                asset_code=asset_code,
                reason_code="take_profit_configuration_unavailable",
                observation=observation,
            )
        levels_value: object = config.get("partial_profit_levels")
        partial_levels: list[float] | None = None
        if levels_value is not None:
            if not isinstance(levels_value, list):
                return _unavailable_take_profit(
                    position_id=position_id,
                    asset_code=asset_code,
                    reason_code="take_profit_configuration_unavailable",
                    observation=observation,
                )
            partial_levels = []
            for level_value in levels_value:
                level = safe_float(level_value)
                if level is None or level < 0 or level > 1:
                    return _unavailable_take_profit(
                        position_id=position_id,
                        asset_code=asset_code,
                        reason_code="take_profit_configuration_unavailable",
                        observation=observation,
                    )
                partial_levels.append(level)

        try:
            check_result = TakeProfitService.check_take_profit(
                entry_price=entry_price,
                current_price=current_price,
                take_profit_pct=take_profit_pct,
                partial_levels=partial_levels,
            )
        except (TypeError, ValueError, ArithmeticError) as exc:
            logger.warning("Take-profit rule unavailable: error_type=%s", type(exc).__name__)
            return _unavailable_take_profit(
                position_id=position_id,
                asset_code=asset_code,
                reason_code="take_profit_configuration_unavailable",
                observation=observation,
            )
        unrealized_pnl, unrealized_pnl_pct = calculate_observed_unrealized_pnl(
            entry_price, shares, current_price
        )
        triggered = check_result.should_trigger
        return TakeProfitCheckOutput(
            position_id=position_id,
            asset_code=asset_code,
            triggered=triggered,
            check_status="evaluated",
            execution_status="blocked" if triggered else "not_triggered",
            reason_code=_LEGACY_EXIT_BLOCKED_REASON if triggered else None,
            check_result=check_result,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            partial_level=check_result.partial_level,
            price_source=observation.source,
            price_observed_at=observation.observed_at,
            price_freshness=observation.freshness,
            must_not_use_for_decision=True,
            must_not_execute=True,
        )

    def _resolve_take_profit_pct(
        self, config: dict[str, Any], portfolio_id: int | None
    ) -> float | None:
        """Resolve the configured take bound, retaining the existing policy fallback."""

        configured_pct = safe_float(config.get("take_profit_pct"))
        if configured_pct is None or configured_pct < 0 or configured_pct > 1:
            return None
        if portfolio_id is None:
            return configured_pct
        try:
            parameters = self.risk_policy_provider.get_effective_parameters(portfolio_id)
        except Exception as exc:
            logger.warning("Risk policy lookup failed; configured take bound retained: %s", exc)
            return configured_pct
        if not isinstance(parameters, dict):
            return configured_pct
        policy_pct = safe_float(parameters.get("take_profit_pct"))
        if policy_pct is None:
            return configured_pct
        if policy_pct < 0 or policy_pct > 1:
            return None
        return min(configured_pct, policy_pct)

    def _get_price_observation(
        self,
        asset_code: str,
        *,
        evaluation_time: datetime,
    ) -> _MarketPriceObservation | None:
        """Read one source observation without discarding its provenance."""

        return _read_realtime_price_observation(
            self.market_data_service,
            asset_code,
            evaluation_time,
        )


class CreateStopLossConfigUseCase:
    """
    创建止损配置用例
    """

    def __init__(
        self,
        position_repo: PositionRepositoryProtocol | None = None,
        stop_loss_repo: StopLossRepositoryProtocol | None = None,
    ) -> None:
        self.position_repo = position_repo or PositionRepository()
        self.stop_loss_repo = stop_loss_repo or StopLossRepository()

    def execute(
        self,
        position_id: int,
        stop_loss_type: str,
        stop_loss_pct: float,
        trailing_stop_pct: float | None = None,
        max_holding_days: int | None = None,
    ) -> dict[str, Any]:
        """
        创建止损配置

        Args:
            position_id: 持仓ID
            stop_loss_type: 止损类型 (fixed/trailing/time_based)
            stop_loss_pct: 止损百分比
            trailing_stop_pct: 移动止损百分比
            max_holding_days: 最大持仓天数

        Returns:
            dict: 创建的止损配置
        """
        # 获取持仓
        position = self.position_repo.get_position_stop_management_context(position_id)
        if position is None:
            raise ValueError(f"持仓 {position_id} 不存在")

        # 检查是否已有止损配置
        if self.stop_loss_repo.get_stop_loss_config_by_position(position_id):
            raise ValueError(f"持仓 {position_id} 已有止损配置")

        # 创建止损配置
        config = self.stop_loss_repo.create_stop_loss_config(
            position_id=position_id,
            stop_loss_type=stop_loss_type,
            stop_loss_pct=stop_loss_pct,
            trailing_stop_pct=trailing_stop_pct,
            max_holding_days=max_holding_days,
            highest_price=position["avg_cost"],  # 初始最高价为开仓价
        )

        return config


class CreateTakeProfitConfigUseCase:
    """
    创建止盈配置用例
    """

    def __init__(
        self,
        position_repo: PositionRepositoryProtocol | None = None,
        take_profit_repo: TakeProfitRepositoryProtocol | None = None,
    ) -> None:
        self.position_repo = position_repo or PositionRepository()
        self.take_profit_repo = take_profit_repo or TakeProfitRepository()

    def execute(
        self,
        position_id: int,
        take_profit_pct: float,
        partial_profit_levels: list[float] | None = None,
    ) -> dict[str, Any]:
        """
        创建止盈配置

        Args:
            position_id: 持仓ID
            take_profit_pct: 止盈百分比
            partial_profit_levels: 分批止盈点位

        Returns:
            dict: 创建的止盈配置
        """
        # 获取持仓
        position = self.position_repo.get_position_stop_management_context(position_id)
        if position is None:
            raise ValueError(f"持仓 {position_id} 不存在")

        # 检查是否已有止盈配置
        if self.take_profit_repo.get_take_profit_config_by_position(position_id):
            raise ValueError(f"持仓 {position_id} 已有止盈配置")

        # 创建止盈配置
        config = self.take_profit_repo.create_take_profit_config(
            position_id=position_id,
            take_profit_pct=take_profit_pct,
            partial_profit_levels=partial_profit_levels,
        )

        return config
