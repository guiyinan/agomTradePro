from datetime import UTC, date, datetime
from types import SimpleNamespace

from core.application.decision_context import DecisionContextUseCase


def test_step1_context_uses_canonical_regime_and_non_refresh_pulse(monkeypatch):
    cached_regime = SimpleNamespace(
        dominant_regime="Recovery",
        confidence=0.91,
        observed_at=date(2026, 5, 9),
    )
    pulse_calls = []

    monkeypatch.setattr(
        "core.application.decision_context.resolve_current_regime",
        lambda **_: SimpleNamespace(
            **cached_regime.__dict__,
            is_stale=False,
            must_not_use_for_decision=False,
            blocked_reason="",
        ),
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
    assert result.must_not_use_for_decision is False
    assert pulse_calls == [
        {
            "as_of_date": date(2026, 5, 9),
            "require_reliable": False,
            "refresh_if_stale": False,
        }
    ]


def test_step1_context_blocks_stale_regime_even_with_strong_pulse(monkeypatch):
    monkeypatch.setattr(
        "core.application.decision_context.resolve_current_regime",
        lambda **_: SimpleNamespace(
            dominant_regime="Unknown",
            observed_at=date(2026, 4, 1),
            is_stale=True,
            must_not_use_for_decision=True,
            blocked_reason="regime_macro_observation_stale",
        ),
    )
    use_case = DecisionContextUseCase()
    use_case.pulse_usecase = SimpleNamespace(
        execute=lambda **_: SimpleNamespace(
            composite_score=0.8,
            regime_strength="strong",
            is_reliable=True,
            observed_at=date(2026, 7, 30),
        )
    )

    result = use_case.get_step1_context(date(2026, 7, 30))

    assert result.must_not_use_for_decision is True
    assert result.overall_verdict == "当前决策数据不可靠，禁止生成投资结论"


def test_step2_direction_exposes_snapshot_validity(monkeypatch):
    monkeypatch.setattr(
        "core.application.decision_context.timezone.now",
        lambda: datetime(2026, 5, 9, 10, 0, tzinfo=UTC),
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
        lambda: datetime(2026, 5, 9, 10, 0, tzinfo=UTC),
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


def test_step2_direction_removes_weights_from_blocked_cached_action(monkeypatch):
    use_case = DecisionContextUseCase()
    use_case.action_usecase = SimpleNamespace(
        execute=lambda *args, **kwargs: SimpleNamespace(
            reasoning="旧建议",
            regime_contribution="Recovery",
            pulse_contribution="Pulse strong",
            position_limit_pct=0.1,
            recommended_sectors=["科技"],
            asset_weights={"equity": 0.7, "cash": 0.3},
            risk_budget_pct=0.8,
            context_observed_at=date(2026, 4, 1),
            context_source="action_log_cached",
            must_not_use_for_decision=True,
            blocked_reason="cached_action_stale",
        )
    )

    result = use_case.get_step2_direction(date(2026, 7, 30))

    assert result.must_not_use_for_decision is True
    assert result.asset_weights == {}
    assert result.risk_budget_pct == 0.0
    assert result.blocked_reason == "cached_action_stale"
