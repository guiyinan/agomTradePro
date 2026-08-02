"""Application-level query helpers for cross-app data-center access."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from apps.data_center.application.query_use_cases import latest_completed_cn_market_session
from apps.data_center.composition import (
    get_asset_repository,
    get_data_center_diagnostic_repository,
    get_financial_fact_repository,
    get_indicator_catalog_repository,
    get_indicator_unit_rule_repository,
    get_macro_fact_cache_warmup_repository,
    get_macro_fact_repository,
    get_market_thermometer_snapshot_repository,
    get_price_bar_repository,
    get_provider_config_repository,
    get_quote_snapshot_repository,
    get_valuation_fact_repository,
)
from apps.data_center.domain.enums import AssetType, MarketExchange

A_SHARE_BEHAVIOR_INDICATORS: dict[str, str] = {
    "up_count": "CN_A_ADVANCE_COUNT",
    "down_count": "CN_A_DECLINE_COUNT",
    "limit_up_count": "CN_A_LIMIT_UP_COUNT",
    "limit_down_count": "CN_A_LIMIT_DOWN_COUNT",
}


def get_data_center_diagnostic_summary() -> dict[str, int]:
    """Return data-center summary counts for operational diagnostics."""

    return get_data_center_diagnostic_repository().get_summary()


def get_active_stock_fact_coverage_payload() -> dict[str, Any]:
    """Return active-stock price, valuation, and financial coverage."""

    return get_data_center_diagnostic_repository().get_active_stock_fact_coverage_summary()


def list_active_stock_codes_for_backfill() -> list[str]:
    """Return the governed production stock universe for bounded sync batches."""

    return get_data_center_diagnostic_repository().list_active_stock_codes()


def list_active_asset_codes() -> list[str]:
    """Return canonical active A-share stock codes for consumers."""

    return get_asset_repository().list_active_codes(
        asset_type=AssetType.STOCK,
        exchanges=(MarketExchange.SSE, MarketExchange.SZSE, MarketExchange.BSE),
    )


def list_price_covered_asset_codes(as_of: date | None = None) -> list[str]:
    """Return canonical assets with price facts through an optional date."""

    return get_price_bar_repository().list_asset_codes(as_of)


def list_valuation_covered_asset_codes(as_of: date | None = None) -> list[str]:
    """Return canonical assets with valuation facts through an optional date."""

    return get_valuation_fact_repository().list_asset_codes(as_of)


def query_financial_facts(
    asset_code: str,
    *,
    limit: int = 20,
) -> list[dict[str, object]]:
    """Return canonical financial facts through the application query port."""

    return [
        fact.to_dict()
        for fact in get_financial_fact_repository().get_facts(asset_code, limit=limit)
    ]


def query_valuation_facts(
    asset_code: str,
    *,
    as_of: date | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    """Return canonical valuation facts through the application query port."""

    facts = get_valuation_fact_repository().get_series(asset_code, end=as_of)
    selected = facts[:limit] if limit is not None else facts
    return [fact.to_dict() for fact in selected]


def query_latest_quote_payloads(
    asset_codes: list[str],
    *,
    observed_after: datetime | None = None,
) -> list[dict[str, object]]:
    """Return latest canonical quote payloads, preserving source observation time."""

    rows: list[dict[str, object]] = []
    repository = get_quote_snapshot_repository()
    for asset_code in asset_codes:
        quote = repository.get_latest(asset_code)
        if quote is None:
            continue
        if observed_after is not None and quote.snapshot_at < observed_after:
            continue
        rows.append(quote.to_dict())
    return rows


def macro_fact_exists_on_or_before(reporting_period: date) -> bool:
    """Return whether macro data exists on or before the reporting period."""

    return get_data_center_diagnostic_repository().macro_fact_exists_on_or_before(reporting_period)


def get_latest_macro_indicator_value(indicator_code: str) -> float | None:
    """Return the latest canonical macro indicator value for one code."""

    latest = get_macro_fact_repository().get_latest(indicator_code)
    return float(latest.value) if latest is not None else None


def query_macro_fact_series(
    indicator_code: str,
    *,
    start: date | None = None,
    end: date | None = None,
    limit: int = 500,
    use_pit: bool = False,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Return canonical macro facts for cross-app consumers.

    ``use_pit`` applies the publication-time boundary in the Data Center
    repository; consumers never need to import ``MacroFactModel``.
    """

    facts = get_macro_fact_repository().get_series(
        indicator_code,
        start=start,
        end=end,
        limit=limit,
        use_pit=use_pit,
    )
    if source:
        facts = [fact for fact in facts if fact.source == source]
    return [fact.to_dict() for fact in facts]


def get_macro_indicator_metadata(indicator_code: str) -> dict[str, Any]:
    """Return catalog metadata for one indicator through the public port."""

    catalog = get_indicator_catalog_repository().get_by_code(indicator_code)
    if catalog is None:
        return {}
    return {
        "code": catalog.code,
        "default_period_type": catalog.default_period_type,
        "default_unit": catalog.default_unit,
        "extra": dict(catalog.extra),
    }


def list_active_provider_summaries() -> list[dict[str, str]]:
    """Return active provider names without exposing provider ORM models."""

    return [
        {"name": config.name, "source_type": config.source_type}
        for config in get_provider_config_repository().list_active()
    ]


