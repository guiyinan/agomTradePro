"""T5 contracts for core deployment and diagnostic management commands."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.core.management.base import CommandError, OutputWrapper

from core.management.commands import (
    healthcheck,
    init_production,
    test_data_connections,
    warmup_cache,
)


def _command(command_type: type[object]) -> tuple[object, StringIO, StringIO]:
    command = command_type()
    stdout = StringIO()
    stderr = StringIO()
    command.stdout = OutputWrapper(stdout)
    command.stderr = OutputWrapper(stderr)
    return command, stdout, stderr


def test_data_connection_runner_counts_declared_and_observed_failures(
    tmp_path: Path,
) -> None:
    output = tmp_path / "diagnostics.json"
    tester = test_data_connections.DataConnectionTester(
        OutputWrapper(StringIO()),
        results_path=output,
    )

    def success() -> bool:
        tester.log_result("Fixture", "success", "success", "ok")
        return True

    def declared_failure() -> bool:
        tester.log_result("Fixture", "failure", "error", "bad")
        return False

    def no_result() -> bool:
        return True

    def raised() -> bool:
        raise RuntimeError("token=secret-value")

    tester.test_database_connection = success  # type: ignore[method-assign]
    tester.test_account_data = declared_failure  # type: ignore[method-assign]
    tester.test_macro_data_update = no_result  # type: ignore[method-assign]
    tester.test_regime_calculation = raised  # type: ignore[method-assign]
    tester.test_policy_events = success  # type: ignore[method-assign]
    tester.test_investment_signals = success  # type: ignore[method-assign]
    tester.test_dashboard_data = success  # type: ignore[method-assign]
    tester.test_data_consistency = success  # type: ignore[method-assign]

    assert tester.run_all_tests() is False
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["overall_success"] is False
    assert "secret-value" not in json.dumps(payload)
    assert output.with_suffix(".json.tmp").exists() is False


def test_data_connection_command_validates_output_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command, _stdout, _stderr = _command(test_data_connections.Command)
    with pytest.raises(CommandError, match="filesystem path"):
        command.handle(no_write=False, output="not-a-path")

    monkeypatch.setattr(
        test_data_connections.DataConnectionTester,
        "run_all_tests",
        lambda _self: False,
    )
    with pytest.raises(CommandError, match="diagnostics failed"):
        command.handle(no_write=True, output=Path("ignored.json"))

    monkeypatch.setattr(
        test_data_connections.DataConnectionTester,
        "run_all_tests",
        lambda _self: True,
    )
    command.handle(no_write=True, output=Path("ignored.json"))


def test_cache_warmup_success_empty_and_failure_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached: list[tuple[str, object]] = []
    cache_state: dict[str, object] = {}

    def set_cache(key: str, value: object, **_kwargs: object) -> None:
        cached.append((key, value))
        cache_state[key] = value

    monkeypatch.setattr(
        warmup_cache.cache,
        "set",
        set_cache,
    )
    monkeypatch.setattr(
        warmup_cache.cache,
        "get",
        lambda key, default=None: cache_state.get(key, default),
    )
    monkeypatch.setattr(
        warmup_cache.cache,
        "delete",
        lambda key: cache_state.pop(key, None) is not None,
    )
    monkeypatch.setattr(
        "apps.regime.application.query_services.get_latest_regime_cache_payload",
        lambda: {"regime": "recovery"},
    )
    monkeypatch.setattr(
        "apps.data_center.application.query_services." "list_latest_macro_indicator_payloads",
        lambda **_kwargs: [{"indicator_code": "CN_CPI", "value": 1, "reporting_period": "2024-01"}],
    )
    monkeypatch.setattr(
        "apps.alpha.application.query_services.list_recent_alpha_score_cache_payloads",
        lambda **_kwargs: [
            {
                "universe_id": "csi300",
                "provider": "qlib",
                "asof_date": "2024-01-02",
                "status": "ready",
            }
        ],
    )
    command, stdout, _stderr = _command(warmup_cache.Command)
    command.handle(only="")
    assert len(cached) == 3
    assert "complete" in stdout.getvalue()

    monkeypatch.setattr(
        "apps.regime.application.query_services.get_latest_regime_cache_payload",
        lambda: None,
    )
    command.handle(only="regime", allow_empty=True)
    assert "SKIP" in stdout.getvalue()

    monkeypatch.setattr(
        "apps.data_center.application.query_services." "list_latest_macro_indicator_payloads",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("macro unavailable")),
    )
    monkeypatch.setattr(
        "apps.alpha.application.query_services.list_recent_alpha_score_cache_payloads",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("alpha unavailable")),
    )
    with pytest.raises(CommandError, match="macro cache warmup preparation failed"):
        command.handle(only="macro")
    with pytest.raises(CommandError, match="alpha cache warmup preparation failed"):
        command.handle(only="alpha")


def test_init_production_dry_skip_success_reload_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command, stdout, _stderr = _command(init_production.Command)
    command.handle(dry_run=True, skip="")
    assert "[DRY] python manage.py bootstrap_cold_start" in stdout.getvalue()

    with pytest.raises(CommandError, match="--skip is no longer supported"):
        command.handle(dry_run=False, skip="first")

    bootstrap = MagicMock()
    monkeypatch.setattr(init_production, "call_command", bootstrap)
    command.handle(dry_run=False, skip="")
    bootstrap.assert_called_once_with(
        "bootstrap_cold_start",
        stdout=command.stdout,
        stderr=command.stderr,
    )

    assert "Production initialization complete" in stdout.getvalue()


def test_healthcheck_json_text_and_unhealthy_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = {
        "database": {"status": "ok"},
        "cache": {"status": "warning", "reason": "optional"},
        "worker": {"status": "error", "error": "offline"},
    }
    monkeypatch.setattr(healthcheck, "run_readiness_checks", lambda: checks)
    monkeypatch.setattr(healthcheck, "is_healthy", lambda _checks: True)
    command, stdout, _stderr = _command(healthcheck.Command)
    command.handle(json=True)
    assert json.loads(stdout.getvalue())["healthy"] is True

    command.handle(json=False)
    text = stdout.getvalue()
    assert "optional" not in text
    assert "offline" not in text

    monkeypatch.setattr(healthcheck, "is_healthy", lambda _checks: False)
    with pytest.raises(SystemExit) as raised:
        command.handle(json=False)
    assert raised.value.code == 1


def test_data_connection_diagnostics_cover_all_successful_business_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tester = test_data_connections.DataConnectionTester(
        OutputWrapper(StringIO()),
        results_path=None,
    )
    monkeypatch.setattr(
        "apps.account.application.query_services.get_account_diagnostic_user_count",
        lambda: 2,
    )
    monkeypatch.setattr(
        "apps.data_center.application.query_services." "get_data_center_diagnostic_summary",
        lambda: {
            "macro_fact_count": 10,
            "provider_config_count": 2,
            "active_provider_config_count": 1,
        },
    )
    monkeypatch.setattr(
        "apps.regime.application.query_services.get_regime_diagnostic_count",
        lambda: 3,
    )
    monkeypatch.setattr(
        "apps.policy.application.query_services.get_policy_event_count",
        lambda: 4,
    )
    monkeypatch.setattr(
        "apps.signal.application.query_services.get_signal_diagnostic_count",
        lambda: 5,
    )
    assert tester.test_database_connection() is True

    monkeypatch.setattr(
        "apps.account.application.query_services.get_account_diagnostic_summary",
        lambda: {
            "currency_count": 2,
            "active_currency_count": 2,
            "asset_category_count": 3,
            "profile_count": 4,
            "pending_profile_count": 1,
            "approved_profile_count": 3,
            "portfolio_count": 2,
            "active_portfolio_count": 1,
            "position_count": 2,
            "open_position_count": 1,
            "open_position_market_value": 1000,
            "open_position_unrealized_pnl": 50,
        },
    )
    assert tester.test_account_data() is True

    today = test_data_connections.django_timezone.now().date()
    monkeypatch.setattr(
        "apps.macro.application.query_services.get_latest_macro_indicator_date",
        lambda _code: today,
    )
    monkeypatch.setattr(
        "apps.macro.application.query_services.sync_macro_indicators",
        lambda **_kwargs: {
            "success": True,
            "synced_count": 1,
            "skipped_count": 0,
            "errors": [],
        },
    )
    assert tester.test_macro_data_update() is True

    monkeypatch.setattr(
        "apps.regime.application.query_services." "get_latest_regime_diagnostic_payload",
        lambda: {
            "observed_at": today,
            "dominant_regime": "recovery",
            "confidence": 0.8,
        },
    )
    monkeypatch.setattr(
        "apps.regime.application.query_services.get_regime_distribution_payload",
        lambda **_kwargs: {"count": 2, "distribution": {"recovery": 2}},
    )
    monkeypatch.setattr(
        "apps.regime.application.query_services.calculate_regime_diagnostic_payload",
        lambda **_kwargs: {
            "success": True,
            "dominant_regime": "recovery",
            "error": "",
        },
    )
    assert tester.test_regime_calculation() is True

    monkeypatch.setattr(
        "apps.policy.application.query_services.get_policy_status_payload",
        lambda: {
            "current_level": 2,
            "level_name": "neutral",
            "is_intervention_active": False,
        },
    )
    monkeypatch.setattr(
        "apps.policy.application.query_services.get_recent_policy_event_summary",
        lambda **_kwargs: {
            "latest": {
                "event_date": today,
                "level": "neutral",
                "title": "Policy event",
            },
            "level_summary": {"neutral": 1},
        },
    )
    monkeypatch.setattr(
        "apps.policy.application.query_services.get_policy_rss_source_summary",
        lambda: {"rss_count": 2, "active_rss_count": 1},
    )
    assert tester.test_policy_events() is True

    monkeypatch.setattr(
        "apps.signal.application.query_services.get_signal_diagnostic_summary",
        lambda: {
            "active_count": 1,
            "invalidated_count": 1,
            "closed_count": 1,
            "total_count": 3,
            "recent_signals": [
                {
                    "asset_code": "000001.SZ",
                    "direction": "long",
                    "status": "active",
                    "created_at": test_data_connections.datetime.now(test_data_connections.UTC),
                }
            ],
            "regime_matched_count": 1,
            "regime_match_available": True,
        },
    )
    assert tester.test_investment_signals() is True

    monkeypatch.setattr(
        "apps.account.application.query_services.get_first_account_user_payload",
        lambda: {"id": 7, "username": "owner"},
    )
    monkeypatch.setattr(
        "apps.dashboard.application.use_cases.GetDashboardDataUseCase",
        lambda: SimpleNamespace(
            execute=lambda _user_id: SimpleNamespace(
                username="owner",
                display_name="Owner",
                total_assets=1000,
                total_return_pct=5,
                invested_ratio=60,
                position_count=2,
                regime_match_score=0.8,
                current_regime="recovery",
                current_policy_level=2,
            )
        ),
    )
    assert tester.test_dashboard_data() is True

    monkeypatch.setattr(
        "apps.account.application.query_services.count_orphan_account_positions",
        lambda: 0,
    )
    monkeypatch.setattr(
        "apps.signal.application.query_services.list_signal_diagnostic_asset_codes",
        lambda: ["000001.SZ"],
    )
    monkeypatch.setattr(
        "apps.account.application.query_services.count_missing_asset_metadata",
        lambda _codes: 0,
    )
    monkeypatch.setattr(
        "apps.regime.application.query_services.get_latest_regime_observed_at",
        lambda: today,
    )
    monkeypatch.setattr(
        "apps.data_center.application.query_services." "macro_fact_exists_on_or_before",
        lambda _date: True,
    )
    assert tester.test_data_consistency() is True


@pytest.mark.parametrize(
    ("method_name", "dependency_path"),
    [
        (
            "test_database_connection",
            "apps.account.application.query_services." "get_account_diagnostic_user_count",
        ),
        (
            "test_account_data",
            "apps.account.application.query_services.get_account_diagnostic_summary",
        ),
        (
            "test_macro_data_update",
            "apps.macro.application.query_services.get_latest_macro_indicator_date",
        ),
        (
            "test_regime_calculation",
            "apps.regime.application.query_services." "get_latest_regime_diagnostic_payload",
        ),
        (
            "test_policy_events",
            "apps.policy.application.query_services.get_policy_status_payload",
        ),
        (
            "test_investment_signals",
            "apps.signal.application.query_services.get_signal_diagnostic_summary",
        ),
        (
            "test_dashboard_data",
            "apps.account.application.query_services.get_first_account_user_payload",
        ),
        (
            "test_data_consistency",
            "apps.account.application.query_services.count_orphan_account_positions",
        ),
    ],
)
def test_data_connection_diagnostics_isolate_outer_failures(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    dependency_path: str,
) -> None:
    tester = test_data_connections.DataConnectionTester(
        OutputWrapper(StringIO()), results_path=None
    )
    monkeypatch.setattr(
        dependency_path,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("dependency failed")),
    )
    assert getattr(tester, method_name)() is False
