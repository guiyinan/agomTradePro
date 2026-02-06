"""
持仓证伪检查服务

定期检查所有持仓的证伪条件是否满足，满足时标记并提示平仓。
"""

from datetime import datetime
from typing import List, Dict, Optional

from django.utils import timezone

from apps.signal.domain.invalidation import (
    InvalidationRule,
    InvalidationCheckResult,
    IndicatorValue,
    evaluate_rule,
)
from apps.simulated_trading.infrastructure.models import PositionModel
from apps.simulated_trading.infrastructure.repositories import PositionRepository


class PositionInvalidationChecker:
    """持仓证伪检查器

    负责检查持仓的证伪条件是否满足。
    """

    def __init__(self):
        """初始化检查器"""
        # 延迟导入避免循环依赖
        from apps.macro.infrastructure.repositories import DjangoMacroRepository
        self.macro_repo = DjangoMacroRepository()
        self.position_repo = PositionRepository()

    def check_all_positions(self) -> List[Dict]:
        """
        检查所有有证伪规则的持仓

        Returns:
            List[Dict]: 被证伪的持仓列表
        """
        # 获取所有有证伪规则且未被证伪的持仓
        positions = PositionModel._default_manager.filter(
            invalidation_rule_json__isnull=False,
            invalidation_rule_json____isnull=False,  # 不为空
            is_invalidated=False,
        ).exclude(invalidation_rule_json={})

        invalidated = []

        for position in positions:
            result = self._check_position(position)
            if result and result.is_invalidated:
                # 更新持仓的证伪状态
                self._mark_position_invalidated(position, result)
                invalidated.append({
                    'position_id': position.id,
                    'account_id': position.account_id,
                    'asset_code': position.asset_code,
                    'asset_name': position.asset_name,
                    'reason': result.reason,
                })

        return invalidated

    def check_position(self, position_id: int) -> Optional[InvalidationCheckResult]:
        """
        检查单个持仓的证伪状态

        Args:
            position_id: 持仓ID

        Returns:
            InvalidationCheckResult 或 None
        """
        try:
            position = PositionModel._default_manager.get(id=position_id)

            if not position.invalidation_rule_json:
                return None

            if position.is_invalidated:
                return None

            return self._check_position(position)

        except PositionModel.DoesNotExist:
            return None

    def _check_position(self, position: PositionModel) -> Optional[InvalidationCheckResult]:
        """
        检查持仓的证伪状态

        Args:
            position: PositionModel 实例

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
        position.invalidation_checked_at = timezone.now()
        position.save(update_fields=['invalidation_checked_at'])

        return result

    def _fetch_indicator_values(self, rule: InvalidationRule) -> Dict[str, IndicatorValue]:
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

    def _mark_position_invalidated(self, position: PositionModel, result: InvalidationCheckResult):
        """
        标记持仓为已证伪

        Args:
            position: 持仓模型
            result: 证伪检查结果
        """
        position.is_invalidated = True
        position.invalidation_reason = result.reason
        position.invalidation_checked_at = timezone.now()
        position.save()

        # 记录日志
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            f"持仓证伪: {position.account_id} - {position.asset_code} - {result.reason}"
        )

    def get_positions_to_close(self) -> List[PositionModel]:
        """
        获取所有应该平仓的持仓（已证伪）

        Returns:
            List[PositionModel]: 应该平仓的持仓列表
        """
        return PositionModel._default_manager.filter(
            is_invalidated=True,
            quantity__gt=0,  # 仍有持仓
        ).order_by('-invalidation_checked_at')


# ==================== 导出函数，供 Celery 任务使用 ====================

def check_and_invalidate_positions() -> Dict:
    """
    检查并证伪满足条件的持仓

    这是一个导出函数，供 Celery 任务调用。

    Returns:
        Dict: 包含统计信息
    """
    checker = PositionInvalidationChecker()
    invalidated = checker.check_all_positions()

    return {
        'checked': PositionModel._default_manager.filter(
            invalidation_rule_json__isnull=False
        ).exclude(invalidation_rule_json={}).count(),
        'invalidated': len(invalidated),
        'positions': invalidated
    }


def get_invalidated_positions_summary() -> List[Dict]:
    """
    获取已证伪持仓的摘要

    Returns:
        List[Dict]: 已证伪持仓的摘要列表
    """
    checker = PositionInvalidationChecker()
    positions = checker.get_positions_to_close()

    return [
        {
            'position_id': p.id,
            'account_id': p.account_id,
            'account_name': p.account.account_name,
            'asset_code': p.asset_code,
            'asset_name': p.asset_name,
            'quantity': p.quantity,
            'market_value': float(p.market_value),
            'unrealized_pnl': float(p.unrealized_pnl),
            'unrealized_pnl_pct': p.unrealized_pnl_pct,
            'invalidation_reason': p.invalidation_reason,
            'invalidation_checked_at': p.invalidation_checked_at.isoformat() if p.invalidation_checked_at else None,
        }
        for p in positions
    ]

