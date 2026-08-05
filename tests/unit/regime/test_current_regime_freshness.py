"""Freshness boundaries for the canonical current-Regime resolver."""

from datetime import date
from types import SimpleNamespace

from apps.regime.application import current_regime, query_services


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


def test_regime_cache_warmup_does_not_reheat_blocked_snapshot(monkeypatch):
    """Current cache warmup must skip stale/blocked resolver results."""

    monkeypatch.setattr(
        current_regime,
        "resolve_current_regime",
        lambda: SimpleNamespace(
            dominant_regime="Unknown",
            confidence=0.8,
            observed_at=date(2026, 5, 31),
            must_not_use_for_decision=True,
            blocked_reason="regime_snapshot_stale",
        ),
    )

    assert query_services.get_latest_regime_cache_payload() is None


def test_regime_cache_warmup_preserves_resolver_observation(monkeypatch):
    """Fresh cache entries retain the resolver observation date and contract."""

    monkeypatch.setattr(
        current_regime,
        "resolve_current_regime",
        lambda: SimpleNamespace(
            dominant_regime="Recovery",
            confidence=0.8,
            observed_at=date(2026, 7, 31),
            must_not_use_for_decision=False,
            blocked_reason="",
        ),
    )

    assert query_services.get_latest_regime_cache_payload() == {
        "regime": "Recovery",
        "observed_at": "2026-07-31",
        "confidence": 0.8,
        "freshness_status": "fresh",
        "must_not_use_for_decision": False,
        "blocked_reason": "",
    }
