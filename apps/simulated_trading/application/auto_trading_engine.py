"""
自动交易引擎

Application层核心组件：
- 每日定时运行(Celery Beat)
- 自动扫描账户、生成订单、更新持仓
- 依赖Use Cases和Domain层服务
- 集成策略系统（Phase 5）
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Protocol

from apps.risk_center.application.trade_guard import (
    EvaluatePreTradeRiskUseCase,
    PreTradeRiskCheckResult,
)
from apps.simulated_trading.application.auto_trading_exit_evaluator import (
    AutoTradingExitEvaluator,
)
from apps.simulated_trading.application.ports import (
    AssetPoolServiceProtocol as AssetPoolServiceProtocol,
)
from apps.simulated_trading.application.ports import (
    AutoTradingTradeRepositoryProtocol as AutoTradingTradeRepositoryProtocol,
)
from apps.simulated_trading.application.ports import (
    ExecutionLinkRecorderProtocol,
    PositionExitAdvice,
    PositionExitAdvisorProtocol,
)
from apps.simulated_trading.application.ports import PriceProviderProtocol as PriceProviderProtocol
from apps.simulated_trading.application.ports import RegimeServiceProtocol as RegimeServiceProtocol
from apps.simulated_trading.application.ports import SignalServiceProtocol as SignalServiceProtocol
from apps.simulated_trading.application.use_cases import (
    ExecuteBuyOrderUseCase,
    ExecuteSellOrderUseCase,
    GetAccountPerformanceUseCase,
    PositionRepositoryProtocol,
    SimulatedAccountRepositoryProtocol,
)
from apps.simulated_trading.domain.auto_trading_outcomes import (
    AccountAutoTradingOutcome,
    AutoTradingIssue,
    AutoTradingIssueKind,
    build_account_auto_trading_outcome,
)
from apps.simulated_trading.domain.entities import (
    AccountType,
    Position,
    SimulatedAccount,
    SimulatedTrade,
)
from apps.simulated_trading.domain.rules import PositionSizingRule
from shared.numeric import safe_float

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from apps.strategy.application.strategy_executor import StrategyExecutor


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


@dataclass(slots=True)
class _AccountOutcomeState:
    """Collect confirmed trades and stable issues for one account run."""

    account_id: int
    buy_count: int = 0
    sell_count: int = 0
    issues: list[AutoTradingIssue] = field(default_factory=list)

    def add_issue(
        self,
        *,
        kind: AutoTradingIssueKind,
        stage: str,
        code: str,
        asset_code: str | None = None,
        effects_indeterminate: bool = False,
    ) -> None:
        """Add one stable issue without exception text."""

        self.issues.append(
            AutoTradingIssue(
                kind=kind,
                stage=stage,
                code=code,
                asset_code=asset_code,
                effects_indeterminate=effects_indeterminate,
            )
        )

    def confirm_trade(self, action: str) -> None:
        """Count a use-case return immediately as a confirmed trade."""

        if action == "buy":
            self.buy_count += 1
        elif action == "sell":
            self.sell_count += 1
        else:
            raise ValueError("action must be buy or sell")

    def build(self) -> AccountAutoTradingOutcome:
        """Build the immutable account outcome accumulated so far."""

        return build_account_auto_trading_outcome(
            self.account_id,
            buy_count=self.buy_count,
            sell_count=self.sell_count,
            issues=tuple(self.issues),
        )


class AutoTradingEngine:
    """
    自动交易引擎

    核心流程:
    1. 扫描所有活跃模拟账户
    2. 检查持仓是否需要卖出
    3. 从可投池+信号获取买入候选
    4. 执行买入/卖出订单
    5. 更新账户绩效

    Phase 5 更新：
    - 支持策略系统集成
    - 如果账户绑定了策略，使用策略执行引擎
    - 如果账户未绑定策略，使用原有逻辑（向后兼容）
    """

    def __init__(
        self,
        account_repo: SimulatedAccountRepositoryProtocol,
        position_repo: PositionRepositoryProtocol,
        trade_repo: AutoTradingTradeRepositoryProtocol,
        buy_use_case: ExecuteBuyOrderUseCase,
        sell_use_case: ExecuteSellOrderUseCase,
        performance_use_case: GetAccountPerformanceUseCase,
        asset_pool_service: AssetPoolServiceProtocol | None = None,
        signal_service: SignalServiceProtocol | None = None,
        price_provider: PriceProviderProtocol | None = None,
        regime_service: RegimeServiceProtocol | None = None,
        exit_advisor: PositionExitAdvisorProtocol | None = None,
        execution_link_recorder: ExecutionLinkRecorderProtocol | None = None,
        strategy_executor: "StrategyExecutor | None" = None,
        pre_trade_risk_guard: PreTradeRiskGuardProtocol | None = None,
    ) -> None:
        self.account_repo = account_repo
        self.position_repo = position_repo
        self.trade_repo = trade_repo
        self.buy_use_case = buy_use_case
        self.sell_use_case = sell_use_case
        self.performance_use_case = performance_use_case
        self.asset_pool_service = asset_pool_service
        self.signal_service = signal_service
        self.price_provider = price_provider
        self.regime_service = regime_service
        self.exit_advisor = exit_advisor
        self.execution_link_recorder = execution_link_recorder
        self.strategy_executor = strategy_executor  # Phase 5: 策略执行引擎
        self._exit_evaluator = AutoTradingExitEvaluator()
        self.pre_trade_risk_guard = (
            pre_trade_risk_guard
            if pre_trade_risk_guard is not None
            else EvaluatePreTradeRiskUseCase()
        )

    def run_daily_trading(
        self,
        trade_date: date,
        account_ids: list[int] | None = None,
    ) -> dict[int, AccountAutoTradingOutcome]:
        """Execute the daily automatic-trading cycle for selected active accounts.

        Args:
            trade_date: 交易日期
            account_ids: 指定账户ID列表，None表示全部活跃账户

        Returns:
            A typed outcome for each active account considered by the cycle.
        """
        logger.info("=" * 60)
        logger.info(f"开始执行模拟盘自动交易: {trade_date}")
        logger.info("=" * 60)

        # 1. 获取所有活跃的模拟账户
        accounts = self.account_repo.get_active_accounts()
        if account_ids is not None:
            allowed_ids = {int(account_id) for account_id in account_ids}
            accounts = [account for account in accounts if account.account_id in allowed_ids]
        logger.info(f"找到 {len(accounts)} 个活跃模拟账户")

        results: dict[int, AccountAutoTradingOutcome] = {}
        for account in accounts:
            if account.account_type is not AccountType.SIMULATED:
                logger.warning(
                    "阻断非模拟账户自动交易: account_id=%s",
                    account.account_id,
                )
                results[account.account_id] = self._unsupported_account_type_outcome(
                    account.account_id
                )
                continue
            if not account.auto_trading_enabled:
                logger.info(
                    f"账户 {account.account_name} (ID={account.account_id}) 未启用自动交易,跳过"
                )
                state = _AccountOutcomeState(account_id=account.account_id)
                state.add_issue(
                    kind=AutoTradingIssueKind.BLOCKED,
                    stage="account",
                    code="AUTO_TRADING_DISABLED",
                )
                results[account.account_id] = state.build()
                continue

            try:
                results[account.account_id] = self._process_account(account, trade_date)
            except Exception:
                logger.error(
                    "账户自动交易处理异常: account_id=%s",
                    account.account_id,
                    exc_info=True,
                )
                results[account.account_id] = build_account_auto_trading_outcome(
                    account.account_id,
                    buy_count=0,
                    sell_count=0,
                    issues=(
                        AutoTradingIssue(
                            AutoTradingIssueKind.FAILED,
                            "account_processing",
                            "ACCOUNT_PROCESSING_FAILED",
                            effects_indeterminate=True,
                        ),
                    ),
                )

        logger.info("=" * 60)
        logger.info(f"模拟盘自动交易完成: {results}")
        logger.info("=" * 60)

        return results

    @staticmethod
    def _unsupported_account_type_outcome(account_id: int) -> AccountAutoTradingOutcome:
        """Build a stable blocked result for non-simulated or unknown accounts."""

        return build_account_auto_trading_outcome(
            account_id,
            buy_count=0,
            sell_count=0,
            issues=(
                AutoTradingIssue(
                    AutoTradingIssueKind.BLOCKED,
                    "account",
                    "AUTO_TRADING_ACCOUNT_TYPE_UNSUPPORTED",
                ),
            ),
        )

    def _process_account(
        self, account: SimulatedAccount, trade_date: date
    ) -> AccountAutoTradingOutcome:
        """Process one account and preserve errors as a typed outcome.

        Phase 5 更新：
        - 检查账户是否绑定了策略
        - 如果有策略，使用策略执行引擎
        - 如果没有策略，使用原有逻辑（向后兼容）
        """
        if account.account_type is not AccountType.SIMULATED:
            return self._unsupported_account_type_outcome(account.account_id)

        state = _AccountOutcomeState(account_id=account.account_id)
        logger.info(f"\n处理账户: {account.account_name} (ID={account.account_id})")
        logger.info(
            f"  当前资金: {account.current_cash:.2f}元, 持仓市值: {account.current_market_value:.2f}元"
        )

        # Phase 5: 检查是否绑定了策略
        try:
            active_strategy_id = self._get_account_strategy_id(account.account_id)
        except Exception:
            logger.warning(
                "获取账户策略绑定失败，阻断本次账户自动交易: account_id=%s", account.account_id
            )
            state.add_issue(
                kind=AutoTradingIssueKind.BLOCKED,
                stage="strategy_binding",
                code="STRATEGY_BINDING_UNAVAILABLE",
            )
            return state.build()

        try:
            if active_strategy_id is not None:
                logger.info(f"  账户绑定策略ID: {active_strategy_id}, 使用策略执行网关")
                return self._execute_strategy_based_trading(
                    account, active_strategy_id, trade_date, state
                )
            logger.info("  账户未绑定策略，使用原有逻辑")
            return self._execute_legacy_trading(account, trade_date, state)
        except Exception:
            logger.error("账户自动交易处理异常: account_id=%s", account.account_id, exc_info=True)
            state.add_issue(
                kind=AutoTradingIssueKind.FAILED,
                stage="account_processing",
                code="ACCOUNT_PROCESSING_FAILED",
            )
            return state.build()

    def _get_account_strategy_id(self, account_id: int) -> int | None:
        """
        获取账户绑定的策略ID

        重构说明 (2026-03-11):
        - 使用 SimulatedTradingFacade 替代直接 ORM 导入
        - 保持 API 兼容

        Args:
            account_id: 账户ID

        Returns:
            策略ID，如果未绑定则返回 None
        """
        from apps.simulated_trading.application.facade import get_simulated_trading_facade

        facade = get_simulated_trading_facade()
        strategy_id = facade.get_active_strategy_id(account_id)
        if strategy_id is None:
            return None
        if type(strategy_id) is not int or strategy_id <= 0:
            raise ValueError("strategy binding reader returned an invalid strategy ID")
        return strategy_id

    def _execute_strategy_based_trading(
        self,
        account: SimulatedAccount,
        strategy_id: int,
        trade_date: date,
        state: _AccountOutcomeState | None = None,
    ) -> AccountAutoTradingOutcome:
        """
        使用策略执行引擎进行交易

        重构说明 (2026-03-11):
        - 使用 StrategyExecutionGateway 替代直接导入 StrategyExecutor
        - 保持 API 兼容

        Args:
            account: 账户实体
            strategy_id: 策略ID
            trade_date: 交易日期

        """
        execution_state = state or _AccountOutcomeState(account_id=account.account_id)
        try:
            # 1. 执行策略，获取信号推荐 - 使用 Gateway 模式
            from apps.strategy.application.execution_gateway import get_strategy_execution_gateway

            gateway = get_strategy_execution_gateway()
            execution_result = gateway.execute_for_account(
                strategy_id=strategy_id, account_id=account.account_id, as_of_date=trade_date
            )
        except Exception:
            logger.warning("策略执行网关失败: account_id=%s", account.account_id)
            execution_state.add_issue(
                kind=AutoTradingIssueKind.FAILED,
                stage="strategy_execution",
                code="STRATEGY_EXECUTION_FAILED",
            )
            return execution_state.build()

        if not execution_result.success:
            execution_state.add_issue(
                kind=AutoTradingIssueKind.FAILED,
                stage="strategy_execution",
                code="STRATEGY_EXECUTION_FAILED",
            )
            return execution_state.build()

        try:
            signals = execution_result.signals
            positions = self.position_repo.get_by_account(account.account_id)
        except Exception:
            execution_state.add_issue(
                kind=AutoTradingIssueKind.FAILED,
                stage="strategy_signals",
                code="STRATEGY_SIGNAL_READ_FAILED",
            )
            return execution_state.build()
        held_positions = {position.asset_code: position for position in positions}
        held_codes = set(held_positions)

        for signal in signals:
            if signal.action != "sell":
                continue
            asset_code = signal.asset_code
            position = held_positions.get(asset_code)
            if position is None:
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.BLOCKED,
                    stage="sell_signal",
                    code="SELL_POSITION_NOT_FOUND",
                    asset_code=asset_code,
                )
                continue
            if position.available_quantity_known is not True:
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.BLOCKED,
                    stage="sell_signal",
                    code="SELLABLE_BALANCE_UNKNOWN",
                    asset_code=asset_code,
                )
                continue
            try:
                price = self._get_current_price(asset_code, trade_date)
            except Exception:
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.FAILED,
                    stage="price",
                    code="SELL_PRICE_READ_FAILED",
                    asset_code=asset_code,
                )
                continue
            if price is None:
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.BLOCKED,
                    stage="price",
                    code="SELL_PRICE_UNAVAILABLE",
                    asset_code=asset_code,
                )
                continue
            if not self._is_price_triggered(
                action="sell", price=price, payload=getattr(signal, "metadata", {}) or {}
            ):
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.BLOCKED,
                    stage="sell_signal",
                    code="SELL_PRICE_NOT_TRIGGERED",
                    asset_code=asset_code,
                )
                continue
            sell_quantity = int(
                signal.quantity if signal.quantity is not None else position.quantity
            )
            if sell_quantity <= 0:
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.BLOCKED,
                    stage="sell_signal",
                    code="SELL_QUANTITY_INVALID",
                    asset_code=asset_code,
                )
                continue
            try:
                trade = self.sell_use_case.execute(
                    account_id=account.account_id,
                    asset_code=asset_code,
                    quantity=sell_quantity,
                    price=price,
                    reason=f"策略信号: {signal.reason}",
                    execution_date=trade_date,
                )
            except Exception:
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.FAILED,
                    stage="sell_execution",
                    code="SELL_EXECUTION_OUTCOME_UNKNOWN",
                    asset_code=asset_code,
                    effects_indeterminate=True,
                )
                continue
            execution_state.confirm_trade("sell")
            self._record_confirmed_execution_link(
                execution_state,
                trade=trade,
                account_id=account.account_id,
                asset_code=asset_code,
                action="sell",
                recommendation_id=None,
                match_if_missing=True,
                notes="Auto strategy sell",
            )

        for signal in signals:
            if signal.action != "buy":
                continue
            asset_code = signal.asset_code
            if asset_code in held_codes:
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.BLOCKED,
                    stage="buy_signal",
                    code="BUY_POSITION_ALREADY_HELD",
                    asset_code=asset_code,
                )
                continue
            self._execute_strategy_buy_signal(account, signal, trade_date, execution_state)

        self._record_performance_outcome(account.account_id, trade_date, execution_state)
        return execution_state.build()

    def _execute_strategy_buy_signal(
        self,
        account: SimulatedAccount,
        signal: object,
        trade_date: date,
        state: _AccountOutcomeState,
    ) -> None:
        """Execute one strategy buy signal and append any stable failure issue."""

        asset_code = getattr(signal, "asset_code", None)
        if not isinstance(asset_code, str) or not asset_code:
            state.add_issue(
                kind=AutoTradingIssueKind.BLOCKED,
                stage="buy_signal",
                code="BUY_SIGNAL_INVALID",
            )
            return
        try:
            price = self._get_current_price(asset_code, trade_date)
        except Exception:
            state.add_issue(
                kind=AutoTradingIssueKind.FAILED,
                stage="price",
                code="BUY_PRICE_READ_FAILED",
                asset_code=asset_code,
            )
            return
        if price is None:
            state.add_issue(
                kind=AutoTradingIssueKind.BLOCKED,
                stage="price",
                code="BUY_PRICE_UNAVAILABLE",
                asset_code=asset_code,
            )
            return
        metadata = getattr(signal, "metadata", {}) or {}
        if not self._is_price_triggered(action="buy", price=price, payload=metadata):
            state.add_issue(
                kind=AutoTradingIssueKind.BLOCKED,
                stage="buy_signal",
                code="BUY_PRICE_NOT_TRIGGERED",
                asset_code=asset_code,
            )
            return
        try:
            buy_quantity = getattr(signal, "quantity", None)
            if buy_quantity is None:
                positions = self.position_repo.get_by_account(account.account_id)
                buy_quantity = PositionSizingRule.calculate_buy_quantity(
                    account=account,
                    asset_price=price,
                    asset_score=float(getattr(signal, "confidence", 0.0)) * 100,
                    existing_positions=positions,
                )
        except Exception:
            state.add_issue(
                kind=AutoTradingIssueKind.FAILED,
                stage="buy_sizing",
                code="BUY_QUANTITY_CALCULATION_FAILED",
                asset_code=asset_code,
            )
            return
        if type(buy_quantity) is not int or buy_quantity <= 0:
            state.add_issue(
                kind=AutoTradingIssueKind.BLOCKED,
                stage="buy_signal",
                code="BUY_QUANTITY_INVALID",
                asset_code=asset_code,
            )
            return
        risk_issue = self._buy_risk_issue(
            account=account,
            asset_code=asset_code,
            quantity=buy_quantity,
            price=price,
        )
        if risk_issue is not None:
            state.issues.append(risk_issue)
            return
        try:
            trade = self.buy_use_case.execute(
                account_id=account.account_id,
                asset_code=asset_code,
                asset_name=str(getattr(signal, "asset_name", asset_code)),
                asset_type="equity",
                quantity=buy_quantity,
                price=price,
                reason="策略信号",
                signal_id=getattr(signal, "signal_id", None),
                execution_date=trade_date,
            )
        except Exception:
            state.add_issue(
                kind=AutoTradingIssueKind.FAILED,
                stage="buy_execution",
                code="BUY_EXECUTION_OUTCOME_UNKNOWN",
                asset_code=asset_code,
                effects_indeterminate=True,
            )
            return
        state.confirm_trade("buy")
        self._record_confirmed_execution_link(
            state,
            trade=trade,
            account_id=account.account_id,
            asset_code=asset_code,
            action="buy",
            recommendation_id=None,
            match_if_missing=True,
            notes="Auto strategy buy",
        )

    def _execute_legacy_trading(
        self,
        account: SimulatedAccount,
        trade_date: date,
        state: _AccountOutcomeState | None = None,
    ) -> AccountAutoTradingOutcome:
        """Run legacy sell/buy checks while recording confirmed results and issues."""
        execution_state = state or _AccountOutcomeState(account_id=account.account_id)
        try:
            positions = self.position_repo.get_by_account(account.account_id)
        except Exception:
            execution_state.add_issue(
                kind=AutoTradingIssueKind.FAILED,
                stage="position_read",
                code="ACCOUNT_POSITION_READ_FAILED",
            )
            self._record_performance_outcome(account.account_id, trade_date, execution_state)
            return execution_state.build()

        logger.info("  当前持仓: %s 个", len(positions))
        advisor_map = self._build_exit_advice_map(
            account.account_id, positions, trade_date, execution_state
        )

        for position in positions:
            try:
                exit_advice = self._get_position_exit_advice(
                    position=position,
                    account=account,
                    trade_date=trade_date,
                    advisor_map=advisor_map,
                )
            except Exception:
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.FAILED,
                    stage="position_exit_check",
                    code="POSITION_EXIT_CHECK_FAILED",
                    asset_code=position.asset_code,
                )
                continue
            if not exit_advice or not (exit_advice.should_exit or exit_advice.should_reduce):
                continue
            if position.available_quantity_known is not True:
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.BLOCKED,
                    stage="sell_signal",
                    code="SELLABLE_BALANCE_UNKNOWN",
                    asset_code=position.asset_code,
                )
                continue
            try:
                price = self._get_current_price(position.asset_code, trade_date)
            except Exception:
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.FAILED,
                    stage="price",
                    code="SELL_PRICE_READ_FAILED",
                    asset_code=position.asset_code,
                )
                continue
            if price is None:
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.BLOCKED,
                    stage="price",
                    code="SELL_PRICE_UNAVAILABLE",
                    asset_code=position.asset_code,
                )
                continue
            if not self._is_exit_advice_price_triggered(exit_advice, price):
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.BLOCKED,
                    stage="sell_signal",
                    code="SELL_PRICE_NOT_TRIGGERED",
                    asset_code=position.asset_code,
                )
                continue
            try:
                quantity = self._resolve_exit_quantity(position, exit_advice)
            except Exception:
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.FAILED,
                    stage="sell_sizing",
                    code="SELL_QUANTITY_CALCULATION_FAILED",
                    asset_code=position.asset_code,
                )
                continue
            if quantity <= 0:
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.BLOCKED,
                    stage="sell_signal",
                    code="SELL_QUANTITY_INVALID",
                    asset_code=position.asset_code,
                )
                continue
            try:
                trade = self.sell_use_case.execute(
                    account_id=account.account_id,
                    asset_code=position.asset_code,
                    quantity=quantity,
                    price=price,
                    reason=self._get_sell_reason(position, exit_advice),
                    execution_date=trade_date,
                )
            except Exception:
                execution_state.add_issue(
                    kind=AutoTradingIssueKind.FAILED,
                    stage="sell_execution",
                    code="SELL_EXECUTION_OUTCOME_UNKNOWN",
                    asset_code=position.asset_code,
                    effects_indeterminate=True,
                )
                continue
            execution_state.confirm_trade("sell")
            self._record_confirmed_execution_link(
                execution_state,
                trade=trade,
                account_id=account.account_id,
                asset_code=position.asset_code,
                action="sell",
                recommendation_id=exit_advice.recommendation_id or None,
                match_if_missing=False,
                notes=f"Auto exit via {exit_advice.source}: {exit_advice.reason_code}",
            )
            logger.info("    ✓ 卖出: %s x%s @ %.2f", position.asset_name, quantity, price)

        candidates, candidate_issue = self._get_buy_candidates(account, trade_date)
        if candidate_issue is not None:
            execution_state.issues.append(candidate_issue)
        logger.info("  买入候选: %s 个", len(candidates))
        for candidate in candidates:
            self._execute_buy(account, candidate, trade_date, execution_state)

        self._record_performance_outcome(account.account_id, trade_date, execution_state)
        return execution_state.build()

    def _build_exit_advice_map(
        self,
        account_id: int,
        positions: list[Position],
        trade_date: date,
        state: _AccountOutcomeState,
    ) -> dict[str, PositionExitAdvice]:
        return self._exit_evaluator.build_exit_advice_map(
            account_id,
            positions,
            trade_date,
            exit_advisor=self.exit_advisor,
            state=state,
            logger=logger,
        )

    def _record_execution_link(
        self,
        *,
        trade_id: int,
        account_id: int,
        security_code: str,
        actual_action: str,
        executed_at: datetime,
        recommendation_id: str | None = None,
        match_if_missing: bool = False,
        notes: str = "",
    ) -> bool:
        if self.execution_link_recorder is None or not trade_id:
            return True

        try:
            self.execution_link_recorder.record_execution(
                recommendation_id=recommendation_id,
                transaction_id=trade_id,
                account_id=account_id,
                security_code=security_code,
                actual_action=actual_action,
                executed_at=executed_at,
                match_if_missing=match_if_missing,
                notes=notes,
            )
            return True
        except Exception:
            logger.warning(
                "记录自动交易执行关联失败: trade=%s asset=%s action=%s",
                trade_id,
                security_code,
                actual_action,
            )
            return False

    def _record_confirmed_execution_link(
        self,
        state: _AccountOutcomeState,
        *,
        trade: SimulatedTrade,
        account_id: int,
        asset_code: str,
        action: str,
        recommendation_id: str | None,
        match_if_missing: bool,
        notes: str,
    ) -> None:
        """Record optional trade linkage after counting the confirmed trade."""

        if self.execution_link_recorder is None:
            return
        trade_id = getattr(trade, "trade_id", None)
        executed_at = getattr(trade, "execution_time", None)
        if type(trade_id) is not int or trade_id <= 0 or not isinstance(executed_at, datetime):
            linked = False
        else:
            linked = self._record_execution_link(
                trade_id=trade_id,
                account_id=account_id,
                security_code=asset_code,
                actual_action=action,
                executed_at=executed_at,
                recommendation_id=recommendation_id,
                match_if_missing=match_if_missing,
                notes=notes,
            )
        if not linked:
            state.add_issue(
                kind=AutoTradingIssueKind.FAILED,
                stage="execution_link",
                code="EXECUTION_LINK_RECORD_FAILED",
                asset_code=asset_code,
            )

    def _record_performance_outcome(
        self,
        account_id: int,
        trade_date: date,
        state: _AccountOutcomeState,
    ) -> None:
        """Record a stable issue if post-trade performance bookkeeping fails."""

        if not self._update_account_performance(account_id, trade_date):
            state.add_issue(
                kind=AutoTradingIssueKind.FAILED,
                stage="account_performance",
                code="ACCOUNT_PERFORMANCE_UPDATE_FAILED",
            )

    def _get_position_exit_advice(
        self,
        position: Position,
        account: SimulatedAccount,
        trade_date: date,
        advisor_map: dict[str, PositionExitAdvice] | None = None,
    ) -> PositionExitAdvice | None:
        """Preserve the engine override seam for ordered exit evaluation."""
        return self._exit_evaluator.get_position_exit_advice(
            position,
            account,
            trade_date,
            advisor_map,
            signal_service=self.signal_service,
            asset_pool_service=self.asset_pool_service,
            logger=logger,
        )

    def _resolve_exit_quantity(self, position: Position, advice: PositionExitAdvice) -> int:
        """Preserve the engine override seam for exit quantity resolution."""
        return self._exit_evaluator.resolve_exit_quantity(position, advice)

    def _get_sell_reason(self, position: Position, advice: PositionExitAdvice | None = None) -> str:
        """Preserve the engine override seam for sell-reason selection."""
        return self._exit_evaluator.get_sell_reason(position, advice)

    def _get_buy_candidates(
        self,
        account: SimulatedAccount,
        trade_date: date,
    ) -> tuple[list[dict[str, object]], AutoTradingIssue | None]:
        """Load candidate assets and distinguish an empty result from a read failure.

        策略:
        1. 从可投池获取高分资产
        2. 筛选有有效信号的资产
        3. 检查账户是否已有持仓(避免重复)
        """
        if not self.asset_pool_service:
            logger.warning("资产池服务未配置，无法获取买入候选")
            return [], AutoTradingIssue(
                AutoTradingIssueKind.BLOCKED,
                "buy_candidates",
                "BUY_CANDIDATE_SOURCE_UNAVAILABLE",
            )

        try:
            # 1. 获取可投池且有有效信号的资产
            candidates = self.asset_pool_service.get_investable_assets_with_signals(
                asset_type="equity", min_score=60.0, limit=20  # 当前只支持股票
            )

            if not candidates:
                logger.info("  未找到符合条件的有信号资产")
                return [], None

            # 2. 过滤掉已持仓的资产
            existing_positions = self.position_repo.get_by_account(account.account_id)
            held_codes = {position.asset_code.strip().upper() for position in existing_positions}

            filtered_candidates: list[dict[str, object]] = []
            for candidate in candidates:
                raw_asset_code = candidate.get("asset_code")
                if not isinstance(raw_asset_code, str):
                    continue
                asset_code = raw_asset_code.strip().upper()
                if not asset_code or asset_code in held_codes:
                    continue
                filtered_candidates.append({**candidate, "asset_code": asset_code})

            logger.info(
                f"  找到 {len(candidates)} 个有信号的资产, "
                f"过滤持仓后剩余 {len(filtered_candidates)} 个"
            )

            return filtered_candidates, None

        except Exception:
            logger.error("获取买入候选失败")
            return [], AutoTradingIssue(
                AutoTradingIssueKind.FAILED,
                "buy_candidates",
                "BUY_CANDIDATE_READ_FAILED",
            )

    def _execute_buy(
        self,
        account: SimulatedAccount,
        candidate: dict[str, object],
        trade_date: date,
        state: _AccountOutcomeState | None = None,
    ) -> bool:
        """Execute one legacy buy candidate and update the account result."""
        state = state or _AccountOutcomeState(account_id=account.account_id)
        raw_asset_code = candidate.get("asset_code")
        asset_code = raw_asset_code.strip().upper() if isinstance(raw_asset_code, str) else ""
        if not asset_code:
            logger.warning("    买入候选缺少有效证券代码,跳过")
            state.add_issue(
                kind=AutoTradingIssueKind.BLOCKED,
                stage="buy_candidate",
                code="BUY_CANDIDATE_INVALID",
            )
            return False

        raw_asset_name = candidate.get("asset_name")
        asset_name = (
            raw_asset_name.strip() if isinstance(raw_asset_name, str) else ""
        ) or asset_code
        raw_asset_type = candidate.get("asset_type")
        asset_type = (raw_asset_type.strip() if isinstance(raw_asset_type, str) else "") or "equity"
        asset_score = safe_float(candidate.get("score"), default=70.0)
        raw_signal_id = candidate.get("signal_id")
        signal_id = (
            raw_signal_id
            if isinstance(raw_signal_id, int) and not isinstance(raw_signal_id, bool)
            else None
        )

        # 1. 获取当前价格
        try:
            price = self._get_current_price(asset_code, trade_date)
        except Exception:
            state.add_issue(
                kind=AutoTradingIssueKind.FAILED,
                stage="price",
                code="BUY_PRICE_READ_FAILED",
                asset_code=asset_code,
            )
            return False
        if price is None:
            logger.warning(f"    无法获取 {asset_code} 价格,跳过")
            state.add_issue(
                kind=AutoTradingIssueKind.BLOCKED,
                stage="price",
                code="BUY_PRICE_UNAVAILABLE",
                asset_code=asset_code,
            )
            return False
        if not self._is_price_triggered(action="buy", price=price, payload=candidate):
            logger.info(
                "    跳过 %s: 当前价 %.4f 未进入买入触发区间",
                asset_code,
                price,
            )
            state.add_issue(
                kind=AutoTradingIssueKind.BLOCKED,
                stage="buy_candidate",
                code="BUY_PRICE_NOT_TRIGGERED",
                asset_code=asset_code,
            )
            return False

        # 2. 检查是否已有持仓
        try:
            existing = self.position_repo.get_position(account.account_id, asset_code)
        except Exception:
            state.add_issue(
                kind=AutoTradingIssueKind.FAILED,
                stage="position_read",
                code="BUY_POSITION_READ_FAILED",
                asset_code=asset_code,
            )
            return False
        if existing:
            logger.info(f"    跳过 {asset_code}: 已有持仓 {existing.quantity} 股")
            state.add_issue(
                kind=AutoTradingIssueKind.BLOCKED,
                stage="buy_candidate",
                code="BUY_POSITION_ALREADY_HELD",
                asset_code=asset_code,
            )
            return False

        # 3. 计算买入数量
        try:
            positions = self.position_repo.get_by_account(account.account_id)
            quantity = PositionSizingRule.calculate_buy_quantity(
                account=account,
                asset_price=price,
                asset_score=asset_score,
                existing_positions=positions,
            )
        except Exception:
            state.add_issue(
                kind=AutoTradingIssueKind.FAILED,
                stage="buy_sizing",
                code="BUY_QUANTITY_CALCULATION_FAILED",
                asset_code=asset_code,
            )
            return False

        if quantity <= 0:
            logger.info(f"    跳过 {asset_code}: 买入数量必须为正数")
            state.add_issue(
                kind=AutoTradingIssueKind.BLOCKED,
                stage="buy_sizing",
                code="BUY_QUANTITY_INVALID",
                asset_code=asset_code,
            )
            return False

        risk_issue = self._buy_risk_issue(
            account=account,
            asset_code=asset_code,
            quantity=quantity,
            price=price,
            positions=positions,
        )
        if risk_issue is not None:
            state.issues.append(risk_issue)
            return False

        # 4. 执行买入
        try:
            trade = self.buy_use_case.execute(
                account_id=account.account_id,
                asset_code=asset_code,
                asset_name=asset_name,
                asset_type=asset_type,
                quantity=quantity,
                price=price,
                reason="自动交易引擎买入",
                signal_id=signal_id,
                execution_date=trade_date,
            )
        except Exception:
            state.add_issue(
                kind=AutoTradingIssueKind.FAILED,
                stage="buy_execution",
                code="BUY_EXECUTION_OUTCOME_UNKNOWN",
                asset_code=asset_code,
                effects_indeterminate=True,
            )
            return False

        state.confirm_trade("buy")
        self._record_confirmed_execution_link(
            state,
            trade=trade,
            account_id=account.account_id,
            asset_code=asset_code,
            action="buy",
            recommendation_id=None,
            match_if_missing=True,
            notes="Auto legacy buy",
        )
        logger.info(f"    ✓ 买入: {asset_name} x{quantity} @ {price:.2f}")
        return True

    def _buy_risk_issue(
        self,
        *,
        account: SimulatedAccount,
        asset_code: str,
        quantity: float,
        price: float,
        positions: list[Position] | None = None,
    ) -> AutoTradingIssue | None:
        """Return a stable issue when the centralized buy risk check blocks or fails."""
        try:
            resolved_positions = (
                positions
                if positions is not None
                else self.position_repo.get_by_account(account.account_id)
            )
            normalized_asset_code = asset_code.strip().upper()
            current_symbol_position_value = sum(
                float(position.market_value)
                for position in resolved_positions
                if position.asset_code.strip().upper() == normalized_asset_code
            )
            result = self.pre_trade_risk_guard.execute(
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

    def _get_current_price(self, asset_code: str, trade_date: date) -> float | None:
        """Preserve the engine override seam for current-price resolution."""
        return self._exit_evaluator.get_current_price(
            asset_code,
            trade_date,
            price_provider=self.price_provider,
        )

    def _is_exit_advice_price_triggered(
        self,
        advice: PositionExitAdvice,
        price: float,
    ) -> bool:
        """Preserve the engine override seam for exit price-band evaluation."""
        return self._exit_evaluator.is_exit_advice_price_triggered(
            advice,
            price,
            price_trigger=self._is_price_triggered,
        )

    def _is_price_triggered(
        self,
        *,
        action: str,
        price: float,
        payload: Mapping[str, object],
    ) -> bool:
        """Preserve the engine override seam for price-band evaluation."""
        return self._exit_evaluator.is_price_triggered(
            action=action,
            price=price,
            payload=payload,
            pick_float=self._pick_float,
        )

    @staticmethod
    def _pick_float(payload: Mapping[str, object], *keys: str) -> float | None:
        """Preserve the engine override seam for numeric payload extraction."""
        return AutoTradingExitEvaluator.pick_float(payload, *keys)

    def _update_account_performance(self, account_id: int, trade_date: date) -> bool:
        """
        更新账户绩效

        在每次交易完成后：
        1. 记录当日净值数据（用于绘制净值曲线）
        2. 重新计算绩效指标（总收益、最大回撤、夏普比率等）
        3. 更新账户实体

        Args:
            account_id: 账户ID
            trade_date: 交易日期

        Returns:
            Whether the daily performance update completed.
        """
        try:
            from apps.simulated_trading.application.daily_net_value_service import (
                DailyNetValueService,
            )

            # 使用净值服务记录和更新绩效
            net_value_service = DailyNetValueService(
                account_repo=self.account_repo,
                position_repo=self.position_repo,
                trade_repo=self.trade_repo,
            )

            # 记录当日净值并计算绩效指标
            metrics = net_value_service.record_and_update_performance(
                account_id=account_id, record_date=trade_date
            )

            if metrics:
                logger.info(
                    f"  账户绩效已更新: 总收益率={metrics.get('total_return', 0):.2f}%, "
                    f"最大回撤={metrics.get('max_drawdown', 0):.2f}%, "
                    f"夏普比率={metrics.get('sharpe_ratio', 0):.2f}"
                )
            return True

        except Exception:
            logger.error("更新账户绩效失败: account_id=%s", account_id, exc_info=True)
            return False


class MockPriceProvider:
    """模拟价格提供者(用于测试)"""

    def __init__(self, prices: dict[str, float] | None = None) -> None:
        self._prices = prices if prices is not None else {}

    def get_price(self, asset_code: str, trade_date: date) -> float | None:
        """获取指定日期的价格(模拟)"""
        return self._prices.get(asset_code)

    def require_price(self, asset_code: str, trade_date: date) -> float:
        """严格获取指定日期的价格(模拟)。"""
        price = self.get_price(asset_code, trade_date)
        if price is None:
            raise ValueError(f"缺少价格: {asset_code} @ {trade_date}")
        return price
