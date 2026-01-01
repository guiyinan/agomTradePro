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
