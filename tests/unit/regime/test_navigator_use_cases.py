from datetime import date
from types import SimpleNamespace

from apps.regime.application.navigator_use_cases import (
    GetActionRecommendationUseCase,
    GetRegimeNavigatorHistoryUseCase,
)


class _FakeNavigatorRepository:
    def __init__(self, action_log):
        self._action_log = action_log

    def get_latest_action_recommendation(self, before_date=None):
        return self._action_log

    def save_action_recommendation(self, observed_at, data):
        raise AssertionError("read-only action recommendation must not be persisted")


def test_get_action_recommendation_prefers_cached_log(monkeypatch):
    cached_log = SimpleNamespace(
        observed_at=date(2026, 5, 8),
        regime_name="Recovery",
        pulse_strength="strong",
        asset_weights={"equity": 0.62, "bond": 0.28, "cash": 0.10},
        risk_budget_pct=0.74,
        recommended_sectors=["科技", "消费"],
        benefiting_styles=["成长"],
        must_not_use_for_decision=False,
        blocked_reason="",
    )

    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.get_navigator_repository",
        lambda: _FakeNavigatorRepository(cached_log),
    )
    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.resolve_current_regime",
        lambda **_: SimpleNamespace(
            confidence=0.83,
            must_not_use_for_decision=False,
            blocked_reason="",
        ),
    )
    monkeypatch.setattr(
        "apps.pulse.application.use_cases.GetLatestPulseUseCase",
        lambda: SimpleNamespace(
            execute=lambda **kwargs: SimpleNamespace(
                observed_at=date(2026, 5, 8),
                is_reliable=True,
                indicator_readings=[],
            )
        ),
    )
    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.BuildRegimeNavigatorUseCase.execute",
        lambda self, target_date: (_ for _ in ()).throw(
            AssertionError("live navigator calculation should not run when cached log exists")
        ),
    )

    result = GetActionRecommendationUseCase().execute(
        date(2026, 5, 9),
        refresh_pulse_if_stale=False,
        prefer_cached=True,
    )

    assert result is not None
    assert result.asset_weights == {"equity": 0.62, "bond": 0.28, "cash": 0.10}
    assert result.risk_budget_pct == 0.74
    assert result.position_limit_pct == 0.10
    assert result.recommended_sectors == ["科技", "消费"]
    assert result.confidence == 0.83
    assert "已复用" in result.reasoning


def test_cached_action_recommendation_blocks_stale_log(monkeypatch):
    cached_log = SimpleNamespace(
        observed_at=date(2026, 5, 8),
        regime_name="Recovery",
        pulse_strength="strong",
        asset_weights={"equity": 0.6, "cash": 0.4},
        risk_budget_pct=0.7,
        recommended_sectors=[],
        benefiting_styles=[],
        must_not_use_for_decision=False,
        blocked_reason="",
    )
    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.get_navigator_repository",
        lambda: _FakeNavigatorRepository(cached_log),
    )
    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.resolve_current_regime",
        lambda **_: SimpleNamespace(
            confidence=0.8,
            must_not_use_for_decision=False,
            blocked_reason="",
        ),
    )
    monkeypatch.setattr(
        "apps.pulse.application.use_cases.GetLatestPulseUseCase",
        lambda: SimpleNamespace(execute=lambda **_: None),
    )

    result = GetActionRecommendationUseCase().execute(
        date(2026, 5, 12),
        prefer_cached=True,
    )

    assert result is not None
    assert result.must_not_use_for_decision is True
    assert result.blocked_reason == "cached_action_stale"


def test_get_action_recommendation_can_compute_without_refresh_or_persistence(monkeypatch):
    navigator = SimpleNamespace(
        regime_name="Recovery",
        confidence=0.72,
        asset_guidance=SimpleNamespace(
            weight_ranges=[
                SimpleNamespace(category="equity", lower=0.50, upper=0.70),
                SimpleNamespace(category="bond", lower=0.15, upper=0.30),
                SimpleNamespace(category="commodity", lower=0.05, upper=0.15),
                SimpleNamespace(category="cash", lower=0.05, upper=0.20),
            ],
            risk_budget_pct=0.80,
            recommended_sectors=["科技", "消费"],
            benefiting_styles=["成长"],
            reasoning="Recovery allocation guidance",
        ),
    )
    pulse_calls = []

    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.BuildRegimeNavigatorUseCase.execute",
        lambda self, target_date: navigator,
    )
    monkeypatch.setattr(
        "apps.pulse.application.use_cases.GetLatestPulseUseCase",
        lambda: SimpleNamespace(
            execute=lambda **kwargs: pulse_calls.append(dict(kwargs))
            or SimpleNamespace(composite_score=0.2, regime_strength="moderate")
        ),
    )
    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.get_navigator_repository",
        lambda: _FakeNavigatorRepository(None),
    )

    result = GetActionRecommendationUseCase().execute(
        date(2026, 7, 13),
        refresh_pulse_if_stale=False,
        persist_result=False,
    )

    assert result is not None
    assert result.must_not_use_for_decision is False
    assert result.asset_weights
    assert pulse_calls == [
        {
            "as_of_date": date(2026, 7, 13),
            "require_reliable": True,
            "refresh_if_stale": False,
        }
    ]


def test_navigator_history_redacts_repository_errors(monkeypatch):
    class _FailingHistoryRepository:
        def get_regimes_in_range(self, start_date, end_date):
            raise RuntimeError("postgresql://secret@internal/regime")

    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.get_navigator_repository",
        lambda: _FailingHistoryRepository(),
    )

    result = GetRegimeNavigatorHistoryUseCase().execute(
        date(2026, 7, 1),
        date(2026, 7, 31),
    )

    assert result["error"] == "history_query_failed"
    assert "secret" not in str(result)
