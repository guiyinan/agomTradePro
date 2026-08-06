"""Persistence for database-backup delivery state."""

from __future__ import annotations

from django.db import models


class BackupDeliveryStateModel(models.Model):
    """Singleton state for one active backup-download link and send marker."""

    state_id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    last_sent_at = models.DateTimeField(null=True, blank=True, db_index=True)
    download_token_digest = models.CharField(max_length=64, blank=True, default="")
    download_token_expires_at = models.DateTimeField(null=True, blank=True)
    download_token_consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "config_center_backup_delivery_state"


__all__ = ["BackupDeliveryStateModel"]
