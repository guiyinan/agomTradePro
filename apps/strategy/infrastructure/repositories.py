"""
Django ORM Repository Implementations for Strategy System

Infrastructure层:
- 实现Domain层定义的Protocol接口
- 负责数据持久化和检索
- 提供ORM对象到Domain实体的转换
"""

from __future__ import annotations

import logging
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from django.apps import apps as django_apps
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Prefetch, Q, QuerySet

from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.prompt.infrastructure.models import ChainConfigORM, PromptTemplateORM
from apps.strategy.domain.entities import (
    ActionType,
    AIConfig,
    ApprovalMode,
    OrderIntent,
    OrderSide,
    OrderStatus,
    RiskControlParams,
    RuleCondition,
    RuleType,
    ScriptConfig,
    SignalRecommendation,
    Strategy,
    StrategyConfig,
    StrategyExecutionResult,
    StrategyType,
    TimeInForce,
)
from apps.strategy.infrastructure.models import (
    AIStrategyConfigModel,
    PortfolioStrategyAssignmentModel,
    PositionManagementRuleModel,
    RuleConditionModel,
    ScriptConfigModel,
    StrategyExecutionLogModel,
    StrategyModel,
    StrategyParamVersionModel,
)
from apps.strategy.infrastructure.order_intent_mapper import (
    build_decision,
    build_risk_snapshot,
    build_sizing,
)

if TYPE_CHECKING:
    from apps.strategy.application.execution_gateway import InspectionSelection

logger = logging.getLogger(__name__)


