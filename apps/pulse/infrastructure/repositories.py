"""Pulse 数据仓储"""

from datetime import date
from typing import Any

from apps.pulse.application.dtos import PulseHistoryDTO
from apps.pulse.domain.entities import DimensionScore, PulseIndicatorReading, PulseSnapshot
from apps.pulse.infrastructure.models import NavigatorAssetConfigModel, PulseLog


class PulseRepository:
    """Pulse 日志仓储"""

    def save_snapshot(self, snapshot: PulseSnapshot) -> PulseLog:
        """持久化 PulseSnapshot 到数据库。"""
        dim_dict = snapshot.dimension_dict

        # 序列化指标明细
        readings_data = []
        for r in snapshot.indicator_readings:
            readings_data.append(
                {
                    "code": r.code,
                    "name": r.name,
                    "dimension": r.dimension,
                    "value": r.value,
                    "z_score": r.z_score,
                    "direction": r.direction,
                    "signal": r.signal,
                    "signal_score": r.signal_score,
                    "weight": r.weight,
                    "data_age_days": r.data_age_days,
                    "is_stale": r.is_stale,
                    "observed_at": r.observed_at.isoformat() if r.observed_at else None,
                    "source_kind": r.source_kind,
                }
            )

        defaults = {
            "regime_context": snapshot.regime_context,
            "growth_score": dim_dict.get("growth", 0.0),
            "inflation_score": dim_dict.get("inflation", 0.0),
            "liquidity_score": dim_dict.get("liquidity", 0.0),
            "sentiment_score": dim_dict.get("sentiment", 0.0),
            "composite_score": snapshot.composite_score,
            "regime_strength": snapshot.regime_strength,
            "transition_warning": snapshot.transition_warning,
            "transition_direction": snapshot.transition_direction,
            "indicator_readings": readings_data,
            "transition_reasons": snapshot.transition_reasons,
            "data_source": snapshot.data_source,
        }
        log, _ = PulseLog.objects.update_or_create(
            observed_at=snapshot.observed_at,
            defaults=defaults,
        )
        return log

    def get_latest(self) -> PulseLog | None:
        """获取最新的 PulseLog 记录。"""
        return PulseLog.objects.order_by("-observed_at", "-created_at").first()

    def get_latest_snapshot(self) -> PulseSnapshot | None:
        """获取最新的 PulseSnapshot（从数据库重建）"""
        log = self.get_latest()
        if not log:
            return None
        return self._log_to_snapshot(log)

    def get_history(self, months: int = 6, limit: int | None = None) -> list[PulseHistoryDTO]:
        """获取历史记录"""
        from datetime import timedelta

        cutoff = date.today() - timedelta(days=months * 30)
        queryset = PulseLog.objects.filter(observed_at__gte=cutoff).order_by(
            "-observed_at",
            "-created_at",
        )
        if limit is not None:
            queryset = queryset[:limit]
        return [
            PulseHistoryDTO(
                observed_at=log.observed_at,
                regime_context=log.regime_context,
                composite_score=log.composite_score,
                regime_strength=log.regime_strength,
                growth_score=log.growth_score,
                inflation_score=log.inflation_score,
                liquidity_score=log.liquidity_score,
                sentiment_score=log.sentiment_score,
                transition_warning=log.transition_warning,
                transition_direction=log.transition_direction,
            )
            for log in queryset
        ]

    def _log_to_snapshot(self, log: PulseLog) -> PulseSnapshot:
        """将 PulseLog ORM 实例转换回 PulseSnapshot 域对象"""
        # 重建指标读数
        readings = []
        for r in log.indicator_readings or []:
            if isinstance(r, dict):
                reading_observed_at = _parse_date(r.get("observed_at"))
                readings.append(
                    PulseIndicatorReading(
                        code=r.get("code", ""),
                        name=r.get("name", ""),
                        dimension=r.get("dimension", ""),
                        value=r.get("value", 0.0),
                        z_score=r.get("z_score", 0.0),
                        direction=r.get("direction", "stable"),
                        signal=r.get("signal", "neutral"),
                        signal_score=r.get("signal_score", 0.0),
                        weight=r.get("weight", 1.0),
                        data_age_days=r.get("data_age_days", 0),
                        is_stale=bool(r.get("is_stale", False)) or reading_observed_at is None,
                        observed_at=reading_observed_at,
                        source_kind=str(r.get("source_kind") or "legacy_unknown"),
                    )
                )

        score_by_dimension = {
            "growth": log.growth_score,
            "inflation": log.inflation_score,
            "liquidity": log.liquidity_score,
            "sentiment": log.sentiment_score,
        }
        dim_scores = [
            DimensionScore(
                dimension=dimension,
                score=score,
                signal=_score_to_signal(score),
                indicator_count=sum(
                    1
                    for reading in readings
                    if reading.dimension == dimension and not reading.is_stale
                ),
                description="",
            )
            for dimension, score in score_by_dimension.items()
        ]

        return PulseSnapshot(
            observed_at=log.observed_at,
            regime_context=log.regime_context,
            dimension_scores=dim_scores,
            composite_score=log.composite_score,
            regime_strength=log.regime_strength,
            transition_warning=log.transition_warning,
            transition_direction=log.transition_direction,
            transition_reasons=log.transition_reasons or [],
            indicator_readings=readings,
            data_source=log.data_source,
            stale_indicator_count=sum(1 for r in readings if r.is_stale),
        )


def _parse_date(value: Any) -> date | None:
    """Parse a JSON date while keeping legacy Pulse rows readable."""

    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


class NavigatorAssetConfigRepository:
    """Navigator 资产配置仓储。"""

    def list_active_config_payloads(self) -> list[dict[str, Any]]:
        """返回激活配置的原始载荷，避免 Application 层直接接触 ORM。"""
        payloads: list[dict[str, Any]] = []
        queryset = NavigatorAssetConfigModel.objects.filter(is_active=True).order_by("regime_name")

        for config in queryset:
            asset_weight_ranges: dict[str, tuple[float, float]] = {}
            for category, bounds in (config.asset_weight_ranges or {}).items():
                if not isinstance(bounds, list | tuple) or len(bounds) < 2:
                    continue
                asset_weight_ranges[str(category)] = (
                    float(bounds[0]),
                    float(bounds[1]),
                )

            payloads.append(
                {
                    "regime_name": str(config.regime_name),
                    "asset_weight_ranges": asset_weight_ranges,
                    "risk_budget": float(config.risk_budget),
                    "recommended_sectors": [str(item) for item in config.recommended_sectors],
                    "benefiting_styles": [str(item) for item in config.benefiting_styles],
                }
            )

        return payloads


def get_navigator_asset_config_repository() -> NavigatorAssetConfigRepository:
    """返回 Navigator 资产配置仓储实例。"""
    return NavigatorAssetConfigRepository()


def _score_to_signal(score: float) -> str:
    if score > 0.2:
        return "bullish"
    elif score < -0.2:
        return "bearish"
    return "neutral"
