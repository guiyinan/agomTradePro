"""Pulse Application Layer Use Cases"""

import logging
from datetime import date, timedelta

from apps.pulse.domain.entities import PulseSnapshot
from apps.pulse.domain.services import calculate_pulse

logger = logging.getLogger(__name__)
DEFAULT_MAX_SNAPSHOT_AGE_DAYS = 8
PULSE_MACRO_SYNC_LOOKBACK_DAYS = 120
PULSE_MACRO_SYNC_INDICATORS = (
    "CN_PMI",
    "CN_NEW_CREDIT",
    "CN_CPI_NATIONAL_YOY",
    "CN_SHIBOR",
    "CN_LPR",
    "CN_M2",
)


def _is_snapshot_usable(
    snapshot: PulseSnapshot,
    *,
    target_date: date,
    require_reliable: bool,
    max_age_days: int,
) -> bool:
    """判断给定快照是否可供当前调用方使用。"""
    if snapshot.observed_at > target_date:
        return False
    if (target_date - snapshot.observed_at).days > max_age_days:
        return False
    if require_reliable and not snapshot.is_reliable:
        return False
    return True


def _refresh_macro_inputs_for_pulse(target_date: date) -> None:
    """Refresh the macro indicators that feed Pulse before recalculation."""
    try:
        from apps.macro.application.use_cases import (
            SyncMacroDataRequest,
            build_sync_macro_data_use_case,
        )

        sync_use_case = build_sync_macro_data_use_case()
        response = sync_use_case.execute(
            SyncMacroDataRequest(
                start_date=target_date - timedelta(days=PULSE_MACRO_SYNC_LOOKBACK_DAYS),
                end_date=target_date,
                indicators=list(PULSE_MACRO_SYNC_INDICATORS),
                force_refresh=False,
            )
        )
        if response.errors:
            logger.warning(
                "Pulse macro refresh completed with errors: %s",
                response.errors,
            )
    except Exception as exc:
        logger.warning("Failed to refresh Pulse macro inputs: %s", exc)


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

            if not regime_context or regime_context == "Unknown":
                logger.warning(
                    "Skipping Pulse calculation for %s because current regime is unavailable",
                    target_date.isoformat(),
                )
                return None

            # 2. 先刷新上游宏观指标，避免 stale 快照持续降级为全 0
            _refresh_macro_inputs_for_pulse(target_date)

            # 3. 获取所有指标读数
            from apps.pulse.infrastructure.data_provider import DjangoPulseDataProvider
            provider = DjangoPulseDataProvider()
            readings = provider.get_all_readings(target_date)

            if not readings:
                logger.warning("No pulse indicator readings available")
                return None

            # 4. 计算 Pulse
            snapshot = calculate_pulse(
                readings=readings,
                regime_context=regime_context,
                observed_at=target_date,
            )

            # 5. 持久化
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

    def execute(
        self,
        as_of_date: date | None = None,
        *,
        require_reliable: bool = False,
        refresh_if_stale: bool = False,
        max_age_days: int = DEFAULT_MAX_SNAPSHOT_AGE_DAYS,
    ) -> PulseSnapshot | None:
        """获取最新快照，并在需要时触发按需重算。"""
        target_date = as_of_date or date.today()
        try:
            from apps.pulse.infrastructure.repositories import PulseRepository

            repo = PulseRepository()
            snapshot = repo.get_latest_snapshot()

            if snapshot and _is_snapshot_usable(
                snapshot,
                target_date=target_date,
                require_reliable=require_reliable,
                max_age_days=max_age_days,
            ):
                return snapshot

            if not refresh_if_stale:
                if require_reliable:
                    return None
                return snapshot

            refreshed = CalculatePulseUseCase().execute(as_of_date=target_date)
            if refreshed and _is_snapshot_usable(
                refreshed,
                target_date=target_date,
                require_reliable=require_reliable,
                max_age_days=max_age_days,
            ):
                return refreshed

            if require_reliable:
                return None
            return refreshed or snapshot
        except Exception as e:
            logger.exception(f"Error getting latest pulse: {e}")
            return None
