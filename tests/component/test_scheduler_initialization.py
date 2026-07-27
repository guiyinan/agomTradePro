import json
from datetime import UTC, datetime
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django_celery_beat.models import PeriodicTask

from apps.account.management.commands.bootstrap_cold_start import (
    Command as BootstrapColdStartCommand,
)
from apps.account.management.commands.init_all import Command as InitAllCommand
from apps.task_monitor.application.use_cases import (
    ConfigureReadinessScheduleUseCase,
    GetReadinessScheduleUseCase,
)
from apps.task_monitor.domain.entities import (
    ScheduledCrontabRecord,
    SchedulerBootstrapResult,
)
from apps.task_monitor.management.commands.init_scheduler_defaults import (
    Command as InitSchedulerDefaultsCommand,
)


def test_init_all_includes_scheduler_defaults_step():
    command = InitAllCommand()

    assert any(step["command"] == "init_scheduler_defaults" for step in command.init_steps)
    assert any(step["command"] == "init_authoritative_rss_sources" for step in command.init_steps)


def test_init_scheduler_defaults_runs_expected_commands(monkeypatch):
    called = []

    class _Atomic:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, traceback):
            return None

    def _fake_call_command(command_name, **kwargs):
        called.append(command_name)
        stdout = kwargs.get("stdout")
        if stdout is not None:
            stdout.write(f"ran {command_name}\n")

    monkeypatch.setattr(
        "apps.task_monitor.management.commands.init_scheduler_defaults.call_command",
        _fake_call_command,
    )
    monkeypatch.setattr(
        "apps.task_monitor.management.commands.init_scheduler_defaults.transaction.atomic",
        lambda: _Atomic(),
    )

    command = InitSchedulerDefaultsCommand()
    command.stdout = StringIO()
    command.handle()

    assert called == [
        "setup_macro_daily_sync",
        "setup_equity_valuation_sync",
        "setup_decision_quote_refresh",
        "setup_workspace_snapshot_refresh",
        "setup_account_risk_tasks",
        "setup_auto_advisor_weekly_report",
        "setup_personal_readiness_daily",
    ]


def test_init_scheduler_defaults_rolls_back_on_subcommand_failure(monkeypatch):
    calls = []
    atomic_events = []

    class _Atomic:
        def __enter__(self):
            atomic_events.append(("enter", None))

        def __exit__(self, exc_type, exc, traceback):
            atomic_events.append(("exit", exc_type))

    def _fake_call_command(command_name, **kwargs):
        calls.append(command_name)
        stdout = kwargs.get("stdout")
        if stdout is not None:
            stdout.write(f"ran {command_name}\n")
        if command_name == "setup_decision_quote_refresh":
            raise RuntimeError("database is locked")

    monkeypatch.setattr(
        "apps.task_monitor.management.commands.init_scheduler_defaults.transaction.atomic",
        lambda: _Atomic(),
    )
    monkeypatch.setattr(
        "apps.task_monitor.management.commands.init_scheduler_defaults.call_command",
        _fake_call_command,
    )
    monkeypatch.setattr(
        "apps.task_monitor.management.commands.init_scheduler_defaults.transaction.atomic",
        lambda: _Atomic(),
    )

    command = InitSchedulerDefaultsCommand()
    command.stdout = StringIO()

    with pytest.raises(CommandError, match="setup_decision_quote_refresh"):
        command.handle()

    assert calls == [
        "setup_macro_daily_sync",
        "setup_equity_valuation_sync",
        "setup_decision_quote_refresh",
    ]
    assert atomic_events == [("enter", None), ("exit", RuntimeError)]
    assert command.stdout.getvalue() == ""


