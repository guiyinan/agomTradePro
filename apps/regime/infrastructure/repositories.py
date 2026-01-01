"""
Repositories for Regime Data.

Infrastructure layer implementation using Django ORM.
"""

from datetime import date
from typing import List, Optional

from django.db import transaction
from django.db.models import Max

from ..domain.entities import RegimeSnapshot, KalmanState
from .models import RegimeLog


class RegimeRepositoryError(Exception):
    """数据仓储异常"""
    pass


class DjangoRegimeRepository:
    """
    Django ORM 实现的 Regime 数据仓储

    提供 Regime 计算结果的持久化。
    """

    def __init__(self):
        self._model = RegimeLog

    def save_snapshot(
        self,
        snapshot: RegimeSnapshot
    ) -> RegimeSnapshot:
        """
        保存 Regime 快照

        Args:
            snapshot: Regime 快照实体

        Returns:
            RegimeSnapshot: 保存后的快照
        """
        # 检查是否已存在
        existing = self._model.objects.filter(
            observed_at=snapshot.observed_at
        ).first()

        if existing:
            # 更新
            existing.growth_momentum_z = snapshot.growth_momentum_z
            existing.inflation_momentum_z = snapshot.inflation_momentum_z
            existing.distribution = snapshot.distribution
            existing.dominant_regime = snapshot.dominant_regime
            existing.confidence = snapshot.confidence
            existing.save()
            orm_obj = existing
        else:
            # 新建
            orm_obj = self._model.objects.create(
                observed_at=snapshot.observed_at,
                growth_momentum_z=snapshot.growth_momentum_z,
                inflation_momentum_z=snapshot.inflation_momentum_z,
                distribution=snapshot.distribution,
                dominant_regime=snapshot.dominant_regime,
                confidence=snapshot.confidence
            )

        return self._orm_to_entity(orm_obj)

    def get_snapshot_by_date(
        self,
        observed_at: date
    ) -> Optional[RegimeSnapshot]:
        """
        按日期获取 Regime 快照

        Args:
            observed_at: 观测日期

        Returns:
            Optional[RegimeSnapshot]: 快照实体，不存在则返回 None
        """
        orm_obj = self._model.objects.filter(
            observed_at=observed_at
        ).first()

        if orm_obj:
            return self._orm_to_entity(orm_obj)
        return None

    def get_latest_snapshot(
        self,
        before_date: Optional[date] = None
    ) -> Optional[RegimeSnapshot]:
        """
        获取最新快照

        Args:
            before_date: 截止日期（None 表示最新）

        Returns:
            Optional[RegimeSnapshot]: 最新快照，无数据则返回 None
        """
        query = self._model.objects.all()

        if before_date:
            query = query.filter(observed_at__lte=before_date)

        orm_obj = query.order_by('-observed_at').first()

        if orm_obj:
            return self._orm_to_entity(orm_obj)
        return None

    def get_snapshots_in_range(
        self,
        start_date: date,
        end_date: date
    ) -> List[RegimeSnapshot]:
        """
        获取日期范围内的快照列表

        Args:
            start_date: 起始日期（包含）
            end_date: 结束日期（包含）

        Returns:
            List[RegimeSnapshot]: 快照列表，按时间升序排列
        """
        query = self._model.objects.filter(
            observed_at__gte=start_date,
            observed_at__lte=end_date
        ).order_by('observed_at')

        return [self._orm_to_entity(obj) for obj in query]

    def get_regime_history(
        self,
        regime_name: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[RegimeSnapshot]:
        """
        获取指定 Regime 的历史快照

        Args:
            regime_name: Regime 名称（Recovery/Overheat/Stagflation/Deflation）
            start_date: 起始日期（包含）
            end_date: 结束日期（包含）

        Returns:
            List[RegimeSnapshot]: 快照列表
        """
        query = self._model.objects.filter(
            dominant_regime=regime_name
        )

        if start_date:
            query = query.filter(observed_at__gte=start_date)
        if end_date:
            query = query.filter(observed_at__lte=end_date)

        query = query.order_by('observed_at')

        return [self._orm_to_entity(obj) for obj in query]

    def delete_snapshot(self, observed_at: date) -> bool:
        """
        删除指定日期的快照

        Args:
            observed_at: 观测日期

        Returns:
            bool: 是否成功删除
        """
        count, _ = self._model.objects.filter(
            observed_at=observed_at
        ).delete()
        return count > 0

    def get_snapshot_count(self) -> int:
        """
        获取快照数量

        Returns:
            int: 快照数量
        """
        return self._model.objects.count()

    def get_earliest_date(self) -> Optional[date]:
        """
        获取最早的快照日期

        Returns:
            Optional[date]: 最早日期，无数据则返回 None
        """
        from django.db.models import Min

        result = self._model.objects.aggregate(
            earliest_date=Min('observed_at')
        )
        return result.get('earliest_date')

    def get_latest_date(self) -> Optional[date]:
        """
        获取最新的快照日期

        Returns:
            Optional[date]: 最新日期，无数据则返回 None
        """
        from django.db.models import Max

        result = self._model.objects.aggregate(
            latest_date=Max('observed_at')
        )
        return result.get('latest_date')

    # 别名方法，用于兼容 backtest 模块的调用
    def get_regime_by_date(self, observed_at: date) -> Optional[RegimeSnapshot]:
        """
        按日期获取 Regime 快照（别名方法）

        Args:
            observed_at: 观测日期

        Returns:
            Optional[RegimeSnapshot]: 快照实体，不存在则返回 None
        """
        return self.get_snapshot_by_date(observed_at)

    def get_regime_distribution_stats(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> dict:
        """
        获取 Regime 分布统计

        Args:
            start_date: 起始日期（包含）
            end_date: 结束日期（包含）

        Returns:
            dict: 各 Regime 的出现次数和占比
        """
        query = self._model.objects.all()

        if start_date:
            query = query.filter(observed_at__gte=start_date)
        if end_date:
            query = query.filter(observed_at__lte=end_date)

        total = query.count()

        # 统计各 Regime 数量
        from django.db.models import Count
        regime_counts = query.values('dominant_regime').annotate(
            count=Count('id')
        ).order_by('-count')

        stats = {}
        for item in regime_counts:
            regime = item['dominant_regime']
            count = item['count']
            stats[regime] = {
                'count': count,
                'percentage': count / total if total > 0 else 0
            }

        return {
            'total': total,
            'by_regime': stats
        }

    @staticmethod
    def _orm_to_entity(orm_obj: RegimeLog) -> RegimeSnapshot:
        """将 ORM 对象转换为 Domain 实体"""
        return RegimeSnapshot(
            growth_momentum_z=orm_obj.growth_momentum_z,
            inflation_momentum_z=orm_obj.inflation_momentum_z,
            distribution=orm_obj.distribution,
            dominant_regime=orm_obj.dominant_regime,
            confidence=orm_obj.confidence,
            observed_at=orm_obj.observed_at
        )
