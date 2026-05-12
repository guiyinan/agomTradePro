"""
Decision Context Orchestration layer for the 6-Step Decision Funnel.

Orchestrates interactions between Regime, Pulse, Policy, Rotation,
Decision_Rhythm, and Audit modules to provide seamless data for the UI pipeline.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

from django.utils import timezone

from apps.pulse.application.use_cases import GetLatestPulseUseCase
from apps.regime.application.navigator_use_cases import (
    BuildRegimeNavigatorUseCase,
    GetActionRecommendationUseCase,
)
from apps.regime.application.repository_provider import get_regime_repository
from apps.rotation.application.integration_service import RotationIntegrationService

logger = logging.getLogger(__name__)


def _next_local_day_expiry(observed_at: date) -> datetime:
    """Return the local end-of-day expiry for the next calendar day."""
    expiry_date = observed_at + timedelta(days=1)
    return timezone.make_aware(datetime.combine(expiry_date, time(23, 59)))


def _build_freshness_payload(
    *,
    label: str,
    observed_at: date | None,
    source: str,
    fallback_note: str | None = None,
) -> dict[str, Any]:
    """Build UI-friendly freshness metadata for nightly workspace snapshots."""
    if observed_at is None:
        return {
            "label": label,
            "observed_at": None,
            "observed_at_display": "-",
            "expires_at": None,
            "expires_at_display": "-",
            "source": source,
            "source_label": "无快照",
            "is_stale": True,
            "status_label": "缺失",
            "badge_class": "danger",
            "note": fallback_note or "尚未生成可用快照。",
        }

    expires_at = _next_local_day_expiry(observed_at)
    now_local = timezone.localtime(timezone.now())
    is_live_fallback = source.startswith("live_")
    is_stale = now_local > expires_at

    if is_live_fallback:
        status_label = "实时回退"
        badge_class = "warning"
        source_label = "页面实时计算"
        note = fallback_note or "未命中夜间快照，当前结果来自页面级实时回退。"
    elif is_stale:
        status_label = "已过期"
        badge_class = "danger"
        source_label = "夜间快照"
        note = fallback_note or "当前展示最近一次夜间快照，已超过预期有效期。"
    else:
        status_label = "有效"
        badge_class = "success"
        source_label = "夜间快照"
        note = fallback_note or "当前展示最近一次夜间预计算快照。"

    return {
        "label": label,
        "observed_at": observed_at,
        "observed_at_display": observed_at.isoformat(),
        "expires_at": expires_at,
        "expires_at_display": timezone.localtime(expires_at).strftime("%Y-%m-%d %H:%M"),
        "source": source,
        "source_label": source_label,
        "is_stale": is_stale,
        "status_label": status_label,
        "badge_class": badge_class,
        "note": note,
    }


@dataclass
class DecisionStep1Response:
    """Step 1: 环境评估 (Environment Assessment)"""

    regime_name: str
    pulse_composite: float
    regime_strength: str
    policy_level: str | None
    overall_verdict: str
    regime_freshness: dict[str, Any]
    pulse_freshness: dict[str, Any]


@dataclass
class DecisionStep2Response:
    """Step 2: 方向选择 (Direction & Asset Allocation)"""

    action_recommendation: dict[str, Any]
    asset_weights: dict[str, float]
    risk_budget_pct: float
    recommendation_freshness: dict[str, Any]


@dataclass
class DecisionStep3Response:
    """Step 3: 板块选择 (Sector Rotation)"""

    sector_recommendations: list[dict[str, Any]]
    rotation_signals: list[dict[str, Any]]
    rotation_data_source: str | None = None
    rotation_is_stale: bool = False
    rotation_warning_message: str | None = None
    rotation_signal_date: str | None = None
    recommendation_freshness: dict[str, Any] | None = None
    rotation_freshness: dict[str, Any] | None = None


@dataclass
class DecisionStep4Response:
    """Step 4: 推优筛选 (Unified Recommendation Screen)"""

    unified_recommendations: list[dict[str, Any]]
    total_candidates: int
    page: int


@dataclass
class DecisionStep5Response:
    """Step 5: 审批执行 (Execution & Approval)"""

    approval_request_id: str
    suggested_weight: float
    position_limit: float
    gate_penalties: dict[str, Any]
    status: str


@dataclass
class DecisionStep6Response:
    """Step 6: 审计复盘 (Audit & Attribution)"""

    attribution_method: str
    benchmark_return: float
    portfolio_return: float
    excess_return: float
    allocation_effect: float
    selection_effect: float
    interaction_effect: float
    loss_source: str | None
    lesson_learned: str
    backtest_id: int | None = None
    report_id: int | None = None
    regime_accuracy: float | None = None
    regime_predicted: str | None = None
    regime_actual: str | None = None


class DecisionContextUseCase:
    """Orchestrates multi-module calls for the decision funnel steps."""

    def __init__(self):
        self.nav_usecase = BuildRegimeNavigatorUseCase()
        self.pulse_usecase = GetLatestPulseUseCase()
        self.action_usecase = GetActionRecommendationUseCase()
        self.rotation_service = RotationIntegrationService()
        self.audit_repository = None
        self.backtest_repository = None

    def _get_audit_repository(self):
        """Load the audit repository lazily for Step 6 only."""
        if self.audit_repository is None:
            from apps.audit.application.repository_provider import get_audit_repository

            self.audit_repository = get_audit_repository()
        return self.audit_repository

    def _get_backtest_repository(self):
        """Load the backtest repository lazily for Step 6 only."""
        if self.backtest_repository is None:
            from apps.backtest.application.repository_provider import get_backtest_repository

            self.backtest_repository = get_backtest_repository()
        return self.backtest_repository

    def get_step1_context(self, as_of_date: date | None = None) -> DecisionStep1Response:
        """Step 1: Environment Assessment
        Combine Regime + Pulse + Policy to output an overall verdict.
        """
        target_date = as_of_date or date.today()

        # 1. Regime - prefer the latest persisted snapshot for page rendering.
        regime_name = "UNKNOWN"
        regime_freshness = _build_freshness_payload(
            label="Regime 快照",
            observed_at=None,
            source="missing",
        )
        try:
            latest_regime = get_regime_repository().get_latest_snapshot(before_date=target_date)
            if latest_regime is not None:
                regime_name = latest_regime.dominant_regime or "UNKNOWN"
                regime_freshness = _build_freshness_payload(
                    label="Regime 快照",
                    observed_at=latest_regime.observed_at,
                    source="regime_snapshot",
                )
            else:
                navigator = self.nav_usecase.execute(target_date)
                regime_name = navigator.regime_name if navigator else "UNKNOWN"
                regime_freshness = _build_freshness_payload(
                    label="Regime 快照",
                    observed_at=target_date,
                    source="live_regime_fallback",
                )
        except Exception as e:
            logger.warning(f"Failed to fetch cached regime snapshot in DecisionContext: {e}")
            navigator = self.nav_usecase.execute(target_date)
            regime_name = navigator.regime_name if navigator else "UNKNOWN"
            regime_freshness = _build_freshness_payload(
                label="Regime 快照",
                observed_at=target_date,
                source="live_regime_fallback",
                fallback_note="夜间 Regime 快照读取失败，当前结果来自页面级实时回退。",
            )

        # 2. Pulse
        pulse = None
        pulse_freshness = _build_freshness_payload(
            label="Pulse 快照",
            observed_at=None,
            source="missing",
        )
        try:
            pulse = self.pulse_usecase.execute(
                as_of_date=target_date,
                require_reliable=False,
                refresh_if_stale=False,
            )
            if pulse is not None:
                pulse_freshness = _build_freshness_payload(
                    label="Pulse 快照",
                    observed_at=getattr(pulse, "observed_at", None),
                    source="pulse_snapshot",
                )
        except Exception as e:
            logger.warning(f"Failed to fetch pulse in DecisionContext: {e}")

        pulse_composite = pulse.composite_score if pulse else 0.0
        regime_strength = pulse.regime_strength if pulse else "moderate"

        # 3. Policy (assuming normal for now until policy module is fully integrated here)
        policy_level = "正常"

        # 4. Overall Verdict (Logic from phase-2-decision-funnel document)
        if regime_name == "Stagflation" and regime_strength == "weak":
            verdict = "不建议新增仓位 (滞胀且脉搏偏弱)"
        elif regime_strength == "weak":
            verdict = "谨慎投资 (系统脉搏偏弱)"
        else:
            verdict = "适合投资 (宏观环境支持)"

        return DecisionStep1Response(
            regime_name=regime_name,
            pulse_composite=pulse_composite,
            regime_strength=regime_strength,
            policy_level=policy_level,
            overall_verdict=verdict,
            regime_freshness=regime_freshness,
            pulse_freshness=pulse_freshness,
        )

    def get_step2_direction(self, as_of_date: date | None = None) -> DecisionStep2Response:
        """Step 2: Direction Selection"""
        target_date = as_of_date or date.today()
        action_rec = self.action_usecase.execute(
            target_date,
            refresh_pulse_if_stale=False,
            prefer_cached=True,
        )

        if not action_rec:
            return DecisionStep2Response(
                action_recommendation={},
                asset_weights={"equity": 0.5, "bond": 0.3, "commodity": 0.1, "cash": 0.1},
                risk_budget_pct=0.5,
                recommendation_freshness=_build_freshness_payload(
                    label="配置建议快照",
                    observed_at=None,
                    source="missing",
                ),
            )

        recommendation_freshness = _build_freshness_payload(
            label="配置建议快照",
            observed_at=getattr(action_rec, "context_observed_at", None) or target_date,
            source=str(getattr(action_rec, "context_source", "live_action_fallback") or "live_action_fallback"),
        )

        return DecisionStep2Response(
            action_recommendation={
                "reasoning": action_rec.reasoning,
                "regime_contribution": action_rec.regime_contribution,
                "pulse_contribution": action_rec.pulse_contribution,
                "position_limit_pct": action_rec.position_limit_pct,
                "recommended_sectors": action_rec.recommended_sectors,
            },
            asset_weights=action_rec.asset_weights,
            risk_budget_pct=action_rec.risk_budget_pct,
            recommendation_freshness=recommendation_freshness,
        )

    def get_step3_sectors(
        self,
        category: str = "equity",
        as_of_date: date | None = None,
    ) -> DecisionStep3Response:
        """Step 3: Sector Selection
        Combine Action Recommended sectors with Momentum Rotation logic.
        """
        target_date = as_of_date or date.today()
        action_rec = self.action_usecase.execute(
            target_date,
            refresh_pulse_if_stale=False,
            prefer_cached=True,
        )
        rotation_payload = self.rotation_service.get_rotation_recommendation(
            "momentum",
            prefer_persisted=True,
        )
        asset_master = self.rotation_service.get_asset_master(include_inactive=False)

        if rotation_payload.get("error"):
            logger.warning(
                "Rotation recommendation unavailable in DecisionContext: %s",
                rotation_payload["error"],
            )
            return DecisionStep3Response(
                sector_recommendations=[],
                rotation_signals=[],
                rotation_data_source=rotation_payload.get("data_source"),
                rotation_is_stale=bool(rotation_payload.get("is_stale", False)),
                rotation_warning_message=rotation_payload.get("warning_message"),
                rotation_signal_date=rotation_payload.get("signal_date"),
                recommendation_freshness=_build_freshness_payload(
                    label="配置建议快照",
                    observed_at=getattr(action_rec, "context_observed_at", None) or target_date if action_rec else None,
                    source=str(getattr(action_rec, "context_source", "missing") or "missing") if action_rec else "missing",
                ),
                rotation_freshness=_build_freshness_payload(
                    label="轮动信号快照",
                    observed_at=None,
                    source="missing",
                ),
            )

        asset_lookup = {
            asset["code"]: asset for asset in asset_master if asset.get("category") == category
        }

        target_allocation = rotation_payload.get("target_allocation", {})
        ranked_allocations = sorted(
            (
                (code, float(weight))
                for code, weight in target_allocation.items()
                if code in asset_lookup and float(weight) > 0
            ),
            key=lambda item: item[1],
            reverse=True,
        )

        recommended_sectors = list(getattr(action_rec, "recommended_sectors", []) or [])
        sector_recommendations = []

        for index, sector_name in enumerate(recommended_sectors[:3]):
            weight = ranked_allocations[index][1] if index < len(ranked_allocations) else 0.0
            sector_recommendations.append(
                {
                    "name": sector_name,
                    "score": round(weight * 100, 2) if weight > 0 else max(60 - index * 10, 30),
                    "alignment": "high" if index == 0 else "medium" if index == 1 else "low",
                    "momentum": "up" if weight >= 0.15 else "flat" if weight > 0 else "down",
                }
            )

        if not sector_recommendations:
            for index, (asset_code, weight) in enumerate(ranked_allocations[:3]):
                asset_name = asset_lookup.get(asset_code, {}).get("name", asset_code)
                sector_recommendations.append(
                    {
                        "name": asset_name,
                        "score": round(weight * 100, 2),
                        "alignment": "high" if index == 0 else "medium" if index == 1 else "low",
                        "momentum": "up" if weight >= 0.15 else "flat",
                    }
                )

        rotation_signals = [
            {
                "sector": asset_lookup.get(asset_code, {}).get("name", asset_code),
                "signal": "BUY" if weight >= 0.05 else "HOLD",
                "strength": round(weight * 100, 2),
            }
            for asset_code, weight in ranked_allocations[:5]
        ]

        recommendation_freshness = _build_freshness_payload(
            label="配置建议快照",
            observed_at=getattr(action_rec, "context_observed_at", None) or target_date if action_rec else None,
            source=str(getattr(action_rec, "context_source", "missing") or "missing") if action_rec else "missing",
        )
        rotation_source = str(rotation_payload.get("data_source") or "live_rotation_fallback")
        rotation_observed_at = None
        signal_date = rotation_payload.get("signal_date")
        if signal_date:
            try:
                rotation_observed_at = date.fromisoformat(str(signal_date))
            except ValueError:
                rotation_observed_at = None

        return DecisionStep3Response(
            sector_recommendations=sector_recommendations,
            rotation_signals=rotation_signals,
            rotation_data_source=rotation_payload.get("data_source"),
            rotation_is_stale=bool(rotation_payload.get("is_stale", False)),
            rotation_warning_message=rotation_payload.get("warning_message"),
            rotation_signal_date=rotation_payload.get("signal_date"),
            recommendation_freshness=recommendation_freshness,
            rotation_freshness=_build_freshness_payload(
                label="轮动信号快照",
                observed_at=rotation_observed_at,
                source=rotation_source,
                fallback_note=rotation_payload.get("warning_message"),
            ),
        )

    def get_step6_audit(
        self,
        trade_id: str | None = None,
        backtest_id: int | None = None,
    ) -> DecisionStep6Response:
        """Step 6: Audit Attribution
        Fetch the attribution results for a given trade/backtest.
        """
        try:
            resolved_backtest_id = self._resolve_backtest_id(trade_id, backtest_id)
            if resolved_backtest_id is None:
                return self._empty_audit_response("缺少可复盘的回测记录，请传入 backtest_id。")

            audit_repository = self._get_audit_repository()
            backtest_repository = self._get_backtest_repository()

            reports = audit_repository.get_reports_by_backtest(resolved_backtest_id)
            report_data = reports[0] if reports else None

            if report_data is None:
                from apps.audit.application.use_cases import (
                    GenerateAttributionReportRequest,
                    GenerateAttributionReportUseCase,
                )

                generation_response = GenerateAttributionReportUseCase(
                    audit_repository=audit_repository,
                    backtest_repository=backtest_repository,
                ).execute(GenerateAttributionReportRequest(backtest_id=resolved_backtest_id))

                if not generation_response.success or generation_response.report_id is None:
                    return self._empty_audit_response(
                        generation_response.error or "归因报告生成失败",
                        backtest_id=resolved_backtest_id,
                    )

                report_data = audit_repository.get_attribution_report(
                    generation_response.report_id
                )

            if report_data is None:
                return self._empty_audit_response(
                    "未找到归因报告记录",
                    backtest_id=resolved_backtest_id,
                )

            report_id = int(report_data["id"])
            loss_analyses = audit_repository.get_loss_analyses(report_id)
            summaries = audit_repository.get_experience_summaries(report_id)
            loss_analysis = loss_analyses[0] if loss_analyses else None
            summary = summaries[0] if summaries else None

            portfolio_return = self._to_percent(float(report_data["total_pnl"]))
            allocation_effect = self._to_percent(float(report_data["regime_timing_pnl"]))
            selection_effect = self._to_percent(float(report_data["asset_selection_pnl"]))
            interaction_effect = self._to_percent(float(report_data["interaction_pnl"]))
            excess_return = round(
                allocation_effect + selection_effect + interaction_effect,
                2,
            )
            benchmark_return = round(portfolio_return - excess_return, 2)

            return DecisionStep6Response(
                attribution_method=str(report_data["attribution_method"]),
                benchmark_return=benchmark_return,
                portfolio_return=portfolio_return,
                excess_return=excess_return,
                allocation_effect=allocation_effect,
                selection_effect=selection_effect,
                interaction_effect=interaction_effect,
                loss_source=(str(loss_analysis["loss_source_display"]) if loss_analysis else None),
                lesson_learned=(
                    str(summary["lesson"])
                    if summary is not None
                    else "已有归因报告，但尚未沉淀经验总结。"
                ),
                backtest_id=int(report_data["backtest_id"]),
                report_id=report_id,
                regime_accuracy=round(float(report_data["regime_accuracy"]), 4),
                regime_predicted=(
                    str(report_data["regime_predicted"])
                    if report_data.get("regime_predicted") is not None
                    else None
                ),
                regime_actual=(
                    str(report_data["regime_actual"])
                    if report_data.get("regime_actual") is not None
                    else None
                ),
            )
        except Exception as e:
            logger.warning(f"Could not load audit for {trade_id}: {e}")

        return self._empty_audit_response(
            "历史数据不足以进行归因分析",
            backtest_id=backtest_id,
        )

    def _resolve_backtest_id(
        self,
        trade_id: str | None,
        backtest_id: int | None,
    ) -> int | None:
        """Resolve the backtest identifier for audit lookup."""
        if backtest_id is not None:
            return backtest_id

        if trade_id and trade_id.isdigit():
            return int(trade_id)

        completed_backtests = self._get_backtest_repository().get_backtests_by_status("completed")
        latest_backtest = next(
            iter(
                sorted(
                    completed_backtests,
                    key=lambda model: (
                        model.completed_at is not None,
                        model.completed_at or model.updated_at,
                        model.id,
                    ),
                    reverse=True,
                )
            ),
            None,
        )
        return latest_backtest.id if latest_backtest is not None else None

    def _empty_audit_response(
        self,
        lesson: str,
        backtest_id: int | None = None,
    ) -> DecisionStep6Response:
        """Build a safe empty audit response."""
        return DecisionStep6Response(
            attribution_method="unknown",
            benchmark_return=0.0,
            portfolio_return=0.0,
            excess_return=0.0,
            allocation_effect=0.0,
            selection_effect=0.0,
            interaction_effect=0.0,
            loss_source=None,
            lesson_learned=lesson,
            backtest_id=backtest_id,
        )

    def _to_percent(self, value: float) -> float:
        """Normalize decimal returns to percentage points for UI display."""
        if -1.0 <= value <= 1.0:
            return round(value * 100, 2)
        return round(value, 2)
