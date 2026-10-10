"""Cold-start contracts for Task Monitor's Celery signal registration."""

import os
import subprocess
import sys
from pathlib import Path


def test_django_setup_registers_task_monitor_lifecycle_signals() -> None:
    """The AppConfig must register monitor signals before eager task dispatch."""

    code = """
import django
django.setup()

from celery import shared_task
from celery.signals import task_postrun, task_prerun

from apps.task_monitor.application import current_task_attempt_identity
from apps.task_monitor.application import tasks as monitor_tasks
from apps.task_monitor.domain.entities import TaskStatus

def is_registered(signal, function_name):
    for _, weak_receiver in signal.receivers:
        receiver = weak_receiver()
        if (
            receiver is not None
            and receiver.__module__ == "apps.task_monitor.application.tasks"
            and receiver.__name__ == function_name
        ):
            return True
    return False

assert is_registered(task_prerun, "task_prerun_handler")
assert is_registered(task_postrun, "task_postrun_handler")

class Repository:
    record = None

    def get_by_task_id(self, task_id):
        if self.record is not None and self.record.task_id == task_id:
            return self.record
        return None

class UseCase:
    def __init__(self, repository):
        self.repository = repository

    def execute(self, record, *, expected_attempt_id=None):
        if expected_attempt_id is not None:
            if self.repository.record.attempt_id != expected_attempt_id:
                return ""
        self.repository.record = record
        return "task-record-id"

repository = Repository()
monitor_tasks.get_repository = lambda: repository
monitor_tasks.get_use_case = lambda: UseCase(repository)
current_task_attempt_identity.get_task_record_repository = lambda: repository

@shared_task(name="tests.task_monitor.eager_lifecycle_contract")
def eager_lifecycle_contract():
    identity = current_task_attempt_identity.get_current_task_attempt_identity()
    assert repository.record.status is TaskStatus.STARTED
    assert repository.record.attempt_id == identity.attempt_id
    return {"outcome": "success", "attempt_id": identity.attempt_id}

result = eager_lifecycle_contract.apply(task_id="eager-task-1", throw=True)
assert result.state == "SUCCESS"
assert repository.record.status is TaskStatus.SUCCESS
assert repository.record.attempt_id == result.result["attempt_id"]
"""
    environment = os.environ.copy()
    environment["DJANGO_SETTINGS_MODULE"] = "core.settings.development_sqlite"
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[3],
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
