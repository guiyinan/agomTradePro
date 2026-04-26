"""Application query service for Alpha Trigger pages."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from django.utils import timezone

from .repository_provider import (
    get_alpha_candidate_repository,
    get_alpha_trigger_repository,
)


ASSET_CLASSES = ["a_股票", "a_债券", "a_商品", "a_现金", "港股", "美股", "黄金", "原油"]


class AlphaTriggerPageQueryService:
    """Build page/API query results without exposing infrastructure to views."""

    def __init__(
        self,
        *,
        trigger_repository: Any | None = None,
        candidate_repository: Any | None = None,
    ) -> None:
        self.trigger_repository = trigger_repository or get_alpha_trigger_repository()
        self.candidate_repository = candidate_repository or get_alpha_candidate_repository()

    def get_list_context(self) -> dict[str, Any]:
        """Build the Alpha Trigger list page context."""

        active_triggers = self.trigger_repository.list_active_models(limit=10)
        actionable_candidates = self.candidate_repository.list_models_by_status(
            "ACTIONABLE",
            limit=10,
        )
        watch_list = self.candidate_repository.list_models_by_status("WATCH", limit=10)
        candidate_list = self.candidate_repository.list_models_by_status("CANDIDATE", limit=10)
        for candidate in [*actionable_candidates, *watch_list, *candidate_list]:
            self._attach_candidate_compat(candidate)

        return {
            "active_triggers": active_triggers,
            "actionable_list": actionable_candidates,
            "candidate_list": candidate_list,
            "watch_list": watch_list,
            "trigger_stats": {
                "active_count": len(active_triggers),
                "total_count": self.trigger_repository.count_all(),
            },
            "candidate_stats": {
                "watch_count": len(watch_list),
                "candidate_count": self.candidate_repository.count_by_status("CANDIDATE"),
                "actionable_count": len(actionable_candidates),
            },
            "page_title": "Alpha 触发器",
            "page_description": "离散、可证伪、可行动的 Alpha 信号触发",
        }

    def get_create_context(self) -> dict[str, Any]:
        """Build the Alpha Trigger create page context."""

        return {
            "current_regime": self._resolve_current_regime(),
            "current_policy": self._resolve_current_policy(),
            "available_indicators": self._list_available_indicators(),
            "all_asset_classes": ASSET_CLASSES,
            "trigger_type_choices": self.trigger_repository.get_trigger_type_choices(),
            "page_title": "创建 Alpha 触发器",
            "page_description": "配置可证伪的 Alpha 信号触发条件",
        }

    def get_edit_context(self, trigger_id: str) -> dict[str, Any] | None:
        """Build the Alpha Trigger edit page context."""

        trigger = self.trigger_repository.get_model_by_id(trigger_id)
        if trigger is None:
            return None
        return {
            "trigger": trigger,
            "available_indicators": self._list_available_indicators(),
            "all_asset_classes": ASSET_CLASSES,
            "trigger_type_choices": self.trigger_repository.get_trigger_type_choices(),
            "page_title": f"编辑触发器: {trigger.trigger_id[:12]}...",
            "page_description": f"修改 {trigger.asset_code} 的触发条件",
        }

    def get_detail_context(self, trigger_id: str) -> dict[str, Any] | None:
        """Build the Alpha Trigger detail page context."""

        trigger = self.trigger_repository.get_model_by_id(trigger_id)
        if trigger is None:
            return None
        candidates = self.candidate_repository.list_models_by_source_trigger_id(
            trigger_id,
            limit=20,
        )
        for candidate in candidates:
            self._attach_candidate_compat(candidate)
        candidate_stats = {
            "total": len(candidates),
            "watch": len([c for c in candidates if c.status == "WATCH"]),
            "candidate": len([c for c in candidates if c.status == "CANDIDATE"]),
            "actionable": len([c for c in candidates if c.status == "ACTIONABLE"]),
            "executed": len([c for c in candidates if c.status == "EXECUTED"]),
        }
        return {
            "trigger": trigger,
            "candidates": candidates,
            "candidate_stats": candidate_stats,
            "page_title": f"触发器详情: {trigger.trigger_id[:12]}...",
            "page_description": f"{trigger.asset_code} - {trigger.get_trigger_type_display()}",
        }

    def get_candidate_detail_context(self, candidate_id: str) -> dict[str, Any] | None:
        """Build the Alpha Candidate detail page context."""

        candidate = self.candidate_repository.get_model_by_id(candidate_id)
        if candidate is None:
            return None
        self._attach_candidate_compat(candidate)
        source_trigger = self.trigger_repository.get_model_by_id(candidate.trigger_id)
        execution_ref = self._get_execution_ref(candidate.last_decision_request_id)
        return {
            "candidate": candidate,
            "source_trigger": source_trigger,
            "invalidation_conditions": self._parse_invalidation_conditions(candidate),
            "status_history": self._build_status_history(candidate),
            "days_active": (timezone.now() - candidate.created_at).days
            if candidate.created_at
            else 0,
            "execution_ref": execution_ref,
            "page_title": f"候选详情: {candidate.asset_code}",
        }

    def get_performance_context(self) -> dict[str, Any]:
        """Build the Alpha Trigger performance page context."""

        trigger_performance = self._build_trigger_performance()
        trigger_performance.sort(key=lambda x: x["performance_score"], reverse=True)
        return {
            "trigger_performance": trigger_performance,
            "trigger_type_stats": self._build_trigger_type_stats(trigger_performance),
            "trend_data": self._build_recent_trend_data(days=30),
            "overall_stats": self._build_overall_stats(trigger_performance),
            "page_title": "触发器性能追踪",
            "page_description": "评估触发器质量和投资效果",
        }

    def get_performance_data(
        self,
        *,
        days: int,
        trigger_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return compact performance rows for the performance API."""

        start_date = timezone.now() - timedelta(days=days)
        triggers = (
            [self.trigger_repository.get_model_by_id(trigger_id)]
            if trigger_id
            else self.trigger_repository.list_active_models()
        )
        rows = []
        for trigger in triggers:
            if not trigger:
                continue
            candidates = self.candidate_repository.list_models_by_source_trigger_id(
                trigger.trigger_id,
                since=start_date,
            )
            total = len(candidates)
            executed = len([c for c in candidates if c.status == "EXECUTED"])
            invalidated = len([c for c in candidates if c.status in ["INVALIDATED", "EXPIRED"]])
            rows.append(
                {
                    "trigger_id": trigger.trigger_id,
                    "asset_code": trigger.asset_code,
                    "trigger_type": trigger.trigger_type,
                    "total_candidates": total,
                    "executed": executed,
                    "invalidated": invalidated,
                    "conversion_rate": round(executed / total * 100, 1) if total > 0 else 0,
                    "invalidation_rate": round(invalidated / total * 100, 1)
                    if total > 0
                    else 0,
                }
            )
        return rows

    def _resolve_current_regime(self) -> Any | None:
        try:
            from apps.regime.application.current_regime import resolve_current_regime

            return resolve_current_regime()
        except Exception:
            return None

    def _resolve_current_policy(self) -> Any | None:
        try:
            from apps.policy.application.repository_provider import get_current_policy_repository
            from apps.policy.application.use_cases import GetCurrentPolicyUseCase

            policy_response = GetCurrentPolicyUseCase(get_current_policy_repository()).execute()
            if policy_response.success and policy_response.policy_level:
                return policy_response.policy_level
        except Exception:
            return None
        return None

    def _list_available_indicators(self) -> list[dict[str, Any]]:
        try:
            from apps.macro.application.indicator_service import (
                get_available_indicators_for_frontend,
            )

            return get_available_indicators_for_frontend(include_stats=False)[:50]
        except Exception:
            return []

    def _get_execution_ref(self, request_id: str | None) -> dict[str, Any] | None:
        if not request_id:
            return None
        try:
            from core.integration.decision_requests import (
                get_decision_request_repository,
            )

            decision_request = get_decision_request_repository().get_by_id(request_id)
            return getattr(decision_request, "execution_ref", None)
        except Exception:
            return None

    def _parse_invalidation_conditions(self, candidate: Any) -> list[Any]:
        conditions = getattr(candidate, "invalidation_conditions", None)
        if isinstance(conditions, list):
            return conditions
        if isinstance(conditions, dict):
            return [conditions]
        if isinstance(conditions, str) and conditions:
            try:
                parsed = json.loads(conditions)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
        return []

    def _build_status_history(self, candidate: Any) -> list[dict[str, Any]]:
        status_history = [
            {
                "status": "CREATED",
                "created_at": candidate.created_at,
                "note": f"由触发器 {candidate.trigger_id[:12]}... 创建",
            }
        ]
        if candidate.status != "CREATED":
            status_history.append(
                {
                    "status": candidate.status,
                    "created_at": candidate.updated_at,
                    "note": "状态已更新",
                }
            )
        return status_history

    def _build_trigger_performance(self) -> list[dict[str, Any]]:
        trigger_performance = []
        for trigger in self.trigger_repository.list_active_models():
            candidates = self.candidate_repository.list_models_by_source_trigger_id(
                trigger.trigger_id
            )
            total_candidates = len(candidates)
            executed_count = len([c for c in candidates if c.status == "EXECUTED"])
            invalidated_count = len(
                [c for c in candidates if c.status in ["INVALIDATED", "EXPIRED"]]
            )
            actionable_count = len([c for c in candidates if c.status == "ACTIONABLE"])
            conversion_rate = (
                round(executed_count / total_candidates * 100, 1)
                if total_candidates > 0
                else 0
            )
            invalidation_rate = (
                round(invalidated_count / total_candidates * 100, 1)
                if total_candidates > 0
                else 0
            )
            avg_confidence = (
                sum(float(getattr(c, "confidence", 0) or 0) for c in candidates)
                / total_candidates
                if total_candidates > 0
                else 0
            )
            avg_holding_days = self._average_holding_days(candidates)
            days_active = (timezone.now() - trigger.created_at).days if trigger.created_at else 0
            trigger_frequency = (
                round(total_candidates / days_active, 2) if days_active > 0 else 0
            )
            performance_score = 0
            if total_candidates > 0:
                performance_score = round(
                    conversion_rate * 0.4
                    + (100 - invalidation_rate) * 0.3
                    + (avg_confidence * 100) * 0.3,
                    1,
                )
            trigger_performance.append(
                {
                    "trigger": trigger,
                    "total_candidates": total_candidates,
                    "executed_count": executed_count,
                    "invalidated_count": invalidated_count,
                    "actionable_count": actionable_count,
                    "conversion_rate": conversion_rate,
                    "invalidation_rate": invalidation_rate,
                    "avg_confidence": round(avg_confidence, 2),
                    "avg_holding_days": avg_holding_days,
                    "days_active": days_active,
                    "trigger_frequency": trigger_frequency,
                    "performance_score": performance_score,
                }
            )
        return trigger_performance

    def _average_holding_days(self, candidates: list[Any]) -> float:
        days_list = []
        for candidate in candidates:
            executed_at = getattr(candidate, "executed_at", None) or getattr(
                candidate,
                "promoted_to_signal_at",
                None,
            )
            if candidate.status == "EXECUTED" and candidate.created_at and executed_at:
                days_list.append((executed_at - candidate.created_at).days)
        return round(sum(days_list) / len(days_list), 1) if days_list else 0

    def _build_trigger_type_stats(
        self,
        trigger_performance: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        trigger_type_stats: dict[str, dict[str, Any]] = {}
        for perf in trigger_performance:
            trigger_type = perf["trigger"].get_trigger_type_display()
            stats = trigger_type_stats.setdefault(
                trigger_type,
                {
                    "count": 0,
                    "total_candidates": 0,
                    "total_executed": 0,
                    "avg_score": 0,
                    "scores": [],
                },
            )
            stats["count"] += 1
            stats["total_candidates"] += perf["total_candidates"]
            stats["total_executed"] += perf["executed_count"]
            stats["scores"].append(perf["performance_score"])
        for stats in trigger_type_stats.values():
            if stats["scores"]:
                stats["avg_score"] = round(sum(stats["scores"]) / len(stats["scores"]), 1)
            stats["conversion_rate"] = (
                round(stats["total_executed"] / stats["total_candidates"] * 100, 1)
                if stats["total_candidates"] > 0
                else 0
            )
            del stats["scores"]
        return trigger_type_stats

    def _build_overall_stats(
        self,
        trigger_performance: list[dict[str, Any]],
    ) -> dict[str, Any]:
        total_candidates = self.candidate_repository.count_all()
        total_executed = self.candidate_repository.count_by_status("EXECUTED")
        return {
            "total_triggers": len(trigger_performance),
            "total_candidates": total_candidates,
            "total_executed": total_executed,
            "conversion_rate": round(total_executed / total_candidates * 100, 1)
            if total_candidates > 0
            else 0,
        }

    def _build_recent_trend_data(self, days: int) -> list[dict[str, Any]]:
        start_date = timezone.now() - timedelta(days=days)
        daily_stats: dict[str, dict[str, int]] = {}
        for candidate in self.candidate_repository.list_recent_models(start_date):
            date_str = candidate.created_at.date().isoformat()
            stats = daily_stats.setdefault(
                date_str,
                {"created": 0, "executed": 0, "invalidated": 0},
            )
            stats["created"] += 1
            if candidate.status == "EXECUTED":
                stats["executed"] += 1
            elif candidate.status in ["INVALIDATED", "EXPIRED"]:
                stats["invalidated"] += 1
        return [
            {"date": date_str, **daily_stats[date_str]}
            for date_str in sorted(daily_stats.keys())
        ]

    def _attach_candidate_compat(self, candidate: Any) -> None:
        if not hasattr(candidate, "source_trigger_id"):
            candidate.source_trigger_id = candidate.trigger_id


def get_alpha_trigger_page_query_service() -> AlphaTriggerPageQueryService:
    """Return the default Alpha Trigger page query service."""

    return AlphaTriggerPageQueryService()
