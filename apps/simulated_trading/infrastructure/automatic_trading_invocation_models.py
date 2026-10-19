"""ORM storage for frozen, non-resumable simulated automatic invocations."""

from __future__ import annotations

from uuid import uuid4

from django.db import models
from django.db.models import Q


class AutomaticTradingInvocationModel(models.Model):
    """Persist one caller-owned automatic run identity and its terminal result."""

    STATE_READY = "ready"
    STATE_PREPARING = "preparing"
    STATE_STARTED = "started"
    STATE_FINISHED = "finished"
    STATE_CHOICES = [
        (STATE_READY, "Ready"),
        (STATE_PREPARING, "Preparing"),
        (STATE_STARTED, "Started"),
        (STATE_FINISHED, "Finished"),
    ]

    invocation_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    namespace = models.CharField(max_length=96)
    invocation_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    request_payload = models.JSONField()
    trade_date = models.DateField()
    account_ids = models.JSONField()
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_READY)
    claim_token = models.UUIDField(null=True, blank=True)
    outcome_payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "simulated_auto_trading_invocation"
        constraints = [
            models.UniqueConstraint(
                fields=("namespace", "invocation_key"),
                name="simautoinv_namespace_key_uq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        state="ready",
                        claim_token__isnull=True,
                        started_at__isnull=True,
                        finished_at__isnull=True,
                        outcome_payload__isnull=True,
                    )
                    | Q(
                        state="preparing",
                        claim_token__isnull=False,
                        started_at__isnull=True,
                        finished_at__isnull=True,
                        outcome_payload__isnull=True,
                    )
                    | Q(
                        state="started",
                        claim_token__isnull=False,
                        started_at__isnull=False,
                        finished_at__isnull=True,
                        outcome_payload__isnull=True,
                    )
                    | Q(
                        state="finished",
                        claim_token__isnull=False,
                        started_at__isnull=False,
                        finished_at__isnull=False,
                        outcome_payload__isnull=False,
                    )
                ),
                name="simautoinv_state_shape_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("state", "created_at"), name="simautoinv_state_ct_idx"),
        ]

    def __str__(self) -> str:
        """Show the invocation identity and lifecycle state for operators."""
        return f"{self.namespace}:{self.invocation_key} ({self.state})"
