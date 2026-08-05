"""Append-only ORM storage for R2 governance and research evidence."""

from __future__ import annotations

import json
from typing import Any, cast

from django.core.exceptions import ValidationError
from django.db import models

from apps.data_center.domain.market_structure import (
    ImmutableMarketStructureEvidence,
    InvestorActorDefinition,
    MarketStructureMeasureConcept,
    MarketStructureResearchStatus,
    MarketStructureSeriesDefinition,
    VersionedEvidenceReference,
)
from apps.data_center.domain.research_data_foundation import InvestorFlowMeasureKind

from .pit_models import ImmutableModelMixin


class InvestorActorDefinitionModel(ImmutableModelMixin):
    """Immutable caller-governed investor classification version."""

    taxonomy_code = models.CharField(max_length=64, db_index=True)
    taxonomy_version = models.PositiveIntegerField()
    actor_code = models.CharField(max_length=64, db_index=True)
    actor_name = models.CharField(max_length=160)
    parent_actor_code = models.CharField(max_length=64, blank=True)
    source = models.CharField(max_length=100, db_index=True)
    revision_policy_ref = models.CharField(max_length=300)
    effective_at = models.DateTimeField(db_index=True)
    effective_to = models.DateTimeField(null=True, blank=True, db_index=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    definition_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_investor_actor_definition"
        ordering = ["taxonomy_code", "taxonomy_version", "actor_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["taxonomy_code", "taxonomy_version", "actor_code"],
                name="dc_ms_actor_version_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_at")),
                name="dc_ms_actor_interval_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["taxonomy_code", "taxonomy_version", "is_active"],
                name="dc_ms_actor_tax_idx",
            ),
            models.Index(
                fields=["actor_code", "is_active"],
                name="dc_ms_actor_code_idx",
            ),
        ]

    def to_domain(self) -> InvestorActorDefinition:
        """Convert and verify the immutable classification payload."""

        definition = InvestorActorDefinition(
            taxonomy_code=self.taxonomy_code,
            taxonomy_version=self.taxonomy_version,
            actor_code=self.actor_code,
            actor_name=self.actor_name,
            parent_actor_code=self.parent_actor_code,
            source=self.source,
            revision_policy_ref=self.revision_policy_ref,
            effective_at=self.effective_at,
            effective_to=self.effective_to,
            description=self.description,
            is_active=self.is_active,
        )
        if self.definition_hash != definition.definition_hash:
            raise ValidationError("investor actor definition hash mismatch")
        return definition

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate hash and immutable semantics before inserting."""

        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("InvestorActorDefinitionModel is immutable")
        self.to_domain()
        super().save(*args, **kwargs)


class MarketStructureSeriesDefinitionModel(ImmutableModelMixin):
    """Immutable research eligibility overlay for one canonical flow series."""

    MEASURE_CONCEPT_CHOICES = [(item.value, item.value) for item in MarketStructureMeasureConcept]
    MEASURE_KIND_CHOICES = [(item.value, item.value) for item in InvestorFlowMeasureKind]

    series_code = models.CharField(max_length=64, db_index=True)
    series_version = models.PositiveIntegerField()
    flow_code = models.CharField(max_length=64, db_index=True)
    flow_definition_version = models.PositiveIntegerField()
    taxonomy_code = models.CharField(max_length=64, db_index=True)
    taxonomy_version = models.PositiveIntegerField()
    actor_code = models.CharField(max_length=64, db_index=True)
    measure_concept = models.CharField(max_length=16, choices=MEASURE_CONCEPT_CHOICES)
    measure_kind = models.CharField(max_length=40, choices=MEASURE_KIND_CHOICES)
    canonical_unit = models.CharField(max_length=40)
    frequency = models.CharField(max_length=40)
    source = models.CharField(max_length=100, db_index=True)
    revision_policy_ref = models.CharField(max_length=300)
    effective_at = models.DateTimeField(db_index=True)
    effective_to = models.DateTimeField(null=True, blank=True, db_index=True)
    is_proxy = models.BooleanField(default=False, db_index=True)
    proxy_target_actor_code = models.CharField(max_length=64, blank=True)
    proxy_methodology_ref = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    definition_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_market_structure_series"
        ordering = ["series_code", "series_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["series_code", "series_version"],
                name="dc_ms_series_version_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_at")),
                name="dc_ms_series_interval_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(is_proxy=True)
                    & ~models.Q(proxy_target_actor_code="")
                    & ~models.Q(proxy_methodology_ref="")
                )
                | (
                    models.Q(is_proxy=False)
                    & models.Q(proxy_target_actor_code="")
                    & models.Q(proxy_methodology_ref="")
                ),
                name="dc_ms_series_proxy_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["actor_code", "measure_concept", "is_active"],
                name="dc_ms_series_actor_idx",
            ),
            models.Index(
                fields=["flow_code", "flow_definition_version"],
                name="dc_ms_series_flow_idx",
            ),
        ]

    def to_domain(self) -> MarketStructureSeriesDefinition:
        """Convert and verify every immutable series semantic."""

        definition = MarketStructureSeriesDefinition(
            series_code=self.series_code,
            series_version=self.series_version,
            flow_code=self.flow_code,
            flow_definition_version=self.flow_definition_version,
            taxonomy_code=self.taxonomy_code,
            taxonomy_version=self.taxonomy_version,
            actor_code=self.actor_code,
            measure_concept=MarketStructureMeasureConcept(self.measure_concept),
            measure_kind=InvestorFlowMeasureKind(self.measure_kind),
            canonical_unit=self.canonical_unit,
            frequency=self.frequency,
            source=self.source,
            revision_policy_ref=self.revision_policy_ref,
            effective_at=self.effective_at,
            effective_to=self.effective_to,
            is_proxy=self.is_proxy,
            proxy_target_actor_code=self.proxy_target_actor_code,
            proxy_methodology_ref=self.proxy_methodology_ref,
            description=self.description,
            is_active=self.is_active,
        )
        if self.definition_hash != definition.definition_hash:
            raise ValidationError("market-structure series definition hash mismatch")
        return definition

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate hash and immutable semantics before inserting."""

        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("MarketStructureSeriesDefinitionModel is immutable")
        self.to_domain()
        super().save(*args, **kwargs)


