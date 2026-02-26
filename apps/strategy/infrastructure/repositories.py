"""
Django ORM Repository Implementations for Strategy System

Infrastructure层:
- 实现Domain层定义的Protocol接口
- 负责数据持久化和检索
- 提供ORM对象到Domain实体的转换
"""
import logging
from typing import List, Optional
from datetime import datetime
from hashlib import sha256

from django.db import transaction
from django.db.models import Q, F, Prefetch

from apps.strategy.domain.entities import (
    Strategy,
    StrategyType,
    ActionType,
    RuleType,
    ApprovalMode,
    RiskControlParams,
    StrategyConfig,
    ScriptConfig,
    AIConfig,
    RuleCondition,
    SignalRecommendation,
    StrategyExecutionResult
)
from apps.strategy.domain.protocols import (
    StrategyRepositoryProtocol,
    RuleConditionRepositoryProtocol,
    StrategyExecutionLogRepositoryProtocol
)
from apps.strategy.infrastructure.models import (
    StrategyModel,
    RuleConditionModel,
    ScriptConfigModel,
    AIStrategyConfigModel,
    PortfolioStrategyAssignmentModel,
    StrategyExecutionLogModel
)

logger = logging.getLogger(__name__)


# ========================================================================
# Strategy Repository
# ========================================================================

