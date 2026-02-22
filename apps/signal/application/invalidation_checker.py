"""
证伪检查服务

Application 层：编排 Domain 层业务逻辑和 Infrastructure 层数据获取。

架构说明：
- Domain 层：evaluate_rule() 纯函数评估证伪规则
- Infrastructure 层：获取指标数据
- Application 层：编排两者，提供检查服务
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

from apps.signal.domain.invalidation import (
    InvalidationRule,
    InvalidationCheckResult,
    IndicatorValue,
    evaluate_rule,
)
from apps.signal.infrastructure.models import InvestmentSignalModel


class InvalidationCheckService:
    """证伪检查服务

    负责检查投资信号的证伪条件，并在满足条件时更新信号状态。
    """

    def __init__(self):
        """初始化服务"""
        # 延迟导入避免循环依赖
        from apps.macro.infrastructure.repositories import DjangoMacroRepository
        self.macro_repo = DjangoMacroRepository()

    def check_signal(self, signal_id: int) -> Optional[InvalidationCheckResult]:
        """检查单个信号的证伪状态

        Args:
            signal_id: 信号ID

        Returns:
            InvalidationCheckResult 或 None（如果信号不存在或无需检查）
        """
        try:
            signal = InvestmentSignalModel._default_manager.get(id=signal_id)
            return self._check_signal_model(signal)
        except InvestmentSignalModel.DoesNotExist:
            return None

    def _check_signal_model(self, signal: InvestmentSignalModel) -> Optional[InvalidationCheckResult]:
        """检查信号模型的证伪状态

        Args:
            signal: InvestmentSignalModel 实例

        Returns:
            InvalidationCheckResult 或 None
        """
        # 转换为 Domain 实体
        entity = signal.to_domain_entity()

        # 检查是否有证伪规则
        if not entity.invalidation_rule:
            return None

        # 对于非批准状态，也需要检查证伪条件
        # 如果 pending 信号的证伪条件已满足，应该标记为 rejected
        # rejected 或 expired 状态的信号不需要检查
        if entity.status.value in ('rejected', 'expired'):
            return None

        # 获取指标值
        indicator_values = self._fetch_indicator_values(entity.invalidation_rule)

        # 评估规则（Domain 层纯函数）
        result = evaluate_rule(entity.invalidation_rule, indicator_values)

        # 如果证伪，更新信号状态
        if result.is_invalidated:
            self._invalidate_signal(signal, result, entity.status.value)

        return result

    def _fetch_indicator_values(self, rule: InvalidationRule) -> Dict[str, IndicatorValue]:
        """获取规则中所有指标的当前值

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

    def _invalidate_signal(
        self,
        signal: InvestmentSignalModel,
        result: InvalidationCheckResult,
        current_status: str
    ):
        """标记信号为已证伪或已拒绝

        Args:
            signal: 信号模型
            result: 证伪检查结果
            current_status: 信号当前状态
        """
        # pending 状态的信号证伪条件满足时，应标记为 rejected
        # approved 状态的信号证伪条件满足时，应标记为 invalidated
        if current_status == 'pending':
            new_status = 'rejected'
        else:  # approved
            new_status = 'invalidated'
            signal.invalidated_at = timezone.now()

        signal.status = new_status
        signal.invalidation_details = {
            'reason': result.reason,
            'checked_conditions': result.checked_conditions,
        }
        signal.rejection_reason = result.reason
        signal.save()

        # 记录日志
        if current_status == 'pending':
            logger.info(
                f"Pending 信号 #{signal.id} ({signal.asset_code}) "
                f"因证伪条件满足而被拒绝: {result.reason}"
            )
        else:  # approved
            logger.info(
                f"Approved 信号 #{signal.id} ({signal.asset_code}) "
                f"已被证伪: {result.reason}"
            )

    def check_all_approved_signals(self) -> List[InvestmentSignalModel]:
        """检查所有已批准的信号

        返回需要证伪的信号列表，并自动更新其状态。

        Returns:
            List[InvestmentSignalModel]: 被证伪的信号列表
        """
        # 获取所有有证伪规则的已批准信号
        approved_signals = InvestmentSignalModel._default_manager.filter(
            status='approved',
            invalidation_rule_json__isnull=False
        ).exclude(invalidation_rule_json={})

        invalidated_signals = []

        for signal in approved_signals:
            result = self._check_signal_model(signal)
            if result and result.is_invalidated:
                invalidated_signals.append(signal)

        return invalidated_signals

    def check_pending_signals(self) -> List[InvestmentSignalModel]:
        """检查所有待处理的信号

        检查 pending 状态的信号是否满足证伪条件，
        如果满足则标记为 rejected（因为还未被批准）。

        Returns:
            List[InvestmentSignalModel]: 被拒绝的信号列表
        """
        # 获取所有有证伪规则的待处理信号
        pending_signals = InvestmentSignalModel._default_manager.filter(
            status='pending',
            invalidation_rule_json__isnull=False
        ).exclude(invalidation_rule_json={})

        rejected_signals = []

        for signal in pending_signals:
            result = self._check_signal_model(signal)
            if result and result.is_invalidated:
                rejected_signals.append(signal)

        return rejected_signals

    def check_signal_by_id(self, signal_id: int) -> Optional[InvalidationCheckResult]:
        """通过ID检查信号（别名，保持向后兼容）

        Args:
            signal_id: 信号ID

        Returns:
            InvalidationCheckResult 或 None
        """
        return self.check_signal(signal_id)


# ==================== 导出函数，供 Celery 任务使用 ====================

def check_and_invalidate_signals() -> Dict:
    """检查并证伪满足条件的信号

    这是一个导出函数，供 Celery 任务调用。

    现在同时检查:
    - approved 信号 -> 证伪条件满足时变为 invalidated
    - pending 信号 -> 证伪条件满足时变为 rejected

    Returns:
        Dict: 包含统计信息
    """
    service = InvalidationCheckService()

    # 检查已批准信号
    invalidated = service.check_all_approved_signals()

    # 检查待处理信号
    rejected = service.check_pending_signals()

    return {
        'checked': (
            InvestmentSignalModel._default_manager.filter(status='approved').count() +
            InvestmentSignalModel._default_manager.filter(status='pending').count()
        ),
        'invalidated': len(invalidated),
        'rejected': len(rejected),
        'invalidated_ids': [s.id for s in invalidated],
        'rejected_ids': [s.id for s in rejected]
    }