@pytest.mark.django_db
def test_setup_personal_readiness_daily_creates_periodic_task():
    output = StringIO()

    call_command(
        "setup_personal_readiness_daily",
        stdout=output,
    )

    task = PeriodicTask.objects.get(name="personal-readiness-daily-evidence")
    assert task.task == (
        "apps.operational_readiness.application.tasks." "run_personal_readiness_daily_task"
    )
    assert task.enabled is True
    assert task.crontab is not None
    assert task.crontab.hour == "16"
    assert task.crontab.minute == "10"
    assert task.args == "[]"
    assert task.headers == "{}"
    assert task.queue is None
    assert task.exchange is None
    assert task.routing_key is None
    assert task.priority is None
    assert task.one_off is False
    assert task.expires is None
    assert task.expire_seconds is None
    assert '"calendar_source": "auto"' in task.kwargs
    assert '"persist_risk_report": true' in task.kwargs
    assert '"repair_accounts": false' in task.kwargs
    assert '"allow_unclosed_target_date": false' in task.kwargs
    assert '"trigger_source": "scheduler"' in task.kwargs
    assert "Personal readiness daily task configured" in output.getvalue()


@pytest.mark.django_db
def test_setup_personal_readiness_daily_repairs_unsafe_periodic_task_controls():
    call_command("setup_personal_readiness_daily", "--hour", "23", "--minute", "50")

    task = PeriodicTask.objects.get(name="personal-readiness-daily-evidence")
    PeriodicTask.objects.filter(pk=task.pk).update(
        args='["2026-07-01"]',
        kwargs=(
            '{"calendar_source": "weekday", "target_date": "2026-07-01", '
            '"run_workspace_refresh": false, "include_weekly_advisor": false, '
            '"max_qlib_staleness_days": 30}'
        ),
        queue="readiness",
        exchange="custom",
        routing_key="readiness.daily",
        priority=3,
        headers='{"x-readiness": true}',
        one_off=True,
        expires=datetime(2026, 7, 10, tzinfo=UTC),
        expire_seconds=3600,
    )

    call_command("setup_personal_readiness_daily", "--hour", "23", "--minute", "50")

    task.refresh_from_db()
    kwargs = json.loads(task.kwargs)
    assert task.args == "[]"
    assert "target_date" not in kwargs
    assert "max_qlib_staleness_days" not in kwargs
    assert kwargs["calendar_source"] == "auto"
    assert kwargs["run_workspace_refresh"] is True
    assert kwargs["include_weekly_advisor"] is True
    assert kwargs["persist_risk_report"] is True
    assert kwargs["trigger_source"] == "scheduler"
    assert task.queue is None
    assert task.exchange is None
    assert task.routing_key is None
    assert task.priority is None
    assert task.headers == "{}"
    assert task.one_off is False
    assert task.expires is None
    assert task.expire_seconds is None


@pytest.mark.django_db
def test_setup_decision_quote_refresh_creates_pre_readiness_refresh():
    output = StringIO()

    call_command("setup_decision_quote_refresh", stdout=output)

    task = PeriodicTask.objects.get(name="decision-quote-pre-readiness-refresh")
    assert task.task == "apps.data_center.application.tasks.refresh_decision_quote_snapshots_task"
    assert task.enabled is True
    assert task.crontab is not None
    assert task.crontab.hour == "15"
    assert task.crontab.minute == "35"
    assert task.crontab.day_of_week == "1,2,3,4,5"
    assert '"quote_max_age_hours": 4.0' in task.kwargs
    assert "decision-quote-pre-readiness-refresh: enabled @ weekdays 15:35" in output.getvalue()