def _order_intent_model() -> Any:
    """Resolve the portfolio-owned compatibility table without a module edge."""

    return django_apps.get_model("portfolio", "OrderIntentModel")


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
            stop_loss_pct=orm_obj.stop_loss_pct,
        )

        # 策略配置
        strategy_type = StrategyType(orm_obj.strategy_type)
        config = StrategyConfig(
            strategy_type=strategy_type, risk_params=risk_params, description=orm_obj.description
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
                        sandbox_config=script_orm.sandbox_config,
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
                        ai_provider_id=ai_orm.ai_provider_id,
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
            updated_at=orm_obj.updated_at,
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
                    created_by_id=strategy.created_by_id,
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

            return int(orm_obj.id)

    def _save_script_config(
        self,
        strategy_orm: StrategyModel,
        script_config: ScriptConfig,
    ) -> None:
        """保存脚本配置"""
        script_hash = sha256(script_config.script_code.encode()).hexdigest()

        ScriptConfigModel._default_manager.update_or_create(
            strategy=strategy_orm,
            defaults={
                "script_language": script_config.script_language,
                "script_code": script_config.script_code,
                "script_hash": script_hash,
                "sandbox_config": script_config.sandbox_config,
                "allowed_modules": script_config.allowed_modules,
                "is_active": True,
            },
        )

    def _save_ai_config(
        self,
        strategy_orm: StrategyModel,
        ai_config: AIConfig,
    ) -> None:
        """保存 AI 配置"""
        AIStrategyConfigModel._default_manager.update_or_create(
            strategy=strategy_orm,
            defaults={
                "prompt_template_id": ai_config.prompt_template_id,
                "chain_config_id": ai_config.chain_config_id,
                "ai_provider_id": ai_config.ai_provider_id,
                "temperature": ai_config.temperature,
                "max_tokens": ai_config.max_tokens,
                "approval_mode": ai_config.approval_mode.value,
                "confidence_threshold": ai_config.confidence_threshold,
            },
        )

    def _save_rule_conditions(
        self,
        strategy_orm: StrategyModel,
        rule_conditions: list[RuleCondition],
    ) -> None:
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
                is_enabled=rule.is_enabled,
            )

    def get_by_id(self, strategy_id: int) -> Strategy | None:
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

    def get_by_user(self, user_id: int, is_active: bool = True) -> list[Strategy]:
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

    def get_active_strategies_for_portfolio(self, portfolio_id: int) -> list[Strategy]:
        """
        获取投资组合的激活策略

        Args:
            portfolio_id: 投资组合ID

        Returns:
            策略实体列表
        """
        assignments = (
            PortfolioStrategyAssignmentModel._default_manager.filter(
                portfolio_id=portfolio_id, is_active=True
            )
            .select_related("strategy")
            .prefetch_related(
                Prefetch(
                    "strategy__rules",
                    queryset=RuleConditionModel._default_manager.filter(is_enabled=True),
                )
            )
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
            "BUY": ActionType.BUY,
            "SELL": ActionType.SELL,
            "HOLD": ActionType.HOLD,
            "WEIGHT": ActionType.WEIGHT,
            "buy": ActionType.BUY,
            "sell": ActionType.SELL,
            "hold": ActionType.HOLD,
            "weight": ActionType.WEIGHT,
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
            created_at=orm_obj.created_at,
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
            if condition.strategy_id is None:
                raise ValueError("new rule condition requires strategy_id")
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
                is_enabled=condition.is_enabled,
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

        return int(orm_obj.id)

    def get_by_strategy(self, strategy_id: int) -> list[RuleCondition]:
        """
        获取策略的所有规则条件

        Args:
            strategy_id: 策略ID

        Returns:
            规则条件实体列表
        """
        orm_objects = (
            RuleConditionModel._default_manager.filter(strategy_id=strategy_id)
            .order_by("-priority", "-created_at")
            .all()
        )

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
        return int(count) > 0


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
            signals.append(
                SignalRecommendation(
                    asset_code=signal_data.get("asset_code", ""),
                    asset_name=signal_data.get("asset_name", ""),
                    action=ActionType(signal_data.get("action", "hold")),
                    weight=signal_data.get("weight"),
                    quantity=signal_data.get("quantity"),
                    reason=signal_data.get("reason", ""),
                    confidence=signal_data.get("confidence", 0.0),
                    metadata=signal_data.get("metadata", {}),
                )
            )

        return StrategyExecutionResult(
            strategy_id=orm_obj.strategy_id,
            portfolio_id=orm_obj.portfolio_id,
            execution_time=orm_obj.execution_time,
            execution_duration_ms=orm_obj.execution_duration_ms,
            signals=signals,
            is_success=orm_obj.is_success,
            error_message=orm_obj.error_message,
            context=orm_obj.execution_result,
        )

    def save(self, result: StrategyExecutionResult) -> int:
        """
        保存执行日志

        Args:
            result: 策略执行结果

        Returns:
            日志ID
        """
        from apps.strategy.infrastructure.models import StrategyModel

        if not StrategyModel._default_manager.filter(id=result.strategy_id).exists():
            logger.warning(
                f"Cannot save execution log: strategy={result.strategy_id} does not exist"
            )
            return 0  # 返回0表示保存失败

        # 转换信号列表为 JSON 格式
        signals_json = [
            {
                "asset_code": s.asset_code,
                "asset_name": s.asset_name,
                "action": s.action.value,
                "weight": s.weight,
                "quantity": s.quantity,
                "reason": s.reason,
                "confidence": s.confidence,
                "metadata": s.metadata,
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
                error_message=result.error_message,
            )
            return int(orm_obj.id)
        except IntegrityError as e:
            logger.warning(
                "Cannot save execution log due to invalid foreign key: "
                f"strategy={result.strategy_id}, portfolio={result.portfolio_id}, error={e}"
            )
            return 0
        except Exception as e:
            # 如果保存失败（如外键约束），记录日志但不抛出异常
            logger.error(f"Failed to save execution log: {e}")
            return 0  # 返回0表示保存失败

    def get_by_strategy(self, strategy_id: int, limit: int = 100) -> list[StrategyExecutionResult]:
        """
        获取策略的执行日志

        Args:
            strategy_id: 策略ID
            limit: 返回数量限制

        Returns:
            执行结果列表
        """
        orm_objects = (
            StrategyExecutionLogModel._default_manager.filter(strategy_id=strategy_id)
            .order_by("-execution_time")[:limit]
            .all()
        )

        return [self._orm_to_domain_entity(obj) for obj in orm_objects]

    def get_by_portfolio(
        self, portfolio_id: int, limit: int = 100
    ) -> list[StrategyExecutionResult]:
        """
        获取投资组合的执行日志

        Args:
            portfolio_id: 投资组合ID
            limit: 返回数量限制

        Returns:
            执行结果列表
        """
        orm_objects = (
            StrategyExecutionLogModel._default_manager.filter(portfolio_id=portfolio_id)
            .order_by("-execution_time")[:limit]
            .all()
        )

        return [self._orm_to_domain_entity(obj) for obj in orm_objects]


# ========================================================================
# Strategy Param Version Repository
# ========================================================================


class StrategyParamRepository:
    """策略参数版本仓储"""

    def get_active_params(self, strategy_id: int) -> dict[str, Any]:
        """
        获取策略的激活参数

        Args:
            strategy_id: 策略ID

        Returns:
            参数字典，如果不存在返回空字典
        """
        try:
            orm_obj = StrategyParamVersionModel._default_manager.filter(
                strategy_id=strategy_id, is_active=True
            ).latest("created_at")
            params: dict[str, Any] = orm_obj.params_json
            return params
        except StrategyParamVersionModel.DoesNotExist:
            return {}

    def save_params(
        self,
        strategy_id: int,
        params: dict[str, Any],
        version: int,
        change_description: str = "",
        changed_by_id: int | None = None,
        set_as_active: bool = True,
        promotion_decision_id: str | None = None,
    ) -> StrategyParamVersionModel | None:
        """
        保存策略参数新版本

        Args:
            strategy_id: 策略ID
            params: 参数字典
            version: 版本号
            change_description: 变更说明
            changed_by_id: 变更者ID
            set_as_active: 是否设置为激活版本

        Returns:
            创建的参数版本对象，失败返回 None
        """
        from apps.strategy.infrastructure.models import StrategyModel

        try:
            with transaction.atomic():
                # 验证策略存在
                StrategyModel._default_manager.get(id=strategy_id)
                if set_as_active and not self._promotion_is_approved(promotion_decision_id):
                    raise ValueError(
                        "active strategy parameters require an approved research promotion"
                    )

                # 如果设置为激活，先取消其他激活版本
                if set_as_active:
                    StrategyParamVersionModel._default_manager.filter(
                        strategy_id=strategy_id, is_active=True
                    ).update(is_active=False)

                # 创建新版本
                param_version = StrategyParamVersionModel._default_manager.create(
                    strategy_id=strategy_id,
                    version=version,
                    params_json=params,
                    is_active=set_as_active,
                    change_description=change_description,
                    changed_by_id=changed_by_id,
                    promotion_decision_id=promotion_decision_id,
                )

                logger.info(
                    f"Created param version {version} for strategy {strategy_id}: "
                    f"{change_description}"
                )
                return param_version

        except StrategyModel.DoesNotExist:
            logger.error(f"Strategy {strategy_id} does not exist")
            return None
        except Exception as e:
            logger.error(f"Failed to save params for strategy {strategy_id}: {e}")
            return None

    def rollback_to_version(self, strategy_id: int, version: int) -> bool:
        """
        回滚到指定版本的参数

        Args:
            strategy_id: 策略ID
            version: 目标版本号

        Returns:
            是否回滚成功
        """
        try:
            with transaction.atomic():
                # 获取目标版本
                target_version = StrategyParamVersionModel._default_manager.get(
                    strategy_id=strategy_id, version=version
                )
                if not self._promotion_is_approved(target_version.promotion_decision_id):
                    raise ValueError("rollback target lacks an approved research promotion")

                # 创建新版本（复制目标版本的参数）
                # 获取当前最大版本号
                max_version = (
                    StrategyParamVersionModel._default_manager.filter(
                        strategy_id=strategy_id
                    ).aggregate(max_v=Max("version"))["max_v"]
                    or 0
                )

                new_version = max_version + 1

                # 取消所有激活版本
                StrategyParamVersionModel._default_manager.filter(
                    strategy_id=strategy_id, is_active=True
                ).update(is_active=False)

                # 创建回滚版本（记录为从旧版本回滚）
                StrategyParamVersionModel._default_manager.create(
                    strategy_id=strategy_id,
                    version=new_version,
                    params_json=target_version.params_json,
                    is_active=True,
                    change_description=f"从版本 {version} 回滚",
                    changed_by_id=target_version.changed_by_id,
                    promotion_decision_id=target_version.promotion_decision_id,
                )

                logger.info(
                    f"Rolled back strategy {strategy_id} to version {version}, "
                    f"created new version {new_version}"
                )
                return True

        except StrategyParamVersionModel.DoesNotExist:
            logger.error(f"Version {version} not found for strategy {strategy_id}")
            return False
        except Exception as e:
            logger.error(f"Failed to rollback strategy {strategy_id} to version {version}: {e}")
            return False

    def get_next_version(self, strategy_id: int) -> int:
        """
        获取下一个版本号

        Args:
            strategy_id: 策略ID

        Returns:
            下一个版本号（如果没有历史版本，返回1）
        """
        from django.db.models import Max

        max_version = StrategyParamVersionModel._default_manager.filter(
            strategy_id=strategy_id
        ).aggregate(max_v=Max("version"))["max_v"]

        return (max_version or 0) + 1

    def set_active_version(self, strategy_id: int, version: int) -> bool:
        """
        设置指定版本为激活版本（不创建新版本）

        Args:
            strategy_id: 策略ID
            version: 版本号

        Returns:
            是否设置成功
        """
        try:
            with transaction.atomic():
                target = StrategyParamVersionModel._default_manager.get(
                    strategy_id=strategy_id,
                    version=version,
                )
                if not self._promotion_is_approved(target.promotion_decision_id):
                    raise ValueError(
                        "active strategy parameters require an approved research promotion"
                    )
                # 取消所有激活版本
                StrategyParamVersionModel._default_manager.filter(
                    strategy_id=strategy_id, is_active=True
                ).update(is_active=False)

                # 激活目标版本
                count = StrategyParamVersionModel._default_manager.filter(
                    strategy_id=strategy_id, version=version
                ).update(is_active=True)

                if count == 0:
                    logger.error(f"Version {version} not found for strategy {strategy_id}")
                    return False

                logger.info(f"Set version {version} as active for strategy {strategy_id}")
                return True

        except Exception as e:
            logger.error(f"Failed to set active version {version} for strategy {strategy_id}: {e}")
            return False

    @staticmethod
    def _promotion_is_approved(promotion_decision_id: str | None) -> bool:
        """Apply the research gate only after its cutover flag is enabled."""

        from django.conf import settings

        if not bool(getattr(settings, "RESEARCH_PIT_REQUIRED_FOR_PROMOTION", False)):
            return True
        if not promotion_decision_id:
            return False
        from core.integration.research_integrity_registry import (
            is_research_promotion_approved,
        )

        return bool(is_research_promotion_approved(promotion_decision_id))


# ========================================================================
# Order Intent Repository
# ========================================================================


class DjangoOrderIntentRepository:
    """订单意图仓储（支持幂等查重与状态更新）"""

    @classmethod
    def _orm_to_domain_entity(cls, orm_obj: Any) -> OrderIntent:
        decision = build_decision(orm_obj.decision_json or {})
        sizing = build_sizing(orm_obj.sizing_json or {})
        risk_snapshot = build_risk_snapshot(orm_obj.risk_snapshot_json or {})
        return OrderIntent(
            intent_id=orm_obj.intent_id,
            strategy_id=orm_obj.strategy_id,
            portfolio_id=orm_obj.portfolio_id,
            symbol=orm_obj.symbol,
            side=OrderSide(orm_obj.side),
            qty=orm_obj.qty,
            decision=decision,
            sizing=sizing,
            risk_snapshot=risk_snapshot,
            limit_price=orm_obj.limit_price,
            time_in_force=TimeInForce(orm_obj.time_in_force),
            reason=orm_obj.reason,
            idempotency_key=orm_obj.idempotency_key,
            status=OrderStatus(orm_obj.status),
            created_at=orm_obj.created_at,
            updated_at=orm_obj.updated_at,
        )

    def save(self, intent: OrderIntent) -> OrderIntent:
        from django.conf import settings

        if bool(getattr(settings, "PORTFOLIO_CANONICAL_PLANNER_ENABLED", False)):
            logger.warning(
                "Blocked deprecated strategy OrderIntent write",
                extra={"intent_id": intent.intent_id},
            )
            raise ValueError("strategy order intents are read-only; use portfolio order drafts")
        model = _order_intent_model()
        with transaction.atomic():
            defaults = {
                "strategy_id": intent.strategy_id,
                "portfolio_id": intent.portfolio_id,
                "symbol": intent.symbol,
                "side": intent.side.value,
                "qty": intent.qty,
                "limit_price": intent.limit_price,
                "time_in_force": intent.time_in_force.value,
                "reason": intent.reason,
                "status": intent.status.value,
                "decision_json": intent.decision.to_dict(),
                "sizing_json": intent.sizing.to_dict(),
                "risk_snapshot_json": intent.risk_snapshot.to_dict(),
            }
            if intent.created_at is not None:
                defaults["created_at"] = intent.created_at

            model._default_manager.update_or_create(
                intent_id=intent.intent_id,
                defaults={**defaults, "idempotency_key": intent.idempotency_key},
            )
            orm_obj = model._default_manager.get(intent_id=intent.intent_id)
            return self._orm_to_domain_entity(orm_obj)

    def get_by_id(self, intent_id: str) -> OrderIntent | None:
        model = _order_intent_model()
        try:
            orm_obj = model._default_manager.get(intent_id=intent_id)
            return self._orm_to_domain_entity(orm_obj)
        except model.DoesNotExist:
            return None

    def get_by_idempotency_key(self, idempotency_key: str) -> OrderIntent | None:
        model = _order_intent_model()
        try:
            orm_obj = model._default_manager.get(idempotency_key=idempotency_key)
            return self._orm_to_domain_entity(orm_obj)
        except model.DoesNotExist:
            return None

    def update_status(self, intent_id: str, status: OrderStatus) -> bool:
        updated = (
            _order_intent_model()
            ._default_manager.filter(intent_id=intent_id)
            .update(status=status.value)
        )
        return int(updated) > 0

    def get_pending_intents(self, portfolio_id: int) -> list[OrderIntent]:
        orm_objects = (
            _order_intent_model()
            ._default_manager.filter(
                portfolio_id=portfolio_id,
                status__in=[
                    OrderStatus.DRAFT.value,
                    OrderStatus.PENDING_APPROVAL.value,
                    OrderStatus.APPROVED.value,
                ],
            )
            .order_by("-created_at")
            .all()
        )
        return [self._orm_to_domain_entity(obj) for obj in orm_objects]


class DjangoStrategyGatewayRepository:
    """Strategy gateway 的只读查询仓储。"""

    def get_strategy_info(self, strategy_id: int) -> dict[str, Any] | None:
        strategy = StrategyModel._default_manager.filter(id=strategy_id).first()
        if not strategy:
            return None
        return {
            "strategy_id": strategy.id,
            "name": strategy.name,
            "strategy_type": strategy.strategy_type,
            "is_active": strategy.is_active,
            "description": strategy.description,
        }

    def get_active_strategy_binding(self, account_id: int) -> dict[str, Any] | None:
        assignment = (
            PortfolioStrategyAssignmentModel._default_manager.filter(
                portfolio_id=account_id,
                is_active=True,
                strategy__is_active=True,
            )
            .select_related("strategy")
            .order_by("-updated_at", "-id")
            .first()
        )
        if not assignment or not assignment.strategy:
            return None
        return {
            "strategy_id": assignment.strategy_id,
            "name": assignment.strategy.name,
            "strategy_type": assignment.strategy.strategy_type,
            "is_active": assignment.strategy.is_active,
            "description": assignment.strategy.description,
        }

    def get_inspection_selection(
        self,
        account_id: int,
        strategy_id: int | None = None,
    ) -> InspectionSelection:
        from apps.strategy.application.execution_gateway import InspectionSelection

        if strategy_id:
            strategy = StrategyModel._default_manager.filter(id=strategy_id).first()
            rule = (
                PositionManagementRuleModel._default_manager.filter(
                    strategy_id=strategy_id,
                    is_active=True,
                )
                .order_by("-updated_at")
                .first()
            )
            return InspectionSelection(
                strategy_id=getattr(strategy, "id", None),
                position_rule_id=getattr(rule, "id", None),
                rule_metadata=getattr(rule, "metadata", {}) or {},
                strategy_name=getattr(strategy, "name", None),
                strategy_type=getattr(strategy, "strategy_type", None),
            )

        rule = (
            PositionManagementRuleModel._default_manager.filter(
                is_active=True,
                metadata__account_id=account_id,
            )
            .select_related("strategy")
            .order_by("-updated_at")
            .first()
        )
        strategy = getattr(rule, "strategy", None)
        return InspectionSelection(
            strategy_id=getattr(strategy, "id", None),
            position_rule_id=getattr(rule, "id", None),
            rule_metadata=getattr(rule, "metadata", {}) or {},
            strategy_name=getattr(strategy, "name", None),
            strategy_type=getattr(strategy, "strategy_type", None),
        )

    def evaluate_position_rule(
        self,
        rule_id: int | None,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not rule_id:
            return None

        from apps.strategy.application.position_management_service import PositionManagementService

        rule = PositionManagementRuleModel._default_manager.filter(id=rule_id).first()
        if not rule:
            return None
        result: dict[str, Any] = PositionManagementService.evaluate(
            rule=rule,
            context=context,
        ).to_dict()
        return result


class StrategyInterfaceRepository:
    """Strategy interface 层只读/轻写入仓储。"""

    def get_strategy_queryset(self) -> QuerySet[StrategyModel]:
        queryset: QuerySet[StrategyModel] = StrategyModel._default_manager.select_related(
            "created_by"
        ).all()
        return queryset

    def get_strategy_queryset_for_owner(
        self,
        owner_profile_id: int,
    ) -> QuerySet[StrategyModel]:
        return self.get_strategy_queryset().filter(created_by_id=owner_profile_id)

    def get_strategy_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> QuerySet[StrategyModel]:
        """Return strategies visible to one authenticated owner or staff caller."""

        queryset = self.get_strategy_queryset()
        if include_all:
            return queryset
        if owner_profile_id is None:
            return queryset.none()
        return queryset.filter(created_by_id=owner_profile_id)

    def list_user_strategies_with_counts(
        self,
        owner_profile_id: int,
    ) -> QuerySet[StrategyModel]:
        queryset: QuerySet[StrategyModel] = (
            self.get_strategy_queryset_for_owner(owner_profile_id)
            .annotate(
                rule_count=Count("rules", distinct=True),
                execution_count=Count("execution_logs", distinct=True),
                portfolio_count=Count("portfolio_assignments", distinct=True),
            )
            .order_by("-created_at")
        )
        return queryset

    def get_user_strategy_stats(self, owner_profile_id: int) -> dict[str, Any]:
        queryset = StrategyModel._default_manager.filter(created_by_id=owner_profile_id)
        return {
            "total": queryset.count(),
            "active": queryset.filter(is_active=True).count(),
            "inactive": queryset.filter(is_active=False).count(),
            "by_type": {
                "rule_based": queryset.filter(strategy_type="rule_based").count(),
                "script_based": queryset.filter(strategy_type="script_based").count(),
                "hybrid": queryset.filter(strategy_type="hybrid").count(),
                "ai_driven": queryset.filter(strategy_type="ai_driven").count(),
            },
        }

    def list_strategy_rule_summary(
        self,
        strategy_id: int,
        limit: int = 3,
    ) -> list[RuleConditionModel]:
        rows: list[RuleConditionModel] = list(
            RuleConditionModel._default_manager.filter(
                strategy_id=strategy_id,
                is_enabled=True,
            ).order_by("-priority", "-created_at")[:limit]
        )
        return rows

    def replace_rule_conditions(
        self,
        strategy_id: int,
        validated_rules: list[dict[str, Any]],
    ) -> None:
        with transaction.atomic():
            RuleConditionModel._default_manager.filter(strategy_id=strategy_id).delete()
            for validated_rule in validated_rules:
                RuleConditionModel._default_manager.create(**validated_rule)

    def get_strategy_script_config(
        self,
        strategy_id: int,
    ) -> ScriptConfigModel | None:
        config: ScriptConfigModel | None = ScriptConfigModel._default_manager.filter(
            strategy_id=strategy_id
        ).first()
        return config

    def delete_strategy_script_config(self, strategy_id: int) -> None:
        ScriptConfigModel._default_manager.filter(strategy_id=strategy_id).delete()

    def get_strategy_ai_config(
        self,
        strategy_id: int,
    ) -> AIStrategyConfigModel | None:
        config: AIStrategyConfigModel | None = AIStrategyConfigModel._default_manager.filter(
            strategy_id=strategy_id
        ).first()
        return config

    def list_active_prompt_templates(self) -> list[PromptTemplateORM]:
        templates: list[PromptTemplateORM] = list(
            PromptTemplateORM._default_manager.filter(is_active=True).order_by("category", "name")
        )
        return templates

    def list_active_chain_configs(self) -> list[ChainConfigORM]:
        configs: list[ChainConfigORM] = list(
            ChainConfigORM._default_manager.filter(is_active=True).order_by("category", "name")
        )
        return configs

    def list_active_ai_providers_for_user(
        self,
        user_id: int,
    ) -> list[AIProviderConfig]:
        providers: list[AIProviderConfig] = list(
            AIProviderConfig._default_manager.filter(
                Q(scope="system") | Q(scope="user", owner_user_id=user_id),
                is_active=True,
            ).order_by("priority", "name")
        )
        return providers

    def get_strategy_execution_logs_page(
        self,
        strategy_id: int,
        offset: int,
        limit: int,
    ) -> tuple[QuerySet[StrategyExecutionLogModel], int]:
        queryset: QuerySet[StrategyExecutionLogModel] = (
            StrategyExecutionLogModel._default_manager.filter(strategy_id=strategy_id)
            .select_related("strategy", "portfolio")
            .order_by("-execution_time")
        )
        return queryset[offset : offset + limit], int(queryset.count())

    def get_strategy_position_rule(
        self,
        strategy_id: int,
    ) -> PositionManagementRuleModel | None:
        rule: PositionManagementRuleModel | None = (
            PositionManagementRuleModel._default_manager.select_related("strategy")
            .filter(strategy_id=strategy_id)
            .first()
        )
        return rule

    def get_position_management_rule_queryset(
        self,
    ) -> QuerySet[PositionManagementRuleModel]:
        queryset: QuerySet[PositionManagementRuleModel] = (
            PositionManagementRuleModel._default_manager.select_related("strategy").all()
        )
        return queryset

    def get_position_management_rule_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> QuerySet[PositionManagementRuleModel]:
        """Return position rules visible to one owner or staff caller."""

        queryset = self.get_position_management_rule_queryset()
        if include_all:
            return queryset
        if owner_profile_id is None:
            return queryset.none()
        return queryset.filter(strategy__created_by_id=owner_profile_id)

    def get_rule_condition_queryset(self) -> QuerySet[RuleConditionModel]:
        queryset: QuerySet[RuleConditionModel] = RuleConditionModel._default_manager.select_related(
            "strategy"
        ).all()
        return queryset

    def get_script_config_queryset(self) -> QuerySet[ScriptConfigModel]:
        queryset: QuerySet[ScriptConfigModel] = ScriptConfigModel._default_manager.select_related(
            "strategy"
        ).order_by(
            "strategy_id",
            "id",
        )
        return queryset

    def get_script_config_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> QuerySet[ScriptConfigModel]:
        """Return script configurations visible to one owner or staff caller."""

        queryset = self.get_script_config_queryset()
        if include_all:
            return queryset
        if owner_profile_id is None:
            return queryset.none()
        return queryset.filter(strategy__created_by_id=owner_profile_id)

    def get_ai_strategy_config_queryset(self) -> QuerySet[AIStrategyConfigModel]:
        queryset: QuerySet[AIStrategyConfigModel] = (
            AIStrategyConfigModel._default_manager.select_related(
                "strategy",
                "prompt_template",
                "chain_config",
                "ai_provider",
            ).order_by("strategy_id", "id")
        )
        return queryset

    def get_ai_strategy_config_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> QuerySet[AIStrategyConfigModel]:
        """Return AI strategy configs visible to one owner or staff caller."""

        queryset = self.get_ai_strategy_config_queryset()
        if include_all:
            return queryset
        if owner_profile_id is None:
            return queryset.none()
        return queryset.filter(strategy__created_by_id=owner_profile_id)

    def strategy_is_accessible(
        self,
        *,
        strategy_id: int,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> bool:
        """Return whether one caller may configure the selected strategy."""

        return self.get_strategy_queryset_for_access(
            owner_profile_id=owner_profile_id,
            include_all=include_all,
        ).filter(pk=strategy_id).exists()

    def get_assignment_queryset(
        self,
    ) -> QuerySet[PortfolioStrategyAssignmentModel]:
        queryset: QuerySet[PortfolioStrategyAssignmentModel] = (
            PortfolioStrategyAssignmentModel._default_manager.select_related(
                "portfolio",
                "strategy",
                "assigned_by",
            ).all()
        )
        return queryset

    def get_assignment_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> QuerySet[PortfolioStrategyAssignmentModel]:
        """Return assignments owned through both strategy and portfolio."""

        queryset = self.get_assignment_queryset()
        if include_all:
            return queryset
        if owner_profile_id is None:
            return queryset.none()
        return queryset.filter(
            strategy__created_by_id=owner_profile_id,
            portfolio__user__account_profile__id=owner_profile_id,
        )

    def list_assignments_by_portfolio(
        self,
        portfolio_id: int,
    ) -> QuerySet[PortfolioStrategyAssignmentModel]:
        return self.get_assignment_queryset().filter(portfolio_id=portfolio_id)

    def list_assignments_by_portfolio_for_access(
        self,
        *,
        portfolio_id: int,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> QuerySet[PortfolioStrategyAssignmentModel]:
        """Return visible assignments for one portfolio."""

        return self.get_assignment_queryset_for_access(
            owner_profile_id=owner_profile_id,
            include_all=include_all,
        ).filter(portfolio_id=portfolio_id)

    def list_active_assignments_for_strategy(
        self,
        strategy_id: int,
    ) -> list[PortfolioStrategyAssignmentModel]:
        assignments: list[PortfolioStrategyAssignmentModel] = list(
            self.get_assignment_queryset().filter(
                strategy_id=strategy_id,
                is_active=True,
            )
        )
        return assignments

    def bind_strategy(
        self,
        *,
        portfolio_id: int,
        strategy: StrategyModel,
        assigned_by: Any,
    ) -> PortfolioStrategyAssignmentModel:
        with transaction.atomic():
            assignments: QuerySet[
                PortfolioStrategyAssignmentModel
            ] = PortfolioStrategyAssignmentModel._default_manager.select_for_update().filter(
                portfolio_id=portfolio_id
            )
            assignments.filter(is_active=True).exclude(strategy=strategy).update(is_active=False)
            assignment_result: tuple[PortfolioStrategyAssignmentModel, bool] = (
                assignments.get_or_create(
                    portfolio_id=portfolio_id,
                    strategy=strategy,
                    defaults={
                        "assigned_by": assigned_by,
                        "is_active": True,
                    },
                )
            )
            assignment, created = assignment_result
            if not created and (
                not assignment.is_active or assignment.assigned_by_id != assigned_by.id
            ):
                assignment.is_active = True
                assignment.assigned_by = assigned_by
                assignment.save(update_fields=["is_active", "assigned_by", "updated_at"])
            return assignment

    def unbind_portfolio_strategies(self, portfolio_id: int) -> None:
        with transaction.atomic():
            PortfolioStrategyAssignmentModel._default_manager.select_for_update().filter(
                portfolio_id=portfolio_id,
                is_active=True,
            ).update(is_active=False)

    def set_strategy_active(
        self,
        strategy_id: int,
        is_active: bool,
    ) -> StrategyModel | None:
        strategy = StrategyModel._default_manager.filter(id=strategy_id).first()
        if strategy is None:
            return None
        strategy.is_active = is_active
        strategy.save(update_fields=["is_active", "updated_at"])
        return strategy

    def set_rule_enabled(
        self,
        rule_id: int,
        is_enabled: bool,
    ) -> RuleConditionModel | None:
        rule = RuleConditionModel._default_manager.filter(id=rule_id).first()
        if rule is None:
            return None
        rule.is_enabled = is_enabled
        rule.save(update_fields=["is_enabled", "updated_at"])
        return rule

    def set_assignment_active(
        self,
        assignment_id: int,
        is_active: bool,
    ) -> PortfolioStrategyAssignmentModel | None:
        assignment = PortfolioStrategyAssignmentModel._default_manager.filter(
            id=assignment_id
        ).first()
        if assignment is None:
            return None
        assignment.is_active = is_active
        assignment.save(update_fields=["is_active", "updated_at"])
        return assignment

    def get_execution_log_queryset(
        self,
    ) -> QuerySet[StrategyExecutionLogModel]:
        queryset: QuerySet[StrategyExecutionLogModel] = (
            StrategyExecutionLogModel._default_manager.select_related(
                "strategy",
                "portfolio",
            ).all()
        )
        return queryset

    def list_execution_logs_by_strategy(
        self,
        strategy_id: int,
        limit: int = 100,
    ) -> list[StrategyExecutionLogModel]:
        logs: list[StrategyExecutionLogModel] = list(
            self.get_execution_log_queryset().filter(strategy_id=strategy_id)[:limit]
        )
        return logs

    def list_execution_logs_by_portfolio(
        self,
        portfolio_id: int,
        limit: int = 100,
    ) -> list[StrategyExecutionLogModel]:
        logs: list[StrategyExecutionLogModel] = list(
            self.get_execution_log_queryset().filter(portfolio_id=portfolio_id)[:limit]
        )
        return logs
