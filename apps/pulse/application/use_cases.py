"""Pulse Application Layer Use Cases"""

import logging
from collections.abc import Sequence
from datetime import date
from typing import Any

from apps.data_center.application.dtos import DecisionReliabilityRepairRequest
from apps.data_center.application.interface_services import make_decision_repair_use_case
from apps.pulse.application.regime_gateway import (
    PulseRegimeContext,
    resolve_current_regime,
)
from apps.pulse.application.repository_provider import (
    get_pulse_data_provider,
    get_pulse_repository,
)
from apps.pulse.domain.entities import PulseSnapshot
from apps.pulse.domain.services import calculate_pulse

logger = logging.getLogger(__name__)
DEFAULT_MAX_SNAPSHOT_AGE_DAYS = 8
PULSE_MACRO_SYNC_INDICATORS = (
    "CN_PMI",
    "CN_NEW_CREDIT",
    "CN_CPI_NATIONAL_YOY",
    "CN_SHIBOR",
    "CN_LPR",
    "CN_M2_YOY",
)


def resolve_current_regime_for_pulse(*, as_of_date: date) -> PulseRegimeContext:
    """Resolve the current regime through the owning regime module."""

    return resolve_current_regime(as_of_date=as_of_date)


def refresh_pulse_macro_inputs(
    *,
    target_date: date,
    macro_indicator_codes: Sequence[str],
    asset_codes: Sequence[str],
) -> dict[str, Any]:
    """Repair the macro and quote inputs that Pulse depends on."""

    report = make_decision_repair_use_case(user=None).execute(
        DecisionReliabilityRepairRequest(
            target_date=target_date,
            portfolio_id=None,
            asset_codes=[str(code).strip().upper() for code in asset_codes if code],
            macro_indicator_codes=[
                str(code).strip().upper() for code in macro_indicator_codes if code
            ],
            strict=False,
            repair_pulse=False,
            repair_alpha=False,
        )
    )
    return report.to_dict()


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
    """Refresh Data Center inputs that feed Pulse before recalculation."""
    try:
        refresh_pulse_macro_inputs(
            target_date=target_date,
            macro_indicator_codes=PULSE_MACRO_SYNC_INDICATORS,
            asset_codes=("000300.SH",),
        )
    except Exception as exc:
        logger.warning(
            "Failed to refresh Pulse Data Center inputs",
            extra={"exception_type": type(exc).__name__},
        )


def _validate_snapshot_request(
    *,
    require_reliable: bool,
    refresh_if_stale: bool,
    max_age_days: int,
) -> None:
    """Validate reliability controls before accessing the Pulse repository."""

    if not isinstance(require_reliable, bool):
        raise ValueError("require_reliable must be a boolean")
    if not isinstance(refresh_if_stale, bool):
        raise ValueError("refresh_if_stale must be a boolean")
    if isinstance(max_age_days, bool) or not isinstance(max_age_days, int) or max_age_days < 0:
        raise ValueError("max_age_days must be a non-negative integer")


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
            regime_result = resolve_current_regime_for_pulse(as_of_date=target_date)
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
            provider = get_pulse_data_provider()
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
            repo = get_pulse_repository()
            repo.save_snapshot(snapshot)

            logger.info(
                "Pulse calculated: composite=%.3f strength=%s warning=%s",
                snapshot.composite_score,
                snapshot.regime_strength,
                snapshot.transition_warning,
            )
            return snapshot

        except Exception as exc:
            logger.error(
                "Error calculating Pulse",
                extra={"exception_type": type(exc).__name__},
            )
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
        _validate_snapshot_request(
            require_reliable=require_reliable,
            refresh_if_stale=refresh_if_stale,
            max_age_days=max_age_days,
        )
        target_date = as_of_date or date.today()
        try:
            repo = get_pulse_repository()
            snapshot = repo.get_latest_snapshot()

            if (
                snapshot
                and _is_snapshot_usable(
                    snapshot,
                    target_date=target_date,
                    require_reliable=require_reliable,
                    max_age_days=max_age_days,
                )
                and (not refresh_if_stale or snapshot.is_reliable)
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
        except Exception as exc:
            logger.error(
                "Error getting latest Pulse",
                extra={"exception_type": type(exc).__name__},
            )
            return None
