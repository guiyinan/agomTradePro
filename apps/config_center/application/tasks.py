"""Celery task discovery for Config Center application tasks."""

from apps.config_center.application.decision_readiness_guard_tasks import (
    audit_decision_readiness_task,
)

__all__ = ["audit_decision_readiness_task"]
