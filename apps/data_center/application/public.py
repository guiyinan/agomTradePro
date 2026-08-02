"""Stable Data Center Application Public Ports.

Business applications may import this module, but must not import Data Center
ORM models, repositories or provider adapters.  The functions intentionally
return plain DTO-shaped values for the current migration bridge; new callers
can use the typed contracts in :mod:`apps.data_center.domain.contracts`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Any

from apps.data_center.application.query_services import (
    fetch_price_bar_payloads,
    get_latest_macro_indicator_value,
    get_macro_indicator_metadata,
    get_runtime_macro_metadata_map,
    list_active_asset_codes,
    list_active_provider_summaries,
    list_latest_macro_indicator_payloads,
    list_price_covered_asset_codes,
    list_valuation_covered_asset_codes,
    query_financial_facts,
    query_latest_quote_payloads,
    query_macro_fact_series,
    query_published_a_share_behavior_payload,
    query_published_capital_flow_series,
    query_published_macro_fact_series,
    query_published_market_news,
    query_published_price_bar_series,
    query_published_quote_payloads,
    query_published_sector_memberships,
    query_valuation_facts,
)
from apps.data_center.application.reconciliation import RecordReconciliationEvidenceUseCase
from apps.data_center.composition import (
    backfill_asset_master_codes,
    build_provider_registry_for_repo,
    build_tushare_client,
    get_akshare_eastmoney_gateway,
    get_akshare_module,
    get_asset_repository,
    get_canonical_publication_repository,
    get_capital_flow_repository,
    get_data_owner_registry_repository,
    get_dataset_contract_repository,
    get_fund_nav_repository,
    get_macro_fact_repository,
    get_macro_projection_repository,
    get_news_repository,
    get_price_bar_repository,
    get_provider_binding_repository,
    get_provider_config_repository,
    get_provider_registry,
    get_publication_policy_repository,
    get_quote_snapshot_repository,
    get_raw_audit_repository,
    get_reconciliation_evidence_repository,
    get_sector_membership_repository,
    get_valuation_fact_repository,
)
from apps.data_center.domain.contracts import (
    DataOwnerRegistration,
    DatasetContract,
    ProviderBinding,
    PublicationPolicy,
)
from apps.data_center.domain.entities import MacroFact
from apps.data_center.domain.macro_semantics import (
    is_direct_consumer_input_allowed as _is_direct_consumer_input_allowed,
)
from apps.data_center.domain.protocols import (
    AssetRepositoryProtocol,
    CapitalFlowRepositoryProtocol,
    FundNavRepositoryProtocol,
    NewsRepositoryProtocol,
    PriceBarRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    QuoteSnapshotRepositoryProtocol,
    RawAuditRepositoryProtocol,
    SectorMembershipRepositoryProtocol,
    ValuationFactRepositoryProtocol,
)
from apps.data_center.domain.reconciliation import ReconciliationEvidence, ReconciliationReport


def get_macro_projection_repository_port() -> object:
    """Return the Data Center-owned macro administrative projection port.

    The concrete repository remains behind the application public boundary;
    this compatibility seam is temporary until the macro UI is fully typed.
    """

    return get_macro_projection_repository()


def record_reconciliation_evidence(
    report: ReconciliationReport,
    *,
    legacy_snapshot_hash: str,
    canonical_snapshot_hash: str,
    evidence_id: str | None = None,
    observed_at: datetime | None = None,
) -> ReconciliationEvidence:
    """Persist maintenance-only shadow evidence behind an Application Port."""

    return RecordReconciliationEvidenceUseCase(get_reconciliation_evidence_repository()).execute(
        report,
        legacy_snapshot_hash=legacy_snapshot_hash,
        canonical_snapshot_hash=canonical_snapshot_hash,
        evidence_id=evidence_id,
        observed_at=observed_at,
    )


def get_latest_reconciliation_evidence(dataset_key: str) -> ReconciliationEvidence | None:
    """Return the newest shadow evidence for operational readiness checks."""

    return get_reconciliation_evidence_repository().get_latest(dataset_key)


def list_active_dataset_contracts() -> list[DatasetContract]:
    """Return the active version of every persisted Dataset Contract."""

    return get_dataset_contract_repository().list_active()


def get_active_dataset_contract(dataset_key: str) -> DatasetContract | None:
    """Return one active Dataset Contract or ``None`` when unregistered."""

    return get_dataset_contract_repository().get_active(dataset_key)


def list_active_provider_bindings(dataset_key: str | None = None) -> list[ProviderBinding]:
    """Return active provider bindings for a dataset or the full catalog."""

    return get_provider_binding_repository().list_active(dataset_key)


def get_active_publication_policy(dataset_key: str) -> PublicationPolicy | None:
    """Return the active publication policy for one dataset."""

    return get_publication_policy_repository().get_active(dataset_key)


def list_active_publication_policies() -> list[PublicationPolicy]:
    """Return all active Dataset Publication Policies in stable order."""

    return get_publication_policy_repository().list_active()


def list_active_data_owner_registrations() -> list[DataOwnerRegistration]:
    """Return active Data Center ownership registrations."""

    return get_data_owner_registry_repository().list_active()


def get_asset_repository_port() -> AssetRepositoryProtocol:
    """Return the canonical asset-master/alias query port."""

    return get_asset_repository()


def get_akshare_module_port() -> Any:
    """Return the configured AKShare module behind the public transport port."""

    return get_akshare_module()


def get_akshare_eastmoney_gateway_port() -> object:
    """Return the Data Center-owned EastMoney market gateway."""

    return get_akshare_eastmoney_gateway()


def backfill_asset_master_codes_port(
    asset_codes: list[str],
    *,
    include_remote: bool = True,
) -> object:
    """Backfill canonical asset identities through the Application boundary."""

    return backfill_asset_master_codes(asset_codes, include_remote=include_remote)


def is_direct_macro_input_allowed(
    extra: dict[str, Any] | None,
    *,
    consumer: str,
) -> bool:
    """Read the canonical macro semantic policy through the public port."""

    return _is_direct_consumer_input_allowed(extra, consumer=consumer)


def get_fund_nav_repository_port() -> FundNavRepositoryProtocol:
    """Return the typed canonical fund-NAV port for other applications."""

    return get_fund_nav_repository()


def get_price_bar_repository_port() -> PriceBarRepositoryProtocol:
    """Return the typed canonical OHLCV port for other applications."""

    return get_price_bar_repository()


def get_quote_snapshot_repository_port() -> QuoteSnapshotRepositoryProtocol:
    """Return the typed canonical quote-snapshot port."""

    return get_quote_snapshot_repository()


def get_provider_config_repository_port() -> ProviderConfigRepositoryProtocol:
    """Return the typed provider configuration port."""

    return get_provider_config_repository()


def get_provider_registry_port() -> ProviderRegistryProtocol:
    """Return the canonical provider registry port."""

    return get_provider_registry()


def build_provider_registry_port(
    repository: ProviderConfigRepositoryProtocol,
) -> ProviderRegistryProtocol:
    """Build an isolated provider registry from an injected config port."""

    return build_provider_registry_for_repo(repository)


def get_raw_audit_repository_port() -> RawAuditRepositoryProtocol:
    """Return the raw-fetch audit port."""

    return get_raw_audit_repository()


def get_valuation_fact_repository_port() -> ValuationFactRepositoryProtocol:
    """Return the typed canonical valuation-fact port."""

    return get_valuation_fact_repository()


def get_sector_membership_repository_port() -> SectorMembershipRepositoryProtocol:
    """Return the canonical sector-membership query port."""

    return get_sector_membership_repository()


def get_news_repository_port() -> NewsRepositoryProtocol:
    """Return the canonical news-fact query port."""

    return get_news_repository()


def get_capital_flow_repository_port() -> CapitalFlowRepositoryProtocol:
    """Return the canonical capital-flow query port."""

    return get_capital_flow_repository()


def get_tushare_client(*, token: str | None = None, http_url: str | None = None) -> object:
    """Return the Data Center-owned Tushare transport for migration adapters."""

    return build_tushare_client(token=token, http_url=http_url)


def get_macro_indicator_value(indicator_code: str) -> float | None:
    """Read one canonical macro value."""

    return get_latest_macro_indicator_value(indicator_code)


def list_latest_macro_values(limit: int = 50) -> list[dict[str, Any]]:
    """Read latest canonical macro values for a bounded consumer snapshot."""

    return list_latest_macro_indicator_payloads(limit=limit)


def get_macro_fact_series(
    indicator_code: str,
    *,
    start: date | None = None,
    end: date | None = None,
    limit: int = 500,
    use_pit: bool = False,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Read canonical macro facts with optional publication-time boundaries."""

    return query_macro_fact_series(
        indicator_code,
        start=start,
        end=end,
        limit=limit,
        use_pit=use_pit,
        source=source,
    )


