import io

import pytest
from django.core.management import call_command
from django_celery_beat.models import PeriodicTask


@pytest.mark.django_db
def test_setup_account_risk_tasks_creates_intraday_periodic_task():
    out = io.StringIO()

    call_command("setup_account_risk_tasks", stdout=out)

    task = PeriodicTask.objects.get(name="account-check-stop-loss-take-profit-intraday")
    assert task.task == "apps.account.application.tasks.check_stop_loss_and_take_profit_task"
    assert task.enabled is True
    assert task.kwargs == "{}"
    assert task.crontab is not None
    assert task.crontab.minute == "*/30"
    assert task.crontab.hour == "10-15"
    assert task.crontab.day_of_week == "1,2,3,4,5"
    assert "Account risk periodic tasks configured" in out.getvalue()
