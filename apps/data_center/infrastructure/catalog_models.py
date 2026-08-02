"""Persistent Data Center catalog and ownership models.

The governance JSON files are importable projections and review artefacts.  A
running process reads the active, versioned rows below so a deployment cannot
silently change its Dataset Contract by changing a repository file.
"""

from __future__ import annotations

from collections.abc import Mapping

from django.db import models

from apps.data_center.domain.contracts import (
    DataOwnerRegistration,
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    ProviderBinding,
    PublicationPolicy,
)


def _dataset_key(
    dataset_key: str,
    contract_version: str,
    schema_version: str,
) -> DatasetKey:
    """Build a domain dataset key from persisted catalog values."""

    return DatasetKey(
        value=dataset_key,
        contract_version=contract_version,
        schema_version=schema_version,
    )


def _field_contracts(raw_fields: object) -> tuple[DatasetFieldContract, ...]:
    """Convert JSON field definitions into validated domain values."""

    if not isinstance(raw_fields, list):
        raise ValueError("Dataset contract fields must be a list")
    fields: list[DatasetFieldContract] = []
    for raw in raw_fields:
        if not isinstance(raw, Mapping):
            raise ValueError("Dataset contract field must be an object")
        fields.append(
            DatasetFieldContract(
                name=str(raw.get("name") or ""),
                value_type=str(raw.get("value_type") or raw.get("type") or ""),
                unit=(str(raw["unit"]) if raw.get("unit") is not None else None),
                nullable=bool(raw.get("nullable", False)),
                zero_allowed=bool(raw.get("zero_allowed", False)),
                minimum=(float(raw["minimum"]) if raw.get("minimum") is not None else None),
                maximum=(float(raw["maximum"]) if raw.get("maximum") is not None else None),
            )
        )
    return tuple(fields)


class DatasetContractModel(models.Model):
    """Versioned, active Dataset Contract runtime record."""

    dataset_key = models.CharField(max_length=160, db_index=True)
    contract_version = models.CharField(max_length=40)
    schema_version = models.CharField(max_length=40)
    owner = models.CharField(max_length=100, db_index=True)
    frequency = models.CharField(max_length=40)
    decision_critical = models.BooleanField(default=False, db_index=True)
    fields = models.JSONField(default=list)
    freshness_seconds = models.PositiveBigIntegerField(null=True, blank=True)
    comparable_group = models.CharField(max_length=120, blank=True)
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_dataset_contract"
        ordering = ["dataset_key", "contract_version", "schema_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_key", "contract_version", "schema_version"],
                name="dc_dataset_contract_version_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["dataset_key", "active"]),
            models.Index(fields=["owner", "decision_critical"]),
        ]

    def to_domain(self) -> DatasetContract:
        """Convert a persisted contract to its validated domain value."""

        return DatasetContract(
            key=_dataset_key(self.dataset_key, self.contract_version, self.schema_version),
            owner=self.owner,
            frequency=self.frequency,
            decision_critical=self.decision_critical,
            fields=_field_contracts(self.fields),
            freshness_seconds=(
                int(self.freshness_seconds) if self.freshness_seconds is not None else None
            ),
            comparable_group=self.comparable_group or None,
        )


class DatasetProviderBindingModel(models.Model):
    """Versioned provider routing row for one dataset contract."""

    dataset_key = models.CharField(max_length=160, db_index=True)
    contract_version = models.CharField(max_length=40)
    schema_version = models.CharField(max_length=40)
    provider = models.CharField(max_length=100, db_index=True)
    capability = models.CharField(max_length=80)
    priority = models.PositiveIntegerField(default=100)
    freshness_seconds = models.PositiveBigIntegerField(null=True, blank=True)
    validator_key = models.CharField(max_length=160)
    enabled = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_dataset_provider_binding"
        ordering = ["dataset_key", "priority", "provider"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "dataset_key",
                    "contract_version",
                    "schema_version",
                    "provider",
                    "capability",
                ],
                name="dc_dataset_binding_version_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["dataset_key", "enabled", "priority"]),
            models.Index(fields=["provider", "capability", "enabled"]),
        ]

    def to_domain(self) -> ProviderBinding:
        """Convert a persisted binding to its validated domain value."""

        return ProviderBinding(
            dataset=_dataset_key(self.dataset_key, self.contract_version, self.schema_version),
            provider=self.provider,
            capability=self.capability,
            priority=int(self.priority),
            freshness_seconds=(
                int(self.freshness_seconds) if self.freshness_seconds is not None else None
            ),
            validator_key=self.validator_key,
            enabled=self.enabled,
        )


class DatasetPublicationPolicyModel(models.Model):
    """Versioned publication gate for one dataset contract."""

    dataset_key = models.CharField(max_length=160, db_index=True)
    contract_version = models.CharField(max_length=40)
    schema_version = models.CharField(max_length=40)
    minimum_coverage_ratio = models.FloatField()
    allow_partial = models.BooleanField(default=False)
    conflict_action = models.CharField(max_length=40)
    required_evidence = models.JSONField(default=list)
    retention_days = models.PositiveIntegerField()
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_dataset_publication_policy"
        ordering = ["dataset_key", "contract_version", "schema_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_key", "contract_version", "schema_version"],
                name="dc_dataset_policy_version_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(minimum_coverage_ratio__gte=0.0)
                & models.Q(minimum_coverage_ratio__lte=1.0),
                name="dc_dataset_policy_coverage_ratio_valid",
            ),
        ]
        indexes = [models.Index(fields=["dataset_key", "active"])]

    def to_domain(self) -> PublicationPolicy:
        """Convert a persisted publication policy to its domain value."""

        evidence = self.required_evidence
        if not isinstance(evidence, list):
            raise ValueError("Publication policy required_evidence must be a list")
        return PublicationPolicy(
            dataset=_dataset_key(self.dataset_key, self.contract_version, self.schema_version),
            minimum_coverage_ratio=float(self.minimum_coverage_ratio),
            allow_partial=self.allow_partial,
            conflict_action=self.conflict_action,
            required_evidence=tuple(str(item) for item in evidence),
            retention_days=int(self.retention_days),
        )


class DataOwnerRegistrationModel(models.Model):
    """Dataset ownership, business accountability and acceptance owner."""

    dataset_key = models.CharField(max_length=160, unique=True)
    data_platform_owner = models.CharField(max_length=100)
    business_owner = models.CharField(max_length=100)
    acceptance_owner = models.CharField(max_length=100)
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_data_owner_registration"
        ordering = ["dataset_key"]
        indexes = [
            models.Index(fields=["business_owner", "active"]),
            models.Index(fields=["acceptance_owner", "active"]),
        ]

    def to_domain(self) -> DataOwnerRegistration:
        """Convert a persisted ownership registration to its domain value."""

        return DataOwnerRegistration(
            dataset_key=self.dataset_key,
            data_platform_owner=self.data_platform_owner,
            business_owner=self.business_owner,
            acceptance_owner=self.acceptance_owner,
            active=self.active,
        )


__all__ = [
    "DataOwnerRegistrationModel",
    "DatasetContractModel",
    "DatasetPublicationPolicyModel",
    "DatasetProviderBindingModel",
]
