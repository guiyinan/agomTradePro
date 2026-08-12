"""Append-only ORM schema for Signal-owned calibration sample evidence."""

from __future__ import annotations

from typing import NoReturn

from django.db import models
from django.db.models.signals import pre_delete

from apps.signal.infrastructure.forecast_realization_models import (
    ForecastRealizationAppendOnlyModel,
)


class ForecastCalibrationSampleDefinitionModel(ForecastRealizationAppendOnlyModel):
    """One outcome-free canonical calibration denominator definition."""

    definition_version = models.CharField(max_length=96)
    sample_id = models.CharField(max_length=128)
    sample_version = models.CharField(max_length=128)
    scope_content_hash = models.CharField(max_length=64)
    scenario_set_revision_id = models.UUIDField()
    scenario_revision_ids = models.JSONField()
    forecast_horizon_microseconds = models.BigIntegerField()
    censoring_rule_version = models.CharField(max_length=128)
    sample_window_start = models.DateTimeField(db_index=True)
    sample_window_end = models.DateTimeField(db_index=True)
    available_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    evidence_ref = models.CharField(max_length=512)
    source_content_hash = models.CharField(max_length=64)
    registered_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "signal"
        db_table = "signal_forecast_calibration_sample_definition"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["sample_id", "sample_version", "registered_at", "content_hash"]
        constraints = [
            models.UniqueConstraint(
                fields=["sample_id", "sample_version", "content_hash"],
                name="sig_cal_def_identity_hash_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(sample_window_start__lt=models.F("sample_window_end"))
                    & models.Q(sample_window_end__lte=models.F("available_at"))
                    & models.Q(available_at__lte=models.F("registered_at"))
                    & models.Q(registered_at__lt=models.F("valid_until"))
                ),
                name="sig_cal_def_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(research_only=True)
                    & models.Q(must_not_use_for_decision=True)
                    & models.Q(must_not_execute=True)
                ),
                name="sig_cal_def_safety_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(forecast_horizon_microseconds__gt=0),
                name="sig_cal_def_horizon_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=[
                    "scope_content_hash",
                    "sample_window_start",
                    "sample_window_end",
                    "available_at",
                ],
                name="sig_cal_def_exact_idx",
            )
        ]


class ForecastCalibrationExpectedMemberModel(ForecastRealizationAppendOnlyModel):
    """One expected Forecast Ledger member in a frozen denominator."""

    definition = models.ForeignKey(
        ForecastCalibrationSampleDefinitionModel,
        on_delete=models.PROTECT,
        related_name="expected_members",
    )
    source_version = models.CharField(max_length=96)
    entry_id = models.CharField(max_length=128)
    observation_version = models.CharField(max_length=128)
    forecast_group_id = models.CharField(max_length=128)
    scenario_revision_id = models.UUIDField()
    scenario_set_revision_id = models.UUIDField()
    subjective_probability = models.DecimalField(max_digits=18, decimal_places=12)
    subjective_probability_source_version = models.CharField(max_length=64)
    model_probability = models.DecimalField(max_digits=18, decimal_places=12, null=True, blank=True)
    model_probability_source_version = models.CharField(max_length=64, blank=True)
    model_promotion_decision_id = models.CharField(max_length=64, blank=True)
    pit_manifest_id = models.CharField(max_length=128)
    pit_manifest_version = models.CharField(max_length=128)
    pit_manifest_hash = models.CharField(max_length=64)
    censoring_rule_version = models.CharField(max_length=128)
    published_at = models.DateTimeField()
    horizon_end = models.DateTimeField(db_index=True)
    entry_recorded_at = models.DateTimeField()
    outcome_evidence_valid_until = models.DateTimeField()
    evidence_ref = models.CharField(max_length=512)
    content_hash = models.CharField(max_length=64)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "signal"
        db_table = "signal_forecast_calibration_expected_member"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["definition_id", "entry_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["definition", "entry_id"],
                name="sig_cal_member_entry_uq",
            ),
            models.UniqueConstraint(
                fields=["definition", "forecast_group_id", "scenario_revision_id"],
                name="sig_cal_member_group_scenario_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(published_at__lt=models.F("horizon_end"))
                    & models.Q(published_at__lte=models.F("entry_recorded_at"))
                    & models.Q(horizon_end__lt=models.F("outcome_evidence_valid_until"))
                ),
                name="sig_cal_member_clock_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["definition", "forecast_group_id"], name="sig_cal_member_group_idx"
            )
        ]


class ForecastCalibrationSampleReceiptModel(ForecastRealizationAppendOnlyModel):
    """One exhaustive PIT reread receipt for a canonical definition."""

    definition = models.ForeignKey(
        ForecastCalibrationSampleDefinitionModel,
        on_delete=models.PROTECT,
        related_name="receipts",
    )
    receipt_version = models.CharField(max_length=96)
    receipt_id = models.CharField(max_length=64, db_index=True)
    pit_as_of = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "signal"
        db_table = "signal_forecast_calibration_sample_receipt"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["definition_id", "pit_as_of", "recorded_at", "content_hash"]
        constraints = [
            models.UniqueConstraint(
                fields=["definition", "pit_as_of", "content_hash"],
                name="sig_cal_receipt_identity_hash_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(pit_as_of__lte=models.F("recorded_at")),
                name="sig_cal_receipt_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(research_only=True)
                    & models.Q(must_not_use_for_decision=True)
                    & models.Q(must_not_execute=True)
                ),
                name="sig_cal_receipt_safety_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["definition", "pit_as_of", "recorded_at"],
                name="sig_cal_receipt_pit_idx",
            )
        ]


