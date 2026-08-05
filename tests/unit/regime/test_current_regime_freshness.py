"""Freshness boundaries for the canonical current-Regime resolver."""

from datetime import date
from types import SimpleNamespace

from apps.regime.application import current_regime


def test_current_regime_preserves_macro_observation_and_blocks_stale_result(monkeypatch):
    """The calculation date cannot replace the oldest required macro observation date."""

    response = SimpleNamespace(
        success=True,
        result=SimpleNamespace(
            regime=SimpleNamespace(value="Recovery"),
            confidence=0.82,
            trend_indicators=[],
            distribution={"Recovery": 0.82},
            growth_level=50.4,
            inflation_level=0.2,
        ),
        warnings=[],
        error=None,
        raw_data={
            "growth": [{"date": "2026-07-01", "value": 50.4, "code": "PMI"}],
            "inflation": [{"date": "2026-05-31", "value": 0.2, "code": "CPI"}],
        },
    )

    captured: dict[str, object] = {}

    class _UseCase:
        def __init__(self, repository):
            self.repository = repository

        def execute(self, request):
            captured["request"] = request
            return response

    monkeypatch.setattr(current_regime, "get_macro_data_provider", lambda: object())
    monkeypatch.setattr(current_regime, "build_macro_repository_adapter", lambda _: object())
    monkeypatch.setattr(current_regime, "CalculateRegimeV2UseCase", _UseCase)

    result = current_regime.resolve_current_regime(as_of_date=date(2026, 7, 30))

    assert result.observed_at == date(2026, 5, 31)
    assert result.diagnostic_regime == "Recovery"
    assert result.dominant_regime == "Unknown"
    assert result.is_stale is True
    assert result.must_not_use_for_decision is True
    assert result.blocked_reason == "regime_macro_observation_stale"
    assert captured["request"].published_only is True
