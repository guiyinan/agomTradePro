"""
Repositories for Investment Signals.

Infrastructure layer implementation using Django ORM.
"""

from datetime import date
from typing import List, Optional

from django.db import transaction

from ..domain.entities import InvestmentSignal, SignalStatus, Eligibility
from .models import InvestmentSignalModel


class SignalRepositoryError(Exception):
    """信号仓储异常"""
    pass


class DjangoSignalRepository:
    """
    Django ORM 实现的投资信号仓储

    提供投资信号的增删改查操作。
    """

    def __init__(self):
        self._model = InvestmentSignalModel

    def save_signal(
        self,
        signal: InvestmentSignal
    ) -> InvestmentSignal:
        """
        保存投资信号

        Args:
            signal: 信号实体

        Returns:
            InvestmentSignal: 保存后的信号
        """
        # 转换 status 枚举
        status_value = (
            signal.status.value if isinstance(signal.status, SignalStatus)
            else signal.status
        )

        # 检查是否已存在（有 ID）
        if signal.id:
            try:
                existing = self._model.objects.get(id=signal.id)
                # 更新
                existing.asset_code = signal.asset_code
                existing.asset_class = signal.asset_class
                existing.direction = signal.direction
                existing.logic_desc = signal.logic_desc
                existing.invalidation_logic = signal.invalidation_logic
                existing.invalidation_threshold = signal.invalidation_threshold
                existing.target_regime = signal.target_regime
                existing.status = status_value
                existing.rejection_reason = signal.rejection_reason
                existing.save()
                orm_obj = existing
            except self._model.DoesNotExist:
                # ID 不存在，创建新记录
                orm_obj = self._model.objects.create(
                    asset_code=signal.asset_code,
                    asset_class=signal.asset_class,
                    direction=signal.direction,
                    logic_desc=signal.logic_desc,
                    invalidation_logic=signal.invalidation_logic,
                    invalidation_threshold=signal.invalidation_threshold,
                    target_regime=signal.target_regime,
                    status=status_value,
                    rejection_reason=signal.rejection_reason
                )
        else:
            # 新建
            orm_obj = self._model.objects.create(
                asset_code=signal.asset_code,
                asset_class=signal.asset_class,
                direction=signal.direction,
                logic_desc=signal.logic_desc,
                invalidation_logic=signal.invalidation_logic,
                invalidation_threshold=signal.invalidation_threshold,
                target_regime=signal.target_regime,
                status=status_value,
                rejection_reason=signal.rejection_reason
            )

        return self._orm_to_entity(orm_obj)

    def get_signal_by_id(self, signal_id: str) -> Optional[InvestmentSignal]:
        """
        按 ID 获取信号

        Args:
            signal_id: 信号 ID

        Returns:
            Optional[InvestmentSignal]: 信号实体，不存在则返回 None
        """
        try:
            orm_obj = self._model.objects.get(id=signal_id)
            return self._orm_to_entity(orm_obj)
        except self._model.DoesNotExist:
            return None

    def get_signals_by_asset(
        self,
        asset_code: str,
        status: Optional[SignalStatus] = None
    ) -> List[InvestmentSignal]:
        """
        按资产代码获取信号列表

        Args:
            asset_code: 资产代码
            status: 状态过滤（None 表示所有状态）

        Returns:
            List[InvestmentSignal]: 信号列表
        """
        query = self._model.objects.filter(asset_code=asset_code)

        if status:
            status_value = status.value if isinstance(status, SignalStatus) else status
            query = query.filter(status=status_value)

        query = query.order_by('-created_at')

        return [self._orm_to_entity(obj) for obj in query]

    def get_signals_by_status(
        self,
        status: SignalStatus
    ) -> List[InvestmentSignal]:
        """
        按状态获取信号列表

        Args:
            status: 信号状态

        Returns:
            List[InvestmentSignal]: 信号列表
        """
        status_value = status.value if isinstance(status, SignalStatus) else status
        query = self._model.objects.filter(status=status_value).order_by('-created_at')

        return [self._orm_to_entity(obj) for obj in query]

    def get_pending_signals(self) -> List[InvestmentSignal]:
        """
        获取待处理信号

        Returns:
            List[InvestmentSignal]: 待处理信号列表
        """
        return self.get_signals_by_status(SignalStatus.PENDING)

    def get_active_signals(self) -> List[InvestmentSignal]:
        """
        获取活跃信号（已批准但未失效）

        Returns:
            List[InvestmentSignal]: 活跃信号列表
        """
        query = self._model.objects.filter(status='approved').order_by('-created_at')
        return [self._orm_to_entity(obj) for obj in query]

    def get_signals_by_regime(
        self,
        target_regime: str,
        status: Optional[SignalStatus] = None
    ) -> List[InvestmentSignal]:
        """
        按目标 Regime 获取信号

        Args:
            target_regime: 目标 Regime
            status: 状态过滤

        Returns:
            List[InvestmentSignal]: 信号列表
        """
        query = self._model.objects.filter(target_regime=target_regime)

        if status:
            status_value = status.value if isinstance(status, SignalStatus) else status
            query = query.filter(status=status_value)

        query = query.order_by('-created_at')

        return [self._orm_to_entity(obj) for obj in query]

    def update_signal_status(
        self,
        signal_id: str,
        new_status: SignalStatus,
        rejection_reason: Optional[str] = None
    ) -> bool:
        """
        更新信号状态

        Args:
            signal_id: 信号 ID
            new_status: 新状态
            rejection_reason: 拒绝原因（仅 REJECTED 状态）

        Returns:
            bool: 是否成功更新
        """
        try:
            orm_obj = self._model.objects.get(id=signal_id)
            orm_obj.status = new_status.value if isinstance(new_status, SignalStatus) else new_status

            if new_status == SignalStatus.REJECTED and rejection_reason:
                orm_obj.rejection_reason = rejection_reason

            orm_obj.save()
            return True
        except self._model.DoesNotExist:
            return False

    def delete_signal(self, signal_id: str) -> bool:
        """
        删除信号

        Args:
            signal_id: 信号 ID

        Returns:
            bool: 是否成功删除
        """
        count, _ = self._model.objects.filter(id=signal_id).delete()
        return count > 0

    def get_signal_count(
        self,
        status: Optional[SignalStatus] = None
    ) -> int:
        """
        获取信号数量

        Args:
            status: 状态过滤

        Returns:
            int: 信号数量
        """
        query = self._model.objects.all()

        if status:
            status_value = status.value if isinstance(status, SignalStatus) else status
            query = query.filter(status=status_value)

        return query.count()

    def get_user_signals(
        self,
        user_id: int,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[InvestmentSignal]:
        """
        获取用户的投资信号列表

        Args:
            user_id: 用户ID
            status: 状态过滤 (pending, approved, rejected)
            limit: 返回数量限制

        Returns:
            List[InvestmentSignal]: 信号列表
        """
        query = self._model.objects.filter(user_id=user_id).order_by('-created_at')

        if status:
            query = query.filter(status=status)

        if limit:
            query = query[:limit]

        return [self._orm_to_entity(obj) for obj in query]

    def get_statistics(self) -> dict:
        """
        获取信号统计信息

        Returns:
            dict: 统计信息字典
        """
        from django.db.models import Count

        total = self._model.objects.count()

        # 按状态统计
        status_stats = {}
        for status_choice in self._model.STATUS_CHOICES:
            status_value = status_choice[0]
            count = self._model.objects.filter(status=status_value).count()
            status_stats[status_value] = {
                'count': count,
                'percentage': count / total if total > 0 else 0
            }

        # 按资产类别统计
        asset_stats = []
        for item in self._model.objects.values('asset_class').annotate(
            count=Count('id')
        ).order_by('-count'):
            asset_stats.append({
                'asset_class': item['asset_class'],
                'count': item['count']
            })

        return {
            'total': total,
            'by_status': status_stats,
            'by_asset_class': asset_stats
        }

    @staticmethod
    def _orm_to_entity(orm_obj: InvestmentSignalModel) -> InvestmentSignal:
        """将 ORM 对象转换为 Domain 实体"""
        return InvestmentSignal(
            id=str(orm_obj.id),
            asset_code=orm_obj.asset_code,
            asset_class=orm_obj.asset_class,
            direction=orm_obj.direction,
            logic_desc=orm_obj.logic_desc,
            invalidation_logic=orm_obj.invalidation_logic,
            invalidation_threshold=orm_obj.invalidation_threshold,
            target_regime=orm_obj.target_regime,
            created_at=orm_obj.created_at.date(),
            status=SignalStatus(orm_obj.status),
            rejection_reason=orm_obj.rejection_reason
        )


class UnifiedSignalRepository:
    """
    统一信号仓储

    管理来自所有模块（Regime、Factor、Rotation、Hedge）的统一信号。
    """

    def __init__(self):
        from .models import UnifiedSignalModel
        self._model = UnifiedSignalModel

    def create_signal(
        self,
        signal_date: date,
        signal_source: str,
        signal_type: str,
        asset_code: str,
        reason: str,
        asset_name: str = "",
        target_weight: float = None,
        current_weight: float = None,
        priority: int = 5,
        action_required: str = "",
        extra_data: dict = None,
        related_signal_id: str = ""
    ) -> dict:
        """
        创建新的统一信号

        Args:
            signal_date: 信号日期
            signal_source: 信号来源 (regime/factor/rotation/hedge/manual)
            signal_type: 信号类型 (buy/sell/rebalance/alert/info)
            asset_code: 资产代码
            reason: 信号原因
            asset_name: 资产名称
            target_weight: 目标权重
            current_weight: 当前权重
            priority: 优先级 (1-10)
            action_required: 所需操作
            extra_data: 额外数据
            related_signal_id: 关联的原始信号ID

        Returns:
            创建的信号字典
        """
        signal = self._model.objects.create(
            signal_date=signal_date,
            signal_source=signal_source,
            signal_type=signal_type,
            asset_code=asset_code,
            asset_name=asset_name,
            target_weight=target_weight,
            current_weight=current_weight,
            priority=priority,
            reason=reason,
            action_required=action_required,
            extra_data=extra_data or {},
            related_signal_id=related_signal_id,
        )

        return self._orm_to_dict(signal)

    def get_signals_by_date(
        self,
        signal_date: date,
        signal_source: str = None,
        signal_type: str = None,
        is_executed: bool = None
    ) -> list:
        """
        按日期获取信号

        Args:
            signal_date: 信号日期
            signal_source: 信号来源过滤
            signal_type: 信号类型过滤
            is_executed: 执行状态过滤

        Returns:
            信号列表
        """
        query = self._model.objects.filter(signal_date=signal_date)

        if signal_source:
            query = query.filter(signal_source=signal_source)
        if signal_type:
            query = query.filter(signal_type=signal_type)
        if is_executed is not None:
            query = query.filter(is_executed=is_executed)

        return [self._orm_to_dict(s) for s in query.order_by('-priority')]

    def get_signals_by_asset(
        self,
        asset_code: str,
        days: int = 30,
        signal_source: str = None
    ) -> list:
        """
        按资产获取最近的信号

        Args:
            asset_code: 资产代码
            days: 查询天数
            signal_source: 信号来源过滤

        Returns:
            信号列表
        """
        from datetime import timedelta
        cutoff_date = date.today() - timedelta(days=days)

        query = self._model.objects.filter(
            asset_code=asset_code,
            signal_date__gte=cutoff_date
        )

        if signal_source:
            query = query.filter(signal_source=signal_source)

        return [self._orm_to_dict(s) for s in query.order_by('-signal_date', '-priority')]

    def get_pending_signals(
        self,
        min_priority: int = 1,
        signal_type: str = None
    ) -> list:
        """
        获取待处理的信号

        Args:
            min_priority: 最低优先级
            signal_type: 信号类型过滤

        Returns:
            待处理信号列表
        """
        query = self._model.objects.filter(
            is_executed=False,
            priority__gte=min_priority
        )

        if signal_type:
            query = query.filter(signal_type=signal_type)

        return [self._orm_to_dict(s) for s in query.order_by('-signal_date', '-priority')]

    def mark_executed(self, signal_id: int) -> bool:
        """
        标记信号为已执行

        Args:
            signal_id: 信号ID

        Returns:
            是否成功
        """
        try:
            signal = self._model.objects.get(id=signal_id)
            signal.mark_executed()
            return True
        except self._model.DoesNotExist:
            return False

    def get_signal_summary(
        self,
        start_date: date,
        end_date: date = None
    ) -> dict:
        """
        获取信号汇总

        Args:
            start_date: 开始日期
            end_date: 结束日期（默认今天）

        Returns:
            汇总信息
        """
        if end_date is None:
            end_date = date.today()

        query = self._model.objects.filter(
            signal_date__gte=start_date,
            signal_date__lte=end_date
        )

        total = query.count()
        executed = query.filter(is_executed=True).count()
        pending = total - executed

        # 按来源统计
        by_source = {}
        for source, _ in self._model.SIGNAL_SOURCE_CHOICES:
            count = query.filter(signal_source=source).count()
            by_source[source] = count

        # 按类型统计
        by_type = {}
        for signal_type, _ in self._model.SIGNAL_TYPE_CHOICES:
            count = query.filter(signal_type=signal_type).count()
            by_type[signal_type] = count

        # 高优先级信号
        high_priority = query.filter(priority__gte=7, is_executed=False).count()

        return {
            'total': total,
            'executed': executed,
            'pending': pending,
            'by_source': by_source,
            'by_type': by_type,
            'high_priority_count': high_priority,
        }

    def delete_old_signals(self, days_to_keep: int = 90) -> int:
        """
        删除旧信号

        Args:
            days_to_keep: 保留天数

        Returns:
            删除的信号数量
        """
        from datetime import timedelta
        cutoff_date = date.today() - timedelta(days=days_to_keep)

        count, _ = self._model.objects.filter(
            signal_date__lt=cutoff_date,
            is_executed=True
        ).delete()

        return count

    @staticmethod
    def _orm_to_dict(orm_obj) -> dict:
        """将 ORM 对象转换为字典"""
        return {
            'id': orm_obj.id,
            'signal_date': orm_obj.signal_date.isoformat(),
            'signal_source': orm_obj.signal_source,
            'signal_type': orm_obj.signal_type,
            'asset_code': orm_obj.asset_code,
            'asset_name': orm_obj.asset_name,
            'target_weight': float(orm_obj.target_weight) if orm_obj.target_weight else None,
            'current_weight': float(orm_obj.current_weight) if orm_obj.current_weight else None,
            'priority': orm_obj.priority,
            'is_executed': orm_obj.is_executed,
            'executed_at': orm_obj.executed_at.isoformat() if orm_obj.executed_at else None,
            'reason': orm_obj.reason,
            'action_required': orm_obj.action_required,
            'extra_data': orm_obj.extra_data,
            'related_signal_id': orm_obj.related_signal_id,
            'created_at': orm_obj.created_at.isoformat(),
        }
