"""
策略执行引擎 - Application 层

遵循项目架构约束：
- 通过依赖注入使用 Protocol 接口
- 不直接依赖 ORM Model
- 编排业务逻辑流程
"""

import logging
import math
from typing import Any

from django.utils import timezone

from apps.strategy.application.ai_strategy_executor import AIStrategyExecutor
from apps.strategy.application.rule_evaluator import CompositeRuleEvaluator
from apps.strategy.application.script_engine import ScriptBasedStrategyExecutor, SecurityMode
from apps.strategy.domain.entities import (
    RuleCondition,
    SignalRecommendation,
    Strategy,
    StrategyExecutionResult,
    StrategyType,
)
from apps.strategy.domain.protocols import (
    AssetPoolProviderProtocol,
    MacroDataProviderProtocol,
    PortfolioDataProviderProtocol,
    RegimeProviderProtocol,
    SignalProviderProtocol,
    StrategyExecutionLogRepositoryProtocol,
    StrategyRepositoryProtocol,
)

logger = logging.getLogger(__name__)


class StrategyContextUnavailableError(RuntimeError):
    """Raised when required strategy execution context cannot be loaded safely."""


# ========================================================================
# 策略执行引擎（中央调度器）
# ========================================================================


class StrategyExecutor:
    """
    策略执行引擎（中央调度器）

    职责：
    1. 加载策略
    2. 准备执行上下文（宏观数据、Regime、资产池、投资组合数据）
    3. 根据策略类型分发到对应执行器
    4. 统一错误处理和日志记录
    """

    def __init__(
        self,
        strategy_repository: StrategyRepositoryProtocol,
        execution_log_repository: StrategyExecutionLogRepositoryProtocol,
        macro_provider: MacroDataProviderProtocol,
        regime_provider: RegimeProviderProtocol,
        asset_pool_provider: AssetPoolProviderProtocol,
        signal_provider: SignalProviderProtocol,
        portfolio_provider: PortfolioDataProviderProtocol,
        script_security_mode: str = SecurityMode.RELAXED,
    ) -> None:
        """
        初始化策略执行引擎

        Args:
            strategy_repository: 策略仓储
            execution_log_repository: 执行日志仓储
            macro_provider: 宏观数据提供者
            regime_provider: Regime 提供者
            asset_pool_provider: 资产池提供者
            signal_provider: 信号提供者
            portfolio_provider: 投资组合数据提供者
            script_security_mode: 脚本沙箱安全模式（strict/standard/relaxed）
        """
        self.strategy_repository = strategy_repository
        self.execution_log_repository = execution_log_repository
        self.macro_provider = macro_provider
        self.regime_provider = regime_provider
        self.asset_pool_provider = asset_pool_provider
        self.signal_provider = signal_provider
        self.portfolio_provider = portfolio_provider
        self.script_security_mode = script_security_mode

        # 初始化规则评估器
        self.rule_evaluator = CompositeRuleEvaluator()

        # 初始化脚本执行器
        self.script_executor = ScriptBasedStrategyExecutor(
            macro_provider=macro_provider,
            regime_provider=regime_provider,
            asset_pool_provider=asset_pool_provider,
            signal_provider=signal_provider,
            portfolio_provider=portfolio_provider,
            security_mode=script_security_mode,
        )

        # 初始化 AI 执行器
        self.ai_executor = AIStrategyExecutor(
            macro_provider=macro_provider,
            regime_provider=regime_provider,
            asset_pool_provider=asset_pool_provider,
            signal_provider=signal_provider,
            portfolio_provider=portfolio_provider,
        )

    def execute_strategy(self, strategy_id: int, portfolio_id: int) -> StrategyExecutionResult:
        """
        执行策略

        Args:
            strategy_id: 策略ID
            portfolio_id: 投资组合ID

        Returns:
            策略执行结果
        """
        start_time = timezone.now()
        error_message = ""
        signals: list[SignalRecommendation] = []
        is_success = False
        context: dict[str, Any] = {}

        try:
            self._validate_execution_ids(strategy_id, portfolio_id)

            # 1. 加载策略
            strategy = self.strategy_repository.get_by_id(strategy_id)
            if strategy is None:
                raise ValueError(f"Strategy not found: {strategy_id}")

            logger.info(f"Executing strategy: {strategy.name} (ID: {strategy_id})")

            # 2. 准备执行上下文
            context = self._prepare_context(portfolio_id)

            # 3. 根据策略类型分发执行
            signals = self._deduplicate_signals(self._dispatch_execution(strategy, context))

            is_success = True
            logger.info(
                f"Strategy execution succeeded: {strategy.name}, generated {len(signals)} signals"
            )

        except Exception as e:
            error_message = f"Strategy execution failed: {str(e)}"
            logger.error(error_message, exc_info=True)
            is_success = False

        # 4. 计算执行时长
        end_time = timezone.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        # 5. 构建执行结果
        result = StrategyExecutionResult(
            strategy_id=strategy_id,
            portfolio_id=portfolio_id,
            execution_time=start_time,
            execution_duration_ms=duration_ms,
            signals=signals,
            is_success=is_success,
            error_message=error_message,
            context=context,
        )

        # 6. 保存执行日志
        try:
            self.execution_log_repository.save(result)
        except Exception:
            logger.error("Failed to save strategy execution log", exc_info=True)
            result.signals = []
            result.is_success = False
            result.error_message = (
                f"{result.error_message}; " if result.error_message else ""
            ) + "Strategy execution log persistence failed"

        return result

    @staticmethod
    def _validate_execution_ids(strategy_id: int, portfolio_id: int) -> None:
        """Reject invalid identifiers before any provider or repository access."""
        if isinstance(strategy_id, bool) or strategy_id <= 0:
            raise ValueError("strategy_id must be a positive integer")
        if isinstance(portfolio_id, bool) or portfolio_id <= 0:
            raise ValueError("portfolio_id must be a positive integer")

    def _prepare_context(self, portfolio_id: int) -> dict[str, Any]:
        """
        准备执行上下文

        Args:
            portfolio_id: 投资组合ID

        Returns:
            上下文字典，包含：
            - macro: 宏观数据
            - regime: Regime 状态
            - asset_pool: 可投资产池
            - portfolio: 投资组合数据（持仓、现金）
            - signals: 有效信号列表
        """
        context: dict[str, Any] = {}

        # 1. 获取宏观数据
        try:
            macro = self.macro_provider.get_all_indicators()
            if not isinstance(macro, dict):
                raise TypeError("macro provider returned a non-mapping payload")
            context["macro"] = macro
        except Exception as e:
            raise StrategyContextUnavailableError(
                "Required strategy context unavailable: macro"
            ) from e

        # 2. 获取 Regime 状态
        try:
            regime = self.regime_provider.get_current_regime()
            if not isinstance(regime, dict):
                raise TypeError("regime provider returned a non-mapping payload")
            context["regime"] = regime
        except Exception as e:
            raise StrategyContextUnavailableError(
                "Required strategy context unavailable: regime"
            ) from e

        # 3. 获取可投资产池
        try:
            raw_asset_pool = self.asset_pool_provider.get_investable_assets(min_score=60.0)
            if not isinstance(raw_asset_pool, list):
                raise TypeError("asset pool provider returned a non-list payload")
            context["asset_pool"] = [
                asset
                for asset in raw_asset_pool
                if isinstance(asset, dict) and self._is_actionable_asset_pool_item(asset)
            ]
        except Exception as e:
            raise StrategyContextUnavailableError(
                "Required strategy context unavailable: asset_pool"
            ) from e

        # 4. 获取投资组合数据
        try:
            positions = self.portfolio_provider.get_positions(portfolio_id)
            cash = self.portfolio_provider.get_cash(portfolio_id)
            if not isinstance(positions, list) or not all(
                isinstance(position, dict) for position in positions
            ):
                raise TypeError("portfolio provider returned invalid positions")
            if (
                isinstance(cash, bool)
                or not isinstance(cash, (int, float))
                or not math.isfinite(float(cash))
                or cash < 0
            ):
                raise ValueError("portfolio provider returned invalid cash")
            context["portfolio"] = {
                "portfolio_id": portfolio_id,
                "positions": positions,
                "cash": float(cash),
            }
        except Exception as e:
            raise StrategyContextUnavailableError(
                "Required strategy context unavailable: portfolio"
            ) from e

        # 5. 获取有效信号
        try:
            valid_signals = self.signal_provider.get_valid_signals()
            if not isinstance(valid_signals, list) or not all(
                isinstance(signal, dict) for signal in valid_signals
            ):
                raise TypeError("signal provider returned an invalid payload")
            context["signals"] = valid_signals
        except Exception as e:
            raise StrategyContextUnavailableError(
                "Required strategy context unavailable: signals"
            ) from e

        return context

    @staticmethod
    def _is_actionable_asset_pool_item(asset: dict[str, Any]) -> bool:
        """Only formal, non-degraded asset-pool rows may drive strategy signals."""
        if asset.get("actionable") is False:
            return False
        if asset.get("is_fallback") is True:
            return False
        data_quality = asset.get("data_quality") or {}
        if not isinstance(data_quality, dict):
            return False
        if data_quality.get("status") in {"degraded", "invalid", "unavailable"}:
            return False
        return True

    @staticmethod
    def _deduplicate_signals(
        signals: list[SignalRecommendation],
    ) -> list[SignalRecommendation]:
        """Keep the first, highest-precedence recommendation for each asset."""
        unique_signals: list[SignalRecommendation] = []
        seen_asset_codes: set[str] = set()
        for signal in signals:
            asset_code = signal.asset_code.strip()
            if not asset_code:
                logger.warning("Discarding strategy signal with an empty asset code")
                continue
            if asset_code in seen_asset_codes:
                logger.warning(
                    "Discarding duplicate strategy signal for asset %s",
                    asset_code,
                )
                continue
            seen_asset_codes.add(asset_code)
            unique_signals.append(signal)
        return unique_signals

    def _dispatch_execution(
        self, strategy: Strategy, context: dict[str, Any]
    ) -> list[SignalRecommendation]:
        """
        根据策略类型分发执行

        Args:
            strategy: 策略实体
            context: 上下文数据

        Returns:
            信号推荐列表
        """
        if strategy.strategy_type == StrategyType.RULE_BASED:
            return self._execute_rule_based_strategy(strategy, context)

        elif strategy.strategy_type == StrategyType.SCRIPT_BASED:
            # 脚本驱动策略 - 使用脚本执行器
            return self.script_executor.execute(
                strategy,
                self._portfolio_id_from_context(context),
            )

        elif strategy.strategy_type == StrategyType.AI_DRIVEN:
            # AI 驱动策略 - 使用 AI 执行器
            return self.ai_executor.execute(
                strategy,
                self._portfolio_id_from_context(context),
            )

        elif strategy.strategy_type == StrategyType.HYBRID:
            # 混合策略 - 组合多种策略类型
            return self._execute_hybrid_strategy(strategy, context)

        else:
            raise ValueError(f"Unknown strategy type: {strategy.strategy_type}")

    @staticmethod
    def _portfolio_id_from_context(context: dict[str, Any]) -> int:
        """Return the already validated portfolio identifier from context."""
        portfolio = context.get("portfolio")
        if not isinstance(portfolio, dict):
            raise ValueError("Strategy context is missing portfolio data")
        portfolio_id = portfolio.get("portfolio_id")
        if isinstance(portfolio_id, bool) or not isinstance(portfolio_id, int) or portfolio_id <= 0:
            raise ValueError("Strategy context contains an invalid portfolio_id")
        return portfolio_id

    def _execute_rule_based_strategy(
        self, strategy: Strategy, context: dict[str, Any]
    ) -> list[SignalRecommendation]:
        """
        执行规则驱动策略

        Args:
            strategy: 策略实体
            context: 上下文数据

        Returns:
            信号推荐列表
        """
        if strategy.rule_conditions is None or len(strategy.rule_conditions) == 0:
            logger.warning(f"Rule-based strategy has no rules: {strategy.name}")
            return []

        signals: list[SignalRecommendation] = []
        raw_asset_pool = context.get("asset_pool")
        if not isinstance(raw_asset_pool, list):
            raise ValueError("Strategy context contains an invalid asset pool")
        asset_pool = [asset for asset in raw_asset_pool if isinstance(asset, dict)]

        # 按优先级排序规则（优先级高的先执行）
        sorted_rules = sorted(strategy.rule_conditions, key=lambda r: r.priority, reverse=True)

        for rule in sorted_rules:
            # 评估规则条件
            is_matched = self.rule_evaluator.evaluate(rule, context)

            if is_matched:
                # 规则匹配，生成信号
                rule_signals = self._generate_signals_from_rule(rule, asset_pool, context)
                signals.extend(rule_signals)

                logger.info(
                    f"Rule matched: {rule.rule_name}, generated {len(rule_signals)} signals"
                )

        return signals

    def _execute_hybrid_strategy(
        self, strategy: Strategy, context: dict[str, Any]
    ) -> list[SignalRecommendation]:
        """
        执行混合策略

        Args:
            strategy: 策略实体
            context: 上下文数据

        Returns:
            信号推荐列表
        """
        signals: list[SignalRecommendation] = []
        portfolio_id = self._portfolio_id_from_context(context)

        # 执行规则部分
        if strategy.rule_conditions and len(strategy.rule_conditions) > 0:
            rule_signals = self._execute_rule_based_strategy(strategy, context)
            signals.extend(rule_signals)

        # 执行脚本部分
        if strategy.script_config:
            script_signals = self.script_executor.execute(strategy, portfolio_id)
            signals.extend(script_signals)

        # 执行 AI 部分
        if strategy.ai_config:
            ai_signals = self.ai_executor.execute(strategy, portfolio_id)
            signals.extend(ai_signals)

        return signals

    def _generate_signals_from_rule(
        self, rule: RuleCondition, asset_pool: list[dict[str, Any]], context: dict[str, Any]
    ) -> list[SignalRecommendation]:
        """
        从规则生成信号

        Args:
            rule: 规则条件
            asset_pool: 可投资产池
            context: 上下文数据

        Returns:
            信号推荐列表
        """
        signals: list[SignalRecommendation] = []

        # 确定目标资产列表
        if rule.target_assets and len(rule.target_assets) > 0:
            # 规则指定了目标资产
            target_asset_codes = rule.target_assets
            target_assets = [
                asset for asset in asset_pool if asset.get("asset_code") in target_asset_codes
            ]
        else:
            # 使用所有可投资产
            target_assets = asset_pool

        # 为每个目标资产生成信号
        for asset in target_assets:
            asset_code_value = asset.get("asset_code")
            asset_name_value = asset.get("asset_name")
            if (
                not isinstance(asset_code_value, str)
                or not asset_code_value.strip()
                or not isinstance(asset_name_value, str)
            ):
                logger.warning("Skipping malformed strategy asset-pool item")
                continue
            asset_code = asset_code_value.strip()
            asset_name = asset_name_value.strip()

            total_score_value = asset.get("total_score")
            if total_score_value is None:
                total_score = None
                confidence = 0.5
            elif (
                isinstance(total_score_value, bool)
                or not isinstance(total_score_value, (int, float))
                or not math.isfinite(float(total_score_value))
            ):
                logger.warning(
                    "Skipping strategy asset %s with invalid total_score",
                    asset_code,
                )
                continue
            else:
                total_score = float(total_score_value)
                confidence = min(max(total_score / 100.0, 0.0), 1.0)

            signal = SignalRecommendation(
                asset_code=asset_code,
                asset_name=asset_name,
                action=rule.action,
                weight=rule.weight,
                quantity=None,  # 由后续的仓位管理模块计算
                reason=f"Rule: {rule.rule_name}",
                confidence=confidence,
                metadata={
                    "rule_id": rule.rule_id,
                    "rule_name": rule.rule_name,
                    "rule_type": rule.rule_type.value,
                    "asset_score": total_score,
                },
            )
            signals.append(signal)

        return signals
