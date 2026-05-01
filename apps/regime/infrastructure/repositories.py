"""
Repositories for Regime Data.

Infrastructure layer implementation using Django ORM.
"""

from datetime import date
from typing import List, Optional

from django.db import transaction
from django.db.models import Count, Max

from ..domain.entities import KalmanState, RegimeSnapshot
from .config_helper import ConfigHelper, ConfigKeys
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
    ) -> RegimeSnapshot | None:
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
        before_date: date | None = None
    ) -> RegimeSnapshot | None:
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
    ) -> list[RegimeSnapshot]:
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
        start_date: date | None = None,
        end_date: date | None = None
    ) -> list[RegimeSnapshot]:
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

    def list_history_payloads(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        regime: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Return API-ready regime history payloads."""

        queryset = self._model._default_manager.all()
        if start_date:
            queryset = queryset.filter(observed_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(observed_at__lte=end_date)
        if regime:
            queryset = queryset.filter(dominant_regime=regime)

        queryset = queryset.order_by("-observed_at")[:limit]
        return [self._serialize_log(log) for log in queryset]

    def get_distribution_payload(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict:
        """Return API-ready distribution statistics."""

        queryset = self._model._default_manager.all()
        if start_date:
            queryset = queryset.filter(observed_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(observed_at__lte=end_date)

        stats = list(
            queryset.values("dominant_regime")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        total = sum(item["count"] for item in stats)
        distribution = []
        for item in stats:
            distribution.append(
                {
                    "dominant_regime": item["dominant_regime"],
                    "count": item["count"],
                    "percentage": round(item["count"] / total * 100, 2) if total > 0 else 0,
                }
            )

        return {
            "total": total,
            "distribution": distribution,
        }

    def get_earliest_date(self) -> date | None:
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

    def get_latest_date(self) -> date | None:
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
    def get_regime_by_date(self, observed_at: date) -> RegimeSnapshot | None:
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
        start_date: date | None = None,
        end_date: date | None = None
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

    def get_active_threshold_config_values(self) -> dict[str, float] | None:
        """Return active Regime V2 threshold config as primitive values."""

        from .models import RegimeThresholdConfig

        config_model = RegimeThresholdConfig._default_manager.filter(is_active=True).first()
        if not config_model:
            return None

        thresholds = {
            threshold.indicator_code: threshold
            for threshold in config_model.thresholds.all()
        }
        pmi_threshold = thresholds.get("PMI")
        cpi_threshold = thresholds.get("CPI")
        trend_config = config_model.trend_indicators.filter(indicator_code="PMI").first()

        return {
            "pmi_expansion": pmi_threshold.level_high if pmi_threshold else 50.0,
            "pmi_contraction": pmi_threshold.level_low if pmi_threshold else 50.0,
            "cpi_high": cpi_threshold.level_high if cpi_threshold else 2.0,
            "cpi_low": cpi_threshold.level_low if cpi_threshold else 1.0,
            "cpi_deflation": 0.0,
            "momentum_weight": trend_config.trend_weight if trend_config else 0.3,
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

    @staticmethod
    def _serialize_log(orm_obj: RegimeLog) -> dict:
        """Serialize a regime log record to a plain payload."""

        return {
            "id": orm_obj.id,
            "observed_at": orm_obj.observed_at,
            "dominant_regime": orm_obj.dominant_regime,
            "confidence": orm_obj.confidence,
            "growth_momentum_z": orm_obj.growth_momentum_z,
            "inflation_momentum_z": orm_obj.inflation_momentum_z,
            "distribution": orm_obj.distribution,
            "created_at": orm_obj.created_at,
        }


def get_regime_repository() -> DjangoRegimeRepository:
    """Backward-compatible repository factory."""
    return DjangoRegimeRepository()


class DjangoNavigatorRepository:
    """
    Django ORM 实现的 Navigator 数据仓储
    """

    def save_action_recommendation(self, observed_at: date, data: dict):
        from .models import ActionRecommendationLog
        ActionRecommendationLog.objects.update_or_create(
            observed_at=observed_at,
            defaults=data
        )

    def get_regimes_in_range(self, start_date: date, end_date: date):
        from .models import RegimeLog
        return RegimeLog.objects.filter(
            observed_at__range=(start_date, end_date)
        ).order_by("observed_at")

    def get_actions_in_range(self, start_date: date, end_date: date):
        from .models import ActionRecommendationLog
        return ActionRecommendationLog.objects.filter(
            observed_at__range=(start_date, end_date)
        ).order_by("observed_at")

    def get_pulses_in_range(self, start_date: date, end_date: date):
        from apps.pulse.infrastructure.models import PulseLog
        return PulseLog.objects.filter(
            observed_at__range=(start_date, end_date)
        ).order_by("observed_at")


def get_navigator_repository() -> DjangoNavigatorRepository:
    """Backward-compatible navigator repository factory."""
    return DjangoNavigatorRepository()


class RegimeConfigRepository:
    """Infrastructure-backed config access for regime application services."""

    def get_spread_threshold_bp(self, default: float) -> float:
        return ConfigHelper.get_float(
            ConfigKeys.REGIME_SPREAD_BP_THRESHOLD,
            default,
        )

    def get_us_yield_threshold(self, default: float) -> float:
        return ConfigHelper.get_float(
            ConfigKeys.REGIME_US_YIELD_THRESHOLD,
            default,
        )

    def get_daily_persist_days(self, default: int) -> int:
        return ConfigHelper.get_int(
            ConfigKeys.REGIME_DAILY_PERSIST_DAYS,
            default,
        )

    def get_conflict_confidence_boost(self, default: float) -> float:
        return ConfigHelper.get_float(
            ConfigKeys.REGIME_CONFLICT_CONFIDENCE_BOOST,
            default,
        )
