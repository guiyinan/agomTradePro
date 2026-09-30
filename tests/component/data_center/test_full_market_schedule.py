import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django_celery_beat.models import PeriodicTask

from apps.data_center.management.commands.setup_full_market_publications import (
    _validate_provider_ready_schedule,
)


@pytest.mark.django_db
def test_full_market_schedule_is_idempotent_and_precedes_inference():
    call_command("setup_full_market_publications")
    call_command("setup_full_market_publications")
    row = PeriodicTask.objects.get(name="full-market-current-publications")
    assert row.task == "data_center.refresh_full_market_publications"
    assert row.enabled
    assert (row.crontab.hour, row.crontab.minute) == ("17", "5")
    assert row.crontab.timezone.key == "Asia/Shanghai"
    assert row.crontab.day_of_week == "1,2,3,4,5"
    assert json.loads(row.kwargs) == {
        "quote_source": "tushare",
        "valuation_source": "akshare",
        "batch_size": 100,
    }
    financial = PeriodicTask.objects.get(name="financial-current-publication-refresh")
    assert financial.task == "data_center.refresh_financial_publications_batch"
    assert financial.enabled
    assert (financial.crontab.hour, financial.crontab.minute) == ("1", "10")
    assert json.loads(financial.kwargs) == {
        "source": "tushare",
        "financial_periods": 8,
        "batch_size": 50,
        "auto_continue": True,
    }
    call_command("setup_full_market_publications", disable=True)
    row.refresh_from_db()
    financial.refresh_from_db()
    assert not row.enabled
    assert not financial.enabled


@pytest.mark.django_db
@pytest.mark.parametrize(
    "options",
    [
        {"hour": 24},
        {"batch_size": 0},
        {"source": "unknown"},
        {"quote_source": "unknown"},
        {"valuation_source": "unknown"},
        {"financial_hour": 24},
        {"financial_batch_size": 0},
    ],
)
def test_invalid_schedule_does_not_write(options):
    with pytest.raises(CommandError):
        call_command("setup_full_market_publications", **options)
    assert not PeriodicTask.objects.filter(name="full-market-current-publications").exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("hour", "minute"),
    [(14, 55), (15, 0), (17, 4)],
    ids=["pre-close", "official-close", "before-provider-ready"],
)
@override_settings(TIME_ZONE="Asia/Shanghai")
def test_full_market_schedule_rejects_before_provider_ready(hour, minute):
    with pytest.raises(CommandError, match="17:05 Asia/Shanghai"):
        call_command("setup_full_market_publications", hour=hour, minute=minute)
    assert not PeriodicTask.objects.filter(name="full-market-current-publications").exists()


@pytest.mark.django_db
def test_full_market_schedule_accepts_provider_ready_boundary():
    call_command("setup_full_market_publications", hour=17, minute=5)

    row = PeriodicTask.objects.get(name="full-market-current-publications")
    assert (row.crontab.hour, row.crontab.minute) == ("17", "5")
    assert row.crontab.timezone.key == "Asia/Shanghai"


@pytest.mark.django_db
@override_settings(TIME_ZONE="UTC")
def test_full_market_schedule_uses_china_timezone_independent_of_django_timezone():
    call_command("setup_full_market_publications", hour=17, minute=5)

    market_row = PeriodicTask.objects.get(name="full-market-current-publications")
    financial_row = PeriodicTask.objects.get(name="financial-current-publication-refresh")
    assert (market_row.crontab.hour, market_row.crontab.minute) == ("17", "5")
    assert market_row.crontab.timezone.key == "Asia/Shanghai"
    assert financial_row.crontab.timezone.key == "UTC"


@pytest.mark.parametrize(
    ("hour", "minute", "reject"),
    [(14, 55, True), (15, 0, True), (17, 5, False)],
    ids=["pre-close", "market-close", "provider-ready"],
)
def test_full_market_provider_ready_schedule_policy(hour, minute, reject):
    if reject:
        with pytest.raises(CommandError, match="17:05 Asia/Shanghai"):
            _validate_provider_ready_schedule(hour, minute)
    else:
        _validate_provider_ready_schedule(hour, minute)
