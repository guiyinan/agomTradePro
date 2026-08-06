from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.backtest.management.commands import run_backtest as command_module


def _response(status: str = "completed") -> SimpleNamespace:
    return SimpleNamespace(
        backtest_id=17,
        status=status,
        result={"total_return": 0.1} if status == "completed" else None,
        errors=[] if status == "completed" else ["missing canonical data"],
        warnings=[],
        audit_status="success" if status == "completed" else "skipped",
        audit_report_id=9 if status == "completed" else None,
    )


def test_run_backtest_command_routes_to_application_without_synthetic_inputs(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _run(payload: dict[str, object], *, user_id: int | None):
        captured["payload"] = payload
        captured["user_id"] = user_id
        return _response()

    monkeypatch.setattr(command_module, "run_backtest_payload", _run)
    output = StringIO()

    call_command(
        "run_backtest",
        start="2024-01-01",
        end="2024-12-31",
        name="Canonical CLI",
        capital=200000.0,
        frequency="quarterly",
        as_json=True,
        stdout=output,
    )

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["name"] == "Canonical CLI"
    assert payload["trust_status"] == "exploratory"
    assert "get_regime_func" not in payload
    assert "get_asset_price_func" not in payload
    assert captured["user_id"] is None
    assert json.loads(output.getvalue())["backtest_id"] == 17


def test_run_backtest_command_fails_closed_for_invalid_dates() -> None:
    with pytest.raises(CommandError, match="backtest_date_range_invalid"):
        call_command(
            "run_backtest",
            start="2024-12-31",
            end="2024-01-01",
        )


def test_run_backtest_command_requires_pit_evidence() -> None:
    with pytest.raises(CommandError, match="backtest_pit_evidence_required"):
        call_command(
            "run_backtest",
            start="2024-01-01",
            end="2024-12-31",
            use_pit_data=True,
        )


def test_run_backtest_command_returns_nonzero_for_application_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        command_module, "run_backtest_payload", lambda *_args, **_kwargs: _response("failed")
    )

    with pytest.raises(CommandError, match="backtest_execution_failed"):
        call_command(
            "run_backtest",
            start="2024-01-01",
            end="2024-12-31",
        )