class DjangoStrategyRepository:
    """Django ORM 实现的策略仓储"""

    @staticmethod
    def _orm_to_domain_entity(orm_obj: StrategyModel) -> Strategy:
        """将 ORM 对象转换为 Domain 实体"""
        # 基础风控参数
        risk_params = RiskControlParams(
            max_position_pct=orm_obj.max_position_pct,
            max_total_position_pct=orm_obj.max_total_position_pct,
            stop_loss_pct=orm_obj.stop_loss_pct
        )

        # 策略配置
        strategy_type = StrategyType(orm_obj.strategy_type)
        config = StrategyConfig(
            strategy_type=strategy_type,
            risk_params=risk_params,
            description=orm_obj.description
        )

        # 可选配置
        script_config = None
        ai_config = None
        rule_conditions = None

        # 加载规则条件（如果是规则驱动策略）
        if strategy_type in [StrategyType.RULE_BASED, StrategyType.HYBRID]:
            rule_conditions_orm = orm_obj.rules.filter(is_enabled=True).all()
            rule_conditions = [
                DjangoRuleConditionRepository._orm_to_domain_entity(rc)
                for rc in rule_conditions_orm
            ]

        # 加载脚本配置（如果是脚本驱动策略）
        if strategy_type in [StrategyType.SCRIPT_BASED, StrategyType.HYBRID]:
            try:
                script_orm = orm_obj.script_config
                if script_orm:
                    script_config = ScriptConfig(
                        script_code=script_orm.script_code,
                        script_language=script_orm.script_language,
                        allowed_modules=script_orm.allowed_modules,
                        sandbox_config=script_orm.sandbox_config
                    )
            except ScriptConfigModel.DoesNotExist:
                pass

        # 加载 AI 配置（如果是 AI 驱动策略）
        if strategy_type in [StrategyType.AI_DRIVEN, StrategyType.HYBRID]:
            try:
                ai_orm = orm_obj.ai_config
                if ai_orm:
                    ai_config = AIConfig(
                        approval_mode=ApprovalMode(ai_orm.approval_mode),
                        confidence_threshold=ai_orm.confidence_threshold,
                        temperature=ai_orm.temperature,
                        max_tokens=ai_orm.max_tokens,
                        prompt_template_id=ai_orm.prompt_template_id,
                        chain_config_id=ai_orm.chain_config_id,
                        ai_provider_id=ai_orm.ai_provider_id
                    )
            except AIStrategyConfigModel.DoesNotExist:
                pass

        return Strategy(
            strategy_id=orm_obj.id,
            name=orm_obj.name,
            strategy_type=strategy_type,
            version=orm_obj.version,
            is_active=orm_obj.is_active,
            created_by_id=orm_obj.created_by_id,
            config=config,
            risk_params=risk_params,
            rule_conditions=rule_conditions,
            script_config=script_config,
            ai_config=ai_config,
            description=orm_obj.description,
            created_at=orm_obj.created_at,
            updated_at=orm_obj.updated_at
        )

    def save(self, strategy: Strategy) -> int:
        """
        保存策略，返回策略ID

        Args:
            strategy: 策略实体

        Returns:
            策略ID
        """
        with transaction.atomic():
            if strategy.strategy_id is None:
                # 创建新策略
                orm_obj = StrategyModel._default_manager.create(
                    name=strategy.name,
                    description=strategy.description,
                    strategy_type=strategy.strategy_type.value,
                    version=strategy.version,
                    is_active=strategy.is_active,
                    max_position_pct=strategy.risk_params.max_position_pct,
                    max_total_position_pct=strategy.risk_params.max_total_position_pct,
                    stop_loss_pct=strategy.risk_params.stop_loss_pct,
                    created_by_id=strategy.created_by_id
                )
            else:
                # 更新现有策略
                orm_obj = StrategyModel._default_manager.get(id=strategy.strategy_id)
                orm_obj.name = strategy.name
                orm_obj.description = strategy.description
                orm_obj.strategy_type = strategy.strategy_type.value
                orm_obj.version = strategy.version
                orm_obj.is_active = strategy.is_active
                orm_obj.max_position_pct = strategy.risk_params.max_position_pct
                orm_obj.max_total_position_pct = strategy.risk_params.max_total_position_pct
                orm_obj.stop_loss_pct = strategy.risk_params.stop_loss_pct
                orm_obj.save()

            # 保存关联配置
            if strategy.script_config:
                self._save_script_config(orm_obj, strategy.script_config)

            if strategy.ai_config:
                self._save_ai_config(orm_obj, strategy.ai_config)

            if strategy.rule_conditions:
                self._save_rule_conditions(orm_obj, strategy.rule_conditions)

            return orm_obj.id

    def _save_script_config(self, strategy_orm: StrategyModel, script_config: ScriptConfig):
        """保存脚本配置"""
        script_hash = sha256(script_config.script_code.encode()).hexdigest()

        ScriptConfigModel._default_manager.update_or_create(
            strategy=strategy_orm,
            defaults={
                'script_language': script_config.script_language,
                'script_code': script_config.script_code,
                'script_hash': script_hash,
                'sandbox_config': script_config.sandbox_config,
                'allowed_modules': script_config.allowed_modules,
                'is_active': True
            }
        )

    def _save_ai_config(self, strategy_orm: StrategyModel, ai_config: AIConfig):
        """保存 AI 配置"""
        AIStrategyConfigModel._default_manager.update_or_create(
            strategy=strategy_orm,
            defaults={
                'prompt_template_id': ai_config.prompt_template_id,
                'chain_config_id': ai_config.chain_config_id,
                'ai_provider_id': ai_config.ai_provider_id,
                'temperature': ai_config.temperature,
                'max_tokens': ai_config.max_tokens,
                'approval_mode': ai_config.approval_mode.value,
                'confidence_threshold': ai_config.confidence_threshold
            }
        )

    def _save_rule_conditions(self, strategy_orm: StrategyModel, rule_conditions: List[RuleCondition]):
        """保存规则条件"""
        # 删除现有规则
        RuleConditionModel._default_manager.filter(strategy=strategy_orm).delete()

        # 创建新规则
        for rule in rule_conditions:
            RuleConditionModel._default_manager.create(
                strategy=strategy_orm,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type.value,
                condition_json=rule.condition_json,
                action=rule.action.value,
                weight=rule.weight,
                target_assets=rule.target_assets,
                priority=rule.priority,
                is_enabled=rule.is_enabled
            )

    def get_by_id(self, strategy_id: int) -> Optional[Strategy]:
        """
        根据ID获取策略

        Args:
            strategy_id: 策略ID

        Returns:
            策略实体，如果不存在返回 None
        """
        try:
            orm_obj = StrategyModel._default_manager.get(id=strategy_id)
            return self._orm_to_domain_entity(orm_obj)
        except StrategyModel.DoesNotExist:
            return None

    def get_by_user(self, user_id: int, is_active: bool = True) -> List[Strategy]:
        """
        获取用户的策略列表

        Args:
            user_id: 用户ID
            is_active: 是否只获取激活的策略

        Returns:
            策略实体列表
        """
        queryset = StrategyModel._default_manager.filter(created_by_id=user_id)
        if is_active:
            queryset = queryset.filter(is_active=True)

        orm_objects = queryset.all()
        return [self._orm_to_domain_entity(obj) for obj in orm_objects]

    def get_active_strategies_for_portfolio(self, portfolio_id: int) -> List[Strategy]:
        """
        获取投资组合的激活策略

        Args:
            portfolio_id: 投资组合ID

        Returns:
            策略实体列表
        """
        assignments = PortfolioStrategyAssignmentModel._default_manager.filter(
            portfolio_id=portfolio_id,
            is_active=True
        ).select_related('strategy').prefetch_related(
            Prefetch('strategy__rules', queryset=RuleConditionModel._default_manager.filter(is_enabled=True))
        )

        strategies = []
        for assignment in assignments:
            if assignment.strategy.is_active:
                strategies.append(self._orm_to_domain_entity(assignment.strategy))

        return strategies

    def delete(self, strategy_id: int) -> bool:
        """
        删除策略

        Args:
            strategy_id: 策略ID

        Returns:
            是否删除成功
        """
        try:
            with transaction.atomic():
                orm_obj = StrategyModel._default_manager.get(id=strategy_id)
                orm_obj.delete()
                return True
        except StrategyModel.DoesNotExist:
            return False


