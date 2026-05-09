from datetime import date
from types import SimpleNamespace

from apps.regime.application.navigator_use_cases import GetActionRecommendationUseCase


class _FakeNavigatorRepository:
    def __init__(self, action_log):
        self._action_log = action_log

    def get_latest_action_recommendation(self, before_date=None):
        return self._action_log


class _FakeRegimeRepository:
    def __init__(self, confidence=0.83):
        self._snapshot = SimpleNamespace(confidence=confidence)

    def get_latest_snapshot(self, before_date=None):
        return self._snapshot


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
        "apps.regime.application.navigator_use_cases.get_regime_repository",
        lambda: _FakeRegimeRepository(),
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
