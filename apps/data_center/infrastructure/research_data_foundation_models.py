"""ORM catalog for governed R1/R2 strategy-research data definitions."""

from __future__ import annotations

from typing import Any

from django.db import models

from apps.data_center.domain.research_data_foundation import (
    AssetGroupRevision,
    InvestorFlowDefinition,
    InvestorFlowMeasureKind,
    OperatingMetricDefinition,
)


class OperatingMetricDefinitionModel(models.Model):
    """Versioned operating-metric taxonomy row; migrations provide no seed."""

    metric_code = models.CharField(max_length=64, db_index=True)
    definition_version = models.PositiveIntegerField()
    name = models.CharField(max_length=160)
    canonical_unit = models.CharField(max_length=40)
    frequency = models.CharField(max_length=40)
    source = models.CharField(max_length=100, db_index=True)
    effective_at = models.DateTimeField(db_index=True)
    effective_to = models.DateTimeField(null=True, blank=True, db_index=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_operating_metric_definition"
        ordering = ["metric_code", "definition_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["metric_code", "definition_version"],
                name="dc_operating_metric_version_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_at")),
                name="dc_operating_metric_interval_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["metric_code", "is_active", "definition_version"],
                name="dc_oper_metric_active_idx",
            ),
            models.Index(
                fields=["source", "is_active"],
                name="dc_oper_metric_source_idx",
            ),
        ]

    def to_domain(self) -> OperatingMetricDefinition:
        """Convert the persisted version to its validated domain contract."""

        return OperatingMetricDefinition(
            metric_code=self.metric_code,
            definition_version=self.definition_version,
            name=self.name,
            canonical_unit=self.canonical_unit,
            frequency=self.frequency,
            source=self.source,
            effective_at=self.effective_at,
            effective_to=self.effective_to,
            description=self.description,
            is_active=self.is_active,
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate domain semantics before persisting a governed version."""

        self.to_domain()
        super().save(*args, **kwargs)


class InvestorFlowDefinitionModel(models.Model):
    """Versioned actor/measure/source definition with mandatory proxy labels."""

    MEASURE_KIND_CHOICES = [(item.value, item.value) for item in InvestorFlowMeasureKind]

    flow_code = models.CharField(max_length=64, db_index=True)
    definition_version = models.PositiveIntegerField()
    actor_code = models.CharField(max_length=64, db_index=True)
    actor_name = models.CharField(max_length=160)
    measure_kind = models.CharField(max_length=40, choices=MEASURE_KIND_CHOICES)
    canonical_unit = models.CharField(max_length=40)
    frequency = models.CharField(max_length=40)
    source = models.CharField(max_length=100, db_index=True)
    effective_at = models.DateTimeField(db_index=True)
    effective_to = models.DateTimeField(null=True, blank=True, db_index=True)
    is_proxy = models.BooleanField(default=False, db_index=True)
    proxy_target_actor_code = models.CharField(max_length=64, blank=True)
    proxy_methodology_ref = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_investor_flow_definition"
        ordering = ["flow_code", "definition_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["flow_code", "definition_version"],
                name="dc_investor_flow_version_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_at")),
                name="dc_investor_flow_interval_valid",
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
                name="dc_investor_flow_proxy_metadata_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["actor_code", "measure_kind", "is_active"],
                name="dc_flow_actor_measure_idx",
            ),
            models.Index(
                fields=["source", "is_proxy", "is_active"],
                name="dc_flow_source_proxy_idx",
            ),
        ]

    def to_domain(self) -> InvestorFlowDefinition:
        """Convert the persisted version to its validated domain contract."""

        return InvestorFlowDefinition(
            flow_code=self.flow_code,
            definition_version=self.definition_version,
            actor_code=self.actor_code,
            actor_name=self.actor_name,
            measure_kind=InvestorFlowMeasureKind(self.measure_kind),
            canonical_unit=self.canonical_unit,
            frequency=self.frequency,
            source=self.source,
            effective_at=self.effective_at,
            effective_to=self.effective_to,
            is_proxy=self.is_proxy,
            proxy_target_actor_code=self.proxy_target_actor_code,
            proxy_methodology_ref=self.proxy_methodology_ref,
            description=self.description,
            is_active=self.is_active,
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate measure and proxy semantics before persistence."""

        self.to_domain()
        super().save(*args, **kwargs)


class AssetGroupRevisionModel(models.Model):
    """Versioned custom asset-group definition without embedded members."""

    group_code = models.CharField(max_length=64, db_index=True)
    revision = models.PositiveIntegerField()
    name = models.CharField(max_length=160)
    source = models.CharField(max_length=100, db_index=True)
    effective_at = models.DateTimeField(db_index=True)
    effective_to = models.DateTimeField(null=True, blank=True, db_index=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_asset_group_revision"
        ordering = ["group_code", "revision"]
        constraints = [
            models.UniqueConstraint(
                fields=["group_code", "revision"],
                name="dc_asset_group_revision_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_at")),
                name="dc_asset_group_interval_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["group_code", "is_active", "revision"],
                name="dc_asset_group_active_idx",
            ),
            models.Index(
                fields=["source", "is_active"],
                name="dc_asset_group_source_idx",
            ),
        ]

    def to_domain(self) -> AssetGroupRevision:
        """Convert the persisted version to its validated domain contract."""

        return AssetGroupRevision(
            group_code=self.group_code,
            revision=self.revision,
            name=self.name,
            source=self.source,
            effective_at=self.effective_at,
            effective_to=self.effective_to,
            description=self.description,
            is_active=self.is_active,
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate domain semantics before persisting a group revision."""

        self.to_domain()
        super().save(*args, **kwargs)


__all__ = [
    "AssetGroupRevisionModel",
    "InvestorFlowDefinitionModel",
    "OperatingMetricDefinitionModel",
]
