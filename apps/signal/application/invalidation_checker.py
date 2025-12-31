"""
自动证伪检查服务

定期检查所有已批准的信号，根据结构化规则判断是否需要证伪
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from django.utils import timezone
from apps.signal.infrastructure.models import InvestmentSignalModel
from apps.macro.infrastructure.repositories import DjangoMacroRepository


@dataclass
class InvalidationResult:
    """证伪检查结果"""
    is_invalidated: bool
    reason: str
    details: Dict[str, Any]


class MacroIndicatorFetcher:
    """宏观经济指标数据获取器"""

    # 指标代码映射
    INDICATOR_CODES = {
        'PMI': 'CN_PMI_MANUFACTURING',
        'CPI': 'CN_CPI_YOY',
        'PPI': 'CN_PPI_YOY',
        'M2': 'CN_M2_YOY',
        'SHIBOR': 'SHIBOR_1M',
        'GDP': 'CN_GDP_YOY',
    }

    def __init__(self):
        self.repo = DjangoMacroRepository()

    def get_current_value(self, indicator: str) -> Optional[float]:
        """获取指标最新值"""
        code = self.INDICATOR_CODES.get(indicator)
        if not code:
            return None

        try:
            data = self.repo.get_by_code_and_date(code, datetime.now().date())
            return data.value if data else None
        except:
            return None

    def get_history_values(self, indicator: str, periods: int = 12) -> List[float]:
        """获取指标历史值"""
        code = self.INDICATOR_CODES.get(indicator)
        if not code:
            return []

        try:
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=periods * 35)  # 粗略估算

            # 获取该指标的所有数据
            from apps.macro.infrastructure.models import MacroIndicator as MacroModel
            data_points = MacroModel.objects.filter(
                code=code,
                observed_at__gte=start_date,
                observed_at__lte=end_date
            ).order_by('-observed_at')[:periods]

            return [d.value for d in data_points]
        except:
            return []

    def get_previous_value(self, indicator: str) -> Optional[float]:
        """获取指标上一期值"""
        history = self.get_history_values(indicator, periods=2)
        return history[1] if len(history) > 1 else None


class InvalidationRuleChecker:
    """证伪规则检查器"""

    def __init__(self):
        self.fetcher = MacroIndicatorFetcher()

    def check_condition(self, condition: Dict[str, Any]) -> bool:
        """
        检查单个条件是否满足

        condition 格式:
        {
            "indicator": "PMI",
            "condition": "lt",  # lt, lte, gt, gte, eq
            "threshold": 50,
            "duration": 2,      # 可选: 连续N期
            "compare_with": "prev_value"  # 可选: 与前值比较
        }
        """
        indicator = condition.get('indicator')
        op = condition.get('condition')
        threshold = condition.get('threshold')
        duration = condition.get('duration', 1)
        compare_with = condition.get('compare_with')

        # 获取当前值
        current_value = self.fetcher.get_current_value(indicator)
        if current_value is None:
            return False

        # 需要与历史值比较
        if compare_with == 'prev_value':
            prev_value = self.fetcher.get_previous_value(indicator)
            if prev_value is None:
                return False
            actual_value = current_value - prev_value  # 计算变化量
        else:
            actual_value = current_value

        # 基础比较
        result = self._compare(actual_value, op, threshold)

        # 检查持续时间
        if result and duration > 1:
            history = self.fetcher.get_history_values(indicator, periods=duration + 1)
            if len(history) < duration + 1:
                return False

            # 检查连续N期是否都满足条件
            consecutive_count = 0
            for value in history[:duration]:
                if self._compare(value, op, threshold):
                    consecutive_count += 1
                else:
                    break

            result = consecutive_count >= duration

        return result

    def _compare(self, value: float, op: str, threshold: float) -> bool:
        """执行比较操作"""
        if op == 'lt':
            return value < threshold
        elif op == 'lte':
            return value <= threshold
        elif op == 'gt':
            return value > threshold
        elif op == 'gte':
            return value >= threshold
        elif op == 'eq':
            return abs(value - threshold) < 0.001
        return False

    def check_rules(self, rules: Dict[str, Any]) -> InvalidationResult:
        """
        检查规则组合

        rules 格式:
        {
            "conditions": [
                {"indicator": "PMI", "condition": "lt", "threshold": 50},
                {"indicator": "CPI", "condition": "gt", "threshold": 3}
            ],
            "logic": "AND"  # 或 "OR"
        }
        """
        conditions = rules.get('conditions', [])
        logic = rules.get('logic', 'AND')

        if not conditions:
            return InvalidationResult(
                is_invalidated=False,
                reason="无证伪规则",
                details={}
            )

        results = []
        details = {}

        for idx, cond in enumerate(conditions):
            is_met = self.check_condition(cond)
            results.append(is_met)

            # 记录详细信息
            indicator = cond.get('indicator')
            details[f'condition_{idx}'] = {
                'indicator': indicator,
                'condition': cond.get('condition'),
                'threshold': cond.get('threshold'),
                'current_value': self.fetcher.get_current_value(indicator),
                'is_met': is_met
            }

        # 根据逻辑判断整体结果
        if logic == 'AND':
            is_invalidated = all(results)
        else:  # OR
            is_invalidated = any(results)

        if is_invalidated:
            reason = self._generate_reason(rules, details)
        else:
            reason = "证伪条件未满足"

        return InvalidationResult(
            is_invalidated=is_invalidated,
            reason=reason,
            details=details
        )

    def _generate_reason(self, rules: Dict, details: Dict) -> str:
        """生成证伪原因描述"""
        conditions = rules.get('conditions', [])
        logic = rules.get('logic', 'AND')

        parts = []
        for idx, cond in enumerate(conditions):
            detail = details.get(f'condition_{idx}', {})
            if not detail.get('is_met'):
                continue

            indicator = cond.get('indicator')
            op = cond.get('condition')
            threshold = cond.get('threshold')
            current = detail.get('current_value', 'N/A')

            op_map = {'lt': '<', 'lte': '≤', 'gt': '>', 'gte': '≥', 'eq': '='}
            parts.append(f"{indicator}={current} {op_map.get(op, op)} {threshold}")

        logic_text = ' 且 ' if logic == 'AND' else ' 或 '
        return f"证伪条件满足: {logic_text.join(parts)}"


class SignalInvalidationService:
    """信号证伪服务"""

    def __init__(self):
        self.checker = InvalidationRuleChecker()

    def check_signal(self, signal: InvestmentSignalModel) -> InvalidationResult:
        """检查单个信号"""
        if not signal.invalidation_rules:
            return InvalidationResult(
                is_invalidated=False,
                reason="未配置结构化证伪规则",
                details={}
            )

        if signal.status != 'approved':
            return InvalidationResult(
                is_invalidated=False,
                reason=f"信号状态为 {signal.status}，无需检查",
                details={}
            )

        return self.checker.check_rules(signal.invalidation_rules)

    def invalidate_signal(self, signal: InvestmentSignalModel, result: InvalidationResult):
        """执行证伪"""
        signal.status = 'invalidated'
        signal.invalidated_at = timezone.now()
        signal.invalidation_details = {
            'reason': result.reason,
            'details': result.details,
            'checked_at': timezone.now().isoformat()
        }
        signal.rejection_reason = result.reason
        signal.save()

    def check_all_approved_signals(self) -> List[InvestmentSignalModel]:
        """检查所有已批准的信号，返回需要证伪的信号列表"""
        approved_signals = InvestmentSignalModel.objects.filter(
            status='approved',
            invalidation_rules__isnull=False
        ).exclude(invalidation_rules={})

        invalidated_signals = []

        for signal in approved_signals:
            result = self.check_signal(signal)
            if result.is_invalidated:
                self.invalidate_signal(signal, result)
                invalidated_signals.append(signal)

        return invalidated_signals

    def check_signal_by_id(self, signal_id: int) -> Optional[InvalidationResult]:
        """通过ID检查信号"""
        try:
            signal = InvestmentSignalModel.objects.get(id=signal_id)
            result = self.check_signal(signal)

            if result.is_invalidated:
                self.invalidate_signal(signal, result)

            return result
        except InvestmentSignalModel.DoesNotExist:
            return None


# 导出函数，供 Celery 任务使用
def check_and_invalidate_signals():
    """检查并证伪满足条件的信号"""
    service = SignalInvalidationService()
    invalidated = service.check_all_approved_signals()

    return {
        'checked': InvestmentSignalModel.objects.filter(status='approved').count(),
        'invalidated': len(invalidated),
        'signal_ids': [s.id for s in invalidated]
    }
