"""Canonical macro fact time-series and macro governance persistence."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Count, Max

from apps.data_center.domain.entities import MacroFact
from apps.data_center.domain.enums import DataQualityStatus
from apps.data_center.infrastructure._repository_helpers import _coerce_bool
from apps.data_center.infrastructure.models import (
    IndicatorCatalogModel,
    IndicatorUnitRuleModel,
    MacroFactModel,
    ProviderConfigModel,
)
from apps.data_center.infrastructure.orm_retry import retry_macro_fact_upsert


class MacroFactRepository:
    """ORM-backed repository for macro-economic fact time-series."""

    REQUIRED_GOVERNANCE_FIELDS = frozenset(
        {
            "source_type",
            "original_unit",
            "display_unit",
            "dimension_key",
            "multiplier_to_storage",
            "matched_rule_id",
            "period_type",
        }
    )

    @staticmethod
    def _from_model(m: MacroFactModel) -> MacroFact:
        return MacroFact(
            indicator_code=m.indicator_code,
            reporting_period=m.reporting_period,
            value=float(m.value),
            unit=m.unit,
            source=m.source,
            revision_number=m.revision_number,
            published_at=m.published_at,
            quality=DataQualityStatus(m.quality),
            fetched_at=m.fetched_at,
            extra=m.extra or {},
        )

    def get_series(
        self,
        indicator_code: str,
        start: date | None = None,
        end: date | None = None,
        limit: int = 500,
    ) -> list[MacroFact]:
        qs = MacroFactModel.objects.filter(indicator_code=indicator_code)
        if start:
            qs = qs.filter(reporting_period__gte=start)
        if end:
            qs = qs.filter(reporting_period__lte=end)
        return [self._from_model(m) for m in qs.order_by("-reporting_period")[:limit]]

    def get_latest(self, indicator_code: str) -> MacroFact | None:
        m = (
            MacroFactModel.objects.filter(indicator_code=indicator_code)
            .order_by("-reporting_period", "-revision_number")
            .first()
        )
        return self._from_model(m) if m else None

    @classmethod
    def _validate_governance(cls, fact: MacroFact) -> None:
        """Reject writes that bypass canonical macro governance normalization."""

        extra = dict(fact.extra or {})
        missing = sorted(
            key for key in cls.REQUIRED_GOVERNANCE_FIELDS if key not in extra or extra[key] is None
        )
        if fact.published_at is not None and "publication_lag_days" not in extra:
            missing.append("publication_lag_days")
        if missing:
            raise ValueError(
                f"MacroFact {fact.indicator_code} is missing governance metadata: "
                + ", ".join(missing)
            )
        if str(extra["source_type"]).strip() != fact.source:
            raise ValueError(
                f"MacroFact {fact.indicator_code} source does not match extra.source_type"
            )

    def bulk_upsert(self, facts: list[MacroFact]) -> int:
        count = 0
        for f in facts:
            self._validate_governance(f)
            retry_macro_fact_upsert(MacroFactModel.objects, f)
            count += 1
        return count


class MacroGovernanceRepository:
    """Audits and repairs macro fact governance issues in the canonical store."""

    DEFAULT_SCOPE = "macro_console"

    def list_governed_indicator_codes(self, *, scope: str = DEFAULT_SCOPE) -> list[str]:
        rows: list[tuple[int, str]] = []
        for catalog in IndicatorCatalogModel.objects.filter(is_active=True):
            extra = dict(catalog.extra or {})
            if str(extra.get("governance_scope") or "").strip() != scope:
                continue
            try:
                display_priority = int(extra.get("display_priority", 9999))
            except (TypeError, ValueError):
                display_priority = 9999
            rows.append((display_priority, catalog.code))
        rows.sort(key=lambda item: (item[0], item[1]))
        return [code for _, code in rows]

    def list_sync_supported_indicator_codes(
        self,
        *,
        scope: str = DEFAULT_SCOPE,
    ) -> set[str]:
        supported_codes: set[str] = set()
        for catalog in IndicatorCatalogModel.objects.filter(is_active=True):
            extra = dict(catalog.extra or {})
            if str(extra.get("governance_scope") or "").strip() != scope:
                continue
            if _coerce_bool(extra.get("governance_sync_supported")):
                supported_codes.add(catalog.code)
        return supported_codes

    def _build_provider_source_lookup(self) -> dict[str, str]:
        provider_lookup: dict[str, str] = {}
        for row in ProviderConfigModel.objects.exclude(name="").values("name", "source_type"):
            provider_name = str(row.get("name") or "").strip()
            source_type = str(row.get("source_type") or "").strip()
            if provider_name and source_type:
                provider_lookup[provider_name] = source_type
        return provider_lookup

    def _resolve_canonical_source_name(
        self,
        source_name: str,
        extra: dict[str, Any],
        provider_lookup: dict[str, str],
    ) -> str:
        source_type = str(extra.get("source_type") or "").strip()
        if source_type:
            return source_type
        return provider_lookup.get(source_name, source_name)

    def build_snapshot(
        self,
        *,
        scope: str = DEFAULT_SCOPE,
    ) -> dict[str, Any]:
        indicator_codes = self.list_governed_indicator_codes(scope=scope)
        supported_sync_codes = self.list_sync_supported_indicator_codes(scope=scope)
        catalogs = {
            item.code: item
            for item in IndicatorCatalogModel.objects.filter(code__in=indicator_codes)
        }
        aggregates = {
            row["indicator_code"]: row
            for row in (
                MacroFactModel.objects.filter(indicator_code__in=indicator_codes)
                .values("indicator_code")
                .annotate(
                    row_count=Count("id"),
                    latest_period=Max("reporting_period"),
                    source_count=Count("source", distinct=True),
                )
            )
        }
        source_rows: dict[str, list[dict[str, Any]]] = {}
        for row in (
            MacroFactModel.objects.filter(indicator_code__in=indicator_codes)
            .values("indicator_code", "source")
            .annotate(
                row_count=Count("id"),
                latest_period=Max("reporting_period"),
            )
            .order_by("indicator_code", "source")
        ):
            source_rows.setdefault(str(row["indicator_code"]), []).append(
                {
                    "source": str(row["source"]),
                    "row_count": int(row["row_count"]),
                    "latest_period": row["latest_period"],
                }
            )

        provider_lookup = self._build_provider_source_lookup()
        legacy_source_codes: set[str] = set()
        alias_row_map: dict[tuple[str, str], dict[str, Any]] = {}
        for fact in (
            MacroFactModel.objects.filter(indicator_code__in=indicator_codes)
            .only("indicator_code", "source", "reporting_period", "extra")
            .order_by("indicator_code", "reporting_period", "id")
            .iterator()
        ):
            source_name = str(fact.source or "")
            canonical_source = self._resolve_canonical_source_name(
                source_name,
                dict(fact.extra or {}),
                provider_lookup,
            )
            if not canonical_source or canonical_source == source_name:
                continue
            legacy_source_codes.add(str(fact.indicator_code))
            key = (source_name, canonical_source)
            row = alias_row_map.setdefault(
                key,
                {
                    "from_source": source_name,
                    "to_source": canonical_source,
                    "row_count": 0,
                    "latest_period": fact.reporting_period,
                },
            )
            row["row_count"] = int(row["row_count"]) + 1
            latest_period = row.get("latest_period")
            if latest_period is None or fact.reporting_period > latest_period:
                row["latest_period"] = fact.reporting_period

        indicator_rows: list[dict[str, Any]] = []
        healthy_count = 0
        missing_supported_count = 0
        catalog_only_gap_count = 0
        alias_catalog_count = 0
        alias_issue_count = 0
        paired_gap_count = 0

        for code in indicator_codes:
            catalog = catalogs.get(code)
            aggregate = aggregates.get(code, {})
            extra = dict((catalog.extra if catalog is not None else {}) or {})
            paired_code = str(extra.get("paired_indicator_code") or "")
            alias_of_code = str(extra.get("alias_of_indicator_code") or "")
            sync_source_type = str(extra.get("governance_sync_source_type") or "").strip()
            paired_count = (
                int(aggregates.get(paired_code, {}).get("row_count", 0)) if paired_code else 0
            )
            alias_target_count = (
                int(aggregates.get(alias_of_code, {}).get("row_count", 0)) if alias_of_code else 0
            )
            sources = source_rows.get(code, [])
            source_names = [str(item["source"]) for item in sources]
            tags: list[str] = []

            row_count = int(aggregate.get("row_count", 0) or 0)
            if row_count == 0:
                if alias_of_code and alias_target_count > 0:
                    tags.append("alias_catalog")
                    alias_catalog_count += 1
                elif code in supported_sync_codes:
                    tags.append("missing_supported")
                    missing_supported_count += 1
                else:
                    tags.append("catalog_only_gap")
                    catalog_only_gap_count += 1
            if code in legacy_source_codes:
                tags.append("legacy_source_alias")
                alias_issue_count += 1
            if row_count > 0 and paired_code and paired_count == 0:
                tags.append("paired_gap")
                paired_gap_count += 1
            if not tags:
                tags.append("healthy")
                healthy_count += 1

            indicator_rows.append(
                {
                    "code": code,
                    "name_cn": catalog.name_cn if catalog is not None else code,
                    "description": catalog.description if catalog is not None else "",
                    "series_semantics": str(extra.get("series_semantics") or ""),
                    "paired_indicator_code": paired_code,
                    "alias_of_indicator_code": alias_of_code,
                    "sync_source_type": sync_source_type,
                    "default_unit": catalog.default_unit if catalog is not None else "",
                    "default_period_type": (
                        catalog.default_period_type if catalog is not None else ""
                    ),
                    "row_count": row_count,
                    "latest_period": aggregate.get("latest_period"),
                    "sources": sources,
                    "source_names": source_names,
                    "has_data": row_count > 0,
                    "paired_has_data": paired_count > 0 if paired_code else True,
                    "sync_supported": code in supported_sync_codes,
                    "tags": tags,
                }
            )

        alias_rows = sorted(
            alias_row_map.values(),
            key=lambda item: (str(item["from_source"]), str(item["to_source"])),
        )

        return {
            "summary": {
                "governed_indicator_count": len(indicator_codes),
                "healthy_indicator_count": healthy_count,
                "missing_supported_count": missing_supported_count,
                "catalog_only_gap_count": catalog_only_gap_count,
                "alias_catalog_count": alias_catalog_count,
                "alias_issue_count": alias_issue_count,
                "paired_gap_count": paired_gap_count,
                "alias_row_count": sum(int(item["row_count"]) for item in alias_rows),
                "total_macro_rows": MacroFactModel.objects.count(),
            },
            "governed_indicator_codes": indicator_codes,
            "supported_sync_codes": sorted(supported_sync_codes),
            "source_alias_issues": alias_rows,
            "indicator_rows": indicator_rows,
        }

    @staticmethod
    def _resolve_preloaded_rule(
        rules: list[IndicatorUnitRuleModel],
        *,
        source_type: str,
        original_unit: str,
    ) -> IndicatorUnitRuleModel | None:
        """Resolve one rule from a preloaded indicator rule set."""

        exact = [rule for rule in rules if rule.original_unit == original_unit]
        for candidates in (exact, rules):
            if source_type:
                scoped = [rule for rule in candidates if rule.source_type == source_type]
                if scoped:
                    return sorted(scoped, key=lambda item: (-item.priority, item.id))[0]
            fallback = [rule for rule in candidates if rule.source_type == ""]
            if fallback:
                return sorted(fallback, key=lambda item: (-item.priority, item.id))[0]
        return None

    @staticmethod
    def _normalize_macro_fact(
        fact: MacroFactModel,
        rules: list[IndicatorUnitRuleModel],
        *,
        dry_run: bool,
        period_type: str,
        provider_lookup: dict[str, str],
    ) -> tuple[str, str | None]:
        extra = dict(fact.extra or {})
        source_type = str(
            extra.get("source_type") or provider_lookup.get(fact.source, fact.source) or ""
        ).strip()
        raw_unit = str(extra.get("original_unit") or fact.unit or "")

        rule = MacroGovernanceRepository._resolve_preloaded_rule(
            rules,
            source_type=source_type,
            original_unit=raw_unit,
        )
        if rule is None:
            return (
                "skipped",
                f"skip {fact.indicator_code} {fact.reporting_period}: no unit rule",
            )

        original_unit = rule.original_unit or raw_unit or fact.unit or ""
        current_value = Decimal(str(fact.value))
        normalized_value = current_value
        normalized_unit = fact.unit or ""

        if fact.unit != rule.storage_unit:
            if fact.unit in {rule.original_unit, rule.display_unit, "", None}:
                normalized_value = current_value * Decimal(str(rule.multiplier_to_storage))
                normalized_unit = rule.storage_unit
            else:
                return (
                    "skipped",
                    (
                        f"skip {fact.indicator_code} {fact.reporting_period}: ambiguous unit "
                        f"{fact.unit!r} for rule storage={rule.storage_unit!r}"
                    ),
                )

        publication_lag_days = extra.get("publication_lag_days")
        if publication_lag_days is None and fact.published_at:
            publication_lag_days = max((fact.published_at - fact.reporting_period).days, 0)

        normalized_extra = {
            **extra,
            "original_unit": original_unit,
            "display_unit": rule.display_unit,
            "dimension_key": rule.dimension_key,
            "multiplier_to_storage": float(rule.multiplier_to_storage),
            "matched_rule_id": rule.id,
            "source_type": source_type,
            "period_type": str(extra.get("period_type") or period_type),
        }
        if publication_lag_days is not None:
            normalized_extra["publication_lag_days"] = publication_lag_days

        changed = (
            normalized_value != current_value
            or normalized_unit != fact.unit
            or normalized_extra != extra
        )
        if not changed:
            return "unchanged", None

        previous_unit = fact.unit or ""
        if not dry_run:
            fact.value = normalized_value
            fact.unit = normalized_unit
            fact.extra = normalized_extra

        return (
            "updated",
            (
                f"{'plan' if dry_run else 'fix'} {fact.indicator_code} {fact.reporting_period}: "
                f"{current_value} {previous_unit or '-'} -> {normalized_value} {normalized_unit or '-'}"
            ),
        )

    @transaction.atomic
    def normalize_macro_fact_units(
        self,
        *,
        indicator_codes: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        queryset = MacroFactModel.objects.all().order_by("indicator_code", "reporting_period", "id")
        if indicator_codes:
            queryset = queryset.filter(indicator_code__in=indicator_codes)

        target_codes = set(queryset.values_list("indicator_code", flat=True).distinct())
        rules_by_code: dict[str, list[IndicatorUnitRuleModel]] = {code: [] for code in target_codes}
        for rule in IndicatorUnitRuleModel.objects.filter(
            indicator_code__in=target_codes,
            is_active=True,
        ).only(
            "id",
            "indicator_code",
            "source_type",
            "dimension_key",
            "original_unit",
            "storage_unit",
            "display_unit",
            "multiplier_to_storage",
            "priority",
        ):
            rules_by_code.setdefault(rule.indicator_code, []).append(rule)
        period_types = dict(
            IndicatorCatalogModel.objects.filter(code__in=target_codes).values_list(
                "code", "default_period_type"
            )
        )
        provider_lookup = self._build_provider_source_lookup()

        updated_count = 0
        skipped_count = 0
        unchanged_count = 0
        messages: list[str] = []
        pending: list[MacroFactModel] = []

        for fact in queryset.iterator(chunk_size=1000):
            action, message = self._normalize_macro_fact(
                fact,
                rules_by_code.get(fact.indicator_code, []),
                dry_run=dry_run,
                period_type=period_types.get(fact.indicator_code, ""),
                provider_lookup=provider_lookup,
            )
            if action == "updated":
                updated_count += 1
                if not dry_run:
                    pending.append(fact)
                    if len(pending) >= 500:
                        MacroFactModel.objects.bulk_update(
                            pending,
                            ["value", "unit", "extra"],
                            batch_size=500,
                        )
                        pending.clear()
            elif action == "skipped":
                skipped_count += 1
            else:
                unchanged_count += 1
            if message:
                messages.append(message)

        if pending:
            MacroFactModel.objects.bulk_update(
                pending,
                ["value", "unit", "extra"],
                batch_size=500,
            )

        return {
            "updated_count": updated_count,
            "unchanged_count": unchanged_count,
            "skipped_count": skipped_count,
            "dry_run": dry_run,
            "messages": messages,
        }

    @transaction.atomic
    def canonicalize_sources(
        self,
        *,
        scope: str = DEFAULT_SCOPE,
        indicator_codes: list[str] | None = None,
    ) -> dict[str, int]:
        target_indicator_codes = indicator_codes or self.list_governed_indicator_codes(scope=scope)
        queryset = MacroFactModel.objects.filter(indicator_code__in=target_indicator_codes)
        provider_lookup = self._build_provider_source_lookup()

        updated_count = 0
        deleted_count = 0
        skipped_conflicts = 0

        for fact in queryset.order_by("indicator_code", "reporting_period", "id").iterator():
            target_source = self._resolve_canonical_source_name(
                str(fact.source or ""),
                dict(fact.extra or {}),
                provider_lookup,
            )
            if not target_source or target_source == fact.source:
                continue

            conflict = (
                MacroFactModel.objects.filter(
                    indicator_code=fact.indicator_code,
                    reporting_period=fact.reporting_period,
                    source=target_source,
                    revision_number=fact.revision_number,
                )
                .exclude(id=fact.id)
                .first()
            )
            if conflict is not None:
                same_payload = (
                    conflict.value == fact.value
                    and conflict.unit == fact.unit
                    and conflict.published_at == fact.published_at
                    and conflict.quality == fact.quality
                    and (conflict.extra or {}) == (fact.extra or {})
                )
                if same_payload:
                    fact.delete()
                    deleted_count += 1
                else:
                    skipped_conflicts += 1
                continue

            next_extra = dict(fact.extra or {})
            if next_extra.get("source_type") != target_source:
                next_extra["source_type"] = target_source
                fact.extra = next_extra
            fact.source = target_source
            fact.save(update_fields=["source", "extra"])
            updated_count += 1

        return {
            "updated_count": updated_count,
            "deleted_count": deleted_count,
            "skipped_conflicts": skipped_conflicts,
        }
