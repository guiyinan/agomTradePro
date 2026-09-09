"""Persistence models for Data Center outbound routing and diagnostics."""

from __future__ import annotations

import uuid

from django.db import models


class EgressRoutingRuleModel(models.Model):
    """One provider/domain/region routing rule."""

    STRATEGY_CHOICES = (
        ("direct", "Direct"),
        ("fixed", "Fixed egress"),
        ("direct_fallback", "Direct then fixed egress"),
    )

    provider_id = models.PositiveBigIntegerField(db_index=True)
    dataset_key = models.CharField(max_length=120)
    domain_pattern = models.CharField(max_length=253)
    deployment_region = models.CharField(max_length=40)
    strategy = models.CharField(max_length=24, choices=STRATEGY_CHOICES)
    fixed_egress_id = models.PositiveBigIntegerField(null=True, blank=True)
    priority = models.PositiveIntegerField(default=100, db_index=True)
    enabled = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_egress_routing_rule"
        ordering = ("priority", "id")


class EgressRequestAuditModel(models.Model):
    """Bounded audit evidence for each attempted egress transport."""

    request_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    provider_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    dataset_key = models.CharField(max_length=120, blank=True, default="")
    target_host = models.CharField(max_length=253, blank=True, default="")
    deployment_region = models.CharField(max_length=40, blank=True, default="")
    rule_id = models.PositiveBigIntegerField(null=True, blank=True)
    egress_id = models.PositiveBigIntegerField(null=True, blank=True)
    attempt = models.PositiveSmallIntegerField(default=1)
    outcome = models.CharField(max_length=24)
    error_code = models.CharField(max_length=80, blank=True, default="")
    latency_ms = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_egress_request_audit"
        indexes = [
            models.Index(
                fields=("target_host", "created_at"),
                name="dc_egress_audit_host_idx",
            ),
            models.Index(
                fields=("egress_id", "created_at"),
                name="dc_egress_audit_exit_idx",
            ),
        ]


__all__ = ["EgressRequestAuditModel", "EgressRoutingRuleModel"]
