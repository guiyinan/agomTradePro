"""Provider and catalog management use cases for Data Center."""

from __future__ import annotations

import logging

from apps.data_center.application.dtos import (
    CreateIndicatorCatalogRequest,
    CreateIndicatorUnitRuleRequest,
    CreateProviderRequest,
    CreatePublisherCatalogRequest,
    IndicatorCatalogResponse,
    IndicatorUnitRuleResponse,
    ProviderResponse,
    PublisherCatalogResponse,
    UpdateIndicatorCatalogRequest,
    UpdateIndicatorUnitRuleRequest,
    UpdateProviderRequest,
    UpdatePublisherCatalogRequest,
)
from apps.data_center.domain.entities import (
    IndicatorCatalog,
    IndicatorUnitRule,
    ProviderConfig,
    PublisherCatalog,
)
from apps.data_center.domain.protocols import (
    IndicatorCatalogRepositoryProtocol,
    IndicatorUnitRuleRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    PublisherCatalogRepositoryProtocol,
)

logger = logging.getLogger(__name__)


def _config_to_response(config: ProviderConfig) -> ProviderResponse:
    return ProviderResponse(
        id=config.id,
        name=config.name,
        source_type=config.source_type,
        is_active=config.is_active,
        priority=config.priority,
        has_api_key=bool(config.api_key),
        has_api_secret=bool(config.api_secret),
        http_url=config.http_url,
        api_endpoint=config.api_endpoint,
        extra_config=config.extra_config,
        description=config.description,
    )


def _publisher_to_response(publisher: PublisherCatalog) -> PublisherCatalogResponse:
    return PublisherCatalogResponse(
        code=publisher.code,
        canonical_name=publisher.canonical_name,
        publisher_class=publisher.publisher_class,
        aliases=list(publisher.aliases),
        canonical_name_en=publisher.canonical_name_en,
        country_code=publisher.country_code,
        website=publisher.website,
        is_active=publisher.is_active,
        description=publisher.description,
    )


def _catalog_to_response(
    catalog: IndicatorCatalog,
    *,
    default_rule: IndicatorUnitRule | None = None,
) -> IndicatorCatalogResponse:
    return IndicatorCatalogResponse(
        code=catalog.code,
        name_cn=catalog.name_cn,
        name_en=catalog.name_en,
        description=catalog.description,
        category=catalog.category,
        default_period_type=catalog.default_period_type,
        is_active=catalog.is_active,
        extra=catalog.extra,
        default_rule=default_rule.to_dict() if default_rule else None,
    )


def _unit_rule_to_response(rule: IndicatorUnitRule) -> IndicatorUnitRuleResponse:
    return IndicatorUnitRuleResponse(
        id=rule.id,
        indicator_code=rule.indicator_code,
        source_type=rule.source_type,
        dimension_key=rule.dimension_key,
        original_unit=rule.original_unit,
        storage_unit=rule.storage_unit,
        display_unit=rule.display_unit,
        multiplier_to_storage=rule.multiplier_to_storage,
        is_active=rule.is_active,
        priority=rule.priority,
        description=rule.description,
    )


class ManageProviderConfigUseCase:
    """CRUD operations for provider configurations.

    Args:
        repo: Injected ProviderConfigRepositoryProtocol implementation.
    """

    def __init__(self, repo: ProviderConfigRepositoryProtocol) -> None:
        self._repo = repo

    def list_all(self) -> list[ProviderResponse]:
        return [_config_to_response(c) for c in self._repo.list_all()]

    def get(self, provider_id: int) -> ProviderResponse | None:
        config = self._repo.get_by_id(provider_id)
        return _config_to_response(config) if config else None

    def create(self, request: CreateProviderRequest) -> ProviderResponse:
        config = ProviderConfig(
            id=None,
            name=request.name,
            source_type=request.source_type,
            is_active=request.is_active,
            priority=request.priority,
            api_key=request.api_key,
            api_secret=request.api_secret,
            http_url=request.http_url,
            api_endpoint=request.api_endpoint,
            extra_config=request.extra_config,
            description=request.description,
        )
        saved = self._repo.save(config)
        logger.info("Created provider config: %s", saved.name)
        return _config_to_response(saved)

    def update(self, request: UpdateProviderRequest) -> ProviderResponse | None:
        existing = self._repo.get_by_id(request.provider_id)
        if existing is None:
            return None

        updated = ProviderConfig(
            id=existing.id,
            name=request.name if request.name is not None else existing.name,
            source_type=(
                request.source_type if request.source_type is not None else existing.source_type
            ),
            is_active=(request.is_active if request.is_active is not None else existing.is_active),
            priority=(request.priority if request.priority is not None else existing.priority),
            api_key=(request.api_key if request.api_key is not None else existing.api_key),
            api_secret=(
                request.api_secret if request.api_secret is not None else existing.api_secret
            ),
            http_url=(request.http_url if request.http_url is not None else existing.http_url),
            api_endpoint=(
                request.api_endpoint if request.api_endpoint is not None else existing.api_endpoint
            ),
            extra_config=(
                request.extra_config if request.extra_config is not None else existing.extra_config
            ),
            description=(
                request.description if request.description is not None else existing.description
            ),
        )
        saved = self._repo.save(updated)
        logger.info("Updated provider config id=%s name=%s", saved.id, saved.name)
        return _config_to_response(saved)

    def delete(self, provider_id: int) -> bool:
        if self._repo.get_by_id(provider_id) is None:
            return False
        self._repo.delete(provider_id)
        logger.info("Deleted provider config id=%s", provider_id)
        return True


