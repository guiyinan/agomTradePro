"""ORM persistence for immutable fixed-income research evidence."""

from __future__ import annotations

import json
from typing import Any, NoReturn

from django.core.exceptions import ValidationError
from django.db import models

from apps.fixed_income.domain.entities import (
    ImmutableResearchResult,
    PublicationInputSeal,
    ResearchPreviewStatus,
)


class FixedIncomeResearchResultModel(models.Model):
    """Append-only, non-executable result from one version-bound R5 calculation."""

    result_id = models.CharField(max_length=64, primary_key=True)
    bond_id = models.CharField(max_length=64, db_index=True)
    valuation_at = models.DateTimeField(db_index=True)
    settlement_date = models.DateField()
    method_version = models.CharField(max_length=64, db_index=True)
    input_hash = models.CharField(max_length=64, db_index=True)
    output_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=[(status.value, status.value) for status in ResearchPreviewStatus],
    )
    payload = models.JSONField()
    publication_ids = models.JSONField()
    publication_evidence = models.JSONField()
    blocked_reasons = models.JSONField(blank=True)
    research_only = models.BooleanField(default=True, editable=False)
    must_not_execute = models.BooleanField(default=True, editable=False)
    must_not_use_for_decision = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fixed_income_research_result"
        indexes = [
            models.Index(
                fields=["bond_id", "-valuation_at"],
                name="fixed_income_bond_val_idx",
            ),
            models.Index(
                fields=["method_version", "status"],
                name="fixed_income_method_stat_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(research_only=True),
                name="fixed_income_result_research_only",
            ),
            models.CheckConstraint(
                condition=models.Q(must_not_execute=True),
                name="fixed_income_result_no_execute",
            ),
            models.CheckConstraint(
                condition=models.Q(must_not_use_for_decision=True),
                name="fixed_income_result_no_decision",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Insert once; updates are rejected as research evidence mutation."""

        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("FixedIncomeResearchResultModel is immutable")
        if (
            not self.research_only
            or not self.must_not_execute
            or not self.must_not_use_for_decision
        ):
            raise ValidationError("fixed-income result must remain research-only")
        self.to_domain()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        """Reject deletion of append-only research evidence."""

        raise ValidationError("FixedIncomeResearchResultModel cannot be deleted")

    def to_domain(self) -> ImmutableResearchResult:
        """Map persisted evidence to its immutable domain record."""

        publication_seals = tuple(
            PublicationInputSeal(
                dataset_key=str(value["dataset_key"]),
                publication_key=str(value["publication_key"]),
                publication_id=str(value["publication_id"]),
                policy_version=str(value["policy_version"]),
                semantic_version=str(value["semantic_version"]),
                content_hash=str(value["content_hash"]),
            )
            for value in self.publication_evidence
        )
        persisted_ids = tuple(str(value) for value in self.publication_ids)
        if persisted_ids != tuple(seal.publication_id for seal in publication_seals):
            raise ValueError("persisted publication ids do not match sealed evidence")
        return ImmutableResearchResult(
            result_id=self.result_id,
            bond_id=self.bond_id,
            valuation_at=self.valuation_at,
            settlement_date=self.settlement_date,
            method_version=self.method_version,
            input_hash=self.input_hash,
            output_hash=self.output_hash,
            status=ResearchPreviewStatus(self.status),
            payload_json=json.dumps(self.payload, sort_keys=True, separators=(",", ":")),
            publication_seals=publication_seals,
            blocked_reasons=tuple(str(value) for value in self.blocked_reasons),
            research_only=self.research_only,
            must_not_execute=self.must_not_execute,
            must_not_use_for_decision=self.must_not_use_for_decision,
        )
