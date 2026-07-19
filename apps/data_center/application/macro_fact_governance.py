"""Canonical governance normalization for macro facts before persistence."""

from __future__ import annotations

import dataclasses

from apps.data_center.domain.entities import MacroFact
from apps.data_center.domain.protocols import (
    IndicatorCatalogRepositoryProtocol,
    IndicatorUnitRuleRepositoryProtocol,
)


class MacroFactGovernanceNormalizer:
    """Apply catalog and unit-rule governance metadata to macro facts."""

    def __init__(
        self,
        catalog_repo: IndicatorCatalogRepositoryProtocol,
        unit_rule_repo: IndicatorUnitRuleRepositoryProtocol,
    ) -> None:
        self._catalog_repo = catalog_repo
        self._unit_rule_repo = unit_rule_repo

    def normalize(
        self,
        fact: MacroFact,
        *,
        source_type: str | None = None,
        provider_name: str | None = None,
    ) -> MacroFact:
        """Return one fact in canonical storage units with audit metadata."""

        catalog = self._catalog_repo.get_by_code(fact.indicator_code)
        if catalog is None or not catalog.is_active:
            raise ValueError(f"Active indicator catalog missing for {fact.indicator_code}")

        extra = dict(fact.extra or {})
        canonical_source = str(source_type or extra.get("source_type") or fact.source).strip()
        original_unit = str(extra.get("original_unit") or fact.unit or "")
        rule = self._unit_rule_repo.resolve_active_rule(
            fact.indicator_code,
            source_type=canonical_source,
            original_unit=original_unit,
        )
        if rule is None:
            rule = self._unit_rule_repo.resolve_active_rule(
                fact.indicator_code,
                source_type=canonical_source,
                original_unit=None,
            )
        if rule is None:
            raise ValueError(
                "Indicator unit rule missing for "
                f"{fact.indicator_code}@{canonical_source} unit={original_unit!r}"
            )

        normalized_value = float(fact.value)
        if fact.unit != rule.storage_unit:
            normalized_value *= float(rule.multiplier_to_storage)

        extra.update(
            {
                "source_type": canonical_source,
                "original_unit": rule.original_unit or original_unit,
                "display_unit": rule.display_unit,
                "dimension_key": rule.dimension_key,
                "multiplier_to_storage": float(rule.multiplier_to_storage),
                "matched_rule_id": rule.id,
                "period_type": str(extra.get("period_type") or catalog.default_period_type),
            }
        )
        resolved_provider_name = str(provider_name or extra.get("provider_name") or "").strip()
        if resolved_provider_name:
            extra["provider_name"] = resolved_provider_name
        if fact.published_at is not None:
            extra["publication_lag_days"] = max(
                0,
                (fact.published_at - fact.reporting_period).days,
            )

        return dataclasses.replace(
            fact,
            value=normalized_value,
            unit=rule.storage_unit,
            source=canonical_source,
            extra=extra,
        )

    def normalize_many(
        self,
        facts: list[MacroFact],
        *,
        source_type: str | None = None,
        provider_name: str | None = None,
    ) -> list[MacroFact]:
        """Normalize a batch while preserving input order."""

        return [
            self.normalize(
                fact,
                source_type=source_type,
                provider_name=provider_name,
            )
            for fact in facts
        ]
