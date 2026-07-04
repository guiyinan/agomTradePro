"""Runtime import bridges for optional cross-app calls."""

from __future__ import annotations

from importlib import import_module
from typing import Any


def record_pending_task(**kwargs: Any) -> Any:
    tracking = import_module("apps.task_monitor.application.tracking")
    return tracking.record_pending_task(**kwargs)


def get_celery_health_checker() -> Any:
    repository_provider = import_module("apps.task_monitor.application.repository_provider")
    return repository_provider.get_celery_health_checker()


def has_active_cooldowns() -> bool:
    query_services = import_module("apps.decision_rhythm.application.query_services")
    return query_services.has_active_cooldowns()


def has_decision_quotas() -> bool:
    query_services = import_module("apps.decision_rhythm.application.query_services")
    return query_services.has_decision_quotas()


def has_recent_decision_requests() -> bool:
    query_services = import_module("apps.decision_rhythm.application.query_services")
    return query_services.has_recent_decision_requests()
