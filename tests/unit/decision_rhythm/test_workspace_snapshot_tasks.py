from datetime import date
from types import SimpleNamespace

from apps.decision_rhythm.application.tasks import refresh_decision_workspace_snapshots


def test_refresh_decision_workspace_snapshots_success(monkeypatch):
    target_date = date(2026, 5, 9)

    class _FakeSyncUseCase:
        def execute(self, request):
            assert request.start_date == date(2026, 3, 10)
            assert request.end_date == target_date
            return SimpleNamespace(synced_count=12, skipped_count=3, errors=[])

    monkeypatch.setattr(
        "apps.decision_rhythm.application.tasks.build_sync_macro_data_use_case",
        lambda source: _FakeSyncUseCase(),
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.tasks.calculate_regime_after_sync",
        SimpleNamespace(
            run=lambda **kwargs: {
                "status": "success",
                "observed_at": kwargs["as_of_date"],
                "dominant_regime": "Recovery",
                "confidence": 0.88,
            }
        ),
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.tasks.refresh_pulse_snapshot",
        lambda **kwargs: SimpleNamespace(
            observed_at=target_date,
            composite_score=0.63,
            regime_strength="strong",
            is_reliable=True,
        ),
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.tasks.GetActionRecommendationUseCase",
        lambda: SimpleNamespace(
            execute=lambda *args, **kwargs: SimpleNamespace(
                context_observed_at=target_date,
                context_source="live_action_fallback",
                risk_budget_pct=0.72,
                recommended_sectors=["科技", "消费"],
                must_not_use_for_decision=False,
            )
        ),
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.tasks.RotationSignalScheduler",
        lambda: SimpleNamespace(
            generate_all_signals=lambda signal_date: {
                "signal_date": signal_date.isoformat(),
                "total_configs": 1,
                "successful": 1,
                "failed": 0,
                "signals": [],
            }
        ),
    )

    result = refresh_decision_workspace_snapshots.run(as_of_date=target_date.isoformat())

    assert result["status"] == "success"
    assert result["as_of_date"] == "2026-05-09"
    assert result["components"]["macro_sync"]["synced_count"] == 12
    assert result["components"]["regime_snapshot"]["dominant_regime"] == "Recovery"
    assert result["components"]["pulse_snapshot"]["is_reliable"] is True
    assert result["components"]["action_recommendation"]["recommended_sectors"] == ["科技", "消费"]
    assert result["components"]["rotation_signals"]["status"] == "success"


def test_refresh_decision_workspace_snapshots_continues_on_partial_failures(monkeypatch):
    target_date = date(2026, 5, 9)

    class _BrokenSyncUseCase:
        def execute(self, request):
            raise RuntimeError("macro unavailable")

    monkeypatch.setattr(
        "apps.decision_rhythm.application.tasks.build_sync_macro_data_use_case",
        lambda source: _BrokenSyncUseCase(),
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.tasks.calculate_regime_after_sync",
        SimpleNamespace(
            run=lambda **kwargs: {
                "status": "success",
                "observed_at": kwargs["as_of_date"],
                "dominant_regime": "Slowdown",
                "confidence": 0.67,
            }
        ),
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.tasks.refresh_pulse_snapshot",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.tasks.GetActionRecommendationUseCase",
        lambda: SimpleNamespace(
            execute=lambda *args, **kwargs: SimpleNamespace(
                context_observed_at=target_date,
                context_source="action_log_cached",
                blocked_reason="Pulse unreliable",
                must_not_use_for_decision=True,
            )
        ),
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.tasks.RotationSignalScheduler",
        lambda: SimpleNamespace(
            generate_all_signals=lambda signal_date: {
                "signal_date": signal_date.isoformat(),
                "total_configs": 2,
                "successful": 1,
                "failed": 1,
                "signals": [],
            }
        ),
    )

    result = refresh_decision_workspace_snapshots.run(as_of_date=target_date.isoformat())

    assert result["status"] == "partial_success"
    assert result["components"]["macro_sync"]["status"] == "error"
    assert result["components"]["regime_snapshot"]["status"] == "success"
    assert result["components"]["pulse_snapshot"]["status"] == "error"
    assert result["components"]["action_recommendation"]["status"] == "blocked"
    assert result["components"]["rotation_signals"]["status"] == "partial_success"
