"""Stable Data Center Application Public Ports.

Business applications may import this module, but must not import Data Center
ORM models, repositories or provider adapters.  The functions intentionally
return plain DTO-shaped values for the current migration bridge; new callers
can use the typed contracts in :mod:`apps.data_center.domain.contracts`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Any, Protocol

from apps.data_center.application.query_services import (
    fetch_price_bar_payloads,
    get_current_publication_gate,
    get_latest_macro_indicator_value,
    get_macro_indicator_metadata,
    get_publication_member_fact_pks,
    get_runtime_macro_metadata_map,
    list_active_asset_codes,
    list_active_provider_summaries,
    list_latest_macro_indicator_payloads,
    list_latest_published_macro_indicator_payloads,
    list_price_covered_asset_codes,
    list_valuation_covered_asset_codes,
    query_financial_facts,
    query_latest_quote_payloads,
    query_macro_fact_series,
    query_published_a_share_behavior_payload,
    query_published_capital_flow_series,
    query_published_financial_facts,
    query_published_fund_nav_series,
    query_published_macro_fact_series,
    query_published_market_news,
    query_published_price_bar_series,
    query_published_quote_payloads,
    query_published_quote_series,
    query_published_sector_memberships,
    query_published_valuation_facts,
    query_valuation_facts,
)
from apps.data_center.application.reconciliation import RecordReconciliationEvidenceUseCase
from apps.data_center.composition import (
    backfill_asset_master_codes,
    build_provider_registry_for_repo,
    build_tushare_client,
    fetch_rss_feed,
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
    probe_rss_feed,
)
from apps.data_center.domain.contracts import (
    DataOwnerRegistration,
    DatasetContract,
    ProviderBinding,
    PublicationPolicy,
)
from apps.data_center.domain.entities import MacroFact, NewsFact
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


class MacroProjectionRepositoryProtocol(Protocol):
    """Application contract for macro administrative/read projections.

    The concrete implementation lives in Data Center infrastructure.  Macro's
    compatibility adapter consumes this contract to convert canonical
    ``MacroFact`` values into its domain projection without importing ORM
    models or a concrete repository.
    """

    def save_indicator(self, fact: MacroFact) -> MacroFact: ...

    def get_series(
        self,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ) -> list[MacroFact]: ...

    def get_latest_observation_date(
        self,
        code: str,
        as_of_date: date | None = None,
    ) -> date | None: ...

    def get_latest_observation(
        self,
        code: str,
        before_date: date | None = None,
    ) -> MacroFact | None: ...

    def get_available_dates(
        self,
        codes: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[date]: ...

    def delete_indicator(
        self,
        code: str,
        observed_at: date,
        revision_number: int | None = None,
    ) -> bool: ...

    def get_indicator_count(self, code: str | None = None) -> int: ...

    def delete_by_conditions(
        self,
        indicator_code: str | None = None,
        source: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int: ...

    def get_record_by_id(self, record_id: int) -> dict[str, Any] | None: ...

    def create_record(
        self,
        *,
        code: str,
        value: float,
        reporting_period: date,
        period_type: str = "D",
        published_at: date | None = None,
        source: str = "manual",
        revision_number: int = 1,
    ) -> dict[str, Any]: ...

    def update_record(self, record_id: int, **updates: Any) -> dict[str, Any] | None: ...

    def delete_record_by_id(self, record_id: int) -> bool: ...

    def delete_records_by_ids(self, record_ids: list[int]) -> int: ...

    def count_records_before_date(self, cutoff_date: date) -> int: ...

    def get_statistics(self) -> dict[str, Any]: ...

    def get_recent_syncs(self, limit: int = 10) -> list[dict[str, Any]]: ...

    def get_indicator_unit_config(
        self,
        indicator_code: str,
        source: str | None = None,
    ) -> dict[str, Any] | None: ...

    def list_distinct_codes(self) -> list[str]: ...

    def get_storage_summary(self) -> dict[str, Any]: ...

    def list_indicator_rollups(self) -> list[dict[str, Any]]: ...

    def list_source_rollups(self) -> list[dict[str, Any]]: ...

    def get_indicator_rows(
        self,
        *,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int | None = None,
        ascending: bool = True,
    ) -> list[dict[str, Any]]: ...

    def count_table_rows(
        self,
        *,
        code_filter: str = "",
        source_filter: str = "",
        period_type_filter: str = "",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int: ...

    def get_table_rows(
        self,
        *,
        code_filter: str = "",
        source_filter: str = "",
        period_type_filter: str = "",
        start_date: date | None = None,
        end_date: date | None = None,
        sort_field: str = "-reporting_period",
        offset: int = 0,
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...

    def get_latest_indicator(self, code: str) -> dict[str, Any] | None: ...

    def get_indicator_stats(self, code: str, start_date: date) -> dict[str, float | None]: ...

    def get_indicator_history(
        self,
        code: str,
        *,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    def get_latest_values_by_codes(self, codes: list[str]) -> list[dict[str, Any]]: ...


def get_macro_projection_repository_port() -> MacroProjectionRepositoryProtocol:
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


def fetch_rss_news_feed(
    *,
    url: str,
    source_name: str,
    timeout_seconds: int = 30,
    retry_times: int = 3,
    proxy_config: dict[str, str] | None = None,
    user_agent: str = "AgomTradePro-RSS-Bot/1.0",
) -> list[NewsFact]:
    """Fetch one external RSS feed through the Data Center transport port."""

    return fetch_rss_feed(
        url=url,
        source_name=source_name,
        timeout_seconds=timeout_seconds,
        retry_times=retry_times,
        proxy_config=proxy_config,
        user_agent=user_agent,
    )


def probe_rss_news_feed(
    *,
    url: str,
    source_name: str,
    timeout_seconds: int = 30,
    retry_times: int = 1,
    proxy_config: dict[str, str] | None = None,
    user_agent: str = "AgomTradePro-RSS-Bot/1.0",
) -> None:
    """Probe one external RSS source through the Data Center transport port."""

    probe_rss_feed(
        url=url,
        source_name=source_name,
        timeout_seconds=timeout_seconds,
        retry_times=retry_times,
        proxy_config=proxy_config,
        user_agent=user_agent,
    )


def get_market_thermometer_payload(
    *,
    user_id: int | None = None,
    use_personal_thresholds: bool = True,
) -> dict[str, Any]:
    """Return a freshness-aware market thermometer payload through the public port.

    The optional user scope only controls presentation thresholds; the underlying
    observation and reliability gate remain owned by Data Center.
    """

    from apps.data_center.application.interface_services import load_market_thermometer_payload

    return load_market_thermometer_payload(
        user_id=user_id,
        use_personal_thresholds=use_personal_thresholds,
    )


def get_current_market_thermometer_payload() -> dict[str, Any]:
    """Return the freshness-aware, non-personal market thermometer payload."""

    return get_market_thermometer_payload(use_personal_thresholds=False)


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


def list_latest_published_macro_values(limit: int = 50) -> list[dict[str, Any]]:
    """Read fresh, member-bound macro values for current-facing consumers."""

    return list_latest_published_macro_indicator_payloads(limit=limit)


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


def get_published_fund_nav_series(
    fund_code: str,
    *,
    publication_key: str = "current",
    start: date | None = None,
    end: date | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    """Read decision-facing fund NAV facts behind a publication gate."""

    return query_published_fund_nav_series(
        fund_code,
        publication_key=publication_key,
        start=start,
        end=end,
        limit=limit,
    )


def sync_fund_nav_from_active_provider(
    fund_code: str,
    *,
    start: date,
    end: date,
) -> dict[str, object]:
    """Synchronize fund NAV through the active Data Center provider route.

    This is the compatibility port for legacy fund callers.  Provider
    selection is capability-based and priority-ordered, so callers do not
    reach a Tushare adapter directly when another active ``fund_nav`` source
    (for example AKShare) is available.
    """

    from apps.data_center.application.dtos import SyncFundNavRequest
    from apps.data_center.application.interface_services import make_sync_fund_nav_use_case
    from apps.data_center.domain.enums import DataCapability

    provider_repo = get_provider_config_repository()
    registry = get_provider_registry()
    active_configs = sorted(
        provider_repo.list_active(),
        key=lambda config: (config.priority, config.id or 0),
    )
    use_case: Any | None = None
    last_result: dict[str, object] | None = None
    attempted_provider = False

    for config in active_configs:
        if config.id is None:
            continue
        provider = registry.get_by_id(config.id)
        if provider is None or not provider.supports(DataCapability.FUND_NAV):
            continue
        attempted_provider = True
        if use_case is None:
            use_case = make_sync_fund_nav_use_case()
        try:
            result = use_case.execute(
                SyncFundNavRequest(
                    provider_id=config.id,
                    fund_code=fund_code,
                    start=start,
                    end=end,
                )
            )
        except Exception as exc:
            last_result = {
                "domain": "fund_nav",
                "provider_name": provider.provider_name(),
                "stored_count": 0,
                "status": "failed",
                "error_message": f"provider_sync_failed:{type(exc).__name__}",
            }
            continue

        last_result = result.to_dict()
        if result.stored_count > 0:
            return last_result

    if last_result is not None:
        if not str(last_result.get("error_message") or "").strip():
            last_result["error_message"] = "active fund NAV providers returned no canonical facts"
        return last_result
    return {
        "domain": "fund_nav",
        "provider_name": "",
        "stored_count": 0,
        "status": "blocked" if not attempted_provider else "noop",
        "error_message": "no active provider supports fund_nav",
    }


def get_current_publication_freshness_gate(
    dataset_key: str,
    publication_key: str,
) -> dict[str, object] | None:
    """Return the freshness-validated gate for a current publication."""

    return get_current_publication_gate(dataset_key, publication_key)


def get_decision_publication_gate(
    dataset_key: str,
    publication_key: str = "current",
) -> dict[str, object] | None:
    """Return one merged publication and freshness gate for decision APIs.

    This port keeps Interface, SDK and MCP callers on the same fail-closed
    semantics without exposing Data Center repositories outside Application.
    """

    publication = get_current_publication(dataset_key, publication_key)
    if publication is None:
        return None
    freshness = get_current_publication_freshness_gate(dataset_key, publication_key)
    if freshness is None:
        return {
            **publication,
            "must_not_use_for_decision": True,
            "blocked_reason": "publication_freshness_unverified",
            "freshness_status": "unverified",
        }
    return {**publication, **freshness}


def get_published_quote_payloads(
    asset_codes: list[str],
    *,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read decision-facing quotes only when publication is current."""

    return query_published_quote_payloads(asset_codes, publication_key=publication_key)


