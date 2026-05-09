from datetime import date, datetime, timezone
from types import SimpleNamespace

from core.application.decision_context import DecisionContextUseCase


def test_step1_context_prefers_cached_regime_and_non_refresh_pulse(monkeypatch):
    cached_regime = SimpleNamespace(
        dominant_regime="Recovery",
        confidence=0.91,
        observed_at=date(2026, 5, 9),
    )
    pulse_calls = []

    monkeypatch.setattr(
        "core.application.decision_context.get_regime_repository",
        lambda: SimpleNamespace(get_latest_snapshot=lambda before_date=None: cached_regime),
    )

    use_case = DecisionContextUseCase()
    use_case.nav_usecase = SimpleNamespace(
        execute=lambda target_date: (_ for _ in ()).throw(
            AssertionError("live navigator path should not run when cached regime exists")
        )
    )

    def _pulse_execute(**kwargs):
        pulse_calls.append(kwargs)
        return SimpleNamespace(composite_score=0.42, regime_strength="strong")

    use_case.pulse_usecase = SimpleNamespace(execute=_pulse_execute)

    result = use_case.get_step1_context(date(2026, 5, 9))

    assert result.regime_name == "Recovery"
    assert result.pulse_composite == 0.42
    assert result.regime_strength == "strong"
    assert result.overall_verdict == "适合投资 (宏观环境支持)"
    assert pulse_calls == [
        {
            "as_of_date": date(2026, 5, 9),
            "require_reliable": False,
            "refresh_if_stale": False,
        }
    ]


def test_step2_direction_exposes_snapshot_validity(monkeypatch):
    monkeypatch.setattr(
        "core.application.decision_context.timezone.now",
        lambda: datetime(2026, 5, 9, 10, 0, tzinfo=timezone.utc),
    )

    use_case = DecisionContextUseCase()
    use_case.action_usecase = SimpleNamespace(
        execute=lambda *args, **kwargs: SimpleNamespace(
            reasoning="测试建议",
            regime_contribution="Recovery",
            pulse_contribution="Pulse strong",
            position_limit_pct=0.1,
            recommended_sectors=["科技"],
            asset_weights={"equity": 0.6, "bond": 0.3, "cash": 0.1},
            risk_budget_pct=0.7,
            context_observed_at=date(2026, 5, 9),
            context_source="action_log_cached",
        )
    )

    result = use_case.get_step2_direction(date(2026, 5, 9))

    assert result.recommendation_freshness["status_label"] == "有效"
    assert result.recommendation_freshness["source_label"] == "夜间快照"
    assert result.recommendation_freshness["observed_at_display"] == "2026-05-09"
    assert result.recommendation_freshness["expires_at_display"] == "2026-05-10 23:59"


def test_step2_direction_marks_live_fallback(monkeypatch):
    monkeypatch.setattr(
        "core.application.decision_context.timezone.now",
        lambda: datetime(2026, 5, 9, 10, 0, tzinfo=timezone.utc),
    )

    use_case = DecisionContextUseCase()
    use_case.action_usecase = SimpleNamespace(
        execute=lambda *args, **kwargs: SimpleNamespace(
            reasoning="实时回退建议",
            regime_contribution="Recovery",
            pulse_contribution="Pulse moderate",
            position_limit_pct=0.1,
            recommended_sectors=[],
            asset_weights={"equity": 0.5, "bond": 0.3, "cash": 0.2},
            risk_budget_pct=0.5,
            context_observed_at=date(2026, 5, 9),
            context_source="live_action_fallback",
        )
    )

    result = use_case.get_step2_direction(date(2026, 5, 9))

    assert result.recommendation_freshness["status_label"] == "实时回退"
    assert result.recommendation_freshness["source_label"] == "页面实时计算"