def get_published_macro_fact_series(
    indicator_code: str,
    *,
    publication_key: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = 500,
) -> dict[str, object]:
    """Read a decision-facing macro series behind a publication gate."""

    return query_published_macro_fact_series(
        indicator_code,
        publication_key=publication_key,
        start=start,
        end=end,
        limit=limit,
    )


def get_published_quote_payloads(
    asset_codes: list[str],
    *,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read decision-facing quotes only when publication is current."""

    return query_published_quote_payloads(asset_codes, publication_key=publication_key)


def get_published_price_bar_series(
    asset_code: str,
    *,
    publication_key: str = "current",
    start: date | None = None,
    end: date | None = None,
    limit: int = 500,
) -> dict[str, object]:
    """Read decision-facing price bars only when publication is current."""

    return query_published_price_bar_series(
        asset_code,
        publication_key=publication_key,
        start=start,
        end=end,
        limit=limit,
    )


def get_published_sector_memberships(
    sector_code: str,
    *,
    as_of: date | None = None,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read decision-facing sector membership facts behind publication."""

    return query_published_sector_memberships(
        sector_code,
        as_of=as_of,
        publication_key=publication_key,
    )


def get_published_market_news(
    *,
    asset_code: str | None = None,
    target_date: date | None = None,
    limit: int = 50,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read decision-facing news facts behind publication."""

    return query_published_market_news(
        asset_code=asset_code,
        target_date=target_date,
        limit=limit,
        publication_key=publication_key,
    )


def get_published_capital_flow_series(
    asset_code: str,
    *,
    start: date | None = None,
    end: date | None = None,
    limit: int | None = None,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read decision-facing capital-flow facts behind publication."""

    return query_published_capital_flow_series(
        asset_code,
        start=start,
        end=end,
        limit=limit,
        publication_key=publication_key,
    )


def get_macro_indicator_catalog(indicator_code: str) -> dict[str, Any]:
    """Read one indicator catalog entry through the application port."""

    return get_macro_indicator_metadata(indicator_code)


def list_active_data_sources() -> list[dict[str, str]]:
    """Read active provider summaries through the canonical application port."""

    return list_active_provider_summaries()


def save_data_source_configuration(
    *,
    source_type: str,
    name: str,
    api_key: str,
    http_url: str = "",
    api_endpoint: str = "",
) -> dict[str, str | int | bool]:
    """Persist one provider configuration through the Data Center boundary."""

    from apps.data_center.domain.entities import ProviderConfig

    existing = get_provider_config_repository().get_active_by_type(source_type)
    current = existing[0] if existing else None
    saved = get_provider_config_repository().save(
        ProviderConfig(
            id=current.id if current is not None else None,
            name=name,
            source_type=source_type,
            is_active=True,
            priority=current.priority if current is not None else 100,
            api_key=api_key,
            api_secret=current.api_secret if current is not None else "",
            http_url=http_url,
            api_endpoint=api_endpoint,
            extra_config=current.extra_config if current is not None else {},
            description=current.description if current is not None else "",
        )
    )
    return {
        "id": saved.id or 0,
        "name": saved.name,
        "source_type": saved.source_type,
        "is_active": saved.is_active,
    }


def update_asset_display_name(asset_code: str, name: str) -> bool:
    """Update an existing canonical asset name without exposing its ORM."""

    asset_repo = get_asset_repository()
    asset = asset_repo.get_by_code(asset_code)
    normalized_name = name.strip()
    if asset is None or not normalized_name:
        return False
    asset_repo.upsert(replace(asset, name=normalized_name, short_name=normalized_name))
    return True


def save_macro_facts(facts: list[MacroFact]) -> int:
    """Persist validated canonical macro facts through the application port."""

    return get_macro_fact_repository().bulk_upsert(facts)


def list_macro_facts_by_original_unit(
    original_unit: str,
    *,
    limit: int = 100_000,
) -> list[MacroFact]:
    """List canonical macro facts for a bounded unit-normalization repair."""

    return get_macro_fact_repository().list_by_original_unit(original_unit, limit=limit)


def get_macro_runtime_metadata() -> dict[str, dict[str, Any]]:
    """Read the catalog-backed macro runtime metadata map."""

    return get_runtime_macro_metadata_map()


def list_macro_indicator_codes() -> list[str]:
    """Return active macro indicator codes from the canonical catalog."""

    return sorted(get_macro_runtime_metadata())


def get_market_breadth_snapshot() -> dict[str, Any]:
    """Read the canonical market-breadth snapshot and reliability contract."""

    return query_published_a_share_behavior_payload()


def list_active_stock_codes() -> list[str]:
    """Read the canonical active A-share universe."""

    return list_active_asset_codes()


def list_price_covered_codes(as_of: date | None = None) -> list[str]:
    """Read canonical price coverage through a bounded application port."""

    return list_price_covered_asset_codes(as_of)


def list_valuation_covered_codes(as_of: date | None = None) -> list[str]:
    """Read canonical valuation coverage through a bounded application port."""

    return list_valuation_covered_asset_codes(as_of)


def get_financial_facts(asset_code: str, *, limit: int = 20) -> list[dict[str, object]]:
    """Read canonical financial facts for one asset."""

    return query_financial_facts(asset_code, limit=limit)


def get_valuation_facts(
    asset_code: str,
    *,
    as_of: date | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    """Read canonical valuation facts for one asset."""

    return query_valuation_facts(asset_code, as_of=as_of, limit=limit)


def get_latest_quote_payloads(
    asset_codes: list[str],
    *,
    observed_after: datetime | None = None,
) -> list[dict[str, object]]:
    """Read latest canonical quotes for a bounded list of assets."""

    return query_latest_quote_payloads(asset_codes, observed_after=observed_after)


def get_price_bar_series(
    asset_code: str,
    *,
    start: date | None = None,
    end: date | None = None,
    limit: int = 500,
) -> list[dict[str, object]]:
    """Read canonical OHLCV bars through the public query port."""

    return fetch_price_bar_payloads(
        asset_code=asset_code,
        start_date=start,
        end_date=end,
        limit=limit,
    )


def get_current_publication(
    dataset_key: str,
    publication_key: str,
) -> dict[str, object] | None:
    """Return the active published selection for a canonical dataset scope."""

    publication = get_canonical_publication_repository().get_current(dataset_key, publication_key)
    if publication is None:
        return None
    return {
        "publication_id": publication.publication_id,
        "dataset_key": publication.dataset_key,
        "publication_key": publication.publication_key,
        "policy_version": publication.policy_version,
        "state": publication.state.value,
        "selected_source": publication.selected_source,
        "publication_hash": publication.publication_hash,
        "coverage_ratio": publication.coverage.coverage_ratio,
        "coverage": {
            "requested_count": publication.coverage.requested_count,
            "eligible_count": publication.coverage.eligible_count,
            "selected_count": publication.coverage.selected_count,
            "missing_count": publication.coverage.missing_count,
            "conflict_count": publication.coverage.conflict_count,
        },
        "published_at": publication.published_at.isoformat() if publication.published_at else None,
        "as_of": publication.as_of.isoformat() if publication.as_of else None,
        "must_not_use_for_decision": publication.must_not_use_for_decision,
        "blocked_reason": publication.blocked_reason,
    }


def get_publication_as_of(
    dataset_key: str,
    publication_key: str,
    as_of: datetime,
) -> dict[str, object] | None:
    """Return the publication visible at an explicit historical boundary."""

    publication = get_canonical_publication_repository().get_as_of(
        dataset_key,
        publication_key,
        as_of,
    )
    if publication is None:
        return None
    return {
        "publication_id": publication.publication_id,
        "dataset_key": publication.dataset_key,
        "publication_key": publication.publication_key,
        "policy_version": publication.policy_version,
        "state": publication.state.value,
        "selected_source": publication.selected_source,
        "publication_hash": publication.publication_hash,
        "coverage_ratio": publication.coverage.coverage_ratio,
        "published_at": publication.published_at.isoformat() if publication.published_at else None,
        "as_of": publication.as_of.isoformat() if publication.as_of else None,
        "must_not_use_for_decision": publication.must_not_use_for_decision,
        "blocked_reason": publication.blocked_reason,
    }


__all__ = [
    "backfill_asset_master_codes_port",
    "get_asset_repository_port",
    "get_active_dataset_contract",
    "get_active_publication_policy",
    "get_financial_facts",
    "get_akshare_eastmoney_gateway_port",
    "get_akshare_module_port",
    "get_current_publication",
    "list_active_data_owner_registrations",
    "list_active_dataset_contracts",
    "list_active_provider_bindings",
    "list_active_publication_policies",
    "get_fund_nav_repository_port",
    "get_macro_fact_series",
    "is_direct_macro_input_allowed",
    "get_macro_indicator_catalog",
    "get_macro_runtime_metadata",
    "get_macro_projection_repository_port",
    "list_macro_indicator_codes",
    "get_macro_indicator_value",
    "get_market_breadth_snapshot",
    "get_latest_quote_payloads",
    "get_latest_reconciliation_evidence",
    "query_published_a_share_behavior_payload",
    "get_price_bar_series",
    "get_price_bar_repository_port",
    "get_quote_snapshot_repository_port",
    "get_sector_membership_repository_port",
    "get_news_repository_port",
    "get_capital_flow_repository_port",
    "get_provider_config_repository_port",
    "get_provider_registry_port",
    "build_provider_registry_port",
    "get_publication_as_of",
    "get_published_macro_fact_series",
    "get_published_market_news",
    "get_published_capital_flow_series",
    "get_published_price_bar_series",
    "get_published_quote_payloads",
    "get_published_sector_memberships",
    "record_reconciliation_evidence",
    "get_valuation_facts",
    "get_valuation_fact_repository_port",
    "get_raw_audit_repository_port",
    "get_tushare_client",
    "list_active_stock_codes",
    "list_active_data_sources",
    "list_latest_macro_values",
    "list_macro_facts_by_original_unit",
    "list_price_covered_codes",
    "list_valuation_covered_codes",
    "update_asset_display_name",
    "save_macro_facts",
]
