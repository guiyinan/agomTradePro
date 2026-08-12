"""Regime high-frequency orchestration success and fallback contracts."""

from __future__ import annotations

from types import SimpleNamespace

from apps.regime.application import orchestration, use_cases


def _assert_task_contract(
    payload: dict[str, object],
    *,
    outcome: str,
    requested: int = 1,
    succeeded: int,
    failed: int,
    stored: int = 0,
) -> None:
    assert {
        key: payload[key]
        for key in ("outcome", "success", "requested", "succeeded", "failed", "stored")
    } == {
        "outcome": outcome,
        "success": outcome in {"success", "noop"},
        "requested": requested,
        "succeeded": succeeded,
        "failed": failed,
        "stored": stored,
    }


def test_generate_daily_regime_signal_success_and_business_failure(monkeypatch) -> None:
    """Daily signal task serializes success and returns business errors unchanged."""
    monkeypatch.setattr(orchestration, "build_macro_data_provider", lambda: object())
    monkeypatch.setattr(
        orchestration, "build_macro_repository_adapter", lambda provider=None: object()
    )

    response = SimpleNamespace(
        success=True,
        signal_direction="BULLISH",
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
    assert result["signal_direction"] == "BULLISH"
    _assert_task_contract(result, outcome="success", succeeded=1, failed=0)

    response.success = False
    response.error = "insufficient observations"
    failed = orchestration.generate_daily_regime_signal("2026-07-24")
    assert failed["status"] == "error"
    assert failed["error"] == "insufficient observations"
    _assert_task_contract(failed, outcome="failed", succeeded=0, failed=1)


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
    _assert_task_contract(fallback, outcome="success", succeeded=1, failed=0)

    daily.success = True
    daily.signal_direction = "BULLISH"
    daily.signal_strength = 0.7
    daily.confidence = 0.8
    daily.contributing_indicators = ["PMI"]
    blended = orchestration.recalculate_regime_with_daily_signal("2026-07-24")
    assert blended["source"] == "MONTHLY_WITH_DAILY_DIRECTION_CONTEXT"
    assert blended["final_regime"] == "Deflation"
    assert blended["daily_signal"] == "BULLISH"
    _assert_task_contract(blended, outcome="success", succeeded=1, failed=0)


def test_calculation_skip_fallback_and_notification_skip(monkeypatch) -> None:
    """Calculation preserves upstream failure and exposes resolver fallback evidence."""
    skipped = orchestration.calculate_regime_after_sync(
        {"success": False, "error": "macro failed"},
        as_of_date="2026-07-24",
    )
    assert skipped["reason"] == "sync_failed"
    _assert_task_contract(skipped, outcome="blocked", succeeded=0, failed=0)
    notification_skip = orchestration.notify_regime_change_after_calculation(None)
    assert notification_skip["status"] == "skipped"
    _assert_task_contract(notification_skip, outcome="blocked", succeeded=0, failed=0)

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
    _assert_task_contract(fallback, outcome="success", succeeded=1, failed=0)

    monkeypatch.setattr(
        current_regime,
        "resolve_current_regime",
        lambda **kwargs: SimpleNamespace(
            observed_at=None,
            dominant_regime="Unknown",
            confidence=0.0,
            warnings=["missing"],
            data_source="none",
            is_fallback=True,
            must_not_use_for_decision=True,
            blocked_reason="regime_data_unavailable",
        ),
    )
    blocked = orchestration.calculate_regime_after_sync(as_of_date="2026-07-24")
    assert blocked["status"] == "blocked"
    assert blocked["observed_at"] is None
    assert blocked["must_not_use_for_decision"] is True
    assert blocked["blocked_reason"] == "regime_data_unavailable"
    _assert_task_contract(blocked, outcome="blocked", succeeded=0, failed=0)


def test_invalid_daily_signal_payload_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(orchestration, "build_macro_data_provider", lambda: object())
    monkeypatch.setattr(
        orchestration, "build_macro_repository_adapter", lambda provider=None: object()
    )
    response = SimpleNamespace(
        success=True,
        signal_direction=None,
        signal_strength=float("nan"),
        confidence=1.2,
        contributing_indicators=[],
        warning_signals=[],
        error=None,
    )
    monkeypatch.setattr(
        use_cases,
        "HighFrequencySignalUseCase",
        lambda repo: SimpleNamespace(execute=lambda request: response),
    )

    result = orchestration.generate_daily_regime_signal("2026-07-24")

    assert result["status"] == "error"
    assert result["error"] == "daily signal payload is incomplete or outside its valid range"


def test_sync_result_requires_explicit_usable_status() -> None:
    assert orchestration._sync_result_allows_calculation({"status": "success"}) is True
    assert orchestration._sync_result_allows_calculation({"status": "partial"}) is True
    assert orchestration._sync_result_allows_calculation({"status": "error"}) is False
    assert orchestration._sync_result_allows_calculation({"unexpected": True}) is False


def test_notification_truthfully_reports_no_change_and_invalid_payload(monkeypatch) -> None:
    previous = SimpleNamespace(dominant_regime="Recovery", confidence=0.8)
    monkeypatch.setattr(
        orchestration,
        "get_regime_repository",
        lambda: SimpleNamespace(get_latest_snapshot=lambda **kwargs: previous),
    )

    unchanged = orchestration.notify_regime_change_after_calculation(
        {
            "status": "success",
            "as_of_date": "2026-07-24",
            "dominant_regime": "Recovery",
            "confidence": 0.8,
        }
    )
    invalid = orchestration.notify_regime_change_after_calculation(
        {
            "status": "success",
            "as_of_date": "2026-07-24",
            "dominant_regime": "Recovery",
            "confidence": float("nan"),
        }
    )

    assert unchanged["status"] == "success"
    assert unchanged["notified"] is False
    assert unchanged["notification_attempted"] is False
    assert unchanged["regime_changed"] is False
    _assert_task_contract(unchanged, outcome="noop", succeeded=1, failed=0)
    assert invalid["status"] == "error"
    assert invalid["reason"] == "invalid_regime_result"
    _assert_task_contract(invalid, outcome="failed", succeeded=0, failed=1)


def test_sync_macro_workflow_dispatch_has_normalized_task_contract(monkeypatch) -> None:
    class Gateway:
        def build_sync_signature(self, **kwargs):
            return ("sync", kwargs)

    class Workflow:
        def apply_async(self):
            return SimpleNamespace(id="workflow-task-1")

    monkeypatch.setattr(orchestration, "build_macro_sync_task_gateway", Gateway)
    monkeypatch.setattr(orchestration, "chain", lambda *steps: Workflow())

    result = orchestration.sync_macro_then_refresh_regime(
        source="akshare",
        indicator="PMI",
        days_back=30,
        as_of_date="2026-07-24",
    )

    assert result["status"] == "started"
    assert result["task_id"] == "workflow-task-1"
    _assert_task_contract(result, outcome="success", succeeded=1, failed=0)
