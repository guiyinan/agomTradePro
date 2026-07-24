"""ORM persistence for canonical decision input snapshots."""

from django.core.exceptions import ValidationError
from django.db import models

__all__ = ["DecisionInputSnapshotModel"]


class DecisionInputSnapshotModel(models.Model):
    """Append-only decision evidence package."""

    snapshot_id = models.CharField(max_length=64, primary_key=True)
    schema_version = models.CharField(max_length=16, default="v1")
    as_of_time = models.DateTimeField(db_index=True)
    state_hash = models.CharField(max_length=64, unique=True)
    pit_manifest_id = models.CharField(max_length=64, db_index=True)
    components = models.JSONField(default=dict)
    portfolio_snapshot_id = models.CharField(max_length=64)
    config_version = models.CharField(max_length=64)
    strategy_version = models.CharField(max_length=64)
    prompt_version = models.CharField(max_length=64, blank=True)
    freshness = models.JSONField(default=dict)
    quality = models.JSONField(default=dict)
    must_not_use = models.BooleanField(default=False, db_index=True)
    missing_components = models.JSONField(default=list)
    creation_reason = models.CharField(max_length=255, blank=True)
    correlation_id = models.CharField(max_length=64, blank=True, db_index=True)
    caller = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "decision_input_snapshot"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["as_of_time", "must_not_use"])]

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("DecisionInputSnapshot is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise ValidationError("DecisionInputSnapshot cannot be deleted.")
