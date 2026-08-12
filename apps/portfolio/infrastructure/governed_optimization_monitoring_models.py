"""Append-only ledgers for governed optimization monitoring evidence."""

from __future__ import annotations

from typing import NoReturn

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.portfolio.infrastructure.optimization_research_models import (
    GovernedOptimizationInputReceiptModel,
    GovernedOptimizationResearchResultModel,
    OptimizationAppendOnlyModel,
)


class GovernedOptimizationMonitoringObservationModel(OptimizationAppendOnlyModel):
    """One immutable canonical monitoring-period observation graph."""

    result = models.ForeignKey(
        GovernedOptimizationResearchResultModel,
        on_delete=models.PROTECT,
        related_name="monitoring_observation_ledgers",
    )
    input_receipt = models.ForeignKey(
        GovernedOptimizationInputReceiptModel,
        on_delete=models.PROTECT,
        related_name="monitoring_observation_ledgers",
    )
    assessment_id = models.CharField(max_length=192)
    observation_id = models.CharField(max_length=192)
    observation_version = models.CharField(max_length=192)
    result_hash = models.CharField(max_length=64)
    receipt_hash = models.CharField(max_length=64)
    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    policy_hash = models.CharField(max_length=64)
    calendar_id = models.CharField(max_length=192)
    calendar_version = models.CharField(max_length=192)
    calendar_hash = models.CharField(max_length=64)
    period_id = models.CharField(max_length=192)
    period_start_at = models.DateTimeField()
    period_end_at = models.DateTimeField()
    latest_owner_available_at = models.DateTimeField()
    portfolio_evidence_payload = models.JSONField()
    broker_evidence_payload = models.JSONField()
    canonical_payload = models.JSONField()
    domain_observation_hash = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_header_hash = models.CharField(max_length=64)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(OptimizationAppendOnlyModel.Meta):
        db_table = "portfolio_governed_optimization_monitoring_observation"
        indexes = [
            models.Index(
                fields=["result", "policy_hash", "ledger_recorded_at"],
                name="pf_opt_mon_obs_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment_id", "period_id"],
                name="pf_opt_mon_obs_period_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(period_start_at__lt=models.F("period_end_at"))
                    & models.Q(period_end_at__lte=models.F("latest_owner_available_at"))
                    & models.Q(latest_owner_available_at__lte=models.F("ledger_recorded_at"))
                ),
                name="pf_opt_mon_obs_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="pf_opt_mon_obs_safe_ck",
            ),
        ]


class GovernedOptimizationMonitoringAssessmentModel(OptimizationAppendOnlyModel):
    """One immutable full monitoring owner graph and derived assessment."""

    assessment_id = models.CharField(max_length=192, primary_key=True)
    assessment_version = models.CharField(max_length=192)
    result = models.ForeignKey(
        GovernedOptimizationResearchResultModel,
        on_delete=models.PROTECT,
        related_name="monitoring_assessment_ledgers",
    )
    input_receipt = models.ForeignKey(
        GovernedOptimizationInputReceiptModel,
        on_delete=models.PROTECT,
        related_name="monitoring_assessment_ledgers",
    )
    result_hash = models.CharField(max_length=64)
    receipt_hash = models.CharField(max_length=64)
    promotion_event_id = models.CharField(max_length=192)
    promotion_event_hash = models.CharField(max_length=64)
    requested_policy_id = models.CharField(max_length=192)
    requested_policy_version = models.CharField(max_length=192)
    expected_policy_hash = models.CharField(max_length=64)
    calendar_id = models.CharField(max_length=192)
    calendar_version = models.CharField(max_length=192)
    calendar_hash = models.CharField(max_length=64)
    evaluated_at = models.DateTimeField()
    latest_owner_available_at = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_header_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=48)
    observation_count = models.PositiveIntegerField()
    observation_hashes = models.JSONField()
    upstream_promotions_payload = models.JSONField()
    policy_payload = models.JSONField()
    calendar_payload = models.JSONField()
    assessment_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    automatic_retirement = models.BooleanField(default=False)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(OptimizationAppendOnlyModel.Meta):
        db_table = "portfolio_governed_optimization_monitoring_assessment"
        indexes = [
            models.Index(
                fields=["result", "expected_policy_hash", "ledger_recorded_at"],
                name="pf_opt_mon_asmt_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "requested_policy_id",
                    "requested_policy_version",
                    "expected_policy_hash",
                    "evaluated_at",
                ],
                name="pf_opt_mon_asmt_cmd_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(latest_owner_available_at__lte=models.F("evaluated_at"))
                    & models.Q(evaluated_at__lte=models.F("ledger_recorded_at"))
                ),
                name="pf_opt_mon_asmt_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "healthy",
                        "breached",
                        "retirement_review_required",
                        "blocked",
                    )
                ),
                name="pf_opt_mon_asmt_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    automatic_retirement=False,
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="pf_opt_mon_asmt_safe_ck",
            ),
        ]


class GovernedOptimizationMonitoringAuditSnapshotModel(OptimizationAppendOnlyModel):
    """Immutable manifest backing signed internal-audit cursors."""

    snapshot_id = models.CharField(max_length=192)
    snapshot_version = models.CharField(max_length=192)
    as_of = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(db_index=True)
    entry_count = models.PositiveIntegerField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64)
    internal_audit_only = models.BooleanField(default=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(OptimizationAppendOnlyModel.Meta):
        db_table = "portfolio_governed_optimization_monitoring_audit_snapshot"
        indexes = [
            models.Index(
                fields=["as_of", "created_at"],
                name="pf_opt_mon_snap_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot_id", "snapshot_version"],
                name="pf_opt_mon_snap_ident_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(as_of__lte=models.F("created_at")),
                name="pf_opt_mon_snap_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    internal_audit_only=True,
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="pf_opt_mon_snap_safe_ck",
            ),
        ]


@receiver(
    pre_delete,
    sender=GovernedOptimizationMonitoringObservationModel,
    weak=False,
)
@receiver(
    pre_delete,
    sender=GovernedOptimizationMonitoringAssessmentModel,
    weak=False,
)
@receiver(
    pre_delete,
    sender=GovernedOptimizationMonitoringAuditSnapshotModel,
    weak=False,
)
def _reject_governed_optimization_monitoring_collector_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject Collector, cascade, and direct signal-aware deletion."""

    raise ValidationError("Governed optimization monitoring evidence cannot be deleted.")


__all__ = [
    "GovernedOptimizationMonitoringAssessmentModel",
    "GovernedOptimizationMonitoringAuditSnapshotModel",
    "GovernedOptimizationMonitoringObservationModel",
]
