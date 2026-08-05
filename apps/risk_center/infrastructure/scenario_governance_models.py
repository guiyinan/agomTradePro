"""Django models for persistent stress-scenario write governance."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.utils import timezone

ACTOR_KIND_CHOICES = [
    ("human", "Human"),
    ("ai", "AI"),
    ("service", "Service"),
]
OPERATION_CHOICES = [
    ("propose", "Propose"),
    ("activate", "Activate"),
    ("rollback", "Rollback"),
    ("retire", "Retire"),
]


class ScenarioGovernancePreviewModel(models.Model):
    """Durable actor-bound preview consumed by at most one committed write."""

    preview_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_id = models.CharField(max_length=150)
    actor_kind = models.CharField(max_length=16, choices=ACTOR_KIND_CHOICES)
    capability_key = models.CharField(max_length=160)
    operation = models.CharField(max_length=16, choices=OPERATION_CHOICES)
    scenario_key = models.CharField(max_length=120, null=True, blank=True)
    exact_payload = models.JSONField(default=dict)
    request_fingerprint = models.CharField(max_length=64)
    base_version = models.PositiveIntegerField(null=True, blank=True)
    base_hash = models.CharField(max_length=64, null=True, blank=True)
    after_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    consumed_idempotency_key = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_scenario_governance_preview"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["actor_id", "capability_key", "-created_at"],
                name="risk_scn_gov_prev_actor",
            ),
            models.Index(
                fields=["operation", "expires_at"],
                name="risk_scn_gov_prev_expiry",
            ),
        ]

    def clean(self) -> None:
        """Reject malformed lifecycle and digest evidence."""

        super().clean()
        for field_name in ("request_fingerprint", "after_hash"):
            _validate_sha256(field_name, str(getattr(self, field_name)))
        if self.base_hash:
            _validate_sha256("base_hash", self.base_hash)
        if self.expires_at <= self.created_at:
            raise ValidationError({"expires_at": "Expiry must be after preview creation."})
        if self.consumed_at is None and self.consumed_idempotency_key:
            raise ValidationError(
                {"consumed_idempotency_key": "Unconsumed previews cannot bind an idempotency key."}
            )
        if self.consumed_at is not None and not self.consumed_idempotency_key:
            raise ValidationError(
                {"consumed_idempotency_key": "Consumed previews require an idempotency key."}
            )


class ScenarioGovernanceIdempotencyModel(models.Model):
    """Persistent terminal result scoped by actor, capability, and idempotency key."""

    record_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_id = models.CharField(max_length=150)
    capability_key = models.CharField(max_length=160)
    idempotency_key = models.CharField(max_length=255)
    operation = models.CharField(max_length=16, choices=OPERATION_CHOICES)
    request_fingerprint = models.CharField(max_length=64)
    preview = models.ForeignKey(
        "risk_center.ScenarioGovernancePreviewModel",
        on_delete=models.PROTECT,
        related_name="idempotency_results",
    )
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_scenario_governance_idempotency"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["actor_id", "capability_key", "idempotency_key"],
                name="risk_scn_gov_idem_uq",
            )
        ]
        indexes = [
            models.Index(
                fields=["actor_id", "capability_key", "-created_at"],
                name="risk_scn_gov_idem_actor",
            )
        ]

    def clean(self) -> None:
        """Require a canonical request fingerprint and non-empty result."""

        super().clean()
        _validate_sha256("request_fingerprint", self.request_fingerprint)
        if not self.result:
            raise ValidationError({"result": "Idempotency records require a terminal result."})


class ScenarioGovernanceProposalLinkModel(models.Model):
    """Risk Center lifecycle binding for one persistent AgentProposal row."""

    STATUS_CHOICES = [
        ("submitted", "Submitted"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("executed", "Executed"),
    ]

    proposal_id = models.PositiveBigIntegerField(primary_key=True)
    preview = models.OneToOneField(
        "risk_center.ScenarioGovernancePreviewModel",
        on_delete=models.PROTECT,
        related_name="proposal_link",
    )
    operation = models.CharField(max_length=16, choices=OPERATION_CHOICES)
    creator_actor_id = models.CharField(max_length=150)
    creator_actor_kind = models.CharField(max_length=16, choices=ACTOR_KIND_CHOICES)
    capability_key = models.CharField(max_length=160)
    request_fingerprint = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default="submitted",
        db_index=True,
    )
    scenario_key = models.CharField(max_length=120, null=True, blank=True)
    revision = models.ForeignKey(
        "risk_center.StressScenarioRevisionModel",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="governance_proposals",
    )
    scenario_set_revision = models.ForeignKey(
        "risk_center.ScenarioSetRevisionModel",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="governance_proposals",
    )
    target_version = models.PositiveIntegerField(null=True, blank=True)
    approved_by_actor_id = models.CharField(max_length=150, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by_actor_id = models.CharField(max_length=150, null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_scenario_governance_proposal"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["operation", "status", "-created_at"],
                name="risk_scn_gov_prop_state",
            ),
            models.Index(
                fields=["creator_actor_id", "-created_at"],
                name="risk_scn_gov_prop_actor",
            ),
        ]

    def clean(self) -> None:
        """Keep local approval evidence consistent with lifecycle status."""

        super().clean()
        _validate_sha256("request_fingerprint", self.request_fingerprint)
        if self.status in {"approved", "executed"} and (
            not self.approved_by_actor_id or self.approved_at is None
        ):
            raise ValidationError("Approved proposal links require approver evidence.")
        if self.status == "rejected" and (
            not self.rejected_by_actor_id or self.rejected_at is None
        ):
            raise ValidationError("Rejected proposal links require reviewer evidence.")
        if self.status == "executed" and self.executed_at is None:
            raise ValidationError("Executed proposal links require executed_at.")


class ImmutableScenarioGovernanceAuditMixin(models.Model):
    """Reject updates and deletes of canonical governance audit evidence."""

    class Meta:
        abstract = True

    def save(
        self,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Allow inserts only."""

        if not self._state.adding:
            raise ValidationError("Scenario governance audit records are immutable.")
        self.full_clean()
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Scenario governance audit records cannot be deleted.")