def get_runtime_macro_metadata_map() -> dict[str, dict[str, Any]]:
    """Build macro runtime metadata from canonical catalog and unit rules."""

    catalog_repo = get_indicator_catalog_repository()
    unit_repo = get_indicator_unit_rule_repository()
    metadata: dict[str, dict[str, Any]] = {}
    for catalog in catalog_repo.list_active():
        rules = [
            rule
            for rule in unit_repo.list_by_indicator(catalog.code)
            if rule.is_active and not rule.source_type
        ]
        selected_rule = sorted(rules, key=lambda rule: (-rule.priority, rule.id or 0))[0] if rules else None
        unit = ""
        if selected_rule is not None:
            unit = selected_rule.display_unit or selected_rule.original_unit or selected_rule.storage_unit
        extra = dict(catalog.extra)
        metadata[catalog.code] = {
            "name": catalog.name_cn,
            "name_en": catalog.name_en or catalog.code,
            "category": catalog.category or "其他",
            "unit": unit,
            "description": catalog.description or "",
            "default_unit": catalog.default_unit or "",
            "default_period_type": catalog.default_period_type or "",
            **extra,
            "publication_lag_days": int(extra.get("publication_lag_days", 0) or 0),
            "publication_lag_description": extra.get("publication_lag_description", "实时"),
        }
    return metadata


def get_latest_a_share_behavior_payload(
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return latest A-share behavior values with an explicit freshness contract."""

    current_now = now or datetime.now(UTC)
    if current_now.tzinfo is None:
        current_now = current_now.replace(tzinfo=UTC)
    expected_session = latest_completed_cn_market_session(current_now)
    repository = get_macro_fact_repository()
    values: dict[str, int | None] = {}
    observed_by_field: dict[str, str | None] = {}
    missing_fields: list[str] = []
    stale_fields: list[str] = []
    observed_dates: list[date] = []

    for field_name, indicator_code in A_SHARE_BEHAVIOR_INDICATORS.items():
        fact = repository.get_latest(indicator_code)
        if fact is None:
            values[field_name] = None
            observed_by_field[field_name] = None
            missing_fields.append(field_name)
            continue
        values[field_name] = int(fact.value)
        observed_by_field[field_name] = fact.reporting_period.isoformat()
        observed_dates.append(fact.reporting_period)
        if expected_session is None or fact.reporting_period != expected_session:
            stale_fields.append(field_name)

    is_reliable = not missing_fields and not stale_fields and expected_session is not None
    market_data_as_of = min(observed_dates).isoformat() if observed_dates else None
    blocked_reason = ""
    if missing_fields:
        blocked_reason = "market_breadth_incomplete"
    elif stale_fields or expected_session is None:
        blocked_reason = "market_breadth_stale"

    return {
        **values,
        "stats_available": is_reliable,
        "contract": {
            "observed_at": market_data_as_of,
            "market_data_as_of": market_data_as_of,
            "expected_market_session": (
                expected_session.isoformat() if expected_session is not None else None
            ),
            "observed_by_field": observed_by_field,
            "is_reliable": is_reliable,
            "is_stale": bool(stale_fields) or (expected_session is None and bool(observed_dates)),
            "must_not_use_for_decision": not is_reliable,
            "blocked_reason": blocked_reason,
            "missing_fields": missing_fields,
            "stale_fields": stale_fields,
        },
    }


def list_latest_macro_indicator_payloads(limit: int = 50) -> list[dict[str, Any]]:
    """Return latest macro indicator payloads for cache warmup."""

    return [
        {
            "indicator_code": fact.indicator_code,
            "value": float(fact.value),
            "reporting_period": str(fact.reporting_period),
        }
        for fact in get_macro_fact_cache_warmup_repository().list_latest_by_indicator(limit=limit)
    ]


def get_latest_market_thermometer_snapshot_payload() -> dict[str, Any] | None:
    """Return the latest market thermometer snapshot as a JSON-safe payload."""

    snapshot = get_market_thermometer_snapshot_repository().get_latest()
    return snapshot.to_dict() if snapshot is not None else None


def fetch_close_price_series(
    *,
    asset_code: str,
    start_date: date,
    end_date: date,
    limit: int = 5000,
) -> list[tuple[date, float]]:
    """Return close-price history from data-center facts, oldest to newest."""

    bars = get_price_bar_repository().get_bars(
        asset_code,
        start=start_date,
        end=end_date,
        limit=limit,
    )
    return [(bar.bar_date, float(bar.close)) for bar in reversed(bars)]


def fetch_close_prices(
    *,
    asset_code: str,
    start_date: date,
    end_date: date,
) -> list[float] | None:
    """Return close prices from data-center facts, oldest to newest."""

    bars = get_price_bar_repository().get_bars(asset_code, start=start_date, end=end_date)
    if not bars:
        return None
    return [float(bar.close) for bar in reversed(bars)]


def fetch_price_bar_payloads(
    *,
    asset_code: str,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return canonical OHLCV facts, oldest to newest, for cross-app reads."""

    bars = get_price_bar_repository().get_bars(
        asset_code,
        start=start_date,
        end=end_date,
        limit=limit,
    )
    return [
        {
            "asset_code": bar.asset_code,
            "timestamp": bar.bar_date.isoformat(),
            "period": bar.freq,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume) if bar.volume is not None else None,
            "amount": float(bar.amount) if bar.amount is not None else None,
            "source": bar.source,
        }
        for bar in reversed(bars)
    ]
