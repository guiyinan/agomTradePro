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
    assert (row.crontab.hour, row.crontab.minute) == ("16", "30")
    assert row.crontab.day_of_week == "1,2,3,4,5"
    assert json.loads(row.kwargs) == {"source": "akshare", "batch_size": 100}
    call_command("setup_full_market_publications", disable=True)
    row.refresh_from_db()
    assert not row.enabled


@pytest.mark.django_db
@pytest.mark.parametrize("options", [{"hour": 24}, {"batch_size": 0}, {"source": "unknown"}])
def test_invalid_schedule_does_not_write(options):
    with pytest.raises(CommandError):
        call_command("setup_full_market_publications", **options)
    assert not PeriodicTask.objects.filter(name="full-market-current-publications").exists()
