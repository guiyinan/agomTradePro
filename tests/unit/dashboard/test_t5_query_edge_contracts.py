"""Degraded-mode and helper contracts for dashboard query services."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.dashboard.application import queries as query_module
from apps.dashboard.application.queries import (
    AlphaDecisionChainQuery,
    AlphaVisualizationQuery,
    DashboardDetailQuery,
    DecisionPlaneQuery,
    RegimeSummaryQuery,
)


def _result(
    *,
    success: bool,
    scores: list[object] | None = None,
    source: str = "cache",
    metadata: dict[str, object] | None = None,
    error_message: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        success=success,
        scores=scores or [],
        source=source,
        status="available" if success else "degraded",
        staleness_days=1,
        metadata=metadata or {},
        error_message=error_message,
    )


def test_alpha_score_payload_uses_fallback_and_builds_reliability_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qlib = _result(success=False, error_message="Qlib not ready", metadata={"async_task_triggered": True})
    score = SimpleNamespace(
        code="600000.SH",
        score=0.87654,
        rank=1,
        source="cache",
        confidence=0.9345,
        factors={"value": 1},
        asof_date=date(2026, 7, 1),
    )
    cached = _result(
        success=True,
        scores=[score],
        metadata={"cache_date": "2026-07-01"},
    )
    service = SimpleNamespace(
        get_stock_scores=lambda **kwargs: qlib if kwargs["provider_filter"] == "qlib" else cached
    )
    monkeypatch.setattr("apps.alpha.application.services.AlphaService", lambda: service)
    monkeypatch.setattr(
        AlphaVisualizationQuery,
        "_resolve_security_names",
        lambda _self, _codes: {"600000.SH": "浦发银行"},
    )

    payload = AlphaVisualizationQuery()._get_stock_scores_payload(1)

    assert payload["items"][0]["name"] == "浦发银行"
    assert payload["items"][0]["score"] == 0.8765
    assert payload["meta"]["fallback_from"] == "qlib"
    assert payload["meta"]["refresh_triggered"] is True
    assert "自动触发" in payload["meta"]["warning_message"]


def test_alpha_score_payload_handles_no_result_and_service_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_score = _result(success=False)
    monkeypatch.setattr(
        "apps.alpha.application.services.AlphaService",
        lambda: SimpleNamespace(get_stock_scores=lambda **_kwargs: no_score),
    )
    payload = AlphaVisualizationQuery()._get_stock_scores_payload(3)
    assert payload["items"] == []
    assert payload["meta"]["status"] == "degraded"

    monkeypatch.setattr(
        "apps.alpha.application.services.AlphaService",
        lambda: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )
    failed = AlphaVisualizationQuery()._get_stock_scores_payload(3)
    assert failed["meta"]["warning_message"] == "alpha_stock_scores_unavailable"


def test_alpha_alias_and_name_helpers_cover_empty_rows_and_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = AlphaVisualizationQuery()
    assert query._build_code_aliases(["", "  ", "600000.sh"]) == {
        "600000.sh": {"600000", "600000.SH"}
    }
    assert query._resolve_security_names([]) == {}

    monkeypatch.setattr(
        "apps.asset_analysis.application.asset_name_service.resolve_asset_names",
        lambda _codes: {"600000": "浦发银行"},
    )
    assert query._resolve_security_names(["600000.SH"]) == {"600000.SH": "浦发银行"}

    monkeypatch.setattr(
        "apps.asset_analysis.application.asset_name_service.resolve_asset_names",
        lambda _codes: (_ for _ in ()).throw(RuntimeError("resolver down")),
    )
    assert query._resolve_security_names(["600000.SH"]) == {}

    names: dict[str, str] = {}
    query._assign_names_from_rows(
        name_map=names,
        code_aliases={"600000.SH": {"600000", "600000.SH"}},
        rows=[
            {"code": "", "name": "ignored"},
            {"code": "600000", "name": ""},
            {"code": "600000", "name": "浦发银行"},
        ],
        code_field="code",
        name_field="name",
    )
    assert names == {"600000.SH": "浦发银行"}


def test_alpha_provider_and_coverage_metrics_support_live_and_degraded_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = SimpleNamespace(
        get_metric=lambda name, labels=None: (
            SimpleNamespace(value=0.9123)
            if name in {"alpha_provider_success_rate", "alpha_coverage_ratio"}
            else SimpleNamespace(value=12)
        )
    )
    metrics = SimpleNamespace(registry=registry)
    service = SimpleNamespace(
        get_provider_status=lambda: {"qlib": {"healthy": True}},
        get_provider_registry_status=lambda: {"cache": {"registered": True}},
    )
    monkeypatch.setattr("apps.alpha.application.services.AlphaService", lambda: service)
    monkeypatch.setattr("shared.infrastructure.metrics.get_alpha_metrics", lambda: metrics)
    query = AlphaVisualizationQuery()

    provider = query._get_provider_status()
    assert provider["metrics"]["qlib"] == {"success_rate": 0.912, "latency_ms": 12}
    lightweight = query._get_lightweight_provider_status()
    assert lightweight["status"] == "registered"
    coverage = query._get_coverage_metrics()
    assert coverage["coverage_ratio"] == 0.912
    assert coverage["total_requests"] == 12

    monkeypatch.setattr(
        "shared.infrastructure.metrics.get_alpha_metrics",
        lambda: (_ for _ in ()).throw(RuntimeError("metrics down")),
    )
    assert query._get_provider_status()["status"] == "degraded"
    assert query._get_lightweight_provider_status()["data_source"] == "fallback"
    assert query._get_coverage_metrics()["warning_message"] == "coverage_metrics_unavailable"


def test_lightweight_provider_status_uses_legacy_status_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(get_provider_status=lambda: {})
    metrics = SimpleNamespace(registry=SimpleNamespace(get_metric=lambda *_args, **_kwargs: None))
    monkeypatch.setattr("apps.alpha.application.services.AlphaService", lambda: service)
    monkeypatch.setattr("shared.infrastructure.metrics.get_alpha_metrics", lambda: metrics)

    assert AlphaVisualizationQuery()._get_lightweight_provider_status()["providers"] == {}


def test_ic_trends_live_empty_and_repository_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SimpleNamespace(get_alpha_ic_trends=lambda _days: [{"ic": 0.1}])
    monkeypatch.setattr(query_module, "get_dashboard_query_repository", lambda: repository)
    query = AlphaVisualizationQuery()
    assert query._get_ic_trends(1) == [{"ic": 0.1}]
    assert query._build_ic_trends_meta([{"ic": 0.1}])["status"] == "available"

    repository.get_alpha_ic_trends = lambda _days: []
    empty = query._get_ic_trends(2)
    assert len(empty) == 2
    assert query._build_ic_trends_meta(empty)["status"] == "unavailable"

    repository.get_alpha_ic_trends = lambda _days: (_ for _ in ()).throw(RuntimeError("db down"))
    assert len(query._get_ic_trends(3)) == 3


def test_decision_plane_config_counts_and_quota_degradation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beta_service = SimpleNamespace(
        get_active_config_context=lambda: {"allowed_asset_classes": ["equity", "fund", "bond", "cash"]}
    )
    alpha_service = SimpleNamespace(
        get_workspace_summary=lambda: {
            "alpha_watch_count": 2,
            "alpha_candidate_count": 3,
            "alpha_actionable_count": 4,
        }
    )
    quota_service = SimpleNamespace(
        get_weekly_quota_usage=lambda: {
            "quota_total": 8,
            "quota_used": 3,
            "quota_remaining": 5,
        }
    )
    monkeypatch.setattr(
        "apps.beta_gate.application.config_summary_service.get_beta_gate_config_summary_service",
        lambda: beta_service,
    )
    monkeypatch.setattr(
        "apps.alpha_trigger.application.global_alert_service.get_alpha_trigger_global_alert_service",
        lambda: alpha_service,
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.global_alert_service.get_decision_rhythm_global_alert_service",
        lambda: quota_service,
    )
    query = DecisionPlaneQuery()

    assert query._get_beta_gate_visible_classes() == "equity, fund, bond"
    assert query._get_alpha_status_count("WATCH") == 2
    assert query._get_alpha_status_count("UNKNOWN") == 0
    assert query._get_quota_total() == 8
    assert query._get_quota_used() == 3
    assert query._get_quota_remaining() == 5
    assert query._get_quota_usage_percent() == 37.5

    beta_service.get_active_config_context = lambda: {}
    quota_service.get_weekly_quota_usage = lambda: None
    assert query._get_beta_gate_visible_classes() == "全部"
    assert query._get_quota_total() == 10
    assert query._get_quota_used() == 0
    assert query._get_quota_remaining() == 10

    monkeypatch.setattr(
        "apps.decision_rhythm.application.global_alert_service.get_decision_rhythm_global_alert_service",
        lambda: (_ for _ in ()).throw(RuntimeError("down")),
    )
    assert query._get_quota_total() == 10
    assert query._get_quota_used() == 0
    assert query._get_quota_remaining() == 10


def test_decision_plane_asset_name_and_list_loading_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = DecisionPlaneQuery()
    unnamed = SimpleNamespace(asset_code="600000.SH", asset_name="")
    named = SimpleNamespace(asset_code="000001.SZ", asset_name="平安银行")
    blank = SimpleNamespace(asset_code="", asset_name="")
    monkeypatch.setattr(
        "apps.asset_analysis.application.asset_name_service.resolve_asset_names",
        lambda _codes: {"600000": "浦发银行"},
    )
    assert query._attach_asset_names([]) == []
    enriched = query._attach_asset_names([unnamed, named, blank])
    assert enriched[0].asset_name == "浦发银行"
    assert enriched[1].asset_name == "平安银行"

    monkeypatch.setattr(
        "apps.asset_analysis.application.asset_name_service.resolve_asset_names",
        lambda _codes: (_ for _ in ()).throw(RuntimeError("down")),
    )
    assert query._attach_asset_names([unnamed]) == [unnamed]

    context_repo = SimpleNamespace(load_actionable_candidates=lambda max_count: [unnamed])
    monkeypatch.setattr(query_module, "get_dashboard_alpha_context_repository", lambda: context_repo)
    monkeypatch.setattr(query, "_attach_asset_names", lambda items: items)
    assert query._get_actionable_candidates(1) == [unnamed]
    context_repo.load_actionable_candidates = lambda max_count: (_ for _ in ()).throw(
        RuntimeError("db down")
    )
    assert query._get_actionable_candidates(1) == []


def test_pending_request_loading_deduplicates_and_isolates_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = SimpleNamespace(asset_code="600000.SH")
    duplicate = SimpleNamespace(asset_code="600000.SH")
    blank = SimpleNamespace(asset_code="")
    second = SimpleNamespace(asset_code="000001.SZ")
    service = SimpleNamespace(
        list_pending_execution_requests=lambda: [blank, first, duplicate, second]
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.global_alert_service.get_decision_rhythm_global_alert_service",
        lambda: service,
    )
    query = DecisionPlaneQuery()
    monkeypatch.setattr(query, "_attach_asset_names", lambda items: items)
    assert query._get_pending_requests(1) == [first]

    service.list_pending_execution_requests = lambda: (_ for _ in ()).throw(RuntimeError("down"))
    assert query._get_pending_requests(None) == []


def test_alpha_decision_chain_match_and_serialization_helpers() -> None:
    query = AlphaDecisionChainQuery()
    top = [{"code": "600000.SH", "rank": 1, "score": 0.9, "source": "qlib"}]
    assert query._build_code_aliases("") == set()
    assert query._build_top_lookup_codes(top) == ["600000", "600000.SH"]
    index = query._build_top_match_index(top)
    assert query._match_top_stock(index, "600000") == top[0]
    assert query._match_top_stock(index, "000001") is None

    pending = [
        SimpleNamespace(asset_code="600000", request_id="r1", execution_status="pending"),
        SimpleNamespace(asset_code="600000.SH", request_id="r2", execution_status="pending"),
        SimpleNamespace(asset_code="000001.SZ", request_id="r3", execution_status="pending"),
    ]
    pending_matches = query._build_pending_matches(top, pending)
    assert pending_matches == {
        "600000.SH": {"request_id": "r1", "execution_status": "pending"}
    }
    assert query._build_pending_matches([], pending) == {}

    candidates = [
        SimpleNamespace(asset_code="600000", candidate_id="c1", direction="buy", confidence=0.8),
        SimpleNamespace(asset_code="000001", candidate_id="c2", direction="buy", confidence=0.7),
    ]
    assert query._build_actionable_matches(
        top,
        candidates,
        pending_matches=pending_matches,
    ) == {}
    assert query._build_actionable_matches([], candidates, pending_matches={}) == {}

    serialized = query._serialize_actionable_candidate(candidates[0], index)
    assert serialized["is_in_top10"] is True
    outside = query._serialize_pending_request(pending[2], index)
    assert outside["origin_stage_label"] == "当前不在 Top 10"


def test_regime_summary_current_empty_and_error_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SimpleNamespace(get_latest_snapshot=lambda: None)
    monkeypatch.setattr(
        "apps.regime.application.repository_provider.get_regime_repository",
        lambda: repository,
    )
    query = RegimeSummaryQuery()
    assert query.execute().regime_warnings == ["No regime data available"]

    repository.get_latest_snapshot = lambda: SimpleNamespace(
        dominant_regime=None,
        observed_at=date(2026, 7, 1),
        confidence=None,
        growth_momentum_z=1.2,
        inflation_momentum_z=-0.3,
    )
    monkeypatch.setattr(query, "_get_latest_macro_value", lambda code: 50.0 if code == "PMI" else 2.0)
    current = query.execute()
    assert current.current_regime == "Unknown"
    assert current.regime_data_health is True

    repository.get_latest_snapshot = lambda: (_ for _ in ()).throw(RuntimeError("db down"))
    assert query.execute().regime_warnings == ["db down"]

    dashboard_repo = SimpleNamespace(
        get_latest_macro_indicator_value=lambda _code: (_ for _ in ()).throw(RuntimeError("down"))
    )
    monkeypatch.setattr(query_module, "get_dashboard_query_repository", lambda: dashboard_repo)
    assert RegimeSummaryQuery()._get_latest_macro_value("PMI") is None


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (ValueError("position not found"), "未找到持仓 600000.SH"),
        (ValueError("invalid user"), "invalid user"),
        (RuntimeError("database down"), "database down"),
    ],
)
def test_dashboard_position_detail_error_contracts(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    message: str,
) -> None:
    repository = SimpleNamespace(
        get_position_detail=lambda **_kwargs: (_ for _ in ()).throw(error)
    )
    monkeypatch.setattr(query_module, "get_dashboard_query_repository", lambda: repository)

    result = DashboardDetailQuery().get_position_detail(1, "600000.SH")
    assert result["error"] == message


def test_generate_alpha_candidates_counts_all_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.alpha_trigger.application import repository_provider, use_cases

    triggers = [
        SimpleNamespace(trigger_id="existing"),
        SimpleNamespace(trigger_id="failed"),
        SimpleNamespace(trigger_id="high"),
        SimpleNamespace(trigger_id="promote-error"),
        SimpleNamespace(trigger_id="low"),
    ]
    responses = {
        "failed": SimpleNamespace(success=False, candidate=None),
        "high": SimpleNamespace(
            success=True,
            candidate=SimpleNamespace(candidate_id="c-high", confidence=0.9),
        ),
        "promote-error": SimpleNamespace(
            success=True,
            candidate=SimpleNamespace(candidate_id="c-error", confidence=0.8),
        ),
        "low": SimpleNamespace(
            success=True,
            candidate=SimpleNamespace(candidate_id="c-low", confidence=0.6),
        ),
    }
    candidate_repo = MagicMock()
    candidate_repo.update_status.side_effect = [None, ValueError("status race")]
    monkeypatch.setattr(repository_provider, "get_alpha_trigger_repository", lambda: MagicMock())
    monkeypatch.setattr(repository_provider, "get_alpha_candidate_repository", lambda: candidate_repo)

    class FakeUseCase:
        def __init__(self, *_args: object) -> None:
            pass

        def execute(self, request: object) -> object:
            return responses[request.trigger_id]  # type: ignore[attr-defined]

    monkeypatch.setattr(use_cases, "GenerateCandidateUseCase", FakeUseCase)
    dashboard_repo = SimpleNamespace(
        load_alpha_candidate_generation_context=lambda: {
            "active_triggers": triggers,
            "existing_trigger_ids": {"existing"},
            "actionable_count": 7,
        }
    )
    monkeypatch.setattr(query_module, "get_dashboard_query_repository", lambda: dashboard_repo)

    result = DashboardDetailQuery().generate_alpha_candidates()

    assert result == {
        "generated": 3,
        "promoted_to_actionable": 1,
        "skipped_existing": 1,
        "failed": 1,
        "active_trigger_count": 5,
        "actionable_count": 7,
    }


def test_query_singletons_are_created_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query_module, "_alpha_visualization_query", None)
    monkeypatch.setattr(query_module, "_decision_plane_query", None)
    monkeypatch.setattr(query_module, "_alpha_decision_chain_query", None)
    monkeypatch.setattr(query_module, "_regime_summary_query", None)
    monkeypatch.setattr(query_module, "_dashboard_detail_query", None)

    assert query_module.get_alpha_visualization_query() is query_module.get_alpha_visualization_query()
    assert query_module.get_decision_plane_query() is query_module.get_decision_plane_query()
    assert query_module.get_alpha_decision_chain_query() is query_module.get_alpha_decision_chain_query()
    assert query_module.get_regime_summary_query() is query_module.get_regime_summary_query()
    assert query_module.get_dashboard_detail_query() is query_module.get_dashboard_detail_query()
