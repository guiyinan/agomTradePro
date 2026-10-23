"""Django ORM repository for strategy execution history."""

from __future__ import annotations

import logging

from django.db import IntegrityError

from apps.strategy.domain.entities import (
    ActionType,
    SignalRecommendation,
    StrategyExecutionResult,
)
from apps.strategy.infrastructure.models import StrategyExecutionLogModel

logger = logging.getLogger("apps.strategy.infrastructure.repositories")


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