class MarketStructureResearchEvidenceModel(ImmutableModelMixin):
    """Hash-sealed, versioned and permanently research-only R2 evidence."""

    STATUS_CHOICES = [(item.value, item.value) for item in MarketStructureResearchStatus]

    evidence_key = models.CharField(max_length=128, db_index=True)
    evidence_version = models.PositiveIntegerField()
    as_of_time = models.DateTimeField(db_index=True)
    group_code = models.CharField(max_length=64, db_index=True)
    group_revision = models.PositiveIntegerField()
    method_version = models.CharField(max_length=64, db_index=True)
    policy_code = models.CharField(max_length=64, db_index=True)
    policy_version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, db_index=True)
    input_hash = models.CharField(max_length=64, db_index=True)
    output_hash = models.CharField(max_length=64)
    evidence_hash = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()
    source_evidence = models.JSONField(default=list, blank=True)
    research_only = models.BooleanField(default=True, editable=False)
    must_not_use_for_decision = models.BooleanField(default=True, editable=False)
    must_not_execute = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_market_structure_evidence"
        ordering = ["evidence_key", "evidence_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["evidence_key", "evidence_version"],
                name="dc_ms_evidence_version_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(research_only=True),
                name="dc_ms_evidence_research_only",
            ),
            models.CheckConstraint(
                condition=models.Q(must_not_use_for_decision=True),
                name="dc_ms_evidence_no_decision",
            ),
            models.CheckConstraint(
                condition=models.Q(must_not_execute=True),
                name="dc_ms_evidence_no_execute",
            ),
        ]
        indexes = [
            models.Index(
                fields=["group_code", "group_revision", "-as_of_time"],
                name="dc_ms_evidence_group_idx",
            ),
            models.Index(
                fields=["method_version", "status"],
                name="dc_ms_evidence_method_idx",
            ),
        ]

    def to_domain(self) -> ImmutableMarketStructureEvidence:
        """Rebuild and fully verify the persisted immutable evidence."""

        if not isinstance(self.payload, dict):
            raise ValidationError("market-structure payload must be an object")
        if not isinstance(self.source_evidence, list):
            raise ValidationError("market-structure source evidence must be a list")
        references: list[VersionedEvidenceReference] = []
        for raw_item in self.source_evidence:
            if not isinstance(raw_item, dict):
                raise ValidationError("market-structure source reference is invalid")
            item = cast(dict[str, object], raw_item)
            dataset = item.get("dataset")
            version_id = item.get("version_id")
            content_hash = item.get("content_hash")
            if (
                not isinstance(dataset, str)
                or not isinstance(version_id, int)
                or isinstance(version_id, bool)
                or not isinstance(content_hash, str)
            ):
                raise ValidationError("market-structure source reference is invalid")
            references.append(
                VersionedEvidenceReference(
                    dataset=dataset,
                    version_id=version_id,
                    content_hash=content_hash,
                )
            )
        return ImmutableMarketStructureEvidence(
            evidence_key=self.evidence_key,
            evidence_version=self.evidence_version,
            as_of_time=self.as_of_time,
            group_code=self.group_code,
            group_revision=self.group_revision,
            method_version=self.method_version,
            policy_code=self.policy_code,
            policy_version=self.policy_version,
            status=MarketStructureResearchStatus(self.status),
            input_hash=self.input_hash,
            output_hash=self.output_hash,
            evidence_hash=self.evidence_hash,
            payload_json=json.dumps(
                self.payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            source_evidence=tuple(references),
            research_only=self.research_only,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_execute=self.must_not_execute,
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Reject non-research flags and verify all hashes before insertion."""

        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("MarketStructureResearchEvidenceModel is immutable")
        if (
            not self.research_only
            or not self.must_not_use_for_decision
            or not self.must_not_execute
        ):
            raise ValidationError("market-structure evidence must remain research-only")
        self.to_domain()
        super().save(*args, **kwargs)


__all__ = [
    "InvestorActorDefinitionModel",
    "MarketStructureResearchEvidenceModel",
    "MarketStructureSeriesDefinitionModel",
]
