"""Encrypted secret material owned by Config Center.

Runtime profiles intentionally persist only stable ``secret_ref`` values.  The
encrypted bytes live in this owner table so domain settings and one-time
delivery state cannot silently become a second credential store.
"""

from __future__ import annotations

from django.db import models


class ConfigCenterSecretModel(models.Model):
    """One encrypted value addressed by a stable Config Center reference."""

    secret_ref = models.CharField(max_length=300, primary_key=True)
    encrypted_value = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "config_center_secret"


__all__ = ["ConfigCenterSecretModel"]
