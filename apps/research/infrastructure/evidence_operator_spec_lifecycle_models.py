"""Append-only approval and activation ledgers for Evidence operator specs."""

from __future__ import annotations

from django.db import models

from apps.research.infrastructure.evidence_models import EvidenceAppendOnlyModel


class EvidenceOperatorSpecApprovalReceiptModel(EvidenceAppendOnlyModel):
    """Research's immutable copy of one external-owner approval receipt."""

    approval_id = models.CharField(max_length=192)
    approval_version = models.CharField(max_length=192)
    owner_record_id = models.CharField(max_length=192)
    owner_record_version = models.CharField(max_length=192)
    owner_record_hash = models.CharField(max_length=64)
    operator_id = models.CharField(max_length=192)
    operator_version = models.CharField(max_length=192)
    definition_hash = models.CharField(max_length=64)
    supersedes_activation_hash = models.CharField(max_length=64, null=True)
    approved_by = models.CharField(max_length=192)
    issued_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    receipt_content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(EvidenceAppendOnlyModel.Meta):
        db_table = "research_evidence_operator_spec_approval"
        constraints = [
            models.UniqueConstraint(
                fields=("approval_id", "approval_version"),
                name="res_ev_op_auth_identity_uq",
            ),
            models.UniqueConstraint(
                fields=("owner_record_id", "owner_record_version"),
                name="res_ev_op_auth_owner_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(issued_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="res_ev_op_auth_clock_ck",
            ),
        ]


class ActivatedEvidenceOperatorSpecModel(EvidenceAppendOnlyModel):
    """One immutable, externally approved operator spec activation version."""

    approval = models.OneToOneField(
        EvidenceOperatorSpecApprovalReceiptModel,
        on_delete=models.PROTECT,
        related_name="activated_operator_spec",
    )
    operator_id = models.CharField(max_length=192)
    operator_version = models.CharField(max_length=192)
    research_family = models.CharField(max_length=192, db_index=True)
    output_artifact_type = models.CharField(max_length=192)
    claim_kind = models.CharField(max_length=32)
    method_kind = models.CharField(max_length=32)
    definition_hash = models.CharField(max_length=64, unique=True)
    supersedes_activation_hash = models.CharField(max_length=64, null=True, db_index=True)
    activated_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(EvidenceAppendOnlyModel.Meta):
        db_table = "research_activated_evidence_operator_spec"
        indexes = [
            models.Index(
                fields=("operator_id", "recorded_at"),
                name="res_ev_op_active_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("operator_id", "operator_version"),
                name="res_ev_op_active_identity_uq",
            ),
            models.UniqueConstraint(
                fields=("operator_id",),
                condition=models.Q(supersedes_activation_hash__isnull=True),
                name="res_ev_op_active_root_uq",
            ),
            models.UniqueConstraint(
                fields=("supersedes_activation_hash",),
                condition=models.Q(supersedes_activation_hash__isnull=False),
                name="res_ev_op_active_child_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(activated_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="res_ev_op_active_clock_ck",
            ),
        ]


__all__ = [
    "ActivatedEvidenceOperatorSpecModel",
    "EvidenceOperatorSpecApprovalReceiptModel",
]