# ========================================================================
# Rule Condition Repository
# ========================================================================

class DjangoRuleConditionRepository:
    """Django ORM 实现的规则条件仓储"""

    @staticmethod
    def _orm_to_domain_entity(orm_obj: RuleConditionModel) -> RuleCondition:
        """将 ORM 对象转换为 Domain 实体"""
        # 转换 action 从大写到小写（数据库存储为大写，Domain 层使用小写）
        action_mapping = {
            'BUY': ActionType.BUY,
            'SELL': ActionType.SELL,
            'HOLD': ActionType.HOLD,
            'WEIGHT': ActionType.WEIGHT,
            'buy': ActionType.BUY,
            'sell': ActionType.SELL,
            'hold': ActionType.HOLD,
            'weight': ActionType.WEIGHT,
        }
        action_value = action_mapping.get(orm_obj.action, ActionType.BUY)

        return RuleCondition(
            rule_id=orm_obj.id,
            strategy_id=orm_obj.strategy_id,
            rule_name=orm_obj.rule_name,
            rule_type=RuleType(orm_obj.rule_type),
            condition_json=orm_obj.condition_json,
            action=action_value,
            weight=orm_obj.weight,
            target_assets=orm_obj.target_assets,
            priority=orm_obj.priority,
            is_enabled=orm_obj.is_enabled,
            created_at=orm_obj.created_at
        )

    def save(self, condition: RuleCondition) -> int:
        """
        保存规则条件

        Args:
            condition: 规则条件实体

        Returns:
            规则条件ID
        """
        # 转换 action 从小写到大写（Domain 层使用小写，数据库存储为大写）
        action_upper = condition.action.value.upper()

        if condition.rule_id is None:
            # 创建新规则条件
            orm_obj = RuleConditionModel._default_manager.create(
                strategy_id=condition.strategy_id,
                rule_name=condition.rule_name,
                rule_type=condition.rule_type.value,
                condition_json=condition.condition_json,
                action=action_upper,
                weight=condition.weight,
                target_assets=condition.target_assets,
                priority=condition.priority,
                is_enabled=condition.is_enabled
            )
        else:
            # 更新现有规则条件
            orm_obj = RuleConditionModel._default_manager.get(id=condition.rule_id)
            orm_obj.rule_name = condition.rule_name
            orm_obj.rule_type = condition.rule_type.value
            orm_obj.condition_json = condition.condition_json
            orm_obj.action = action_upper
            orm_obj.weight = condition.weight
            orm_obj.target_assets = condition.target_assets
            orm_obj.priority = condition.priority
            orm_obj.is_enabled = condition.is_enabled
            orm_obj.save()

        return orm_obj.id

    def get_by_strategy(self, strategy_id: int) -> List[RuleCondition]:
        """
        获取策略的所有规则条件

        Args:
            strategy_id: 策略ID

        Returns:
            规则条件实体列表
        """
        orm_objects = RuleConditionModel._default_manager.filter(
            strategy_id=strategy_id
        ).order_by('-priority', '-created_at').all()

        return [self._orm_to_domain_entity(obj) for obj in orm_objects]

    def delete_by_strategy(self, strategy_id: int) -> bool:
        """
        删除策略的所有规则条件

        Args:
            strategy_id: 策略ID

        Returns:
            是否删除成功
        """
        count, _ = RuleConditionModel._default_manager.filter(strategy_id=strategy_id).delete()
        return count > 0


