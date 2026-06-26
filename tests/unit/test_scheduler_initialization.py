from io import StringIO

from apps.account.management.commands.bootstrap_cold_start import (
    Command as BootstrapColdStartCommand,
)
from apps.account.management.commands.init_all import Command as InitAllCommand
from apps.task_monitor.management.commands.init_scheduler_defaults import (
    Command as InitSchedulerDefaultsCommand,
)


def test_init_all_includes_scheduler_defaults_step():
    command = InitAllCommand()

    assert any(
        step["command"] == "init_scheduler_defaults"
        for step in command.init_steps
    )
    assert any(
        step["command"] == "init_authoritative_rss_sources"
        for step in command.init_steps
    )


def test_init_scheduler_defaults_runs_expected_commands(monkeypatch):
    called = []

    def _fake_call_command(command_name, **kwargs):
        called.append(command_name)
        stdout = kwargs.get("stdout")
        if stdout is not None:
            stdout.write(f"ran {command_name}\n")

    monkeypatch.setattr(
        "apps.task_monitor.management.commands.init_scheduler_defaults.call_command",
        _fake_call_command,
    )

    command = InitSchedulerDefaultsCommand()
    command.stdout = StringIO()
    command.handle()

    assert called == [
        "setup_macro_daily_sync",
        "setup_equity_valuation_sync",
        "setup_decision_quote_refresh",
        "setup_workspace_snapshot_refresh",
    ]


def test_bootstrap_cold_start_detects_scheduler_defaults_ready(monkeypatch):
    class _Manager:
        @staticmethod
        def values_list(*args, **kwargs):
            return [
                "daily-sync-and-calculate",
                "check-data-freshness",
                "high-frequency-generate-signal",
                "high-frequency-recalculate-regime",
                "equity-valuation-daily-sync",
                "equity-valuation-quality-validate",
                "equity-valuation-freshness-check",
                "decision-quote-intraday-refresh",
                "decision-quote-post-close-refresh",
                "decision-quote-freshness-check",
                "decision-workspace-nightly-snapshot-refresh",
            ]

    class _PeriodicTaskModel:
        _default_manager = _Manager()

    monkeypatch.setattr(
        "apps.account.management.commands.bootstrap_cold_start.django_apps.get_model",
        lambda app_label, model_name: _PeriodicTaskModel,
    )

    command = BootstrapColdStartCommand()

    assert command._scheduler_defaults_ready() is True


def test_bootstrap_cold_start_detects_authoritative_rss_sources_ready(monkeypatch):
    from apps.policy.management.commands.init_authoritative_rss_sources import (
        AUTHORITATIVE_RSS_SOURCES,
    )

    expected_routes = {source.route_path for source in AUTHORITATIVE_RSS_SOURCES}

    class _Config:
        enabled = True

    class _ConfigQuery:
        @staticmethod
        def first():
            return _Config()

    class _ConfigManager:
        @staticmethod
        def filter(*args, **kwargs):
            return _ConfigQuery()

    class _SourceQuery:
        @staticmethod
        def values_list(*args, **kwargs):
            return list(expected_routes)

    class _SourceManager:
        @staticmethod
        def filter(*args, **kwargs):
            return _SourceQuery()

    class _RSSHubConfigModel:
        _default_manager = _ConfigManager()

    class _RSSSourceModel:
        _default_manager = _SourceManager()

    def _fake_get_model(app_label, model_name):
        if model_name == "RSSHubGlobalConfig":
            return _RSSHubConfigModel
        if model_name == "RSSSourceConfigModel":
            return _RSSSourceModel
        raise AssertionError(f"Unexpected model lookup: {app_label}.{model_name}")

    monkeypatch.setattr(
        "apps.account.management.commands.bootstrap_cold_start.django_apps.get_model",
        _fake_get_model,
    )

    command = BootstrapColdStartCommand()

    assert command._authoritative_rss_sources_ready() is True
