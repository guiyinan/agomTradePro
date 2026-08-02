"""Asset master, publisher, and indicator catalog persistence."""

from __future__ import annotations

from apps.data_center.domain.entities import (
    AssetAlias,
    AssetMaster,
    IndicatorCatalog,
    IndicatorUnitRule,
    PublisherCatalog,
)
from apps.data_center.domain.enums import AssetType, MarketExchange
from apps.data_center.infrastructure._repository_helpers import (
    _dedupe_names,
    _resolve_asset_code_candidates,
)
from apps.data_center.infrastructure.models import (
    AssetAliasModel,
    AssetMasterModel,
    IndicatorCatalogModel,
    IndicatorUnitRuleModel,
    PublisherCatalogModel,
)


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
            defaults={
                "name": asset.name,
                "short_name": asset.short_name,
                "asset_type": asset.asset_type.value,
                "exchange": asset.exchange.value,
                "is_active": asset.is_active,
                "list_date": asset.list_date,
                "delist_date": asset.delist_date,
                "sector": asset.sector,
                "industry": asset.industry,
                "currency": asset.currency,
                "total_shares": asset.total_shares,
                "extra": asset.extra,
            },
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

    def list_active_codes(
        self,
        *,
        asset_type: AssetType | None = None,
        exchanges: tuple[MarketExchange, ...] = (),
    ) -> list[str]:
        """Return canonical active codes without exposing the ORM to consumers."""

        queryset = AssetMasterModel.objects.filter(is_active=True)
        if asset_type is not None:
            queryset = queryset.filter(asset_type=asset_type.value)
        if exchanges:
            queryset = queryset.filter(exchange__in=[item.value for item in exchanges])
        return list(queryset.order_by("code").values_list("code", flat=True))


class PublisherCatalogRepository:
    """ORM-backed repository for provenance publisher definitions."""

    @staticmethod
    def _from_model(m: PublisherCatalogModel) -> PublisherCatalog:
        return PublisherCatalog(
            code=m.code,
            canonical_name=m.canonical_name,
            canonical_name_en=m.canonical_name_en,
            publisher_class=m.publisher_class,
            aliases=list(m.aliases or []),
            country_code=m.country_code,
            website=m.website,
            is_active=m.is_active,
            description=m.description,
        )

    def get_by_code(self, code: str) -> PublisherCatalog | None:
        try:
            return self._from_model(PublisherCatalogModel.objects.get(code=code.strip().upper()))
        except PublisherCatalogModel.DoesNotExist:
            return None

    def list_all(self) -> list[PublisherCatalog]:
        return [self._from_model(m) for m in PublisherCatalogModel.objects.all()]

    def list_active(self) -> list[PublisherCatalog]:
        return [self._from_model(m) for m in PublisherCatalogModel.objects.filter(is_active=True)]

    def upsert(self, publisher: PublisherCatalog) -> PublisherCatalog:
        aliases = _dedupe_names(
            [
                alias
                for alias in publisher.aliases
                if alias.strip() and alias.strip() != publisher.canonical_name.strip()
            ]
        )
        model, _ = PublisherCatalogModel.objects.update_or_create(
            code=publisher.code.strip().upper(),
            defaults={
                "canonical_name": publisher.canonical_name,
                "canonical_name_en": publisher.canonical_name_en,
                "publisher_class": publisher.publisher_class,
                "aliases": aliases,
                "country_code": publisher.country_code,
                "website": publisher.website,
                "is_active": publisher.is_active,
                "description": publisher.description,
            },
        )
        return self._from_model(model)

    def delete(self, code: str) -> None:
        PublisherCatalogModel.objects.filter(code=code.strip().upper()).delete()


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
            defaults={
                "name_cn": catalog.name_cn,
                "name_en": catalog.name_en,
                "description": catalog.description,
                "default_unit": catalog.default_unit,
                "default_period_type": catalog.default_period_type,
                "category": catalog.category,
                "is_active": catalog.is_active,
                "extra": catalog.extra,
            },
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
            defaults={
                "dimension_key": rule.dimension_key,
                "storage_unit": rule.storage_unit,
                "display_unit": rule.display_unit,
                "multiplier_to_storage": rule.multiplier_to_storage,
                "is_active": rule.is_active,
                "priority": rule.priority,
                "description": rule.description,
            },
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

        scoped = (
            list(queryset.filter(source_type=source_type).order_by("-priority", "id")[:1])
            if source_type
            else []
        )
        if scoped:
            return self._from_model(scoped[0])

        fallback = queryset.filter(source_type="").order_by("-priority", "id").first()
        return self._from_model(fallback) if fallback else None
