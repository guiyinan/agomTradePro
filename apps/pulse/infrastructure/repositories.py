"""Pulse 数据仓储"""

from datetime import date

from apps.pulse.domain.entities import DimensionScore, PulseIndicatorReading, PulseSnapshot
from apps.pulse.infrastructure.models import PulseLog


class PulseRepository:
    """Pulse 日志仓储"""

    def save_snapshot(self, snapshot: PulseSnapshot) -> PulseLog:
        """持久化 PulseSnapshot 到数据库。"""
        dim_dict = snapshot.dimension_dict

        # 序列化指标明细
        readings_data = []
        for r in snapshot.indicator_readings:
            readings_data.append({
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
            })

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

    def get_history(self, months: int = 6) -> list[PulseLog]:
        """获取历史记录"""
        from datetime import timedelta
        cutoff = date.today() - timedelta(days=months * 30)
        return list(PulseLog.objects.filter(observed_at__gte=cutoff))

    def _log_to_snapshot(self, log: PulseLog) -> PulseSnapshot:
        """将 PulseLog ORM 实例转换回 PulseSnapshot 域对象"""
        # 重建维度分数
        dim_scores = [
            DimensionScore(
                dimension="growth",
                score=log.growth_score,
                signal=_score_to_signal(log.growth_score),
                indicator_count=0,
                description="",
            ),
            DimensionScore(
                dimension="inflation",
                score=log.inflation_score,
                signal=_score_to_signal(log.inflation_score),
                indicator_count=0,
                description="",
            ),
            DimensionScore(
                dimension="liquidity",
                score=log.liquidity_score,
                signal=_score_to_signal(log.liquidity_score),
                indicator_count=0,
                description="",
            ),
            DimensionScore(
                dimension="sentiment",
                score=log.sentiment_score,
                signal=_score_to_signal(log.sentiment_score),
                indicator_count=0,
                description="",
            ),
        ]

        # 重建指标读数
        readings = []
        for r in (log.indicator_readings or []):
            if isinstance(r, dict):
                readings.append(PulseIndicatorReading(
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
                    is_stale=r.get("is_stale", False),
                ))

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


def _score_to_signal(score: float) -> str:
    if score > 0.2:
        return "bullish"
    elif score < -0.2:
        return "bearish"
    return "neutral"
