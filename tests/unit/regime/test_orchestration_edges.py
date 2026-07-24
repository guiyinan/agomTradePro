"""Regime high-frequency orchestration success and fallback contracts."""

from __future__ import annotations

from types import SimpleNamespace

from apps.regime.application import orchestration, use_cases


def test_generate_daily_regime_signal_success_and_business_failure(monkeypatch) -> None:
    """Daily signal task serializes success and returns business errors unchanged."""
    monkeypatch.setattr(orchestration, "build_macro_data_provider", lambda: object())
    monkeypatch.setattr(
        orchestration, "build_macro_repository_adapter", lambda provider=None: object()
    )

    response = SimpleNamespace(
        success=True,
        signal_direction="Recovery",
        signal_strength=0.7,
        confidence=0.8,
        contributing_indicators=["PMI"],
        warning_signals=["credit_spread"],
        error=None,
    )
    monkeypatch.setattr(
        use_cases,
        "HighFrequencySignalUseCase",
        lambda repo: SimpleNamespace(execute=lambda request: response),
    )
    result = orchestration.generate_daily_regime_signal("2026-07-24")
    assert result["status"] == "success"
    assert result["signal_direction"] == "Recovery"

    response.success = False
    response.error = "insufficient observations"
    failed = orchestration.generate_daily_regime_signal("2026-07-24")
    assert failed == {"status": "error", "error": "insufficient observations"}


def test_recalculation_uses_monthly_fallback_and_conflict_resolution(monkeypatch) -> None:
    """Recalculation explicitly identifies monthly-only and blended outcomes."""
    from apps.regime.application import current_regime

    monkeypatch.setattr(orchestration, "build_macro_data_provider", lambda: object())
    monkeypatch.setattr(
        orchestration, "build_macro_repository_adapter", lambda provider=None: object()
    )
    monthly = SimpleNamespace(dominant_regime="Deflation", confidence=0.6)
    monkeypatch.setattr(current_regime, "resolve_current_regime", lambda **kwargs: monthly)
    daily = SimpleNamespace(
        success=False,
        signal_direction=None,
        confidence=0.0,
        contributing_indicators=[],
        warning_signals=[],
        error="no data",
    )
    monkeypatch.setattr(
        use_cases,
        "HighFrequencySignalUseCase",
        lambda repo: SimpleNamespace(execute=lambda request: daily),
    )
    fallback = orchestration.recalculate_regime_with_daily_signal("2026-07-24")
    assert fallback["source"] == "MONTHLY_ONLY"
    assert fallback["daily_signal"] is None

    daily.success = True
    daily.signal_direction = "Recovery"
    daily.confidence = 0.8
    daily.contributing_indicators = ["PMI"]
    monkeypatch.setattr(
        use_cases,
        "ResolveSignalConflictUseCase",
        lambda: SimpleNamespace(
            execute=lambda request: SimpleNamespace(
                final_signal="Recovery",
                final_confidence=0.72,
                source="HYBRID",
                resolution_reason="daily lead confirmed",
            )
        ),
    )
    blended = orchestration.recalculate_regime_with_daily_signal("2026-07-24")
    assert blended["source"] == "HYBRID"
    assert blended["final_regime"] == "Recovery"


def test_calculation_skip_fallback_and_notification_skip(monkeypatch) -> None:
    """Calculation preserves upstream failure and exposes resolver fallback evidence."""
    skipped = orchestration.calculate_regime_after_sync(
        {"success": False, "error": "macro failed"},
        as_of_date="2026-07-24",
    )
    assert skipped["reason"] == "sync_failed"
    assert orchestration.notify_regime_change_after_calculation(None)["status"] == "skipped"

    response = SimpleNamespace(success=False, result=None, warnings=["v2 unavailable"])
    monkeypatch.setattr(
        use_cases,
        "CalculateRegimeV2UseCase",
        lambda repo: SimpleNamespace(execute=lambda request: response),
    )
    monkeypatch.setattr(orchestration, "build_macro_repository_adapter", lambda: object())
    from apps.regime.application import current_regime

    monkeypatch.setattr(
        current_regime,
        "resolve_current_regime",
        lambda **kwargs: SimpleNamespace(
            observed_at=__import__("datetime").date(2026, 7, 24),
            dominant_regime="Deflation",
            confidence=0.55,
            warnings=["fallback"],
            data_source="cached",
            is_fallback=True,
        ),
    )
    fallback = orchestration.calculate_regime_after_sync(as_of_date="2026-07-24")
    assert fallback["is_fallback"] is True
    assert fallback["data_source"] == "cached"
