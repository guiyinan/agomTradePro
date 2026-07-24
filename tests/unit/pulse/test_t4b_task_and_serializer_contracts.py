"""Pulse task and serializer contracts for success, no-op, and invalid payloads."""

from datetime import date
from types import SimpleNamespace

import pytest

from apps.pulse.application import tasks
from apps.pulse.interface.serializers import PulseSnapshotSerializer


def test_weekly_pulse_task_reports_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.pulse.application.use_cases.CalculatePulseUseCase",
        lambda: SimpleNamespace(execute=lambda: SimpleNamespace(composite_score=0.375)),
    )

    assert tasks.calculate_weekly_pulse.run() == {
        "success": True,
        "composite_score": 0.375,
    }


def test_weekly_pulse_task_reports_business_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "apps.pulse.application.use_cases.CalculatePulseUseCase",
        lambda: SimpleNamespace(execute=lambda: None),
    )

    assert tasks.calculate_weekly_pulse.run() == {"success": False}


def _snapshot_payload() -> dict[str, object]:
    return {
        "observed_at": date(2026, 7, 25),
        "regime_context": {"name": "recovery"},
        "composite_score": 0.4,
        "regime_strength": "moderate",
        "transition_warning": False,
        "transition_direction": "",
        "transition_reasons": [],
        "data_source": "calculated",
        "is_reliable": True,
        "is_stale": False,
        "stale_indicator_codes": [],
        "must_not_use_for_decision": False,
        "blocked_reason": "",
        "market_data_as_of": date(2026, 7, 24),
        "indicator_observed_at": {"PMI": date(2026, 7, 1), "CPI": None},
        "contract": {"version": "v1"},
        "dimensions": {
            "growth": {
                "score": 0.5,
                "signal": "bullish",
                "indicator_count": 2,
                "description": "growth improving",
            }
        },
    }


def test_pulse_snapshot_serializer_accepts_complete_contract() -> None:
    serializer = PulseSnapshotSerializer(data=_snapshot_payload())

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["dimensions"]["growth"]["indicator_count"] == 2


def test_pulse_snapshot_serializer_rejects_missing_dimension_fields() -> None:
    payload = _snapshot_payload()
    payload["dimensions"] = {"growth": {"score": 0.5}}
    serializer = PulseSnapshotSerializer(data=payload)

    assert serializer.is_valid() is False
    assert "signal" in serializer.errors["dimensions"]["growth"]
