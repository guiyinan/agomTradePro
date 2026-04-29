"""Phase 3 sync use case tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from apps.data_center.application.dtos import (
    SyncMacroRequest,
    SyncNewsRequest,
)
from apps.data_center.application.use_cases import (
    SyncMacroUseCase,
    SyncNewsUseCase,
)
from apps.data_center.domain.entities import MacroFact, NewsFact, ProviderConfig, RawAudit
from apps.data_center.domain.entities import IndicatorCatalog, IndicatorUnitRule


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        id=1,
        name="provider-main",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="token",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )


class _ProviderRepo:
    def __init__(self):
        self.saved: list[ProviderConfig] = []

    def get_by_id(self, provider_id: int):
        return _provider_config() if provider_id == 1 else None

    def save(self, config: ProviderConfig):
        self.saved.append(config)
        return config


class _ProviderFactory:
    def __init__(self, provider):
        self._provider = provider

    def get_by_id(self, provider_id: int):
        return self._provider if provider_id == 1 else None


class _RawAuditRepo:
    def __init__(self):
        self.items: list[RawAudit] = []

    def log(self, audit: RawAudit):
        self.items.append(audit)
        return audit


class _MacroFactRepo:
    def __init__(self):
        self.saved: list[MacroFact] = []

    def bulk_upsert(self, facts: list[MacroFact]) -> int:
        self.saved.extend(facts)
        return len(facts)


class _IndicatorCatalogRepo:
    def __init__(self, items: list[IndicatorCatalog] | None = None):
        self._items = {item.code: item for item in (items or [])}

    def get_by_code(self, code: str):
        return self._items.get(code)


class _IndicatorUnitRuleRepo:
    def __init__(self, rules: list[IndicatorUnitRule] | None = None):
        self._rules = rules or []

    def resolve_active_rule(
        self,
        indicator_code: str,
        *,
        source_type: str = "",
        original_unit: str | None = None,
    ):
        candidates = [
            rule
            for rule in self._rules
            if rule.indicator_code == indicator_code and rule.is_active
        ]
        if original_unit is not None:
            candidates = [rule for rule in candidates if rule.original_unit == original_unit]
        if source_type:
            scoped = [rule for rule in candidates if rule.source_type == source_type]
            if scoped:
                return sorted(scoped, key=lambda item: (-item.priority, item.id or 0))[0]
        defaults = [rule for rule in candidates if rule.source_type == ""]
        if defaults:
            return sorted(defaults, key=lambda item: (-item.priority, item.id or 0))[0]
        return None


class _NewsRepo:
    def __init__(self):
        self.saved: list[NewsFact] = []

    def bulk_insert(self, articles: list[NewsFact]) -> int:
        self.saved.extend(articles)
        return len(articles)


class _Provider:
    def provider_name(self) -> str:
        return "provider-main"

    def fetch_macro_series(self, indicator_code: str, start_date: date, end_date: date):
        return [
            MacroFact(
                indicator_code=indicator_code,
                reporting_period=date(2025, 3, 1),
                value=5.2,
                unit="%",
                source="provider-main",
            )
        ]

    def fetch_news(self, asset_code: str, limit: int = 20):
        return [
            NewsFact(
                asset_code=asset_code,
                title="headline",
                summary="summary",
                published_at=datetime(2025, 3, 2, tzinfo=timezone.utc),
                source="provider-main",
                external_id="news-1",
            )
        ]


def test_sync_macro_use_case_stores_facts_and_audit():
    provider = _Provider()
    provider_repo = _ProviderRepo()
    raw_repo = _RawAuditRepo()
    fact_repo = _MacroFactRepo()
    catalog_repo = _IndicatorCatalogRepo(
        [
            IndicatorCatalog(
                code="CN_PMI",
                name_cn="采购经理指数",
                name_en="PMI",
                description="",
                category="growth",
                default_period_type="M",
                default_unit="%",
                is_active=True,
                extra={},
            )
        ]
    )
    unit_rule_repo = _IndicatorUnitRuleRepo(
        [
            IndicatorUnitRule(
                id=1,
                indicator_code="CN_PMI",
                source_type="tushare",
                dimension_key="rate",
                original_unit="%",
                storage_unit="%",
                display_unit="%",
                multiplier_to_storage=1.0,
                is_active=True,
                priority=10,
                description="",
            )
        ]
    )
    use_case = SyncMacroUseCase(
        provider_repo=provider_repo,
        provider_factory=_ProviderFactory(provider),
        fact_repo=fact_repo,
        catalog_repo=catalog_repo,
        unit_rule_repo=unit_rule_repo,
        raw_audit_repo=raw_repo,
    )

    result = use_case.execute(
        SyncMacroRequest(
            provider_id=1,
            indicator_code="CN_PMI",
            start=date(2025, 3, 1),
            end=date(2025, 3, 31),
        )
    )

    assert result.domain == "macro"
    assert result.stored_count == 1
    assert len(fact_repo.saved) == 1
    assert len(raw_repo.items) == 1
    assert raw_repo.items[0].capability == "macro"
    assert raw_repo.items[0].status == "ok"
    assert provider_repo.saved
    assert provider_repo.saved[-1].extra_config["health_metrics"]["macro"]["last_success_at"]


def test_sync_news_use_case_stores_articles_and_audit():
    provider = _Provider()
    provider_repo = _ProviderRepo()
    raw_repo = _RawAuditRepo()
    news_repo = _NewsRepo()
    use_case = SyncNewsUseCase(
        provider_repo=provider_repo,
        provider_factory=_ProviderFactory(provider),
        fact_repo=news_repo,
        raw_audit_repo=raw_repo,
    )

    result = use_case.execute(
        SyncNewsRequest(
            provider_id=1,
            asset_code="000001.SZ",
            limit=10,
        )
    )

    assert result.domain == "news"
    assert result.stored_count == 1
    assert len(news_repo.saved) == 1
    assert news_repo.saved[0].external_id == "news-1"
    assert raw_repo.items[0].capability == "news"
