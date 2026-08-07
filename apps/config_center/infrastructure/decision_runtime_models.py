"""Persistence model for the Config Center decision-runtime gate."""

from __future__ import annotations

from django.db import models

from apps.config_center.domain.entities import DecisionRuntimeStatus


class DecisionRuntimeStateModel(models.Model):
    """Singleton controlled state kept separate from ordinary runtime values."""

    state_id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    status = models.CharField(
        max_length=16,
        choices=[(item.value, item.value) for item in DecisionRuntimeStatus],
        default=DecisionRuntimeStatus.BLOCKED.value,
        db_index=True,
    )
    reason = models.TextField(blank=True)
    changed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    changed_by = models.CharField(max_length=150, blank=True)
    release_ref = models.CharField(max_length=100, blank=True)
    expected_resume_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "config_center_decision_runtime_state"


__all__ = ["DecisionRuntimeStateModel"]