class ManagePublisherCatalogUseCase:
    """CRUD operations for provenance publisher definitions."""

    def __init__(self, repo: PublisherCatalogRepositoryProtocol) -> None:
        self._repo = repo

    def list_all(self, *, active_only: bool = False) -> list[PublisherCatalogResponse]:
        publishers = self._repo.list_active() if active_only else self._repo.list_all()
        return [_publisher_to_response(item) for item in publishers]

    def get(self, code: str) -> PublisherCatalogResponse | None:
        publisher = self._repo.get_by_code(code)
        return _publisher_to_response(publisher) if publisher else None

    def create(self, request: CreatePublisherCatalogRequest) -> PublisherCatalogResponse:
        publisher = PublisherCatalog(
            code=request.code.strip().upper(),
            canonical_name=request.canonical_name,
            publisher_class=request.publisher_class,
            aliases=list(request.aliases),
            canonical_name_en=request.canonical_name_en,
            country_code=request.country_code,
            website=request.website,
            is_active=request.is_active,
            description=request.description,
        )
        saved = self._repo.upsert(publisher)
        return _publisher_to_response(saved)

    def update(self, request: UpdatePublisherCatalogRequest) -> PublisherCatalogResponse | None:
        existing = self._repo.get_by_code(request.code)
        if existing is None:
            return None
        updated = PublisherCatalog(
            code=existing.code.strip().upper(),
            canonical_name=(
                request.canonical_name
                if request.canonical_name is not None
                else existing.canonical_name
            ),
            publisher_class=(
                request.publisher_class
                if request.publisher_class is not None
                else existing.publisher_class
            ),
            aliases=request.aliases if request.aliases is not None else list(existing.aliases),
            canonical_name_en=(
                request.canonical_name_en
                if request.canonical_name_en is not None
                else existing.canonical_name_en
            ),
            country_code=(
                request.country_code if request.country_code is not None else existing.country_code
            ),
            website=request.website if request.website is not None else existing.website,
            is_active=request.is_active if request.is_active is not None else existing.is_active,
            description=(
                request.description if request.description is not None else existing.description
            ),
        )
        saved = self._repo.upsert(updated)
        return _publisher_to_response(saved)

    def delete(self, code: str) -> bool:
        if self._repo.get_by_code(code) is None:
            return False
        self._repo.delete(code)
        return True


class ManageIndicatorCatalogUseCase:
    """CRUD operations for indicator catalog definitions."""

    def __init__(
        self,
        repo: IndicatorCatalogRepositoryProtocol,
        unit_rule_repo: IndicatorUnitRuleRepositoryProtocol,
    ) -> None:
        self._repo = repo
        self._unit_rules = unit_rule_repo

    def list_all(self, *, active_only: bool = False) -> list[IndicatorCatalogResponse]:
        catalogs = self._repo.list_active() if active_only else self._repo.list_all()
        return [
            _catalog_to_response(
                catalog,
                default_rule=self._unit_rules.resolve_active_rule(catalog.code),
            )
            for catalog in catalogs
        ]

    def get(self, code: str) -> IndicatorCatalogResponse | None:
        catalog = self._repo.get_by_code(code)
        if catalog is None:
            return None
        return _catalog_to_response(
            catalog,
            default_rule=self._unit_rules.resolve_active_rule(code),
        )

    def create(self, request: CreateIndicatorCatalogRequest) -> IndicatorCatalogResponse:
        catalog = IndicatorCatalog(
            code=request.code,
            name_cn=request.name_cn,
            name_en=request.name_en,
            description=request.description,
            default_period_type=request.default_period_type,
            category=request.category,
            is_active=request.is_active,
            extra=request.extra,
        )
        saved = self._repo.upsert(catalog)
        return _catalog_to_response(saved)

    def update(self, request: UpdateIndicatorCatalogRequest) -> IndicatorCatalogResponse | None:
        existing = self._repo.get_by_code(request.code)
        if existing is None:
            return None

        updated = IndicatorCatalog(
            code=existing.code,
            name_cn=request.name_cn if request.name_cn is not None else existing.name_cn,
            name_en=request.name_en if request.name_en is not None else existing.name_en,
            description=(
                request.description if request.description is not None else existing.description
            ),
            default_period_type=(
                request.default_period_type
                if request.default_period_type is not None
                else existing.default_period_type
            ),
            category=request.category if request.category is not None else existing.category,
            is_active=request.is_active if request.is_active is not None else existing.is_active,
            extra=request.extra if request.extra is not None else existing.extra,
        )
        saved = self._repo.upsert(updated)
        return _catalog_to_response(
            saved,
            default_rule=self._unit_rules.resolve_active_rule(saved.code),
        )

    def delete(self, code: str) -> bool:
        if self._repo.get_by_code(code) is None:
            return False
        self._repo.delete(code)
        return True


