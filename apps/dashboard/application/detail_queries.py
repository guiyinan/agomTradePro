"""Regime summary and dashboard detail query services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from django.db import DatabaseError

from apps.dashboard.application.query_value_helpers import DEGRADED_DASHBOARD_QUERY_EXCEPTIONS

logger = logging.getLogger(__name__)


def _query_facade() -> Any:
    """Resolve the compatibility facade lazily for monkeypatch-safe tests."""

    from apps.dashboard.application import queries

    return queries


# ============================================================================
# Regime Summary Query Service
# ============================================================================


@dataclass(frozen=True)
class RegimeSummaryData:
    """Regime 摘要数据"""

    current_regime: str
    regime_date: date | None
    regime_confidence: float
    growth_momentum_z: float
    inflation_momentum_z: float
    pmi_value: float | None
    cpi_value: float | None
    regime_distribution: dict[str, float]
    regime_data_health: bool
    regime_warnings: list[str]


class RegimeSummaryQuery:
    """
    Regime 摘要查询服务

    聚合当前 Regime 状态和宏观指标数据。

    Example:
        >>> query = RegimeSummaryQuery()
        >>> data = query.execute()
        >>> print(data.current_regime)
    """

    def execute(self, user_id: int | None = None) -> RegimeSummaryData:
        """
        执行查询

        Args:
            user_id: 用户 ID（用于某些个性化数据）

        Returns:
            RegimeSummaryData
        """
        try:
            current = _query_facade().resolve_current_regime()
            if (
                current.dominant_regime
                and current.dominant_regime != "Unknown"
                and not current.must_not_use_for_decision
            ):
                return RegimeSummaryData(
                    current_regime=current.dominant_regime,
                    regime_date=current.observed_at,
                    regime_confidence=float(current.confidence or 0.0),
                    growth_momentum_z=float(current.growth_momentum_z or 0.0),
                    inflation_momentum_z=float(current.inflation_momentum_z or 0.0),
                    pmi_value=self._get_latest_macro_value("PMI"),
                    cpi_value=self._get_latest_macro_value("CPI"),
                    regime_distribution=dict(current.distribution or {}),
                    regime_data_health=True,
                    regime_warnings=list(current.warnings),
                )

            warnings = list(current.warnings)
            if not warnings:
                warnings.append("No regime data available")
            return RegimeSummaryData(
                current_regime="Unknown",
                regime_date=current.observed_at,
                regime_confidence=float(current.confidence or 0.0),
                growth_momentum_z=float(current.growth_momentum_z or 0.0),
                inflation_momentum_z=float(current.inflation_momentum_z or 0.0),
                pmi_value=None,
                cpi_value=None,
                regime_distribution={},
                regime_data_health=False,
                regime_warnings=warnings,
            )

        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as exc:
            logger.warning("Failed to get regime summary: error_type=%s", type(exc).__name__)
            return RegimeSummaryData(
                current_regime="Unknown",
                regime_date=None,
                regime_confidence=0.0,
                growth_momentum_z=0.0,
                inflation_momentum_z=0.0,
                pmi_value=None,
                cpi_value=None,
                regime_distribution={},
                regime_data_health=False,
                regime_warnings=["Regime data unavailable"],
            )

    def _get_latest_macro_value(self, indicator_code: str) -> float | None:
        """获取最新宏观指标值"""
        try:
            value = (
                _query_facade()
                .get_dashboard_query_repository()
                .get_latest_macro_indicator_value(indicator_code)
            )
            return cast(float | None, value)
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as exc:
            logger.debug("Failed to get macro value: error_type=%s", type(exc).__name__)
            return None


class DashboardDetailQuery:
    """Dashboard 详情查询服务。"""

    def get_position_detail(self, user_id: int, asset_code: str) -> dict[str, Any]:
        """获取持仓详情和相关信号。"""
        try:
            payload = (
                _query_facade()
                .get_dashboard_query_repository()
                .get_position_detail(
                    user_id=user_id,
                    asset_code=asset_code,
                )
            )
            return cast(dict[str, Any], payload)
        except ValueError as exc:
            position_error = str(exc)
            if "position not found" in position_error.lower():
                return {
                    "position": None,
                    "related_signals": [],
                    "asset_code": asset_code,
                    "error": f"未找到持仓 {asset_code}",
                }
            logger.warning("Failed to get position detail: error_type=%s", type(exc).__name__)
            return {
                "position": None,
                "related_signals": [],
                "asset_code": asset_code,
                "error": "持仓详情暂不可用",
            }
        except DEGRADED_DASHBOARD_QUERY_EXCEPTIONS as exc:
            logger.warning("Failed to get position detail: error_type=%s", type(exc).__name__)
            return {
                "position": None,
                "related_signals": [],
                "asset_code": asset_code,
                "error": "持仓详情暂不可用",
            }

    def generate_alpha_candidates(self) -> dict[str, int]:
        """批量生成 Alpha 候选并返回统计结果。"""
        from apps.alpha_trigger.application.repository_provider import (
            get_alpha_candidate_repository,
            get_alpha_trigger_repository,
        )
        from apps.alpha_trigger.application.use_cases import (
            GenerateCandidateRequest,
            GenerateCandidateUseCase,
        )
        from apps.alpha_trigger.domain.entities import CandidateStatus

        trigger_repo = get_alpha_trigger_repository()
        candidate_repo = get_alpha_candidate_repository()
        use_case = GenerateCandidateUseCase(trigger_repo, candidate_repo)
        generation_context = (
            _query_facade()
            .get_dashboard_query_repository()
            .load_alpha_candidate_generation_context()
        )
        active_triggers = generation_context["active_triggers"]
        existing_trigger_ids = generation_context["existing_trigger_ids"]

        generated = 0
        promoted = 0
        failed = 0
        skipped = 0

        for trigger in active_triggers:
            if trigger.trigger_id in existing_trigger_ids:
                skipped += 1
                continue

            resp = use_case.execute(
                GenerateCandidateRequest(
                    trigger_id=trigger.trigger_id,
                    time_window_days=90,
                )
            )
            if not resp.success or not resp.candidate:
                failed += 1
                continue

            generated += 1
            if float(resp.candidate.confidence or 0) >= 0.70:
                try:
                    candidate_repo.update_status(
                        resp.candidate.candidate_id, CandidateStatus.ACTIONABLE
                    )
                    promoted += 1
                except (DatabaseError, TypeError, ValueError) as exc:
                    logger.warning(
                        "Failed to promote Alpha candidate %s to ACTIONABLE: %s",
                        getattr(resp.candidate, "candidate_id", None),
                        exc,
                    )

        return {
            "generated": generated,
            "promoted_to_actionable": promoted,
            "skipped_existing": skipped,
            "failed": failed,
            "active_trigger_count": len(active_triggers),
            "actionable_count": generation_context["actionable_count"],
        }
