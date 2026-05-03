"""
Data Center — Infrastructure Layer Repositories

ORM-backed implementations of domain repository protocols.

Phase 1: ProviderConfigRepository, DataProviderSettingsRepository
Phase 2: AssetRepository, IndicatorCatalogRepository, MacroFactRepository,
         PriceBarRepository, QuoteSnapshotRepository, FundNavRepository,
         FinancialFactRepository, ValuationFactRepository,
         SectorMembershipRepository, NewsRepository, CapitalFlowRepository,
         RawAuditRepository
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db import transaction
from django.db.models import Count, Max

from apps.data_center.domain.entities import (
    AssetAlias,
    AssetMaster,
    CapitalFlowFact,
    DataProviderSettings,
    FinancialFact,
    FundNavFact,
    IndicatorCatalog,
    IndicatorUnitRule,
    MacroFact,
    NewsFact,
    PriceBar,
    ProviderConfig,
    QuoteSnapshot,
    RawAudit,
    SectorMembershipFact,
    ValuationFact,
)
from apps.data_center.domain.enums import (
    AssetType,
    DataQualityStatus,
    FinancialPeriodType,
    MarketExchange,
    PriceAdjustment,
)
from apps.data_center.infrastructure.models import (
    AssetAliasModel,
    AssetMasterModel,
    CapitalFlowFactModel,
    DataProviderSettingsModel,
    FinancialFactModel,
    FundNavFactModel,
    IndicatorCatalogModel,
    IndicatorUnitRuleModel,
    MacroFactModel,
    NewsFactModel,
    PriceBarModel,
    ProviderConfigModel,
    QuoteSnapshotModel,
    RawAuditModel,
    SectorMembershipFactModel,
    ValuationFactModel,
)


class ProviderConfigRepository:
    """Persists and retrieves ProviderConfig domain objects via Django ORM."""

    def list_all(self) -> list[ProviderConfig]:
        return [m.to_domain() for m in ProviderConfigModel.objects.all()]

    def list_active(self) -> list[ProviderConfig]:
        """Return active provider configs ordered by priority."""
        return [
            m.to_domain()
            for m in ProviderConfigModel.objects.filter(is_active=True).order_by("priority")
        ]

    def get_by_id(self, provider_id: int) -> ProviderConfig | None:
        try:
            return ProviderConfigModel.objects.get(pk=provider_id).to_domain()
        except ProviderConfigModel.DoesNotExist:
            return None

    def get_by_name(self, name: str) -> ProviderConfig | None:
        try:
            return ProviderConfigModel.objects.get(name=name).to_domain()
        except ProviderConfigModel.DoesNotExist:
            return None

    def get_active_by_type(self, source_type: str) -> list[ProviderConfig]:
        return [
            m.to_domain()
            for m in ProviderConfigModel.objects.filter(
                source_type=source_type, is_active=True
            ).order_by("priority")
        ]

    def save(self, config: ProviderConfig) -> ProviderConfig:
        """Create or update a ProviderConfigModel row."""
        if config.id is not None:
            model = ProviderConfigModel.objects.get(pk=config.id)
        else:
            model = ProviderConfigModel()

        model.name = config.name
        model.source_type = config.source_type
        model.is_active = config.is_active
        model.priority = config.priority
        model.api_key = config.api_key
        model.api_secret = config.api_secret
        model.http_url = config.http_url
        model.api_endpoint = config.api_endpoint
        model.extra_config = config.extra_config
        model.description = config.description
        model.save()
        return model.to_domain()

    def delete(self, provider_id: int) -> None:
        ProviderConfigModel.objects.filter(pk=provider_id).delete()


class DataProviderSettingsRepository:
    """Persists and retrieves global provider settings (singleton)."""

    def has_settings(self) -> bool:
        """Return whether the singleton settings row already exists."""

        return DataProviderSettingsModel.objects.exists()

    def load(self) -> DataProviderSettings:
        return DataProviderSettingsModel.load().to_domain()

    def save(self, settings: DataProviderSettings) -> DataProviderSettings:
        model = DataProviderSettingsModel.load()
        model.default_source = settings.default_source
        model.enable_failover = settings.enable_failover
        model.failover_tolerance = settings.failover_tolerance
        model.save()
        return model.to_domain()


# ---------------------------------------------------------------------------
# Phase 2 — helpers
# ---------------------------------------------------------------------------


def _to_date(value: date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _dedupe_codes(codes: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for code in codes:
        normalized = code.strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _infer_market_suffixes(base_code: str) -> list[str]:
    if not base_code:
        return []
    if base_code.startswith(("0", "3")):
        return ["SZ"]
    if base_code.startswith(("6", "9")):
        return ["SH"]
    if base_code.startswith(("4", "8")):
        return ["BJ"]
    return []


def _build_asset_code_candidates(asset_code: str) -> list[str]:
    normalized = (asset_code or "").strip().upper()
    if not normalized:
        return []

    suffix_aliases = {
        "XSHE": "SZ",
        "SZSE": "SZ",
        "XSHG": "SH",
        "SSE": "SH",
        "BSE": "BJ",
    }

    candidates = [normalized]
    if "." in normalized:
        base_code, suffix = normalized.rsplit(".", 1)
        canonical_suffix = suffix_aliases.get(suffix)
        if canonical_suffix:
            candidates.append(f"{base_code}.{canonical_suffix}")
    else:
        base_code = normalized.split(".", 1)[0]
        for suffix in _infer_market_suffixes(base_code):
            candidates.append(f"{base_code}.{suffix}")
        candidates.append(base_code)

    return _dedupe_codes(candidates)


def _resolve_asset_code_candidates(asset_code: str) -> list[str]:
    normalized = (asset_code or "").strip().upper()
    candidates = _build_asset_code_candidates(normalized)
    if not candidates:
        return []

    resolved_codes = list(
        AssetMasterModel.objects.filter(code__in=candidates).values_list("code", flat=True)
    )
    resolved_codes.extend(
        AssetAliasModel.objects.filter(alias_code__in=candidates)
        .select_related("asset")
        .values_list("asset__code", flat=True)
    )

    base_code = candidates[0].split(".", 1)[0]
    if base_code and "." not in normalized:
        resolved_codes.extend(
            AssetMasterModel.objects.filter(code__startswith=f"{base_code}.").values_list(
                "code", flat=True
            )[:5]
        )

    return _dedupe_codes(candidates + resolved_codes)


# ---------------------------------------------------------------------------
# Phase 2 — Master data repositories
# ---------------------------------------------------------------------------


class AssetRepository:
    """ORM-backed repository for AssetMaster."""

    @staticmethod
    def _from_model(m: AssetMasterModel) -> AssetMaster:
        return AssetMaster(
            code=m.code,
            name=m.name,
            short_name=m.short_name,
            asset_type=AssetType(m.asset_type),
            exchange=MarketExchange(m.exchange),
            is_active=m.is_active,
            list_date=m.list_date,
            delist_date=m.delist_date,
            sector=m.sector,
            industry=m.industry,
            currency=m.currency,
            total_shares=float(m.total_shares) if m.total_shares is not None else None,
            extra=m.extra or {},
        )

    def get_by_code(self, code: str) -> AssetMaster | None:
        for candidate in _resolve_asset_code_candidates(code):
            try:
                return self._from_model(AssetMasterModel.objects.get(code=candidate))
            except AssetMasterModel.DoesNotExist:
                continue
        return None

    def search(self, query: str, limit: int = 20) -> list[AssetMaster]:
        from django.db.models import Q

        qs = AssetMasterModel.objects.filter(
            Q(code__icontains=query) | Q(name__icontains=query) | Q(short_name__icontains=query)
        )[:limit]
        return [self._from_model(m) for m in qs]

    def upsert(self, asset: AssetMaster) -> AssetMaster:
        m, _ = AssetMasterModel.objects.update_or_create(
            code=asset.code,
            defaults=dict(
                name=asset.name,
                short_name=asset.short_name,
                asset_type=asset.asset_type.value,
                exchange=asset.exchange.value,
                is_active=asset.is_active,
                list_date=asset.list_date,
                delist_date=asset.delist_date,
                sector=asset.sector,
                industry=asset.industry,
                currency=asset.currency,
                total_shares=asset.total_shares,
                extra=asset.extra,
            ),
        )
        return self._from_model(m)

    def upsert_alias(self, alias: AssetAlias) -> AssetAlias:
        asset = AssetMasterModel.objects.get(code=alias.asset_code)
        m, _ = AssetAliasModel.objects.update_or_create(
            provider_name=alias.provider_name,
            alias_code=alias.alias_code,
            defaults={"asset": asset},
        )
        return AssetAlias(
            asset_code=m.asset.code,
            provider_name=m.provider_name,
            alias_code=m.alias_code,
        )

    def list_by_exchange(self, exchange: str) -> list[AssetMaster]:
        return [
            self._from_model(m)
            for m in AssetMasterModel.objects.filter(exchange=exchange, is_active=True)
        ]


class IndicatorCatalogRepository:
    """ORM-backed repository for IndicatorCatalog definitions."""

    @staticmethod
    def _from_model(m: IndicatorCatalogModel) -> IndicatorCatalog:
        return IndicatorCatalog(
            code=m.code,
            name_cn=m.name_cn,
            name_en=m.name_en,
            description=m.description,
            default_unit=m.default_unit,
            default_period_type=m.default_period_type,
            category=m.category,
            is_active=m.is_active,
            extra=m.extra or {},
        )

    def get_by_code(self, code: str) -> IndicatorCatalog | None:
        try:
            return self._from_model(IndicatorCatalogModel.objects.get(code=code))
        except IndicatorCatalogModel.DoesNotExist:
            return None

    def list_all(self) -> list[IndicatorCatalog]:
        return [self._from_model(m) for m in IndicatorCatalogModel.objects.all()]

    def list_active(self) -> list[IndicatorCatalog]:
        return [self._from_model(m) for m in IndicatorCatalogModel.objects.filter(is_active=True)]

    def upsert(self, catalog: IndicatorCatalog) -> IndicatorCatalog:
        m, _ = IndicatorCatalogModel.objects.update_or_create(
            code=catalog.code,
            defaults=dict(
                name_cn=catalog.name_cn,
                name_en=catalog.name_en,
                description=catalog.description,
                default_unit=catalog.default_unit,
                default_period_type=catalog.default_period_type,
                category=catalog.category,
                is_active=catalog.is_active,
                extra=catalog.extra,
            ),
        )
        return self._from_model(m)

    def delete(self, code: str) -> None:
        IndicatorCatalogModel.objects.filter(code=code).delete()


class IndicatorUnitRuleRepository:
    """ORM-backed repository for IndicatorUnitRule definitions."""

    @staticmethod
    def _from_model(m: IndicatorUnitRuleModel) -> IndicatorUnitRule:
        return IndicatorUnitRule(
            id=m.id,
            indicator_code=m.indicator_code,
            source_type=m.source_type,
            dimension_key=m.dimension_key,
            original_unit=m.original_unit,
            storage_unit=m.storage_unit,
            display_unit=m.display_unit,
            multiplier_to_storage=float(m.multiplier_to_storage),
            is_active=m.is_active,
            priority=m.priority,
            description=m.description,
        )

    def get_by_id(self, rule_id: int) -> IndicatorUnitRule | None:
        try:
            return self._from_model(IndicatorUnitRuleModel.objects.get(id=rule_id))
        except IndicatorUnitRuleModel.DoesNotExist:
            return None

    def list_by_indicator(self, indicator_code: str) -> list[IndicatorUnitRule]:
        return [
            self._from_model(m)
            for m in IndicatorUnitRuleModel.objects.filter(indicator_code=indicator_code).order_by(
                "-priority", "source_type", "original_unit", "id"
            )
        ]

    def upsert(self, rule: IndicatorUnitRule) -> IndicatorUnitRule:
        m, _ = IndicatorUnitRuleModel.objects.update_or_create(
            indicator_code=rule.indicator_code,
            source_type=rule.source_type,
            original_unit=rule.original_unit,
            defaults=dict(
                dimension_key=rule.dimension_key,
                storage_unit=rule.storage_unit,
                display_unit=rule.display_unit,
                multiplier_to_storage=rule.multiplier_to_storage,
                is_active=rule.is_active,
                priority=rule.priority,
                description=rule.description,
            ),
        )
        return self._from_model(m)

    def delete(self, rule_id: int) -> None:
        IndicatorUnitRuleModel.objects.filter(id=rule_id).delete()

    def resolve_active_rule(
        self,
        indicator_code: str,
        *,
        source_type: str = "",
        original_unit: str | None = None,
    ) -> IndicatorUnitRule | None:
        queryset = IndicatorUnitRuleModel.objects.filter(
            indicator_code=indicator_code,
            is_active=True,
        )
        if original_unit is not None:
            queryset = queryset.filter(original_unit=original_unit)

        scoped = list(
            queryset.filter(source_type=source_type).order_by("-priority", "id")[:1]
        ) if source_type else []
        if scoped:
            return self._from_model(scoped[0])

        fallback = queryset.filter(source_type="").order_by("-priority", "id").first()
        return self._from_model(fallback) if fallback else None


# ---------------------------------------------------------------------------
# Phase 2 — Fact table repositories
# ---------------------------------------------------------------------------


class MacroFactRepository:
    """ORM-backed repository for macro-economic fact time-series."""

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

    def bulk_upsert(self, facts: list[MacroFact]) -> int:
        count = 0
        for f in facts:
            MacroFactModel.objects.update_or_create(
                indicator_code=f.indicator_code,
                reporting_period=f.reporting_period,
                source=f.source,
                revision_number=f.revision_number,
                defaults=dict(
                    value=f.value,
                    unit=f.unit,
                    published_at=f.published_at,
                    quality=f.quality.value,
                    extra=f.extra,
                ),
            )
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
            paired_count = int(aggregates.get(paired_code, {}).get("row_count", 0)) if paired_code else 0
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
                    "default_unit": catalog.default_unit if catalog is not None else "",
                    "default_period_type": catalog.default_period_type if catalog is not None else "",
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


class PriceBarRepository:
    """ORM-backed repository for OHLCV price bars."""

    @staticmethod
    def _from_model(m: PriceBarModel) -> PriceBar:
        return PriceBar(
            asset_code=m.asset_code,
            bar_date=m.bar_date,
            freq=m.freq,
            adjustment=PriceAdjustment(m.adjustment),
            open=float(m.open),
            high=float(m.high),
            low=float(m.low),
            close=float(m.close),
            volume=float(m.volume) if m.volume is not None else None,
            amount=float(m.amount) if m.amount is not None else None,
            source=m.source,
            fetched_at=m.fetched_at,
        )

    def get_bars(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
        limit: int = 500,
    ) -> list[PriceBar]:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = PriceBarModel.objects.filter(asset_code=candidate)
            if start:
                qs = qs.filter(bar_date__gte=start)
            if end:
                qs = qs.filter(bar_date__lte=end)
            rows = list(qs.order_by("-bar_date")[:limit])
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def get_latest(self, asset_code: str) -> PriceBar | None:
        for candidate in _resolve_asset_code_candidates(asset_code):
            m = PriceBarModel.objects.filter(asset_code=candidate).order_by("-bar_date").first()
            if m is not None:
                return self._from_model(m)
        return None

    def bulk_upsert(self, bars: list[PriceBar]) -> int:
        count = 0
        for b in bars:
            PriceBarModel.objects.update_or_create(
                asset_code=b.asset_code,
                bar_date=b.bar_date,
                freq=b.freq,
                adjustment=b.adjustment.value,
                source=b.source,
                defaults=dict(
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    volume=b.volume,
                    amount=b.amount,
                ),
            )
            count += 1
        return count


class QuoteSnapshotRepository:
    """ORM-backed repository for real-time quote snapshots."""

    @staticmethod
    def _from_model(m: QuoteSnapshotModel) -> QuoteSnapshot:
        return QuoteSnapshot(
            asset_code=m.asset_code,
            snapshot_at=m.snapshot_at,
            current_price=float(m.current_price),
            open=float(m.open) if m.open is not None else None,
            high=float(m.high) if m.high is not None else None,
            low=float(m.low) if m.low is not None else None,
            prev_close=float(m.prev_close) if m.prev_close is not None else None,
            volume=float(m.volume) if m.volume is not None else None,
            amount=float(m.amount) if m.amount is not None else None,
            bid=float(m.bid) if m.bid is not None else None,
            ask=float(m.ask) if m.ask is not None else None,
            source=m.source,
            extra=m.extra or {},
        )

    def get_latest(self, asset_code: str) -> QuoteSnapshot | None:
        for candidate in _resolve_asset_code_candidates(asset_code):
            m = (
                QuoteSnapshotModel.objects.filter(asset_code=candidate)
                .order_by("-snapshot_at")
                .first()
            )
            if m is not None:
                return self._from_model(m)
        return None

    def get_series(
        self,
        asset_code: str,
        snapshot_date: date | None = None,
        limit: int = 500,
    ) -> list[QuoteSnapshot]:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = QuoteSnapshotModel.objects.filter(asset_code=candidate)
            if snapshot_date is not None:
                qs = qs.filter(snapshot_at__date=snapshot_date)
            rows = list(qs.order_by("-snapshot_at")[:limit])
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def bulk_upsert(self, quotes: list[QuoteSnapshot]) -> int:
        count = 0
        for q in quotes:
            QuoteSnapshotModel.objects.update_or_create(
                asset_code=q.asset_code,
                snapshot_at=q.snapshot_at,
                source=q.source,
                defaults=dict(
                    current_price=q.current_price,
                    open=q.open,
                    high=q.high,
                    low=q.low,
                    prev_close=q.prev_close,
                    volume=q.volume,
                    amount=q.amount,
                    bid=q.bid,
                    ask=q.ask,
                    extra=q.extra,
                ),
            )
            count += 1
        return count


class FundNavRepository:
    """ORM-backed repository for fund NAV facts."""

    @staticmethod
    def _from_model(m: FundNavFactModel) -> FundNavFact:
        return FundNavFact(
            fund_code=m.fund_code,
            nav_date=m.nav_date,
            nav=float(m.nav),
            acc_nav=float(m.acc_nav) if m.acc_nav is not None else None,
            daily_return=float(m.daily_return) if m.daily_return is not None else None,
            source=m.source,
            fetched_at=m.fetched_at,
            extra=m.extra or {},
        )

    def get_series(
        self,
        fund_code: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[FundNavFact]:
        qs = FundNavFactModel.objects.filter(fund_code=fund_code)
        if start:
            qs = qs.filter(nav_date__gte=start)
        if end:
            qs = qs.filter(nav_date__lte=end)
        return [self._from_model(m) for m in qs.order_by("-nav_date")]

    def get_latest(self, fund_code: str) -> FundNavFact | None:
        m = FundNavFactModel.objects.filter(fund_code=fund_code).order_by("-nav_date").first()
        return self._from_model(m) if m else None

    def bulk_upsert(self, facts: list[FundNavFact]) -> int:
        count = 0
        for f in facts:
            FundNavFactModel.objects.update_or_create(
                fund_code=f.fund_code,
                nav_date=f.nav_date,
                source=f.source,
                defaults=dict(
                    nav=f.nav,
                    acc_nav=f.acc_nav,
                    daily_return=f.daily_return,
                    extra=f.extra,
                ),
            )
            count += 1
        return count


class FinancialFactRepository:
    """ORM-backed repository for financial statement facts."""

    @staticmethod
    def _from_model(m: FinancialFactModel) -> FinancialFact:
        return FinancialFact(
            asset_code=m.asset_code,
            period_end=m.period_end,
            period_type=FinancialPeriodType(m.period_type),
            metric_code=m.metric_code,
            value=float(m.value),
            unit=m.unit,
            source=m.source,
            report_date=m.report_date,
            fetched_at=m.fetched_at,
            extra=m.extra or {},
        )

    def get_facts(
        self,
        asset_code: str,
        period_type: FinancialPeriodType | None = None,
        limit: int = 20,
    ) -> list[FinancialFact]:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = FinancialFactModel.objects.filter(asset_code=candidate)
            if period_type:
                qs = qs.filter(period_type=period_type.value)
            rows = list(qs.order_by("-period_end")[:limit])
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def get_latest(
        self, asset_code: str, period_type: FinancialPeriodType | None = None
    ) -> FinancialFact | None:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = FinancialFactModel.objects.filter(asset_code=candidate)
            if period_type:
                qs = qs.filter(period_type=period_type.value)
            m = qs.order_by("-period_end").first()
            if m is not None:
                return self._from_model(m)
        return None

    def bulk_upsert(self, facts: list[FinancialFact]) -> int:
        count = 0
        for f in facts:
            FinancialFactModel.objects.update_or_create(
                asset_code=f.asset_code,
                period_end=f.period_end,
                period_type=f.period_type.value,
                metric_code=f.metric_code,
                source=f.source,
                defaults=dict(
                    value=f.value,
                    unit=f.unit,
                    report_date=f.report_date,
                    extra=f.extra,
                ),
            )
            count += 1
        return count


class ValuationFactRepository:
    """ORM-backed repository for daily valuation multiples."""

    @staticmethod
    def _from_model(m: ValuationFactModel) -> ValuationFact:
        return ValuationFact(
            asset_code=m.asset_code,
            val_date=m.val_date,
            pe_ttm=float(m.pe_ttm) if m.pe_ttm is not None else None,
            pe_static=float(m.pe_static) if m.pe_static is not None else None,
            pb=float(m.pb) if m.pb is not None else None,
            ps_ttm=float(m.ps_ttm) if m.ps_ttm is not None else None,
            market_cap=float(m.market_cap) if m.market_cap is not None else None,
            float_market_cap=float(m.float_market_cap) if m.float_market_cap is not None else None,
            dv_ratio=float(m.dv_ratio) if m.dv_ratio is not None else None,
            source=m.source,
            fetched_at=m.fetched_at,
            extra=m.extra or {},
        )

    def get_series(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[ValuationFact]:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = ValuationFactModel.objects.filter(asset_code=candidate)
            if start:
                qs = qs.filter(val_date__gte=start)
            if end:
                qs = qs.filter(val_date__lte=end)
            rows = list(qs.order_by("-val_date"))
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def get_latest(self, asset_code: str) -> ValuationFact | None:
        for candidate in _resolve_asset_code_candidates(asset_code):
            m = (
                ValuationFactModel.objects.filter(asset_code=candidate)
                .order_by("-val_date")
                .first()
            )
            if m is not None:
                return self._from_model(m)
        return None

    def bulk_upsert(self, facts: list[ValuationFact]) -> int:
        count = 0
        for f in facts:
            ValuationFactModel.objects.update_or_create(
                asset_code=f.asset_code,
                val_date=f.val_date,
                source=f.source,
                defaults=dict(
                    pe_ttm=f.pe_ttm,
                    pe_static=f.pe_static,
                    pb=f.pb,
                    ps_ttm=f.ps_ttm,
                    market_cap=f.market_cap,
                    float_market_cap=f.float_market_cap,
                    dv_ratio=f.dv_ratio,
                    extra=f.extra,
                ),
            )
            count += 1
        return count


class SectorMembershipRepository:
    """ORM-backed repository for sector / index constituent membership."""

    @staticmethod
    def _from_model(m: SectorMembershipFactModel) -> SectorMembershipFact:
        return SectorMembershipFact(
            asset_code=m.asset_code,
            sector_code=m.sector_code,
            sector_name=m.sector_name,
            effective_date=m.effective_date,
            expiry_date=m.expiry_date,
            weight=float(m.weight) if m.weight is not None else None,
            source=m.source,
            fetched_at=m.fetched_at,
        )

    def get_members(
        self, sector_code: str, as_of: date | None = None
    ) -> list[SectorMembershipFact]:
        qs = SectorMembershipFactModel.objects.filter(sector_code=sector_code)
        if as_of:
            qs = qs.filter(effective_date__lte=as_of).filter(expiry_date__isnull=True) | qs.filter(
                effective_date__lte=as_of, expiry_date__gte=as_of
            )
        return [self._from_model(m) for m in qs]

    def get_sectors_for_asset(
        self, asset_code: str, as_of: date | None = None
    ) -> list[SectorMembershipFact]:
        qs = SectorMembershipFactModel.objects.filter(asset_code=asset_code)
        if as_of:
            qs = qs.filter(effective_date__lte=as_of).filter(expiry_date__isnull=True) | qs.filter(
                effective_date__lte=as_of, expiry_date__gte=as_of
            )
        return [self._from_model(m) for m in qs]

    def bulk_upsert(self, facts: list[SectorMembershipFact]) -> int:
        count = 0
        for f in facts:
            SectorMembershipFactModel.objects.update_or_create(
                asset_code=f.asset_code,
                sector_code=f.sector_code,
                effective_date=f.effective_date,
                defaults=dict(
                    sector_name=f.sector_name,
                    expiry_date=f.expiry_date,
                    weight=f.weight,
                    source=f.source,
                ),
            )
            count += 1
        return count


class NewsRepository:
    """ORM-backed repository for news articles."""

    @staticmethod
    def _from_model(m: NewsFactModel) -> NewsFact:
        return NewsFact(
            asset_code=m.asset_code,
            title=m.title,
            summary=m.summary,
            url=m.url,
            published_at=m.published_at,
            source=m.source,
            external_id=m.external_id,
            sentiment_score=m.sentiment_score,
            extra=m.extra or {},
            fetched_at=m.fetched_at,
        )

    def get_recent(
        self,
        asset_code: str | None = None,
        limit: int = 50,
    ) -> list[NewsFact]:
        qs = NewsFactModel.objects.all()
        if not asset_code:
            return [self._from_model(m) for m in qs.order_by("-published_at")[:limit]]

        for candidate in _resolve_asset_code_candidates(asset_code):
            rows = list(qs.filter(asset_code=candidate).order_by("-published_at")[:limit])
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def bulk_insert(self, articles: list[NewsFact]) -> int:
        count = 0
        for a in articles:
            if not a.external_id:
                # No dedup key — insert unconditionally
                NewsFactModel.objects.create(
                    asset_code=a.asset_code,
                    title=a.title,
                    summary=a.summary,
                    url=a.url,
                    published_at=a.published_at,
                    source=a.source,
                    external_id=a.external_id,
                    sentiment_score=a.sentiment_score,
                    extra=a.extra,
                )
                count += 1
            else:
                _, created = NewsFactModel.objects.get_or_create(
                    source=a.source,
                    external_id=a.external_id,
                    defaults=dict(
                        asset_code=a.asset_code,
                        title=a.title,
                        summary=a.summary,
                        url=a.url,
                        published_at=a.published_at,
                        sentiment_score=a.sentiment_score,
                        extra=a.extra,
                    ),
                )
                if created:
                    count += 1
        return count


class CapitalFlowRepository:
    """ORM-backed repository for capital-flow facts."""

    @staticmethod
    def _from_model(m: CapitalFlowFactModel) -> CapitalFlowFact:
        return CapitalFlowFact(
            asset_code=m.asset_code,
            flow_date=m.flow_date,
            main_net=float(m.main_net) if m.main_net is not None else None,
            retail_net=float(m.retail_net) if m.retail_net is not None else None,
            super_large_net=float(m.super_large_net) if m.super_large_net is not None else None,
            large_net=float(m.large_net) if m.large_net is not None else None,
            medium_net=float(m.medium_net) if m.medium_net is not None else None,
            small_net=float(m.small_net) if m.small_net is not None else None,
            source=m.source,
            fetched_at=m.fetched_at,
            extra=m.extra or {},
        )

    def get_series(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[CapitalFlowFact]:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = CapitalFlowFactModel.objects.filter(asset_code=candidate)
            if start:
                qs = qs.filter(flow_date__gte=start)
            if end:
                qs = qs.filter(flow_date__lte=end)
            rows = list(qs.order_by("-flow_date"))
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def get_latest(self, asset_code: str) -> CapitalFlowFact | None:
        for candidate in _resolve_asset_code_candidates(asset_code):
            m = (
                CapitalFlowFactModel.objects.filter(asset_code=candidate)
                .order_by("-flow_date")
                .first()
            )
            if m is not None:
                return self._from_model(m)
        return None

    def bulk_upsert(self, facts: list[CapitalFlowFact]) -> int:
        count = 0
        for f in facts:
            CapitalFlowFactModel.objects.update_or_create(
                asset_code=f.asset_code,
                flow_date=f.flow_date,
                source=f.source,
                defaults=dict(
                    main_net=f.main_net,
                    retail_net=f.retail_net,
                    super_large_net=f.super_large_net,
                    large_net=f.large_net,
                    medium_net=f.medium_net,
                    small_net=f.small_net,
                    extra=f.extra,
                ),
            )
            count += 1
        return count


class RawAuditRepository:
    """ORM-backed repository for the raw fetch audit log."""

    @staticmethod
    def _from_model(m: RawAuditModel) -> RawAudit:
        return RawAudit(
            provider_name=m.provider_name,
            capability=m.capability,
            request_params=m.request_params or {},
            status=m.status,
            row_count=m.row_count,
            latency_ms=m.latency_ms,
            error_message=m.error_message,
            fetched_at=m.fetched_at,
            extra=m.extra or {},
        )

    def log(self, audit: RawAudit) -> RawAudit:
        m = RawAuditModel.objects.create(
            provider_name=audit.provider_name,
            capability=audit.capability,
            request_params=audit.request_params,
            status=audit.status,
            row_count=audit.row_count,
            latency_ms=audit.latency_ms,
            error_message=audit.error_message,
            fetched_at=audit.fetched_at,
            extra=audit.extra,
        )
        return self._from_model(m)

    def get_recent(
        self,
        provider_name: str | None = None,
        capability: str | None = None,
        limit: int = 100,
    ) -> list[RawAudit]:
        qs = RawAuditModel.objects.all()
        if provider_name:
            qs = qs.filter(provider_name=provider_name)
        if capability:
            qs = qs.filter(capability=capability)
        return [self._from_model(m) for m in qs.order_by("-fetched_at")[:limit]]
