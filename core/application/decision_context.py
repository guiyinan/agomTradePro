"""
Decision Context Orchestration layer for the 6-Step Decision Funnel.

Orchestrates interactions between Regime, Pulse, Policy, Rotation,
Decision_Rhythm, and Audit modules to provide seamless data for the UI pipeline.
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

from apps.audit.application.use_cases import (
    GenerateAttributionReportRequest,
    GenerateAttributionReportUseCase,
)
from apps.audit.infrastructure.repositories import DjangoAuditRepository
from apps.backtest.infrastructure.repositories import DjangoBacktestRepository
from apps.regime.application.navigator_use_cases import (
    BuildRegimeNavigatorUseCase,
    GetActionRecommendationUseCase,
)
from apps.pulse.application.use_cases import GetLatestPulseUseCase
from apps.rotation.infrastructure.services import RotationIntegrationService

logger = logging.getLogger(__name__)


@dataclass
class DecisionStep1Response:
    """Step 1: 环境评估 (Environment Assessment)"""

    regime_name: str
    pulse_composite: float
    regime_strength: str
    policy_level: Optional[str]
    overall_verdict: str


@dataclass
class DecisionStep2Response:
    """Step 2: 方向选择 (Direction & Asset Allocation)"""

    action_recommendation: Dict[str, Any]
    asset_weights: Dict[str, float]
    risk_budget_pct: float


@dataclass
class DecisionStep3Response:
    """Step 3: 板块选择 (Sector Rotation)"""

    sector_recommendations: List[Dict[str, Any]]
    rotation_signals: List[Dict[str, Any]]


@dataclass
class DecisionStep4Response:
    """Step 4: 推优筛选 (Unified Recommendation Screen)"""

    unified_recommendations: List[Dict[str, Any]]
    total_candidates: int
    page: int


@dataclass
class DecisionStep5Response:
    """Step 5: 审批执行 (Execution & Approval)"""

    approval_request_id: str
    suggested_weight: float
    position_limit: float
    gate_penalties: Dict[str, Any]
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
    loss_source: Optional[str]
    lesson_learned: str
    backtest_id: Optional[int] = None
    report_id: Optional[int] = None
    regime_accuracy: Optional[float] = None
    regime_predicted: Optional[str] = None
    regime_actual: Optional[str] = None


class DecisionContextUseCase:
    """Orchestrates multi-module calls for the decision funnel steps."""

    def __init__(self):
        self.nav_usecase = BuildRegimeNavigatorUseCase()
        self.pulse_usecase = GetLatestPulseUseCase()
        self.action_usecase = GetActionRecommendationUseCase()
        self.rotation_service = RotationIntegrationService()
        self.audit_repository = DjangoAuditRepository()
        self.backtest_repository = DjangoBacktestRepository()

    def get_step1_context(self, as_of_date: Optional[date] = None) -> DecisionStep1Response:
        """Step 1: Environment Assessment
        Combine Regime + Pulse + Policy to output an overall verdict.
        """
        target_date = as_of_date or date.today()

        # 1. Regime
        navigator = self.nav_usecase.execute(target_date)
        regime_name = navigator.regime_name if navigator else "UNKNOWN"

        # 2. Pulse
        pulse = None
        try:
            pulse = self.pulse_usecase.execute()
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
        )

    def get_step2_direction(self, as_of_date: Optional[date] = None) -> DecisionStep2Response:
        """Step 2: Direction Selection"""
        target_date = as_of_date or date.today()
        action_rec = self.action_usecase.execute(target_date)

        if not action_rec:
            return DecisionStep2Response(
                action_recommendation={},
                asset_weights={"equity": 0.5, "bond": 0.3, "commodity": 0.1, "cash": 0.1},
                risk_budget_pct=0.5,
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
        )

    def get_step3_sectors(
        self,
        category: str = "equity",
        as_of_date: Optional[date] = None,
    ) -> DecisionStep3Response:
        """Step 3: Sector Selection
        Combine Action Recommended sectors with Momentum Rotation logic.
        """
        target_date = as_of_date or date.today()
        action_rec = self.action_usecase.execute(target_date)
        rotation_payload = self.rotation_service.get_rotation_recommendation("momentum")
        asset_master = self.rotation_service.get_asset_master(include_inactive=False)

        if rotation_payload.get("error"):
            logger.warning(
                "Rotation recommendation unavailable in DecisionContext: %s",
                rotation_payload["error"],
            )
            return DecisionStep3Response(
                sector_recommendations=[],
                rotation_signals=[],
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

        return DecisionStep3Response(
            sector_recommendations=sector_recommendations,
            rotation_signals=rotation_signals,
        )

    def get_step6_audit(
        self,
        trade_id: Optional[str] = None,
        backtest_id: Optional[int] = None,
    ) -> DecisionStep6Response:
        """Step 6: Audit Attribution
        Fetch the attribution results for a given trade/backtest.
        """
        try:
            resolved_backtest_id = self._resolve_backtest_id(trade_id, backtest_id)
            if resolved_backtest_id is None:
                return self._empty_audit_response("缺少可复盘的回测记录，请传入 backtest_id。")

            reports = self.audit_repository.get_reports_by_backtest(resolved_backtest_id)
            report_data = reports[0] if reports else None

            if report_data is None:
                generation_response = GenerateAttributionReportUseCase(
                    audit_repository=self.audit_repository,
                    backtest_repository=self.backtest_repository,
                ).execute(GenerateAttributionReportRequest(backtest_id=resolved_backtest_id))

                if not generation_response.success or generation_response.report_id is None:
                    return self._empty_audit_response(
                        generation_response.error or "归因报告生成失败",
                        backtest_id=resolved_backtest_id,
                    )

                report_data = self.audit_repository.get_attribution_report(
                    generation_response.report_id
                )

            if report_data is None:
                return self._empty_audit_response(
                    "未找到归因报告记录",
                    backtest_id=resolved_backtest_id,
                )

            report_id = int(report_data["id"])
            loss_analyses = self.audit_repository.get_loss_analyses(report_id)
            summaries = self.audit_repository.get_experience_summaries(report_id)
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
        trade_id: Optional[str],
        backtest_id: Optional[int],
    ) -> Optional[int]:
        """Resolve the backtest identifier for audit lookup."""
        if backtest_id is not None:
            return backtest_id

        if trade_id and trade_id.isdigit():
            return int(trade_id)

        completed_backtests = self.backtest_repository.get_backtests_by_status("completed")
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
        backtest_id: Optional[int] = None,
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
