"""
持仓证伪检查服务

定期检查所有持仓的证伪条件是否满足，满足时标记并提示平仓。
"""

from datetime import datetime
from typing import Dict, List, Optional

from django.utils import timezone

from apps.signal.domain.invalidation import (
    IndicatorValue,
    InvalidationCheckResult,
    InvalidationRule,
    evaluate_rule,
)
from apps.simulated_trading.domain.entities import Position
from apps.simulated_trading.infrastructure.repositories import DjangoPositionRepository


class PositionInvalidationChecker:
    """持仓证伪检查器

    负责检查持仓的证伪条件是否满足。
    """

    def __init__(self):
        """初始化检查器"""
        # 延迟导入避免循环依赖
        from apps.macro.infrastructure.repositories import DjangoMacroRepository
        self.macro_repo = DjangoMacroRepository()
        self.position_repo = DjangoPositionRepository()

    def check_all_positions(self) -> list[dict]:
        """
        检查所有有证伪规则的持仓

        Returns:
            List[Dict]: 被证伪的持仓列表
        """
        # 获取所有有证伪规则且未被证伪的持仓
        positions = self.position_repo.get_pending_invalidation_positions()

        invalidated = []

        for position in positions:
            result = self._check_position(position)
            if result and result.is_invalidated:
                # 更新持仓的证伪状态
                self._mark_position_invalidated(position, result)
                invalidated.append({
                    'position_id': None,
                    'account_id': position.account_id,
                    'asset_code': position.asset_code,
                    'asset_name': position.asset_name,
                    'reason': result.reason,
                })

        return invalidated

    def check_position(self, position_id: int) -> InvalidationCheckResult | None:
        """
        检查单个持仓的证伪状态

        Args:
            position_id: 持仓ID

        Returns:
            InvalidationCheckResult 或 None
        """
        position = self.position_repo.get_position_by_id(position_id)
        if not position or not position.invalidation_rule_json or position.is_invalidated:
            return None
        return self._check_position(position)

    def _check_position(self, position: Position) -> InvalidationCheckResult | None:
        """
        检查持仓的证伪状态

        Args:
            position: Position 实体

        Returns:
            InvalidationCheckResult 或 None
        """
        import json

        # 解析证伪规则
        try:
            rule_dict = position.invalidation_rule_json
            rule = InvalidationRule.from_dict(rule_dict)
        except (KeyError, ValueError, TypeError):
            # 规则格式错误，无法检查
            return None

        # 获取指标值
        indicator_values = self._fetch_indicator_values(rule)

        # 评估规则（Domain 层纯函数）
        result = evaluate_rule(rule, indicator_values)

        # 更新检查时间
        self.position_repo.mark_invalidation_checked(
            account_id=position.account_id,
            asset_code=position.asset_code,
            checked_at=timezone.now(),
        )

        return result

    def _fetch_indicator_values(self, rule: InvalidationRule) -> dict[str, IndicatorValue]:
        """
        获取规则中所有指标的当前值

        Args:
            rule: 证伪规则

        Returns:
            Dict[str, IndicatorValue]: 指标值字典
        """
        values = {}

        for condition in rule.conditions:
            code = condition.indicator_code

            # 避免重复获取
            if code in values:
                continue

            # 从数据库获取指标数据
            try:
                latest = self.macro_repo.get_latest_by_code(code)
                if latest:
                    history = self.macro_repo.get_history_by_code(code, periods=12)
                    values[code] = IndicatorValue(
                        code=code,
                        current_value=latest.value,
                        history_values=[d.value for d in history],
                        unit=latest.unit or "",
                        last_updated=latest.observed_at.isoformat() if latest.observed_at else None,
                    )
                else:
                    values[code] = IndicatorValue(
                        code=code,
                        current_value=None,
                        history_values=[],
                        unit="",
                        last_updated=None,
                    )
            except Exception:
                # 获取失败，使用空值
                values[code] = IndicatorValue(
                    code=code,
                    current_value=None,
                    history_values=[],
                    unit="",
                    last_updated=None,
                )

        return values

    def _mark_position_invalidated(self, position: Position, result: InvalidationCheckResult):
        """
        标记持仓为已证伪

        Args:
            position: 持仓模型
            result: 证伪检查结果
        """
        self.position_repo.mark_invalidated(
            account_id=position.account_id,
            asset_code=position.asset_code,
            reason=result.reason,
            checked_at=timezone.now(),
        )

        # 记录日志
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            f"持仓证伪: {position.account_id} - {position.asset_code} - {result.reason}"
        )

    def get_positions_to_close(self) -> list[dict]:
        """
        获取所有应该平仓的持仓（已证伪）

        Returns:
            List[dict]: 应该平仓的持仓摘要列表
        """
        return self.position_repo.get_invalidated_position_summaries()


# ==================== 导出函数，供 Celery 任务使用 ====================

def check_and_invalidate_positions() -> dict:
    """
    检查并证伪满足条件的持仓

    这是一个导出函数，供 Celery 任务调用。

    Returns:
        Dict: 包含统计信息
    """
    checker = PositionInvalidationChecker()
    invalidated = checker.check_all_positions()

    return {
        'checked': checker.position_repo.count_positions_with_invalidation_rules(),
        'invalidated': len(invalidated),
        'positions': invalidated
    }


def get_invalidated_positions_summary() -> list[dict]:
    """
    获取已证伪持仓的摘要

    Returns:
        List[Dict]: 已证伪持仓的摘要列表
    """
    checker = PositionInvalidationChecker()
    positions = checker.get_positions_to_close()

    return positions