class ForecastCalibrationSampleMemberReceiptModel(ForecastRealizationAppendOnlyModel):
    """One explicit resolved/unresolved/censored/invalidated receipt member."""

    receipt = models.ForeignKey(
        ForecastCalibrationSampleReceiptModel,
        on_delete=models.PROTECT,
        related_name="member_receipts",
    )
    expected_member = models.ForeignKey(
        ForecastCalibrationExpectedMemberModel,
        on_delete=models.PROTECT,
        related_name="receipt_members",
    )
    receipt_version = models.CharField(max_length=96)
    entry_id = models.CharField(max_length=128)
    expected_member_hash = models.CharField(max_length=64)
    owner_record_version = models.CharField(max_length=96)
    owner_record_hash = models.CharField(max_length=64)
    scenario_revision_id = models.UUIDField()
    scenario_set_revision_id = models.UUIDField()
    pit_manifest_id = models.CharField(max_length=128)
    published_at = models.DateTimeField()
    horizon_end = models.DateTimeField()
    entry_recorded_at = models.DateTimeField()
    resolution = models.CharField(max_length=16)
    scenario_realized = models.BooleanField(null=True, blank=True)
    outcome_recorded_at = models.DateTimeField(null=True, blank=True)
    outcome_source_type = models.CharField(max_length=128, blank=True)
    outcome_source_hash = models.CharField(max_length=64, blank=True)
    invalidation_payload = models.JSONField(null=True, blank=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)
    invalidation_rule_version = models.CharField(max_length=128, blank=True)
    invalidation_content_hash = models.CharField(max_length=64, blank=True)
    recorded_at = models.DateTimeField()
    content_hash = models.CharField(max_length=64)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "signal"
        db_table = "signal_forecast_calibration_sample_member_receipt"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["receipt_id", "entry_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["receipt", "entry_id"],
                name="sig_cal_rcpt_member_entry_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(published_at__lt=models.F("horizon_end"))
                    & models.Q(published_at__lte=models.F("entry_recorded_at"))
                    & models.Q(entry_recorded_at__lte=models.F("recorded_at"))
                    & (
                        models.Q(outcome_recorded_at__isnull=True)
                        | models.Q(horizon_end__lte=models.F("outcome_recorded_at"))
                        | models.Q(resolution="invalidated")
                    )
                ),
                name="sig_cal_rcpt_member_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(resolution="resolved")
                        & models.Q(scenario_realized__isnull=False)
                        & models.Q(outcome_recorded_at__isnull=False)
                        & ~models.Q(outcome_source_type="")
                        & ~models.Q(outcome_source_hash="")
                        & models.Q(invalidation_payload__isnull=True)
                    )
                    | (
                        models.Q(resolution="unresolved")
                        & models.Q(scenario_realized__isnull=True)
                        & models.Q(outcome_recorded_at__isnull=True)
                        & models.Q(outcome_source_type="")
                        & models.Q(outcome_source_hash="")
                        & models.Q(invalidation_payload__isnull=True)
                    )
                    | (
                        models.Q(resolution="censored")
                        & models.Q(scenario_realized__isnull=True)
                        & models.Q(outcome_recorded_at__isnull=False)
                        & ~models.Q(outcome_source_type="")
                        & ~models.Q(outcome_source_hash="")
                        & models.Q(invalidation_payload__isnull=True)
                    )
                    | (
                        models.Q(resolution="invalidated")
                        & models.Q(scenario_realized__isnull=True)
                        & models.Q(outcome_recorded_at__isnull=False)
                        & ~models.Q(outcome_source_type="")
                        & ~models.Q(outcome_source_hash="")
                        & models.Q(invalidation_payload__isnull=False)
                        & models.Q(invalidated_at__isnull=False)
                        & ~models.Q(invalidation_rule_version="")
                        & ~models.Q(invalidation_content_hash="")
                    )
                ),
                name="sig_cal_rcpt_member_state_ck",
            ),
        ]
        indexes = [models.Index(fields=["receipt", "resolution"], name="sig_cal_rcpt_state_idx")]


def _reject_calibration_delete(**kwargs: object) -> NoReturn:
    raise ValueError("forecast calibration evidence cannot be deleted")


for _model in (
    ForecastCalibrationSampleDefinitionModel,
    ForecastCalibrationExpectedMemberModel,
    ForecastCalibrationSampleReceiptModel,
    ForecastCalibrationSampleMemberReceiptModel,
):
    pre_delete.connect(
        _reject_calibration_delete,
        sender=_model,
        dispatch_uid=f"signal.forecast_calibration.reject_delete.{_model.__name__}",
    )


__all__ = [
    "ForecastCalibrationExpectedMemberModel",
    "ForecastCalibrationSampleDefinitionModel",
    "ForecastCalibrationSampleMemberReceiptModel",
    "ForecastCalibrationSampleReceiptModel",
]