@pytest.mark.django_db
def test_setup_decision_quote_refresh_accepts_custom_pre_readiness_time():
    output = StringIO()

    call_command(
        "setup_decision_quote_refresh",
        "--pre-readiness-hour",
        "16",
        "--pre-readiness-minute",
        "5",
        stdout=output,
    )

    task = PeriodicTask.objects.get(name="decision-quote-pre-readiness-refresh")
    assert task.crontab is not None
    assert task.crontab.hour == "16"
    assert task.crontab.minute == "5"
    assert "decision-quote-pre-readiness-refresh: enabled @ weekdays 16:05" in output.getvalue()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"pre_readiness_hour": 24}, "pre-readiness-hour"),
        ({"pre_readiness_minute": 60}, "pre-readiness-minute"),
        ({"pre_readiness_hour": 15, "pre_readiness_minute": 20}, "after post-close"),
        ({"quote_max_age_hours": 0.0}, "finite and positive"),
        ({"quote_max_age_hours": float("nan")}, "finite and positive"),
    ],
)
def test_setup_decision_quote_refresh_rejects_invalid_values_before_writes(
    kwargs,
    message,
):
    """Invalid scheduling and freshness values fail without partial Beat rows."""

    with pytest.raises(CommandError, match=message):
        call_command("setup_decision_quote_refresh", **kwargs)

    assert not PeriodicTask.objects.filter(name__startswith="decision-quote-").exists()


@pytest.mark.django_db
@override_settings(DECISION_READINESS_ASSET_CODES="510300.SH", TIME_ZONE="UTC")
def test_setup_decision_quote_refresh_rejects_string_settings_asset_codes():
    """A string setting cannot be misread as an iterable of asset codes."""

    with pytest.raises(CommandError, match="string list"):
        call_command("setup_decision_quote_refresh")

    assert not PeriodicTask.objects.filter(name__startswith="decision-quote-").exists()


@pytest.mark.django_db
@override_settings(
    DECISION_READINESS_ASSET_CODES=[" 510300.sh ", "510300.SH", "000300.sh"],
    TIME_ZONE="UTC",
)
def test_setup_decision_quote_refresh_uses_typed_settings_timezone_and_deduped_codes():
    """Beat rows use project timezone and stable normalized asset-code kwargs."""

    call_command("setup_decision_quote_refresh")

    task = PeriodicTask.objects.get(name="decision-quote-pre-readiness-refresh")
    assert task.crontab is not None
    assert str(task.crontab.timezone) == "UTC"
    assert json.loads(task.kwargs)["asset_codes"] == ["510300.SH", "000300.SH"]


def test_configure_readiness_schedule_rejects_daily_evidence_before_safe_close():
    class _Gateway:
        def configure_readiness_schedule(self, **kwargs):
            raise AssertionError("Gateway should not be called for unsafe schedule")

    use_case = ConfigureReadinessScheduleUseCase(gateway=_Gateway())

    with pytest.raises(ValueError, match="不早于 16:00"):
        use_case.execute(
            quote_pre_refresh_time="15:35",
            daily_evidence_time="15:55",
            weekly_auto_advisor_time="17:30",
        )


def test_get_readiness_schedule_includes_weekly_auto_advisor_time():
    class _Repository:
        def get_crontab_task(self, task_name):
            schedules = {
                "decision-quote-pre-readiness-refresh": ScheduledCrontabRecord(
                    name=task_name,
                    exists=True,
                    enabled=True,
                    minute="35",
                    hour="15",
                    day_of_week="1,2,3,4,5",
                ),
                "personal-readiness-daily-evidence": ScheduledCrontabRecord(
                    name=task_name,
                    exists=True,
                    enabled=True,
                    minute="10",
                    hour="16",
                    day_of_week="mon-fri",
                ),
                "dashboard-auto-advisor-weekly-report": ScheduledCrontabRecord(
                    name=task_name,
                    exists=True,
                    enabled=True,
                    minute="30",
                    hour="17",
                    day_of_week="fri",
                ),
            }
            return schedules[task_name]

    response = GetReadinessScheduleUseCase(scheduler_repository=_Repository()).execute()

    assert response.quote_pre_refresh_time == "15:35"
    assert response.daily_evidence_time == "16:10"
    assert response.weekly_auto_advisor_time == "17:30"
    assert response.weekly_auto_advisor_enabled is True
    assert response.weekly_auto_advisor_task_exists is True
    assert response.weekly_auto_advisor_day_of_week == "fri"