class ManageIndicatorUnitRuleUseCase:
    """CRUD operations for indicator unit-governance rules."""

    def __init__(
        self,
        catalog_repo: IndicatorCatalogRepositoryProtocol,
        repo: IndicatorUnitRuleRepositoryProtocol,
    ) -> None:
        self._catalog = catalog_repo
        self._repo = repo

    def list_by_indicator(self, indicator_code: str) -> list[IndicatorUnitRuleResponse]:
        return [
            _unit_rule_to_response(rule) for rule in self._repo.list_by_indicator(indicator_code)
        ]

    def get(self, rule_id: int) -> IndicatorUnitRuleResponse | None:
        rule = self._repo.get_by_id(rule_id)
        return _unit_rule_to_response(rule) if rule else None

    def create(self, request: CreateIndicatorUnitRuleRequest) -> IndicatorUnitRuleResponse:
        if self._catalog.get_by_code(request.indicator_code) is None:
            raise ValueError(f"Unknown indicator code: {request.indicator_code}")
        rule = IndicatorUnitRule(
            id=None,
            indicator_code=request.indicator_code,
            source_type=request.source_type,
            dimension_key=request.dimension_key,
            original_unit=request.original_unit,
            storage_unit=request.storage_unit,
            display_unit=request.display_unit,
            multiplier_to_storage=request.multiplier_to_storage,
            is_active=request.is_active,
            priority=request.priority,
            description=request.description,
        )
        saved = self._repo.upsert(rule)
        return _unit_rule_to_response(saved)

    def update(self, request: UpdateIndicatorUnitRuleRequest) -> IndicatorUnitRuleResponse | None:
        existing = self._repo.get_by_id(request.rule_id)
        if existing is None:
            return None

        next_indicator_code = request.indicator_code or existing.indicator_code
        if self._catalog.get_by_code(next_indicator_code) is None:
            raise ValueError(f"Unknown indicator code: {next_indicator_code}")

        updated = IndicatorUnitRule(
            id=existing.id,
            indicator_code=next_indicator_code,
            source_type=(
                request.source_type if request.source_type is not None else existing.source_type
            ),
            dimension_key=(
                request.dimension_key
                if request.dimension_key is not None
                else existing.dimension_key
            ),
            original_unit=(
                request.original_unit
                if request.original_unit is not None
                else existing.original_unit
            ),
            storage_unit=(
                request.storage_unit if request.storage_unit is not None else existing.storage_unit
            ),
            display_unit=(
                request.display_unit if request.display_unit is not None else existing.display_unit
            ),
            multiplier_to_storage=(
                request.multiplier_to_storage
                if request.multiplier_to_storage is not None
                else existing.multiplier_to_storage
            ),
            is_active=request.is_active if request.is_active is not None else existing.is_active,
            priority=request.priority if request.priority is not None else existing.priority,
            description=(
                request.description if request.description is not None else existing.description
            ),
        )
        saved = self._repo.upsert(updated)
        return _unit_rule_to_response(saved)

    def delete(self, rule_id: int) -> bool:
        if self._repo.get_by_id(rule_id) is None:
            return False
        self._repo.delete(rule_id)
        return True


__all__ = [
    "ManageIndicatorCatalogUseCase",
    "ManageIndicatorUnitRuleUseCase",
    "ManageProviderConfigUseCase",
    "ManagePublisherCatalogUseCase",
]
