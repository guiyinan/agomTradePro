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
