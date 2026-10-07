"""Candidate-side contracts for the aggregate S6 environment preflight."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.management.base import OutputWrapper

from apps.data_center.management.commands import preflight_s6_stage_environment as command


class _BrokenConnection:
    def cursor(self) -> object:
        raise RuntimeError("database details must not enter evidence")


class _BrokenPeriodicManager:
    def filter(self, **_kwargs: object) -> object:
        raise RuntimeError("scheduler details must not enter evidence")


class _BrokenPeriodicTask:
    _default_manager = _BrokenPeriodicManager()


def test_candidate_preflight_aggregates_safe_codes_after_independent_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = tmp_path / "provider-settings.json"
    settings_path.write_text("{}\n", encoding="utf-8", newline="\n")
    identities_path = tmp_path / "provider-identities.json"
    identities_path.write_text("[]\n", encoding="utf-8", newline="\n")

    class _BlockedUseCase:
        def execute(self, **_kwargs: object) -> object:
            return SimpleNamespace(outcome="blocked")

    monkeypatch.setattr(
        command,
        "build_full_market_publication_preflight_use_case",
        lambda **_kwargs: _BlockedUseCase(),
    )
    monkeypatch.setattr(command, "load_rehearsal_identities", lambda _path: ())
    monkeypatch.setattr(command, "verify_configured_rehearsal_identities", lambda value: value)
    monkeypatch.setattr(command, "_select_provider", lambda _value: (object(), object()))
    monkeypatch.setattr(
        command,
        "_require_akshare_financial_egress_routes",
        lambda _provider: (_ for _ in ()).throw(RuntimeError("secret provider response")),
    )
    monkeypatch.setattr(
        command,
        "resolve_financial_response_artifact_config",
        lambda: (_ for _ in ()).throw(RuntimeError("secret reference")),
    )
    monkeypatch.setattr(
        command,
        "load_akshare_financial_slice_sync_budget",
        lambda: (_ for _ in ()).throw(RuntimeError("private policy")),
    )
    monkeypatch.setattr(command, "connection", _BrokenConnection())
    monkeypatch.setattr(command, "PeriodicTask", _BrokenPeriodicTask)

    stream = StringIO()
    instance = command.Command()
    instance.stdout = OutputWrapper(stream)
    instance.handle(
        provider_settings_json=settings_path,
        provider_identities=identities_path,
    )

    payload = json.loads(stream.getvalue())
    assert payload["schema"] == "release.s6-stage-environment-preflight.v1"
    assert {item["code"] for item in payload["issues"]} == {
        "REHEARSAL_STAGE_MODEL_MARKET_ROUTE_INVALID",
        "REHEARSAL_FINANCIAL_SLICE_EGRESS_ROUTE_REQUIRED",
        "REHEARSAL_STAGE_FINANCIAL_SECRET_CONTRACT_INVALID",
        "REHEARSAL_STAGE_DATABASE_CLOCK_INVALID",
        "REHEARSAL_STAGE_FINANCIAL_BUDGET_INVALID",
        "REHEARSAL_STAGE_PERIODIC_ENTRYPOINT_INVALID",
    }
    assert "secret provider response" not in stream.getvalue()
    assert "secret reference" not in stream.getvalue()
    assert "private policy" not in stream.getvalue()


def test_candidate_preflight_reports_missing_provider_identity_and_keeps_checking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = tmp_path / "provider-settings.json"
    settings_path.write_text("{}\n", encoding="utf-8", newline="\n")
    identities_path = tmp_path / "provider-identities.json"
    identities_path.write_text("[]\n", encoding="utf-8", newline="\n")

    monkeypatch.setattr(
        command,
        "verify_configured_rehearsal_identities",
        lambda _value: (_ for _ in ()).throw(ValueError("private identity")),
    )
    monkeypatch.setattr(command, "load_rehearsal_identities", lambda _path: ())
    monkeypatch.setattr(command.Command, "_check_model_market_routes", lambda *_args: None)
    monkeypatch.setattr(command.Command, "_check_clock", lambda *_args: None)
    monkeypatch.setattr(command.Command, "_check_external_state", lambda *_args: None)
    monkeypatch.setattr(command, "resolve_financial_response_artifact_config", lambda: object())
    monkeypatch.setattr(
        command,
        "load_akshare_financial_slice_sync_budget",
        lambda: SimpleNamespace(
            max_slices=1,
            provider_requests_per_slice=2,
            max_provider_requests=2,
        ),
    )

    stream = StringIO()
    instance = command.Command()
    instance.stdout = OutputWrapper(stream)
    instance.handle(
        provider_settings_json=settings_path,
        provider_identities=identities_path,
    )

    payload = json.loads(stream.getvalue())
    assert payload["issues"] == [
        {
            "category": "identity_and_secrets",
            "code": "REHEARSAL_STAGE_PROVIDER_IDENTITY_INVALID",
            "stages": ["akshare_financial_slice"],
        }
    ]
