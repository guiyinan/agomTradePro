"""ORM persistence for append-only R3 macro-factor research results."""

from __future__ import annotations

import json
from typing import Any, NoReturn

from django.core.exceptions import ValidationError
from django.db import models

from apps.macro_factor.domain.entities import (
    FactorLifecycleStatus,
    ImmutableMacroFactorResearchRecord,
)

from .append_only import MacroFactorAppendOnlyManager


class MacroFactorResearchResultModel(models.Model):
    """Immutable external result that can never authorize a decision."""

    objects = MacroFactorAppendOnlyManager()

    result_id = models.CharField(max_length=160, primary_key=True)
    factor_version = models.CharField(max_length=160, unique=True)
    target_code = models.CharField(max_length=160, db_index=True)
    evidence_produced_at = models.DateTimeField(db_index=True)
    pit_manifest_id = models.CharField(max_length=160, db_index=True)
    pit_manifest_hash = models.CharField(max_length=64)
    code_version = models.CharField(max_length=160)
    parameter_version = models.CharField(max_length=160)
    external_evidence_id = models.CharField(max_length=160, db_index=True)
    lifecycle_status = models.CharField(
        max_length=24,
        choices=[(status.value, status.value) for status in FactorLifecycleStatus],
        db_index=True,
    )
    content_hash = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()
    research_only = models.BooleanField(default=True, editable=False)
    must_not_use_for_decision = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "macro_factor_research_result"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=["target_code", "-evidence_produced_at"],
                name="macro_factor_target_time_idx",
            ),
            models.Index(
                fields=["pit_manifest_id", "lifecycle_status"],
                name="macro_factor_manifest_life_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(research_only=True),
                name="macro_factor_result_research_only",
            ),
            models.CheckConstraint(
                condition=models.Q(must_not_use_for_decision=True),
                name="macro_factor_result_decision_blocked",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Insert once and reject any mutation of research evidence."""

        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("MacroFactorResearchResultModel is immutable")
        if not self.research_only or not self.must_not_use_for_decision:
            raise ValidationError("macro-factor results must remain decision-blocked")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        """Reject deletion of append-only R3 evidence."""

        raise ValidationError("MacroFactorResearchResultModel cannot be deleted")

    def to_domain(self) -> ImmutableMacroFactorResearchRecord:
        """Map the persisted JSON payload back to an immutable storage record."""

        return ImmutableMacroFactorResearchRecord(
            result_id=self.result_id,
            factor_version=self.factor_version,
            target_code=self.target_code,
            evidence_produced_at=self.evidence_produced_at,
            pit_manifest_id=self.pit_manifest_id,
            pit_manifest_hash=self.pit_manifest_hash,
            code_version=self.code_version,
            parameter_version=self.parameter_version,
            external_evidence_id=self.external_evidence_id,
            lifecycle_status=FactorLifecycleStatus(self.lifecycle_status),
            payload_json=json.dumps(self.payload, sort_keys=True, separators=(",", ":")),
            content_hash=self.content_hash,
            research_only=self.research_only,
            must_not_use_for_decision=self.must_not_use_for_decision,
        )


__all__ = ["MacroFactorResearchResultModel"]
