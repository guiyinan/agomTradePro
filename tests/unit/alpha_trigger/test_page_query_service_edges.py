"""Behavioral tests for Alpha Trigger page query aggregation."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from django.utils import timezone

from apps.alpha_trigger.application.page_query_service import AlphaTriggerPageQueryService


class _TriggerRepo:
    def __init__(self, triggers: list[SimpleNamespace]) -> None:
        self.triggers = triggers

    def list_active_models(self, limit: int | None = None) -> list[SimpleNamespace]:
        return self.triggers[:limit]

    def count_all(self) -> int:
        return len(self.triggers)

    def get_model_by_id(self, trigger_id: str) -> SimpleNamespace | None:
        return next((item for item in self.triggers if item.trigger_id == trigger_id), None)

    def get_trigger_type_choices(self) -> list[tuple[str, str]]:
        return [("MOMENTUM_SIGNAL", "Momentum")]


class _CandidateRepo:
    def __init__(self, candidates: list[SimpleNamespace]) -> None:
        self.candidates = candidates

    def list_models_by_status(
        self,
        status: str,
        limit: int | None = None,
    ) -> list[SimpleNamespace]:
        rows = [item for item in self.candidates if item.status == status]
        return rows[:limit]

    def list_models_by_source_trigger_id(
        self,
        trigger_id: str,
        **kwargs: object,
    ) -> list[SimpleNamespace]:
        return [item for item in self.candidates if item.trigger_id == trigger_id]

    def get_model_by_id(self, candidate_id: str) -> SimpleNamespace | None:
        return next((item for item in self.candidates if item.candidate_id == candidate_id), None)

    def count_by_status(self, status: str) -> int:
        return len([item for item in self.candidates if item.status == status])

    def count_all(self) -> int:
        return len(self.candidates)

    def list_recent_models(self, start_date: object) -> list[SimpleNamespace]:
        return self.candidates


def _fixtures() -> tuple[_TriggerRepo, _CandidateRepo]:
    now = timezone.now()
    trigger = SimpleNamespace(
        trigger_id="trigger-contract-001",
        asset_code="000001.SZ",
        trigger_type="MOMENTUM_SIGNAL",
        created_at=now - timedelta(days=10),
        get_trigger_type_display=lambda: "Momentum",
    )
    candidates = [
        SimpleNamespace(
            candidate_id=f"candidate-{index}",
            trigger_id=trigger.trigger_id,
            asset_code="000001.SZ",
            status=status,
            confidence=confidence,
            invalidation_conditions=conditions,
            created_at=now - timedelta(days=4 - index),
            updated_at=now,
            executed_at=now if status == "EXECUTED" else None,
            promoted_to_signal_at=None,
            last_decision_request_id=None,
        )
        for index, (status, confidence, conditions) in enumerate(
            (
                ("WATCH", 0.5, [{"type": "price"}]),
                ("CANDIDATE", 0.6, '{"type": "regime"}'),
                ("ACTIONABLE", 0.8, "invalid-json"),
                ("EXECUTED", 0.9, []),
                ("INVALIDATED", 0.4, {}),
            )
        )
    ]
    return _TriggerRepo([trigger]), _CandidateRepo(candidates)


def test_page_service_builds_list_detail_candidate_and_performance_contexts() -> None:
    """Page contexts aggregate counts, conversions, and compatibility attributes."""
    triggers, candidates = _fixtures()
    service = AlphaTriggerPageQueryService(
        trigger_repository=triggers,
        candidate_repository=candidates,
    )

    listing = service.get_list_context()
    assert listing["trigger_stats"] == {"active_count": 1, "total_count": 1}
    assert listing["candidate_stats"]["actionable_count"] == 1
    assert listing["watch_list"][0].source_trigger_id == "trigger-contract-001"

    assert service.get_edit_context("missing") is None
    edit = service.get_edit_context("trigger-contract-001")
    assert edit is not None and edit["trigger_type_choices"]

    assert service.get_detail_context("missing") is None
    detail = service.get_detail_context("trigger-contract-001")
    assert detail is not None
    assert detail["candidate_stats"]["executed"] == 1

    assert service.get_candidate_detail_context("missing") is None
    candidate = service.get_candidate_detail_context("candidate-1")
    assert candidate is not None
    assert candidate["invalidation_conditions"] == [{"type": "regime"}]
    assert len(candidate["status_history"]) == 2

    performance = service.get_performance_context()
    assert performance["overall_stats"]["total_candidates"] == 5
    assert performance["trigger_performance"][0]["performance_score"] > 0
    assert performance["trigger_type_stats"]["Momentum"]["count"] == 1
    assert performance["trend_data"]


def test_page_service_performance_api_and_parsing_boundaries() -> None:
    """Performance API handles empty filters and JSON condition shapes safely."""
    triggers, candidates = _fixtures()
    service = AlphaTriggerPageQueryService(
        trigger_repository=triggers,
        candidate_repository=candidates,
    )
    rows = service.get_performance_data(days=30)
    assert rows[0]["total_candidates"] == 5
    assert rows[0]["conversion_rate"] == 20.0
    assert service.get_performance_data(days=30, trigger_id="missing") == []

    assert service._parse_invalidation_conditions(SimpleNamespace(invalidation_conditions={})) == [
        {}
    ]
    assert (
        service._parse_invalidation_conditions(SimpleNamespace(invalidation_conditions="invalid"))
        == []
    )
    assert service._parse_invalidation_conditions(SimpleNamespace(invalidation_conditions="")) == []
    assert service._build_overall_stats([])["conversion_rate"] == 20.0
