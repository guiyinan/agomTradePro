"""Append-only ORM projections for the Research-owned R7 analogy/path graph."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.research.infrastructure.r5_relative_value_monitoring_models import (
    R5MonitoringAppendOnlyModel,
)


class R7HistoricalAnalogyDefinitionModel(R5MonitoringAppendOnlyModel):
    """One immutable historical-analogy owner definition."""

    definition_id = models.CharField(max_length=300)
    definition_version = models.CharField(max_length=128)
    definition_hash = models.CharField(max_length=64, unique=True)
    scope_hash = models.CharField(max_length=64, db_index=True)
    study_version = models.CharField(max_length=128)
    feature_definition_version = models.CharField(max_length=128)
    similarity_method_version = models.CharField(max_length=128)
    activated_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    definition_payload = models.JSONField()
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta(R5MonitoringAppendOnlyModel.Meta):
        db_table = "research_r7_analogy_definition"
        indexes = [
            models.Index(
                fields=("scope_hash", "ledger_recorded_at"),
                name="res_r7_an_def_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("definition_id", "definition_version"),
                name="res_r7_an_def_id_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(activated_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("valid_until"))
                ),
                name="res_r7_an_def_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r7_an_def_safe_ck",
            ),
        ]


class R7HistoricalAnalogyReceiptModel(R5MonitoringAppendOnlyModel):
    """One complete immutable analogy raw-source receipt."""

    definition = models.ForeignKey(
        R7HistoricalAnalogyDefinitionModel,
        on_delete=models.PROTECT,
        related_name="receipts",
    )
    receipt_id = models.CharField(max_length=300)
    receipt_version = models.CharField(max_length=128)
    receipt_hash = models.CharField(max_length=64, unique=True)
    scope_hash = models.CharField(max_length=64, db_index=True)
    query_manifest_id = models.CharField(max_length=300)
    query_manifest_version = models.CharField(max_length=128)
    query_manifest_hash = models.CharField(max_length=64)
    query_manifest_reference_hash = models.CharField(max_length=64)
    query_as_of = models.DateTimeField()
    source_available_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    definition_valid_until = models.DateTimeField()
    receipt_payload = models.JSONField()
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta(R5MonitoringAppendOnlyModel.Meta):
        db_table = "research_r7_analogy_receipt"
        indexes = [
            models.Index(
                fields=("scope_hash", "query_as_of", "recorded_at"),
                name="res_r7_an_rcpt_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("receipt_id", "receipt_version"),
                name="res_r7_an_rcpt_id_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(query_as_of__lte=models.F("source_available_at"))
                    & models.Q(source_available_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("definition_valid_until"))
                ),
                name="res_r7_an_rcpt_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    receipt_version="r7-analogy-receipt.v1",
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r7_an_rcpt_safe_ck",
            ),
        ]


class R7HistoricalAnalogyCandidateModel(R5MonitoringAppendOnlyModel):
    """One immutable normalized candidate projection under an analogy receipt."""

    receipt = models.ForeignKey(
        R7HistoricalAnalogyReceiptModel,
        on_delete=models.PROTECT,
        related_name="candidates",
    )
    candidate_id = models.CharField(max_length=300)
    candidate_version = models.CharField(max_length=128)
    candidate_hash = models.CharField(max_length=64)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    decision_cutoff = models.DateTimeField()
    manifest_id = models.CharField(max_length=300)
    manifest_version = models.CharField(max_length=128)
    manifest_hash = models.CharField(max_length=64)
    manifest_reference_hash = models.CharField(max_length=64)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    candidate_payload = models.JSONField()
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta(R5MonitoringAppendOnlyModel.Meta):
        db_table = "research_r7_analogy_candidate"
        indexes = [
            models.Index(
                fields=("candidate_id", "decision_cutoff"),
                name="res_r7_an_cand_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("receipt", "candidate_id", "candidate_version"),
                name="res_r7_an_cand_id_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(window_start__lt=models.F("window_end"))
                    & models.Q(window_end__lte=models.F("decision_cutoff"))
                    & models.Q(decision_cutoff__lte=models.F("ledger_recorded_at"))
                ),
                name="res_r7_an_cand_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r7_an_cand_safe_ck",
            ),
        ]


class R7ScenarioPathDefinitionModel(R5MonitoringAppendOnlyModel):
    """One immutable path expected-membership and shock definition."""

    definition_id = models.CharField(max_length=300)
    definition_version = models.CharField(max_length=128)
    definition_hash = models.CharField(max_length=64, unique=True)
    scope_hash = models.CharField(max_length=64, db_index=True)
    study_version = models.CharField(max_length=128)
    source_version = models.CharField(max_length=128)
    sample_definition_version = models.CharField(max_length=128)
    activated_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    definition_payload = models.JSONField()
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta(R5MonitoringAppendOnlyModel.Meta):
        db_table = "research_r7_path_definition"
        indexes = [
            models.Index(
                fields=("scope_hash", "ledger_recorded_at"),
                name="res_r7_path_def_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("definition_id", "definition_version"),
                name="res_r7_path_def_id_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(activated_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("valid_until"))
                ),
                name="res_r7_path_def_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r7_path_def_safe_ck",
            ),
        ]


class R7ScenarioPathReceiptModel(R5MonitoringAppendOnlyModel):
    """One complete immutable path raw-source receipt."""

    definition = models.ForeignKey(
        R7ScenarioPathDefinitionModel,
        on_delete=models.PROTECT,
        related_name="receipts",
    )
    receipt_id = models.CharField(max_length=300)
    receipt_version = models.CharField(max_length=128)
    receipt_hash = models.CharField(max_length=64, unique=True)
    scope_hash = models.CharField(max_length=64, db_index=True)
    pit_manifest_id = models.CharField(max_length=300)
    pit_manifest_version = models.CharField(max_length=128)
    pit_manifest_hash = models.CharField(max_length=64)
    pit_manifest_reference_hash = models.CharField(max_length=64)
    pit_as_of = models.DateTimeField()
    source_available_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    definition_valid_until = models.DateTimeField()
    receipt_payload = models.JSONField()
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta(R5MonitoringAppendOnlyModel.Meta):
        db_table = "research_r7_path_receipt"
        indexes = [
            models.Index(
                fields=("scope_hash", "pit_as_of", "recorded_at"),
                name="res_r7_path_rcpt_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("receipt_id", "receipt_version"),
                name="res_r7_path_rcpt_id_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(pit_as_of__lte=models.F("source_available_at"))
                    & models.Q(source_available_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("definition_valid_until"))
                ),
                name="res_r7_path_rcpt_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    receipt_version="r7-path-receipt.v1",
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r7_path_rcpt_safe_ck",
            ),
        ]


class R7ScenarioPathMemberModel(R5MonitoringAppendOnlyModel):
    """One immutable normalized sample or shock member under a path receipt."""

    receipt = models.ForeignKey(
        R7ScenarioPathReceiptModel,
        on_delete=models.PROTECT,
        related_name="members",
    )
    member_kind = models.CharField(max_length=16)
    member_key = models.CharField(max_length=420)
    member_version = models.CharField(max_length=128)
    member_hash = models.CharField(max_length=64)
    period_index = models.PositiveIntegerField()
    resolution = models.CharField(max_length=16, blank=True)
    from_scenario_revision_id = models.UUIDField(null=True, blank=True)
    to_scenario_revision_id = models.UUIDField(null=True, blank=True)
    observed_at = models.DateTimeField(null=True, blank=True)
    source_available_at = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    member_payload = models.JSONField()
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta(R5MonitoringAppendOnlyModel.Meta):
        db_table = "research_r7_path_member"
        indexes = [
            models.Index(
                fields=("member_kind", "period_index", "ledger_recorded_at"),
                name="res_r7_path_mem_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("receipt", "member_kind", "member_key"),
                name="res_r7_path_mem_id_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(member_kind__in=("sample", "shock")),
                name="res_r7_path_mem_kind_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(source_available_at__lte=models.F("ledger_recorded_at"))
                    & (
                        models.Q(observed_at__isnull=True)
                        | models.Q(observed_at__lte=models.F("source_available_at"))
                    )
                ),
                name="res_r7_path_mem_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        member_kind="sample",
                        resolution="resolved",
                        to_scenario_revision_id__isnull=False,
                        observed_at__isnull=False,
                    )
                    | models.Q(
                        member_kind="sample",
                        resolution__in=("unresolved", "censored", "invalidated"),
                        to_scenario_revision_id__isnull=True,
                        observed_at__isnull=True,
                    )
                    | models.Q(
                        member_kind="shock",
                        resolution="",
                        from_scenario_revision_id__isnull=True,
                        to_scenario_revision_id__isnull=True,
                        observed_at__isnull=True,
                    )
                ),
                name="res_r7_path_mem_state_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r7_path_mem_safe_ck",
            ),
        ]


@receiver(
    pre_delete,
    sender=R7HistoricalAnalogyDefinitionModel,
    dispatch_uid="reject_research_r7_analogy_definition_delete",
    weak=False,
)
@receiver(
    pre_delete,
    sender=R7HistoricalAnalogyReceiptModel,
    dispatch_uid="reject_research_r7_analogy_receipt_delete",
    weak=False,
)
@receiver(
    pre_delete,
    sender=R7HistoricalAnalogyCandidateModel,
    dispatch_uid="reject_research_r7_analogy_candidate_delete",
    weak=False,
)
@receiver(
    pre_delete,
    sender=R7ScenarioPathDefinitionModel,
    dispatch_uid="reject_research_r7_path_definition_delete",
    weak=False,
)
@receiver(
    pre_delete,
    sender=R7ScenarioPathReceiptModel,
    dispatch_uid="reject_research_r7_path_receipt_delete",
    weak=False,
)
@receiver(
    pre_delete,
    sender=R7ScenarioPathMemberModel,
    dispatch_uid="reject_research_r7_path_member_delete",
    weak=False,
)
def _reject_r7_analogy_path_owner_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("R7 analogy/path owner evidence cannot be deleted.")


__all__ = [
    "R7HistoricalAnalogyCandidateModel",
    "R7HistoricalAnalogyDefinitionModel",
    "R7HistoricalAnalogyReceiptModel",
    "R7ScenarioPathDefinitionModel",
    "R7ScenarioPathMemberModel",
    "R7ScenarioPathReceiptModel",
]