# ========================================================================
# Strategy Execution Log Repository
# ========================================================================

class DjangoStrategyExecutionLogRepository:
    """Django ORM 实现的策略执行日志仓储"""

    @staticmethod
    def _orm_to_domain_entity(orm_obj: StrategyExecutionLogModel) -> StrategyExecutionResult:
        """将 ORM 对象转换为 Domain 实体"""
        # 解析信号列表
        signals = []
        for signal_data in orm_obj.signals_generated:
            signals.append(SignalRecommendation(
                asset_code=signal_data.get('asset_code', ''),
                asset_name=signal_data.get('asset_name', ''),
                action=ActionType(signal_data.get('action', 'hold')),
                weight=signal_data.get('weight'),
                quantity=signal_data.get('quantity'),
                reason=signal_data.get('reason', ''),
                confidence=signal_data.get('confidence', 0.0),
                metadata=signal_data.get('metadata', {})
            ))

        return StrategyExecutionResult(
            strategy_id=orm_obj.strategy_id,
            portfolio_id=orm_obj.portfolio_id,
            execution_time=orm_obj.execution_time,
            execution_duration_ms=orm_obj.execution_duration_ms,
            signals=signals,
            is_success=orm_obj.is_success,
            error_message=orm_obj.error_message,
            context=orm_obj.execution_result
        )

    def save(self, result: StrategyExecutionResult) -> int:
        """
        保存执行日志

        Args:
            result: 策略执行结果

        Returns:
            日志ID
        """
        from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
        from apps.strategy.infrastructure.models import StrategyModel

        # 检查外键是否存在
        try:
            StrategyModel._default_manager.get(id=result.strategy_id)
            SimulatedAccountModel._default_manager.get(id=result.portfolio_id)
        except (StrategyModel.DoesNotExist, SimulatedAccountModel.DoesNotExist):
            logger.warning(f"Cannot save execution log: strategy={result.strategy_id} or portfolio={result.portfolio_id} does not exist")
            return 0  # 返回0表示保存失败

        # 转换信号列表为 JSON 格式
        signals_json = [
            {
                'asset_code': s.asset_code,
                'asset_name': s.asset_name,
                'action': s.action.value,
                'weight': s.weight,
                'quantity': s.quantity,
                'reason': s.reason,
                'confidence': s.confidence,
                'metadata': s.metadata
            }
            for s in result.signals
        ]

        try:
            orm_obj = StrategyExecutionLogModel._default_manager.create(
                strategy_id=result.strategy_id,
                portfolio_id=result.portfolio_id,
                execution_duration_ms=result.execution_duration_ms,
                execution_result=result.context,
                signals_generated=signals_json,
                is_success=result.is_success,
                error_message=result.error_message
            )
            return orm_obj.id
        except Exception as e:
            # 如果保存失败（如外键约束），记录日志但不抛出异常
            logger.error(f"Failed to save execution log: {e}")
            return 0  # 返回0表示保存失败

    def get_by_strategy(self, strategy_id: int, limit: int = 100) -> List[StrategyExecutionResult]:
        """
        获取策略的执行日志

        Args:
            strategy_id: 策略ID
            limit: 返回数量限制

        Returns:
            执行结果列表
        """
        orm_objects = StrategyExecutionLogModel._default_manager.filter(
            strategy_id=strategy_id
        ).order_by('-execution_time')[:limit].all()

        return [self._orm_to_domain_entity(obj) for obj in orm_objects]

    def get_by_portfolio(self, portfolio_id: int, limit: int = 100) -> List[StrategyExecutionResult]:
        """
        获取投资组合的执行日志

        Args:
            portfolio_id: 投资组合ID
            limit: 返回数量限制

        Returns:
            执行结果列表
        """
        orm_objects = StrategyExecutionLogModel._default_manager.filter(
            portfolio_id=portfolio_id
        ).order_by('-execution_time')[:limit].all()

        return [self._orm_to_domain_entity(obj) for obj in orm_objects]

