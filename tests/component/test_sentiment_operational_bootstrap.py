"""Cold-start regressions for sentiment configuration and scheduling."""

from io import StringIO

import pytest
from django.core.management import call_command
from django_celery_beat.models import PeriodicTask

from apps.policy.infrastructure.models import SentimentGateConfig


@pytest.mark.django_db
def test_policy_sentiment_gate_defaults_are_idempotent() -> None:
    """A fresh database receives every canonical gate config exactly once."""

    call_command("init_policy_sentiment_gate_defaults", stdout=StringIO())
    call_command("init_policy_sentiment_gate_defaults", stdout=StringIO())

    expected_asset_classes = {value for value, _label in SentimentGateConfig.ASSET_CLASS_CHOICES}
    rows = SentimentGateConfig._default_manager.all()
    assert set(rows.values_list("asset_class", flat=True)) == expected_asset_classes
    assert rows.count() == len(expected_asset_classes)


@pytest.mark.django_db
def test_sentiment_refresh_schedule_is_created_and_idempotent() -> None:
    """Cold start installs one weekday intraday/post-close refresh schedule."""

    call_command("setup_sentiment_refresh", stdout=StringIO())
    call_command("setup_sentiment_refresh", stdout=StringIO())

    task = PeriodicTask._default_manager.get(name="sentiment-refresh-current-index")
    assert task.task == "sentiment.refresh_current_sentiment_index"
    assert task.enabled is True
    assert task.crontab is not None
    assert task.crontab.minute == "15"
    assert task.crontab.hour == "9-11,13-15,18,23"
    assert task.crontab.day_of_week == "mon-fri"
    assert PeriodicTask._default_manager.filter(name=task.name).count() == 1


def test_scheduler_bootstrap_includes_sentiment_refresh() -> None:
    """The aggregate startup command must not omit the sentiment scheduler."""

    from apps.task_monitor.management.commands.init_scheduler_defaults import (
        SCHEDULER_COMMANDS,
    )

    assert "setup_sentiment_refresh" in SCHEDULER_COMMANDS


def test_cold_start_includes_policy_gate_defaults() -> None:
    """Production bootstrap owns the missing policy gate configuration."""

    from apps.account.management.commands.bootstrap_cold_start import Command

    command = Command()
    step_names = {step.name for step in command._build_steps("prod")}
    assert "policy_sentiment_gate_defaults" in step_names
