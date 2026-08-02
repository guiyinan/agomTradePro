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
    get_latest_a_share_behavior_payload,
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
    query_valuation_facts,
)
from apps.data_center.composition import (
    get_asset_repository,
    get_macro_fact_repository,
    get_provider_config_repository,
)
from apps.data_center.domain.entities import MacroFact


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


def get_macro_runtime_metadata() -> dict[str, dict[str, Any]]:
    """Read the catalog-backed macro runtime metadata map."""

    return get_runtime_macro_metadata_map()


def list_macro_indicator_codes() -> list[str]:
    """Return active macro indicator codes from the canonical catalog."""

    return sorted(get_macro_runtime_metadata())


def get_market_breadth_snapshot() -> dict[str, Any]:
    """Read the canonical market-breadth snapshot and reliability contract."""

    return get_latest_a_share_behavior_payload()


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


__all__ = [
    "get_financial_facts",
    "get_macro_fact_series",
    "get_macro_indicator_catalog",
    "get_macro_runtime_metadata",
    "list_macro_indicator_codes",
    "get_macro_indicator_value",
    "get_market_breadth_snapshot",
    "get_latest_quote_payloads",
    "get_price_bar_series",
    "get_valuation_facts",
    "list_active_stock_codes",
    "list_active_data_sources",
    "list_latest_macro_values",
    "list_price_covered_codes",
    "list_valuation_covered_codes",
    "update_asset_display_name",
    "save_macro_facts",
]
