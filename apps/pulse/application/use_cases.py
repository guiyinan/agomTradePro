"""Pulse Application Layer Use Cases"""

import logging
from datetime import date

from apps.pulse.domain.entities import PulseConfig, PulseSnapshot
from apps.pulse.domain.services import calculate_pulse

logger = logging.getLogger(__name__)


class CalculatePulseUseCase:
    """
    计算当前 Pulse 脉搏

    编排流程：
    1. 通过 DjangoPulseDataProvider 获取各指标最新数据
    2. 获取当前 regime 上下文
    3. 调用 domain services 计算 PulseSnapshot
    4. 持久化到 PulseLog
    """

    def execute(self, as_of_date: date | None = None) -> PulseSnapshot | None:
        """执行 Pulse 计算"""
        target_date = as_of_date or date.today()

        try:
            # 1. 获取当前 regime
            from apps.regime.application.current_regime import resolve_current_regime
            regime_result = resolve_current_regime(as_of_date=target_date)
            regime_context = regime_result.dominant_regime

            # 2. 获取所有指标读数
            from apps.pulse.infrastructure.data_provider import DjangoPulseDataProvider
            provider = DjangoPulseDataProvider()
            readings = provider.get_all_readings(target_date)

            if not readings:
                logger.warning("No pulse indicator readings available")
                return None

            # 3. 计算 Pulse
            snapshot = calculate_pulse(
                readings=readings,
                regime_context=regime_context,
                observed_at=target_date,
            )

            # 4. 持久化
            from apps.pulse.infrastructure.repositories import PulseRepository
            repo = PulseRepository()
            repo.save_snapshot(snapshot)

            logger.info(
                f"Pulse calculated: composite={snapshot.composite_score:.3f}, "
                f"strength={snapshot.regime_strength}, "
                f"warning={snapshot.transition_warning}"
            )
            return snapshot

        except Exception as e:
            logger.exception(f"Error calculating pulse: {e}")
            return None


class GetLatestPulseUseCase:
    """获取最新的 Pulse 脉搏快照（从数据库读取）"""

    def execute(self) -> PulseSnapshot | None:
        """获取最新快照"""
        try:
            from apps.pulse.infrastructure.repositories import PulseRepository
            repo = PulseRepository()
            return repo.get_latest_snapshot()
        except Exception as e:
            logger.exception(f"Error getting latest pulse: {e}")
            return None
