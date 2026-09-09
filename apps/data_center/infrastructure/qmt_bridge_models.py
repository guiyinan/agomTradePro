"""Persistent owner/server pairing and receipts for the QMT bridge."""

import uuid

from django.conf import settings
from django.db import models


class QmtBridgeBindingModel(models.Model):
    """One local Agent paired to this server and an authenticated owner."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    agent_id = models.CharField(max_length=100)
    server_url = models.URLField()
    provider = models.OneToOneField(
        "data_center.ProviderConfigModel", null=True, blank=True, on_delete=models.PROTECT
    )
    assets = models.JSONField(default=list)
    pairing_hash = models.CharField(max_length=64, blank=True, db_index=True)
    pairing_expires_at = models.DateTimeField(null=True)
    token_hash = models.CharField(max_length=64, blank=True)
    token_expires_at = models.DateTimeField(null=True)
    paired_at = models.DateTimeField(null=True)
    enabled = models.BooleanField(default=False)
    revoked = models.BooleanField(default=False)
    poll_seconds = models.PositiveIntegerField(default=10)
    freshness_seconds = models.PositiveIntegerField(default=60)
    quote_volume_multiplier = models.DecimalField(max_digits=12, decimal_places=4, null=True)
    bar_volume_multiplier = models.DecimalField(max_digits=12, decimal_places=4, null=True)
    last_seen_at = models.DateTimeField(null=True)
    last_observed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_qmt_bridge_binding"
        constraints = [
            models.UniqueConstraint(fields=["owner", "agent_id"], name="dc_qmt_owner_agent")
        ]


class QmtBridgeBatchModel(models.Model):
    """Immutable batch digest and durable receipt for retry safety."""

    binding = models.ForeignKey(QmtBridgeBindingModel, on_delete=models.CASCADE)
    batch_id = models.UUIDField()
    digest = models.CharField(max_length=64)
    receipt = models.JSONField(default=dict)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_qmt_bridge_batch"
        constraints = [
            models.UniqueConstraint(fields=["binding", "batch_id"], name="dc_qmt_batch_identity")
        ]


class QmtBridgeNonceModel(models.Model):
    """Replay protection for signed machine requests."""

    binding = models.ForeignKey(QmtBridgeBindingModel, on_delete=models.CASCADE)
    nonce = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_qmt_bridge_nonce"
        constraints = [
            models.UniqueConstraint(fields=["binding", "nonce"], name="dc_qmt_nonce_identity")
        ]


class QmtBridgeAuditModel(models.Model):
    """Append-only binding lifecycle audit, without credentials or local paths."""

    binding = models.ForeignKey(QmtBridgeBindingModel, on_delete=models.CASCADE)
    actor_id = models.PositiveBigIntegerField(null=True)
    action = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_qmt_bridge_audit"
