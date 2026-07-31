import importlib
import io
import sys

import pytest
from django.core.management import call_command
from django_celery_beat.models import CrontabSchedule, PeriodicTask


def _reload_module(module_name: str):
    """Reload a settings module so schedule changes are reflected in assertions."""
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_development_settings_use_database_scheduler_and_canonical_regime_tasks() -> None:
    """Development should rely on django-celery-beat and point schedule entries at live tasks."""
    settings_module = _reload_module("core.settings.development")

    assert (
        settings_module.CELERY_BEAT_SCHEDULER == "django_celery_beat.schedulers.DatabaseScheduler"
    )
    assert (
        settings_module.CELERY_BEAT_SCHEDULE["daily-sync-and-calculate"]["task"]
        == "apps.regime.application.orchestration.sync_macro_then_refresh_regime"
    )
    assert (
        settings_module.CELERY_BEAT_SCHEDULE["high-frequency-generate-signal"]["task"]
        == "apps.regime.application.orchestration.generate_daily_regime_signal"
    )
    assert (
        settings_module.CELERY_BEAT_SCHEDULE["high-frequency-recalculate-regime"]["task"]
        == "apps.regime.application.orchestration.recalculate_regime_with_daily_signal"
    )
    assert (
        settings_module.CELERY_BEAT_SCHEDULE["account-check-stop-loss-take-profit-intraday"]["task"]
        == "apps.account.application.tasks.check_stop_loss_and_take_profit_task"
    )
    readiness_entry = settings_module.CELERY_BEAT_SCHEDULE["personal-readiness-daily-evidence"]
    assert (
        readiness_entry["task"]
        == "apps.operational_readiness.application.tasks.run_personal_readiness_daily_task"
    )
    assert readiness_entry["kwargs"]["calendar_source"] == "auto"
    assert readiness_entry["kwargs"]["repair_accounts"] is False
    assert readiness_entry["kwargs"]["allow_unclosed_target_date"] is False


def test_database_scheduler_entries_use_persisted_expiration_field() -> None:
    """Periodic jobs must use only options persisted by django-celery-beat."""

    settings_module = _reload_module("core.settings.development")
    schedule = settings_module.CELERY_BEAT_SCHEDULE
    allowed_options = {
        "queue",
        "exchange",
        "routing_key",
        "priority",
        "headers",
        "expire_seconds",
    }

    for task_name, entry in schedule.items():
        options = entry.get("options", {})
        unsupported_options = set(options) - allowed_options
        assert not unsupported_options, (
            f"{task_name} has unsupported options: {unsupported_options}"
        )

    assert schedule["broker-execution-maintenance"]["options"]["expire_seconds"] == 50
    assert schedule["alpha-evaluate-alerts"]["options"]["expire_seconds"] == 60
    assert schedule["alpha-check-queue-lag"]["options"]["expire_seconds"] == 60
    assert schedule["sentiment-refresh-current-index"]["options"]["expire_seconds"] == 3300
    assert schedule["daily-sync-and-calculate"]["kwargs"]["source"] == "akshare"
    assert schedule["high-frequency-sync-bonds"]["kwargs"]["years_back"] == 1
    assert schedule["high-frequency-recalculate-regime"]["kwargs"]["use_pit"] is True
    assert schedule["alpha-cleanup-metrics"]["kwargs"]["days"] == 30
    assert schedule["task-monitor-cleanup"]["kwargs"]["days_to_keep"] == 30


@pytest.mark.django_db
def test_setup_macro_daily_sync_reconciles_periodic_tasks() -> None:
    """The setup command should rewrite managed tasks onto the canonical regime orchestration chain."""
    out = io.StringIO()
    legacy_crontab = CrontabSchedule.objects.create(
        minute="0",
        hour="8",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
    )
    PeriodicTask.objects.create(
        name="legacy-macro-sync",
        task="apps.macro.application.tasks.sync_and_calculate_regime",
        enabled=True,
        crontab=legacy_crontab,
    )

    call_command("setup_macro_daily_sync", "--hour", "8", "--minute", "5", stdout=out)

    daily_task = PeriodicTask.objects.get(name="daily-sync-and-calculate")
    freshness_task = PeriodicTask.objects.get(name="check-data-freshness")
    signal_task = PeriodicTask.objects.get(name="high-frequency-generate-signal")
    recalc_task = PeriodicTask.objects.get(name="high-frequency-recalculate-regime")
    legacy_task = PeriodicTask.objects.get(name="legacy-macro-sync")

    assert daily_task.task == "apps.regime.application.orchestration.sync_macro_then_refresh_regime"
    assert daily_task.crontab is not None
    assert daily_task.crontab.hour == "8"
    assert daily_task.crontab.minute == "5"
    assert (
        daily_task.kwargs
        == '{"source": "akshare", "indicator": null, "days_back": 60, "use_pit": true}'
    )

    assert freshness_task.task == "apps.macro.application.tasks.check_data_freshness"
    assert freshness_task.interval is not None
    assert freshness_task.interval.every == 6

    assert signal_task.task == "apps.regime.application.orchestration.generate_daily_regime_signal"
    assert signal_task.crontab is not None
    assert signal_task.crontab.hour == "17"
    assert signal_task.crontab.minute == "0"

    assert (
        recalc_task.task
        == "apps.regime.application.orchestration.recalculate_regime_with_daily_signal"
    )
    assert recalc_task.crontab is not None
    assert recalc_task.crontab.hour == "17"
    assert recalc_task.crontab.minute == "5"
    assert recalc_task.kwargs == '{"use_pit": true}'

    assert legacy_task.enabled is False
    assert "Disabled legacy task path" in legacy_task.description

    output = out.getvalue()
    assert "Macro periodic tasks configured" in output
    assert "high-frequency-generate-signal" in output
    assert "high-frequency-recalculate-regime" in output
