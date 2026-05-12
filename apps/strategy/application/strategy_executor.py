"""
策略执行引擎 - Application 层

遵循项目架构约束：
- 通过依赖注入使用 Protocol 接口
- 不直接依赖 ORM Model
- 编排业务逻辑流程
"""
import logging
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
        script_security_mode: str = SecurityMode.RELAXED
    ):
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
            security_mode=script_security_mode
        )

        # 初始化 AI 执行器
        self.ai_executor = AIStrategyExecutor(
            macro_provider=macro_provider,
            regime_provider=regime_provider,
            asset_pool_provider=asset_pool_provider,
            signal_provider=signal_provider,
            portfolio_provider=portfolio_provider
        )

    def execute_strategy(
        self,
        strategy_id: int,
        portfolio_id: int
    ) -> StrategyExecutionResult:
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
        signals = []
        is_success = False
        context = {}

        try:
            # 1. 加载策略
            strategy = self.strategy_repository.get_by_id(strategy_id)
            if strategy is None:
                raise ValueError(f"Strategy not found: {strategy_id}")

            logger.info(f"Executing strategy: {strategy.name} (ID: {strategy_id})")

            # 2. 准备执行上下文
            context = self._prepare_context(portfolio_id)

            # 3. 根据策略类型分发执行
            signals = self._dispatch_execution(strategy, context)

            is_success = True
            logger.info(f"Strategy execution succeeded: {strategy.name}, generated {len(signals)} signals")

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
            context=context
        )

        # 6. 保存执行日志
        try:
            self.execution_log_repository.save(result)
        except Exception as e:
            logger.error(f"Failed to save execution log: {e}")

        return result

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
        context = {}

        # 1. 获取宏观数据
        try:
            context['macro'] = self.macro_provider.get_all_indicators()
        except Exception as e:
            logger.warning(f"Failed to get macro data: {e}")
            context['macro'] = {}

        # 2. 获取 Regime 状态
        try:
            context['regime'] = self.regime_provider.get_current_regime()
        except Exception as e:
            logger.warning(f"Failed to get regime data: {e}")
            context['regime'] = {}

        # 3. 获取可投资产池
        try:
            context['asset_pool'] = self.asset_pool_provider.get_investable_assets(min_score=60.0)
        except Exception as e:
            logger.warning(f"Failed to get asset pool: {e}")
            context['asset_pool'] = []

        # 4. 获取投资组合数据
        try:
            positions = self.portfolio_provider.get_positions(portfolio_id)
            cash = self.portfolio_provider.get_cash(portfolio_id)
            context['portfolio'] = {
                'portfolio_id': portfolio_id,
                'positions': positions,
                'cash': cash
            }
        except Exception as e:
            logger.warning(f"Failed to get portfolio data: {e}")
            context['portfolio'] = {'portfolio_id': portfolio_id, 'positions': [], 'cash': 0.0}

        # 5. 获取有效信号
        try:
            context['signals'] = self.signal_provider.get_valid_signals()
        except Exception as e:
            logger.warning(f"Failed to get signals: {e}")
            context['signals'] = []

        return context

    def _dispatch_execution(
        self,
        strategy: Strategy,
        context: dict[str, Any]
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
            return self.script_executor.execute(strategy, context['portfolio'].get('portfolio_id', 0))

        elif strategy.strategy_type == StrategyType.AI_DRIVEN:
            # AI 驱动策略 - 使用 AI 执行器
            return self.ai_executor.execute(strategy, context['portfolio'].get('portfolio_id', 0))

        elif strategy.strategy_type == StrategyType.HYBRID:
            # 混合策略 - 组合多种策略类型
            return self._execute_hybrid_strategy(strategy, context)

        else:
            raise ValueError(f"Unknown strategy type: {strategy.strategy_type}")

    def _execute_rule_based_strategy(
        self,
        strategy: Strategy,
        context: dict[str, Any]
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

        signals = []
        asset_pool = context.get('asset_pool', [])

        # 按优先级排序规则（优先级高的先执行）
        sorted_rules = sorted(strategy.rule_conditions, key=lambda r: r.priority, reverse=True)

        for rule in sorted_rules:
            # 评估规则条件
            is_matched = self.rule_evaluator.evaluate(rule, context)

            if is_matched:
                # 规则匹配，生成信号
                rule_signals = self._generate_signals_from_rule(rule, asset_pool, context)
                signals.extend(rule_signals)

                logger.info(f"Rule matched: {rule.rule_name}, generated {len(rule_signals)} signals")

        return signals

    def _execute_hybrid_strategy(
        self,
        strategy: Strategy,
        context: dict[str, Any]
    ) -> list[SignalRecommendation]:
        """
        执行混合策略

        Args:
            strategy: 策略实体
            context: 上下文数据

        Returns:
            信号推荐列表
        """
        signals = []
        portfolio_id = context['portfolio'].get('portfolio_id', 0)

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
        self,
        rule: RuleCondition,
        asset_pool: list[dict[str, Any]],
        context: dict[str, Any]
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
        signals = []

        # 确定目标资产列表
        if rule.target_assets and len(rule.target_assets) > 0:
            # 规则指定了目标资产
            target_asset_codes = rule.target_assets
            target_assets = [
                asset for asset in asset_pool
                if asset.get('asset_code') in target_asset_codes
            ]
        else:
            # 使用所有可投资产
            target_assets = asset_pool

        # 为每个目标资产生成信号
        for asset in target_assets:
            asset_code = asset.get('asset_code', '')
            asset_name = asset.get('asset_name', '')
            total_score = asset.get('total_score', 0)

            signal = SignalRecommendation(
                asset_code=asset_code,
                asset_name=asset_name,
                action=rule.action,
                weight=rule.weight,
                quantity=None,  # 由后续的仓位管理模块计算
                reason=f"Rule: {rule.rule_name}",
                confidence=min(total_score / 100.0, 1.0) if total_score else 0.5,
                metadata={
                    'rule_id': rule.rule_id,
                    'rule_name': rule.rule_name,
                    'rule_type': rule.rule_type.value,
                    'asset_score': total_score
                }
            )
            signals.append(signal)

        return signals
