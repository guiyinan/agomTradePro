import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django_celery_beat.models import PeriodicTask


@pytest.mark.django_db
def test_full_market_schedule_is_idempotent_and_precedes_inference():
    call_command("setup_full_market_publications")
    call_command("setup_full_market_publications")
    row = PeriodicTask.objects.get(name="full-market-current-publications")
    assert row.task == "data_center.refresh_full_market_publications"
    assert row.enabled
    assert (row.crontab.hour, row.crontab.minute) == ("17", "5")
    assert row.crontab.day_of_week == "1,2,3,4,5"
    assert json.loads(row.kwargs) == {
        "quote_source": "akshare",
        "valuation_source": "tushare",
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