def get_published_latest_quote_payload(
    asset_code: str,
    *,
    publication_key: str = "current",
) -> dict[str, object] | None:
    """Return one publication-bound quote payload for a decision consumer.

    A blocked publication is returned as an explicit blocked payload so callers
    can preserve the reason in risk evidence; a usable publication with no
    selected member returns ``None``.
    """

    normalized_code = str(asset_code or "").strip().upper()
    if not normalized_code:
        return None
    published = get_published_quote_payloads(
        [normalized_code],
        publication_key=publication_key,
    )
    if bool(published.get("must_not_use_for_decision")):
        return {
            "asset_code": normalized_code,
            "is_stale": True,
            "must_not_use_for_decision": True,
            "freshness_status": published.get("freshness_status") or "blocked",
            "blocked_reason": published.get("blocked_reason") or "canonical_publication_missing",
            "publication_id": published.get("publication_id"),
            "dataset_key": published.get("dataset_key"),
        }
    rows = published.get("rows")
    if not isinstance(rows, list):
        return None
    row = next((item for item in rows if isinstance(item, dict)), None)
    if row is None:
        return None
    result = dict(row)
    for key in (
        "publication_id",
        "dataset_key",
        "publication_key",
        "published_at",
        "as_of",
        "observed_at",
        "age_seconds",
        "max_age_seconds",
        "freshness_status",
        "blocked_reason",
    ):
        if key not in result and key in published:
            result[key] = published[key]
    result.setdefault("is_stale", False)
    result.setdefault("must_not_use_for_decision", False)
    return result


