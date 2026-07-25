"""
Repositories for Regime Data.

Infrastructure layer implementation using Django ORM.
"""

import math
from datetime import date
from typing import Any

from django.db import transaction
from django.db.models import Count, Max, Min, QuerySet

from ..domain.entities import RegimeSnapshot
from .config_helper import ConfigHelper, ConfigKeys
from .models import ActionRecommendationLog, RegimeLog


class RegimeRepositoryError(Exception):
    """数据仓储异常"""


class DjangoRegimeRepository:
    """
    Django ORM 实现的 Regime 数据仓储

    提供 Regime 计算结果的持久化。
    """

    VALID_REGIMES = frozenset({"Recovery", "Overheat", "Stagflation", "Deflation"})

    def __init__(self) -> None:
        self._model: type[RegimeLog] = RegimeLog

    def save_snapshot(self, snapshot: RegimeSnapshot) -> RegimeSnapshot:
        """
        保存 Regime 快照

        Args:
            snapshot: Regime 快照实体

        Returns:
            RegimeSnapshot: 保存后的快照
        """
        self._validate_snapshot(snapshot)
        with transaction.atomic():
            orm_obj, _ = self._model._default_manager.update_or_create(
                observed_at=snapshot.observed_at,
                defaults={
                    "growth_momentum_z": snapshot.growth_momentum_z,
                    "inflation_momentum_z": snapshot.inflation_momentum_z,
                    "distribution": snapshot.distribution,
                    "dominant_regime": snapshot.dominant_regime,
                    "confidence": snapshot.confidence,
                },
            )

        return self._orm_to_entity(orm_obj)

    def get_snapshot_by_date(self, observed_at: date) -> RegimeSnapshot | None:
        """
        按日期获取 Regime 快照

        Args:
            observed_at: 观测日期

        Returns:
            Optional[RegimeSnapshot]: 快照实体，不存在则返回 None
        """
        orm_obj = self._model.objects.filter(observed_at=observed_at).first()

        if orm_obj:
            return self._orm_to_entity(orm_obj)
        return None

    def get_latest_snapshot(self, before_date: date | None = None) -> RegimeSnapshot | None:
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

        orm_obj = query.order_by("-observed_at").first()

        if orm_obj:
            return self._orm_to_entity(orm_obj)
        return None

    def get_snapshots_in_range(self, start_date: date, end_date: date) -> list[RegimeSnapshot]:
        """
        获取日期范围内的快照列表

        Args:
            start_date: 起始日期（包含）
            end_date: 结束日期（包含）

        Returns:
            List[RegimeSnapshot]: 快照列表，按时间升序排列
        """
        query = self._model.objects.filter(
            observed_at__gte=start_date, observed_at__lte=end_date
        ).order_by("observed_at")

        return [self._orm_to_entity(obj) for obj in query]

    def get_regime_history(
        self, regime_name: str, start_date: date | None = None, end_date: date | None = None
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
        query = self._model.objects.filter(dominant_regime=regime_name)

        if start_date:
            query = query.filter(observed_at__gte=start_date)
        if end_date:
            query = query.filter(observed_at__lte=end_date)

        query = query.order_by("observed_at")

        return [self._orm_to_entity(obj) for obj in query]

    def delete_snapshot(self, observed_at: date) -> bool:
        """
        删除指定日期的快照

        Args:
            observed_at: 观测日期

        Returns:
            bool: 是否成功删除
        """
        count, _ = self._model.objects.filter(observed_at=observed_at).delete()
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
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return API-ready regime history payloads."""

        if limit <= 0 or offset < 0:
            return []
        queryset = self._model._default_manager.all()
        if start_date:
            queryset = queryset.filter(observed_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(observed_at__lte=end_date)
        if regime:
            queryset = queryset.filter(dominant_regime=regime)

        queryset = queryset.order_by("-observed_at")[offset : offset + limit]
        return [self._serialize_log(log) for log in queryset]

    def count_history_payloads(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        regime: str | None = None,
    ) -> int:
        """Count regime history rows matching the API filters."""

        queryset = self._model._default_manager.all()
        if start_date:
            queryset = queryset.filter(observed_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(observed_at__lte=end_date)
        if regime:
            queryset = queryset.filter(dominant_regime=regime)
        return queryset.count()

    def replace_snapshots_in_range(
        self,
        *,
        start_date: date,
        end_date: date,
        snapshots: list[RegimeSnapshot],
    ) -> int:
        """Atomically replace persisted snapshots inside one inclusive date range."""

        if start_date > end_date:
            raise RegimeRepositoryError("start_date must be on or before end_date")

        observed_dates: set[date] = set()
        for snapshot in snapshots:
            self._validate_snapshot(snapshot)
            if not start_date <= snapshot.observed_at <= end_date:
                raise RegimeRepositoryError(
                    "replacement snapshot is outside the requested date range"
                )
            if snapshot.observed_at in observed_dates:
                raise RegimeRepositoryError(
                    "replacement snapshots contain duplicate observed_at dates"
                )
            observed_dates.add(snapshot.observed_at)

        rows = [
            self._model(
                observed_at=snapshot.observed_at,
                growth_momentum_z=snapshot.growth_momentum_z,
                inflation_momentum_z=snapshot.inflation_momentum_z,
                distribution=snapshot.distribution,
                dominant_regime=snapshot.dominant_regime,
                confidence=snapshot.confidence,
            )
            for snapshot in snapshots
        ]
        with transaction.atomic():
            self._model._default_manager.filter(
                observed_at__gte=start_date,
                observed_at__lte=end_date,
            ).delete()
            self._model._default_manager.bulk_create(rows)
        return len(rows)

    def get_distribution_payload(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, object]:
        """Return API-ready distribution statistics."""

        queryset = self._model._default_manager.all()
        if start_date:
            queryset = queryset.filter(observed_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(observed_at__lte=end_date)

        stats = list(
            queryset.values("dominant_regime").annotate(count=Count("id")).order_by("-count")
        )
        total = sum(item["count"] for item in stats)
        distribution: list[dict[str, object]] = []
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
        result = self._model._default_manager.aggregate(earliest_date=Min("observed_at"))
        value = result.get("earliest_date")
        return value if isinstance(value, date) else None

    def get_latest_date(self) -> date | None:
        """
        获取最新的快照日期

        Returns:
            Optional[date]: 最新日期，无数据则返回 None
        """
        result = self._model._default_manager.aggregate(latest_date=Max("observed_at"))
        value = result.get("latest_date")
        return value if isinstance(value, date) else None

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
        self, start_date: date | None = None, end_date: date | None = None
    ) -> dict[str, object]:
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
        regime_counts = (
            query.values("dominant_regime").annotate(count=Count("id")).order_by("-count")
        )

        stats: dict[str, dict[str, float | int]] = {}
        for item in regime_counts:
            regime = item["dominant_regime"]
            count = item["count"]
            stats[regime] = {
                "count": count,
                "percentage": count / total if total > 0 else 0,
            }

        return {
            "total": total,
            "by_regime": stats,
        }

    def get_active_threshold_config_values(self) -> dict[str, float] | None:
        """Return active Regime V2 threshold config as primitive values."""

        from .models import RegimeThresholdConfig

        config_model = RegimeThresholdConfig._default_manager.filter(is_active=True).first()
        if not config_model:
            return None

        thresholds = {
            threshold.indicator_code: threshold for threshold in config_model.thresholds.all()
        }
        pmi_threshold = thresholds.get("PMI")
        cpi_threshold = thresholds.get("CPI")
        trend_config = config_model.trend_indicators.filter(indicator_code="PMI").first()

        if (
            pmi_threshold is None
            or pmi_threshold.level_high is None
            or pmi_threshold.level_low is None
            or cpi_threshold is None
            or cpi_threshold.level_high is None
            or cpi_threshold.level_low is None
            or trend_config is None
        ):
            return None

        values = {
            "pmi_expansion": float(pmi_threshold.level_high),
            "pmi_contraction": float(pmi_threshold.level_low),
            "cpi_high": float(cpi_threshold.level_high),
            "cpi_low": float(cpi_threshold.level_low),
            "cpi_deflation": 0.0,
            "momentum_weight": float(trend_config.trend_weight),
        }
        if not all(math.isfinite(value) for value in values.values()):
            return None
        return values

    @staticmethod
    def _orm_to_entity(orm_obj: RegimeLog) -> RegimeSnapshot:
        """将 ORM 对象转换为 Domain 实体"""
        return RegimeSnapshot(
            growth_momentum_z=orm_obj.growth_momentum_z,
            inflation_momentum_z=orm_obj.inflation_momentum_z,
            distribution=orm_obj.distribution,
            dominant_regime=orm_obj.dominant_regime,
            confidence=orm_obj.confidence,
            observed_at=orm_obj.observed_at,
        )

    @staticmethod
    def _serialize_log(orm_obj: RegimeLog) -> dict[str, Any]:
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

    @classmethod
    def _validate_snapshot(cls, snapshot: RegimeSnapshot) -> None:
        """Reject invalid decision-state snapshots before any database mutation."""

        if snapshot.dominant_regime not in cls.VALID_REGIMES:
            raise RegimeRepositoryError("snapshot has an invalid dominant_regime")
        numeric_values = (
            snapshot.growth_momentum_z,
            snapshot.inflation_momentum_z,
            snapshot.confidence,
            *snapshot.distribution.values(),
        )
        if not all(math.isfinite(value) for value in numeric_values):
            raise RegimeRepositoryError("snapshot contains non-finite numeric values")
        if not 0.0 <= snapshot.confidence <= 1.0:
            raise RegimeRepositoryError("snapshot confidence must be between 0 and 1")
        if (
            not snapshot.distribution
            or snapshot.dominant_regime not in snapshot.distribution
            or any(value < 0.0 for value in snapshot.distribution.values())
        ):
            raise RegimeRepositoryError("snapshot has an invalid regime distribution")


def get_regime_repository() -> DjangoRegimeRepository:
    """Backward-compatible repository factory."""
    return DjangoRegimeRepository()


class DjangoNavigatorRepository:
    """
    Django ORM 实现的 Navigator 数据仓储
    """

    def save_action_recommendation(
        self,
        observed_at: date,
        data: dict[str, Any],
    ) -> None:
        ActionRecommendationLog.objects.update_or_create(observed_at=observed_at, defaults=data)

    def get_latest_action_recommendation(
        self,
        before_date: date | None = None,
    ) -> ActionRecommendationLog | None:
        """Return the latest persisted action recommendation log."""

        queryset = ActionRecommendationLog.objects.all()
        if before_date is not None:
            queryset = queryset.filter(observed_at__lte=before_date)
        return queryset.order_by("-observed_at", "-id").first()

    def get_regimes_in_range(
        self,
        start_date: date,
        end_date: date,
    ) -> QuerySet[RegimeLog]:
        return RegimeLog.objects.filter(observed_at__range=(start_date, end_date)).order_by(
            "observed_at"
        )

    def get_actions_in_range(
        self,
        start_date: date,
        end_date: date,
    ) -> QuerySet[ActionRecommendationLog]:
        return ActionRecommendationLog.objects.filter(
            observed_at__range=(start_date, end_date)
        ).order_by("observed_at")

    def get_pulses_in_range(
        self,
        start_date: date,
        end_date: date,
    ) -> QuerySet[Any]:
        from apps.pulse.infrastructure.models import PulseLog

        return PulseLog.objects.filter(observed_at__range=(start_date, end_date)).order_by(
            "observed_at"
        )


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