class ScenarioGovernanceAuditModel(ImmutableScenarioGovernanceAuditMixin):
    """Append-only canonical audit written with the governed business change."""

    audit_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operation = models.CharField(max_length=40, db_index=True)
    actor_id = models.CharField(max_length=150, db_index=True)
    actor_kind = models.CharField(max_length=16, choices=ACTOR_KIND_CHOICES)
    approver_actor_id = models.CharField(max_length=150, null=True, blank=True)
    capability_key = models.CharField(max_length=160, db_index=True)
    request_fingerprint = models.CharField(max_length=64)
    correlation_id = models.CharField(max_length=120, db_index=True)
    scenario_key = models.CharField(max_length=120, null=True, blank=True)
    proposal_id = models.PositiveBigIntegerField(null=True, blank=True)
    preview_id = models.UUIDField(null=True, blank=True)
    revision_id = models.UUIDField(null=True, blank=True)
    scenario_set_revision_id = models.UUIDField(null=True, blank=True)
    activation_id = models.UUIDField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)
    base_version = models.PositiveIntegerField(null=True, blank=True)
    before_hash = models.CharField(max_length=64, null=True, blank=True)
    after_hash = models.CharField(max_length=64, null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_scenario_governance_audit"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["scenario_key", "-created_at"],
                name="risk_scn_gov_audit_scn",
            ),
            models.Index(
                fields=["proposal_id", "-created_at"],
                name="risk_scn_gov_audit_prop",
            ),
        ]

    def clean(self) -> None:
        """Validate digest evidence before immutable insertion."""

        super().clean()
        _validate_sha256("request_fingerprint", self.request_fingerprint)
        for field_name in ("before_hash", "after_hash"):
            value = getattr(self, field_name)
            if value:
                _validate_sha256(field_name, str(value))


def _validate_sha256(field_name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValidationError({field_name: "A lower-case SHA-256 digest is required."})


__all__ = [
    "ScenarioGovernanceAuditModel",
    "ScenarioGovernanceIdempotencyModel",
    "ScenarioGovernancePreviewModel",
    "ScenarioGovernanceProposalLinkModel",
]