def get_published_quote_series(
    asset_code: str,
    *,
    publication_key: str = "current",
    snapshot_date: date | None = None,
    limit: int = 500,
) -> dict[str, object]:
    """Read current intraday quote snapshots behind the Publication gate."""

    return query_published_quote_series(
        asset_code,
        publication_key=publication_key,
        snapshot_date=snapshot_date,
        limit=limit,
    )


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


def get_published_financial_facts(
    asset_code: str,
    *,
    limit: int = 20,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read decision-facing financial facts behind a publication gate."""

    return query_published_financial_facts(
        asset_code,
        limit=limit,
        publication_key=publication_key,
    )


def get_published_valuation_facts(
    asset_code: str,
    *,
    as_of: date | None = None,
    limit: int | None = None,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read decision-facing valuation facts behind a publication gate."""

    return query_published_valuation_facts(
        asset_code,
        as_of=as_of,
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


def get_active_stock_fact_coverage_payload() -> dict[str, Any]:
    """Return the diagnostic coverage payload through the public port."""

    from apps.data_center.application.query_services import (
        get_active_stock_fact_coverage_payload as _get_coverage,
    )

    return _get_coverage()


def get_decision_data_readiness_payload(
    *,
    asset_codes: list[str] | None = None,
    quote_max_age_hours: float | None = None,
) -> dict[str, Any]:
    """Return the fail-closed decision-data readiness payload."""

    from apps.data_center.application.interface_services import (
        get_decision_data_readiness_payload as _get_readiness,
    )

    return _get_readiness(
        asset_codes=asset_codes,
        quote_max_age_hours=quote_max_age_hours,
    )


def resolve_asset_payload(asset_code: str) -> dict[str, Any] | None:
    """Resolve one canonical AssetMaster record into a plain public payload."""

    normalized_code = str(asset_code or "").strip().upper()
    if not normalized_code:
        return None

    from apps.data_center.application.dtos import ResolveAssetRequest
    from apps.data_center.application.interface_services import make_resolve_asset_use_case

    response = make_resolve_asset_use_case().execute(
        ResolveAssetRequest(code=normalized_code),
    )
    if response is None:
        return None
    return response.to_dict()


def list_active_stock_codes() -> list[str]:
    """Read the canonical active A-share universe."""

    return list_active_asset_codes()


def list_price_covered_codes(as_of: date | None = None) -> list[str]:
    """Read canonical price coverage through a bounded application port."""

    return list_price_covered_asset_codes(as_of)


def list_valuation_covered_codes(as_of: date | None = None) -> list[str]:
    """Read canonical valuation coverage through a bounded application port."""

    return list_valuation_covered_asset_codes(as_of)


def get_financial_facts(
    asset_code: str,
    *,
    limit: int = 20,
    as_of: date | None = None,
) -> list[dict[str, object]]:
    """Read canonical financial facts for one asset through an optional as-of date."""

    return query_financial_facts(asset_code, limit=limit, end=as_of)


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
    "MacroProjectionRepositoryProtocol",
    "backfill_asset_master_codes_port",
    "get_asset_repository_port",
    "get_active_dataset_contract",
    "get_active_publication_policy",
    "get_financial_facts",
    "get_akshare_eastmoney_gateway_port",
    "get_akshare_module_port",
    "get_current_publication",
    "get_current_publication_freshness_gate",
    "get_decision_publication_gate",
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
    "fetch_rss_news_feed",
    "probe_rss_news_feed",
    "get_current_market_thermometer_payload",
    "get_market_thermometer_payload",
    "get_active_stock_fact_coverage_payload",
    "get_decision_data_readiness_payload",
    "resolve_asset_payload",
    "get_capital_flow_repository_port",
    "get_provider_config_repository_port",
    "get_provider_registry_port",
    "build_provider_registry_port",
    "get_publication_as_of",
    "get_publication_member_fact_pks",
    "get_published_macro_fact_series",
    "get_published_market_news",
    "get_published_capital_flow_series",
    "get_published_financial_facts",
    "get_published_latest_quote_payload",
    "get_published_fund_nav_series",
    "sync_fund_nav_from_active_provider",
    "get_published_price_bar_series",
    "get_published_quote_payloads",
    "get_published_quote_series",
    "get_published_sector_memberships",
    "get_published_valuation_facts",
    "record_reconciliation_evidence",
    "get_valuation_facts",
    "get_valuation_fact_repository_port",
    "get_raw_audit_repository_port",
    "get_tushare_client",
    "list_active_stock_codes",
    "list_active_data_sources",
    "list_latest_macro_values",
    "list_latest_published_macro_values",
    "list_macro_facts_by_original_unit",
    "list_price_covered_codes",
    "list_valuation_covered_codes",
    "update_asset_display_name",
    "save_macro_facts",
]