def test_configure_readiness_schedule_rejects_weekly_before_daily_evidence():
    class _Gateway:
        def configure_readiness_schedule(self, **kwargs):
            raise AssertionError("Gateway should not be called for unsafe schedule")

    use_case = ConfigureReadinessScheduleUseCase(gateway=_Gateway())

    with pytest.raises(ValueError, match="晚于每日 readiness 证据时间"):
        use_case.execute(
            quote_pre_refresh_time="15:35",
            daily_evidence_time="16:10",
            weekly_auto_advisor_time="16:05",
        )


def test_configure_readiness_schedule_passes_post_close_times_to_gateway():
    class _Gateway:
        def __init__(self):
            self.kwargs = None

        def configure_readiness_schedule(self, **kwargs):
            self.kwargs = kwargs
            return SchedulerBootstrapResult(
                executed_commands=[
                    "setup_decision_quote_refresh",
                    "setup_personal_readiness_daily",
                    "setup_auto_advisor_weekly_report",
                ],
                output_lines=["updated"],
            )

    gateway = _Gateway()
    use_case = ConfigureReadinessScheduleUseCase(gateway=gateway)

    response = use_case.execute(
        quote_pre_refresh_time="15:35",
        daily_evidence_time="16:10",
        weekly_auto_advisor_time="17:30",
    )

    assert gateway.kwargs == {
        "quote_pre_refresh_hour": 15,
        "quote_pre_refresh_minute": 35,
        "daily_evidence_hour": 16,
        "daily_evidence_minute": 10,
        "weekly_auto_advisor_hour": 17,
        "weekly_auto_advisor_minute": 30,
    }
    assert response.executed_commands == [
        "setup_decision_quote_refresh",
        "setup_personal_readiness_daily",
        "setup_auto_advisor_weekly_report",
    ]
    assert response.output_lines == ["updated"]
    assert response.quote_pre_refresh_time == "15:35"
    assert response.daily_evidence_time == "16:10"
    assert response.weekly_auto_advisor_time == "17:30"


@pytest.mark.django_db
def test_management_gateway_configures_weekly_auto_advisor_schedule():
    from apps.task_monitor.infrastructure.repositories import (
        ManagementCommandSchedulerConfigurationGateway,
    )

    gateway = ManagementCommandSchedulerConfigurationGateway()

    result = gateway.configure_readiness_schedule(
        quote_pre_refresh_hour=15,
        quote_pre_refresh_minute=40,
        daily_evidence_hour=16,
        daily_evidence_minute=20,
        weekly_auto_advisor_hour=17,
        weekly_auto_advisor_minute=45,
    )

    weekly_task = PeriodicTask.objects.get(name="dashboard-auto-advisor-weekly-report")
    assert "setup_auto_advisor_weekly_report" in result.executed_commands
    assert weekly_task.task == "dashboard.generate_auto_advisor_weekly_reports"
    assert weekly_task.enabled is True
    assert weekly_task.crontab is not None
    assert weekly_task.crontab.day_of_week == "fri"
    assert weekly_task.crontab.hour == "17"
    assert weekly_task.crontab.minute == "45"


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
                "decision-quote-pre-readiness-refresh",
                "decision-quote-freshness-check",
                "decision-workspace-nightly-snapshot-refresh",
                "account-check-stop-loss-take-profit-intraday",
                "dashboard-auto-advisor-weekly-report",
                "personal-readiness-daily-evidence",
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


def test_bootstrap_cold_start_macro_governance_readiness_uses_check_mode(monkeypatch):
    command = BootstrapColdStartCommand()
    calls = []
    monkeypatch.setattr(
        command, "_run_command", lambda name, **kwargs: calls.append((name, kwargs))
    )

    assert command._macro_indicator_governance_ready() is True
    assert calls == [("init_macro_indicator_governance", {"check": True})]


def test_bootstrap_cold_start_macro_governance_readiness_detects_drift(monkeypatch):
    command = BootstrapColdStartCommand()

    def _raise_drift(name, **kwargs):
        del name, kwargs
        raise CommandError("governance drift")

    monkeypatch.setattr(command, "_run_command", _raise_drift)

    assert command._macro_indicator_governance_ready() is False
