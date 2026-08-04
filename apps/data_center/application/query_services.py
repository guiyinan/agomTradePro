"""Application-level query helpers for cross-app data-center access."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from apps.data_center.application.query_use_cases import latest_completed_cn_market_session
from apps.data_center.composition import (
    get_asset_repository,
    get_canonical_publication_repository,
    get_capital_flow_repository,
    get_data_center_diagnostic_repository,
    get_dataset_contract_repository,
    get_financial_fact_repository,
    get_fund_nav_repository,
    get_indicator_catalog_repository,
    get_indicator_unit_rule_repository,
    get_macro_fact_cache_warmup_repository,
    get_macro_fact_repository,
    get_market_thermometer_snapshot_repository,
    get_news_repository,
    get_price_bar_repository,
    get_provider_config_repository,
    get_quote_snapshot_repository,
    get_sector_membership_repository,
    get_valuation_fact_repository,
)
from apps.data_center.domain.entities import CapitalFlowFact
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
    end: date | None = None,
    fact_pks: Sequence[str] | None = None,
) -> list[dict[str, object]]:
    """Return canonical financial facts through the application query port."""

    repository = get_financial_fact_repository()
    if fact_pks is None:
        facts = repository.get_facts(asset_code, limit=limit, end=end)
    else:
        facts = repository.get_facts(asset_code, limit=limit, end=end, fact_pks=fact_pks)
    return [fact.to_dict() for fact in facts]


def query_valuation_facts(
    asset_code: str,
    *,
    as_of: date | None = None,
    limit: int | None = None,
    fact_pks: Sequence[str] | None = None,
) -> list[dict[str, object]]:
    """Return canonical valuation facts through the application query port."""

    repository = get_valuation_fact_repository()
    if fact_pks is None:
        facts = repository.get_series(asset_code, end=as_of)
    else:
        facts = repository.get_series(asset_code, end=as_of, fact_pks=fact_pks)
    selected = facts[:limit] if limit is not None else facts
    return [fact.to_dict() for fact in selected]


def query_latest_quote_payloads(
    asset_codes: list[str],
    *,
    observed_after: datetime | None = None,
    observed_before: datetime | None = None,
    fact_pks: Sequence[str] | None = None,
) -> list[dict[str, object]]:
    """Return latest canonical quote payloads, preserving source observation time."""

    rows: list[dict[str, object]] = []
    repository = get_quote_snapshot_repository()
    for asset_code in asset_codes:
        quote = (
            repository.get_latest(asset_code)
            if fact_pks is None
            else repository.get_latest(asset_code, fact_pks=fact_pks)
        )
        if quote is None:
            continue
        if observed_after is not None and quote.snapshot_at < observed_after:
            continue
        if observed_before is not None and quote.snapshot_at > observed_before:
            continue
        rows.append(quote.to_dict())
    return rows


def macro_fact_exists_on_or_before(reporting_period: date) -> bool:
    """Return whether macro data exists on or before the reporting period."""

    return get_data_center_diagnostic_repository().macro_fact_exists_on_or_before(reporting_period)


def get_latest_macro_indicator_value(indicator_code: str) -> float | None:
    """Return a current macro value only when its Publication gate passes."""

    published = query_published_macro_fact_series(indicator_code, limit=1)
    if bool(published.get("must_not_use_for_decision")):
        return None
    rows = published.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[-1]
    if not isinstance(row, dict):
        return None
    raw_value = row.get("value")
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float, str)):
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def query_macro_fact_series(
    indicator_code: str,
    *,
    start: date | None = None,
    end: date | None = None,
    limit: int = 500,
    use_pit: bool = False,
    source: str | None = None,
    fact_pks: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Return canonical macro facts for cross-app consumers.

    ``use_pit`` applies the publication-time boundary in the Data Center
    repository; consumers never need to import ``MacroFactModel``.
    """

    repository = get_macro_fact_repository()
    if fact_pks is None:
        facts = repository.get_series(
            indicator_code,
            start=start,
            end=end,
            limit=limit,
            use_pit=use_pit,
        )
    else:
        facts = repository.get_series(
            indicator_code,
            start=start,
            end=end,
            limit=limit,
            use_pit=use_pit,
            fact_pks=fact_pks,
        )
    if source:
        facts = [fact for fact in facts if fact.source == source]
    return [fact.to_dict() for fact in facts]


def query_published_macro_fact_series(
    indicator_code: str,
    *,
    publication_key: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = 500,
) -> dict[str, object]:
    """Read macro facts only after the publication freshness gate passes.

    This explicit current-data port prevents a non-empty, unpublished, or
    stale fact from being mistaken for a decision-ready value.  The legacy
    series port remains available for historical/maintenance views.
    """

    key = publication_key or indicator_code
    gate = _publication_gate("macro.fact", key)
    if gate is None or bool(gate.get("must_not_use_for_decision")):
        return _blocked_publication_result(gate)
    member_pks = _publication_member_fact_pks(
        gate,
        expected_fact_table="data_center_macro_fact",
    )
    if member_pks == []:
        return _blocked_publication_members_result(gate)
    bounded_end = _bounded_end_date(end, _publication_as_of_date(gate))
    if start is not None and bounded_end is not None and start > bounded_end:
        result = _blocked_publication_result(gate)
        result["blocked_reason"] = "publication_as_of_before_requested_range"
        return result
    return {
        "rows": query_macro_fact_series(
            indicator_code,
            start=start,
            end=bounded_end,
            limit=limit,
            fact_pks=member_pks,
        ),
        **gate,
    }


def query_published_fund_nav_series(
    fund_code: str,
    *,
    publication_key: str = "current",
    start: date | None = None,
    end: date | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    """Read fund NAV facts only from the selected current publication members."""

    gate = _publication_gate("fund.nav", publication_key)
    if gate is None or bool(gate.get("must_not_use_for_decision")):
        return _blocked_publication_result(gate)
    member_pks = _publication_member_fact_pks(
        gate,
        expected_fact_table="data_center_fund_nav_fact",
    )
    if member_pks == []:
        return _blocked_publication_members_result(gate)
    bounded_end = _bounded_end_date(end, _publication_as_of_date(gate))
    if start is not None and bounded_end is not None and start > bounded_end:
        result = _blocked_publication_result(gate)
        result["blocked_reason"] = "publication_as_of_before_requested_range"
        return result
    repository = get_fund_nav_repository()
    if member_pks is None:
        facts = repository.get_series(fund_code, start, bounded_end)
    else:
        facts = repository.get_series(
            fund_code,
            start,
            bounded_end,
            fact_pks=member_pks,
        )
    if limit is not None:
        facts = facts[:limit]
    return {"rows": [fact.to_dict() for fact in facts], **gate}


def _publication_gate(
    dataset_key: str,
    publication_key: str,
    *,
    now: datetime | None = None,
) -> dict[str, object] | None:
    """Return publication metadata after validating source observation freshness."""

    repository = get_canonical_publication_repository()
    publication = repository.get_current(dataset_key, publication_key)
    if publication is None:
        return None
    publication_as_of = getattr(publication, "as_of", None)
    gate: dict[str, object] = {
        "publication_id": publication.publication_id,
        "dataset_key": getattr(publication, "dataset_key", dataset_key),
        "publication_key": getattr(publication, "publication_key", publication_key),
        "published_at": publication.published_at.isoformat() if publication.published_at else None,
        "as_of": publication_as_of.isoformat() if publication_as_of else None,
        "must_not_use_for_decision": publication.must_not_use_for_decision,
        "blocked_reason": publication.blocked_reason,
    }
    member_observation_reader = getattr(repository, "get_oldest_member_observed_at", None)
    if callable(member_observation_reader):
        contract = get_dataset_contract_repository().get_active(dataset_key)
        max_age_seconds = getattr(contract, "freshness_seconds", None)
        if contract is None or max_age_seconds is None:
            gate.update(
                must_not_use_for_decision=True,
                blocked_reason="publication_freshness_policy_missing",
                freshness_status="unverified",
            )
            return gate
        oldest_observed_at = member_observation_reader(publication.publication_id)
        if oldest_observed_at is None:
            gate.update(
                must_not_use_for_decision=True,
                blocked_reason="publication_observation_missing",
                freshness_status="missing",
            )
            return gate
    else:
        max_age_seconds = None
        oldest_observed_at = getattr(publication, "as_of", None) or publication.published_at

    # ``as_of`` is the publication's knowledge boundary.  A publication can
    # otherwise look fresh when a member was re-indexed or its ingestion
    # timestamp was refreshed while the selected fact set still represents an
    # older market snapshot.  Current reads must be bounded by both pieces of
    # evidence; use the oldest aware boundary so metadata cannot wash stale
    # facts into a decision-facing response.
    publication_as_of = getattr(publication, "as_of", None)
    if publication_as_of is not None and oldest_observed_at is not None:
        if (
            publication_as_of.tzinfo is not None
            and publication_as_of.utcoffset() is not None
            and oldest_observed_at.tzinfo is not None
            and oldest_observed_at.utcoffset() is not None
        ):
            oldest_observed_at = min(oldest_observed_at, publication_as_of)
    if oldest_observed_at is None:
        gate.update(
            must_not_use_for_decision=True,
            blocked_reason="publication_observation_missing",
            freshness_status="missing",
        )
        return gate
    if oldest_observed_at.tzinfo is None or oldest_observed_at.utcoffset() is None:
        gate.update(
            must_not_use_for_decision=True,
            blocked_reason="publication_observation_naive",
            freshness_status="invalid",
        )
        return gate
    observed_at_utc = oldest_observed_at.astimezone(UTC)
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None or reference.utcoffset() is None:
        reference = reference.replace(tzinfo=UTC)
    age_seconds = max((reference.astimezone(UTC) - observed_at_utc).total_seconds(), 0.0)
    gate["observed_at"] = observed_at_utc.isoformat()
    gate["age_seconds"] = age_seconds
    gate["max_age_seconds"] = max_age_seconds
    if max_age_seconds is not None and age_seconds > max_age_seconds:
        gate.update(
            must_not_use_for_decision=True,
            blocked_reason="canonical_publication_stale",
            freshness_status="stale",
        )
    else:
        gate["freshness_status"] = "fresh"
    return gate


def get_current_publication_gate(
    dataset_key: str,
    publication_key: str,
) -> dict[str, object] | None:
    """Return a freshness-validated gate for one current publication."""

    return _publication_gate(dataset_key, publication_key)


def _blocked_publication_result(
    gate: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return the stable fail-closed shape for an absent or stale publication."""

    result: dict[str, object] = {
        "rows": [],
        "publication_id": None,
        "published_at": None,
        "must_not_use_for_decision": True,
        "blocked_reason": "canonical_publication_missing",
    }
    if gate is not None:
        result.update(gate)
    result["rows"] = []
    result["must_not_use_for_decision"] = True
    return result


def get_publication_member_fact_pks(
    publication_id: str,
    *,
    dataset_key: str,
    expected_fact_table: str,
) -> list[str] | None:
    """Return selected fact primary keys for one publication-bound dataset.

    ``None`` is reserved for compatibility fakes that do not expose the member
    reader yet. A real publication repository always exposes ``list_members``;
    an empty or malformed member set therefore fails closed at the query port.
    """

    member_reader = getattr(get_canonical_publication_repository(), "list_members", None)
    if not callable(member_reader):
        return None
    try:
        members = member_reader(publication_id)
    except Exception:
        return []
    selected_pks: list[str] = []
    for member in members:
        if isinstance(member, dict):
            member_dataset = member.get("dataset_key")
            member_table = member.get("fact_table")
            member_pk = member.get("fact_pk")
            natural_key = member.get("natural_key")
        else:
            member_dataset = getattr(member, "dataset_key", None)
            member_table = getattr(member, "fact_table", None)
            member_pk = getattr(member, "fact_pk", None)
            natural_key = getattr(member, "natural_key", None)
        if (
            member_dataset != dataset_key
            or member_table != expected_fact_table
            or not str(natural_key or "").strip()
            or not str(member_pk or "").strip()
        ):
            return []
        selected_pks.append(str(member_pk))
    return selected_pks


def _publication_member_fact_pks(
    gate: dict[str, object],
    *,
    expected_fact_table: str,
) -> list[str] | None:
    """Return selected fact primary keys for a publication gate."""

    publication_id = gate.get("publication_id")
    dataset_key = gate.get("dataset_key")
    if not isinstance(publication_id, str) or not publication_id:
        return []
    if not isinstance(dataset_key, str) or not dataset_key:
        return []
    return get_publication_member_fact_pks(
        publication_id,
        dataset_key=dataset_key,
        expected_fact_table=expected_fact_table,
    )


def _blocked_publication_members_result(
    gate: dict[str, object],
    *,
    reason: str = "canonical_publication_members_missing",
) -> dict[str, object]:
    """Return a stable blocked envelope when selected members are unusable."""

    result = _blocked_publication_result(gate)
    result["blocked_reason"] = reason
    return result


def _publication_as_of_datetime(gate: dict[str, object]) -> datetime | None:
    """Parse a publication knowledge boundary for current-row upper bounds."""

    raw_as_of = gate.get("as_of")
    if isinstance(raw_as_of, datetime):
        return raw_as_of
    if not isinstance(raw_as_of, str) or not raw_as_of.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw_as_of)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _publication_as_of_date(gate: dict[str, object]) -> date | None:
    """Return the date portion of a publication knowledge boundary."""

    as_of = _publication_as_of_datetime(gate)
    return as_of.date() if as_of is not None else None


def _bounded_end_date(requested: date | None, publication_as_of: date | None) -> date | None:
    """Limit a current-data query to the publication's knowledge boundary."""

    if publication_as_of is None:
        return requested
    if requested is None:
        return publication_as_of
    return min(requested, publication_as_of)


def query_published_quote_payloads(
    asset_codes: list[str],
    *,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read quote snapshots only behind an active publication."""

    gate = _publication_gate("equity.quote.snapshot", publication_key)
    if gate is None or bool(gate.get("must_not_use_for_decision")):
        return _blocked_publication_result(gate)
    member_pks = _publication_member_fact_pks(
        gate,
        expected_fact_table="data_center_quote_snapshot",
    )
    if member_pks == []:
        return _blocked_publication_members_result(gate)
    return {
        "rows": query_latest_quote_payloads(
            asset_codes,
            observed_before=_publication_as_of_datetime(gate),
            fact_pks=member_pks,
        ),
        **gate,
    }


def query_published_price_bar_series(
    asset_code: str,
    *,
    publication_key: str = "current",
    start: date | None = None,
    end: date | None = None,
    limit: int = 500,
) -> dict[str, object]:
    """Read price bars only behind an active publication."""

    gate = _publication_gate("equity.price.bar", publication_key)
    if gate is None or bool(gate.get("must_not_use_for_decision")):
        return _blocked_publication_result(gate)
    member_pks = _publication_member_fact_pks(
        gate,
        expected_fact_table="data_center_price_bar",
    )
    if member_pks == []:
        return _blocked_publication_members_result(gate)
    bounded_end = _bounded_end_date(end, _publication_as_of_date(gate))
    if start is not None and bounded_end is not None and start > bounded_end:
        rows: list[dict[str, Any]] = []
    else:
        rows = fetch_price_bar_payloads(
            asset_code=asset_code,
            start_date=start,
            end_date=bounded_end,
            limit=limit,
            fact_pks=member_pks,
        )
    return {
        "rows": rows,
        **gate,
    }


def query_published_quote_series(
    asset_code: str,
    *,
    publication_key: str = "current",
    snapshot_date: date | None = None,
    limit: int = 500,
) -> dict[str, object]:
    """Read quote snapshots only from the selected current publication members."""

    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    gate = _publication_gate("equity.quote.snapshot", publication_key)
    if gate is None or bool(gate.get("must_not_use_for_decision")):
        return _blocked_publication_result(gate)
    member_pks = _publication_member_fact_pks(
        gate,
        expected_fact_table="data_center_quote_snapshot",
    )
    if member_pks == []:
        return _blocked_publication_members_result(gate)
    publication_as_of = _publication_as_of_date(gate)
    if snapshot_date is not None and publication_as_of is not None:
        if snapshot_date > publication_as_of:
            result = _blocked_publication_result(gate)
            result["blocked_reason"] = "publication_as_of_before_requested_range"
            return result
    repository = get_quote_snapshot_repository()
    rows = repository.get_series(
        asset_code,
        snapshot_date=snapshot_date,
        limit=limit,
        fact_pks=member_pks,
    )
    publication_as_of_datetime = _publication_as_of_datetime(gate)
    if publication_as_of_datetime is not None:
        rows = [row for row in rows if row.snapshot_at <= publication_as_of_datetime]
    return {"rows": [quote.to_dict() for quote in rows], **gate}


def query_published_financial_facts(
    asset_code: str,
    *,
    limit: int = 20,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read financial facts only after the current financial publication gate."""

    gate = _publication_gate("equity.financial.fact", publication_key)
    if gate is None or bool(gate.get("must_not_use_for_decision")):
        return _blocked_publication_result(gate)
    member_pks = _publication_member_fact_pks(
        gate,
        expected_fact_table="data_center_financial_fact",
    )
    if member_pks == []:
        return _blocked_publication_members_result(gate)
    return {
        "rows": query_financial_facts(
            asset_code,
            limit=limit,
            end=_publication_as_of_date(gate),
            fact_pks=member_pks,
        ),
        **gate,
    }


def query_published_valuation_facts(
    asset_code: str,
    *,
    as_of: date | None = None,
    limit: int | None = None,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read valuation facts only after the current valuation publication gate."""

    gate = _publication_gate("equity.valuation.fact", publication_key)
    if gate is None or bool(gate.get("must_not_use_for_decision")):
        return _blocked_publication_result(gate)
    member_pks = _publication_member_fact_pks(
        gate,
        expected_fact_table="data_center_valuation_fact",
    )
    if member_pks == []:
        return _blocked_publication_members_result(gate)
    bounded_as_of = _bounded_end_date(as_of, _publication_as_of_date(gate))
    return {
        "rows": query_valuation_facts(
            asset_code,
            as_of=bounded_as_of,
            limit=limit,
            fact_pks=member_pks,
        ),
        **gate,
    }


def query_published_sector_memberships(
    sector_code: str,
    *,
    as_of: date | None = None,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read sector membership facts only from an active publication."""

    gate = _publication_gate("sector.membership", publication_key)
    if gate is None or bool(gate.get("must_not_use_for_decision")):
        return _blocked_publication_result(gate)
    member_pks = _publication_member_fact_pks(
        gate,
        expected_fact_table="data_center_sector_membership",
    )
    if member_pks == []:
        return _blocked_publication_members_result(gate)
    repository = get_sector_membership_repository()
    bounded_as_of = _bounded_end_date(as_of, _publication_as_of_date(gate))
    if member_pks is None:
        rows = repository.get_members(sector_code, bounded_as_of)
    else:
        rows = repository.get_members(sector_code, bounded_as_of, fact_pks=member_pks)
    return {"rows": [row.to_dict() for row in rows], **gate}


def query_published_market_news(
    *,
    asset_code: str | None = None,
    target_date: date | None = None,
    limit: int = 50,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read market news only from an active publication."""

    gate = _publication_gate("market.news", publication_key)
    if gate is None or bool(gate.get("must_not_use_for_decision")):
        return _blocked_publication_result(gate)
    member_pks = _publication_member_fact_pks(
        gate,
        expected_fact_table="data_center_news_fact",
    )
    if member_pks == []:
        return _blocked_publication_members_result(gate)
    repository = get_news_repository()
    publication_as_of = _publication_as_of_date(gate)
    if target_date is not None and not asset_code:
        if publication_as_of is not None and target_date > publication_as_of:
            rows = []
        elif member_pks is None:
            rows = repository.list_market_news_for_date(target_date, limit=limit)
        else:
            rows = repository.list_market_news_for_date(
                target_date,
                limit=limit,
                fact_pks=member_pks,
            )
    else:
        if member_pks is None:
            rows = repository.get_recent(asset_code, limit=limit, end=publication_as_of)
        else:
            rows = repository.get_recent(
                asset_code,
                limit=limit,
                end=publication_as_of,
                fact_pks=member_pks,
            )
    return {"rows": [row.to_dict() for row in rows], **gate}


def query_published_capital_flow_series(
    asset_code: str,
    *,
    start: date | None = None,
    end: date | None = None,
    limit: int | None = None,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read capital-flow facts only from an active publication."""

    gate = _publication_gate("market.capital_flow", publication_key)
    if gate is None or bool(gate.get("must_not_use_for_decision")):
        return _blocked_publication_result(gate)
    member_pks = _publication_member_fact_pks(
        gate,
        expected_fact_table="data_center_capital_flow_fact",
    )
    if member_pks == []:
        return _blocked_publication_members_result(gate)
    bounded_end = _bounded_end_date(end, _publication_as_of_date(gate))
    if start is not None and bounded_end is not None and start > bounded_end:
        rows: list[CapitalFlowFact] = []
    elif member_pks is None:
        rows = get_capital_flow_repository().get_series(asset_code, start, bounded_end, limit)
    else:
        rows = get_capital_flow_repository().get_series(
            asset_code,
            start,
            bounded_end,
            limit,
            fact_pks=member_pks,
        )
    return {"rows": [row.to_dict() for row in rows], **gate}


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
        selected_rule = (
            sorted(rules, key=lambda rule: (-rule.priority, rule.id or 0))[0] if rules else None
        )
        unit = ""
        if selected_rule is not None:
            unit = (
                selected_rule.display_unit
                or selected_rule.original_unit
                or selected_rule.storage_unit
            )
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


def query_published_a_share_behavior_payload(
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read current market breadth only after every component is published.

    A breadth payload is a composite of four macro facts.  Checking a single
    aggregate publication would allow one missing component to be hidden by a
    non-empty legacy row, so each component has its own publication scope.
    """

    current_now = now or datetime.now(UTC)
    if current_now.tzinfo is None or current_now.utcoffset() is None:
        current_now = current_now.replace(tzinfo=UTC)
    publication_ids: dict[str, str] = {}
    publication_gates: dict[str, dict[str, object]] = {}
    missing_publications: list[str] = []
    blocked_publications: list[str] = []
    for indicator_code in A_SHARE_BEHAVIOR_INDICATORS.values():
        gate = _publication_gate("macro.fact", indicator_code, now=current_now)
        if gate is None:
            missing_publications.append(indicator_code)
            continue
        publication_gates[indicator_code] = gate
        publication_id = gate.get("publication_id")
        if isinstance(publication_id, str) and publication_id:
            publication_ids[indicator_code] = publication_id
        if bool(gate.get("must_not_use_for_decision")):
            blocked_publications.append(indicator_code)
    if missing_publications or blocked_publications:
        missing_fields = [
            field_name
            for field_name, indicator_code in A_SHARE_BEHAVIOR_INDICATORS.items()
            if indicator_code in missing_publications
        ]
        blocked_fields = [
            field_name
            for field_name, indicator_code in A_SHARE_BEHAVIOR_INDICATORS.items()
            if indicator_code in blocked_publications
        ]
        stale_fields = [
            field_name
            for field_name, indicator_code in A_SHARE_BEHAVIOR_INDICATORS.items()
            if indicator_code in blocked_publications
            and publication_gates[indicator_code].get("freshness_status") in {"stale", "invalid"}
        ]
        blocked_reasons = [
            str(publication_gates[indicator_code].get("blocked_reason") or "")
            for indicator_code in blocked_publications
        ]
        blocked_reason = next(
            (reason for reason in blocked_reasons if reason),
            (
                "canonical_publication_missing"
                if missing_publications
                else "canonical_publication_blocked"
            ),
        )
        return {
            **dict.fromkeys(A_SHARE_BEHAVIOR_INDICATORS, None),
            "stats_available": False,
            "publication_ids": publication_ids,
            "publication_gates": publication_gates,
            "contract": {
                "observed_at": None,
                "market_data_as_of": None,
                "expected_market_session": None,
                "observed_by_field": {},
                "is_reliable": False,
                "is_stale": bool(stale_fields),
                "must_not_use_for_decision": True,
                "blocked_reason": blocked_reason,
                "missing_fields": missing_fields,
                "stale_fields": stale_fields,
                "blocked_fields": blocked_fields,
                "missing_publications": missing_publications,
                "blocked_publications": blocked_publications,
                "publication_ids": publication_ids,
                "publication_gates": publication_gates,
            },
        }
    payload = get_latest_a_share_behavior_payload(now=current_now)
    contract = dict(payload.get("contract") or {})
    contract["publication_ids"] = publication_ids
    contract["publication_gates"] = publication_gates
    return {
        **payload,
        "publication_ids": publication_ids,
        "publication_gates": publication_gates,
        "contract": contract,
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


def list_latest_published_macro_indicator_payloads(limit: int = 50) -> list[dict[str, Any]]:
    """Return only fresh, member-bound macro values for current consumers.

    The cache-warmup helper above intentionally reads the latest canonical fact
    for deployment warming and maintenance.  Current/ops consumers must not
    use that compatibility query because a non-empty fact can be unpublished or
    stale.  Indicator catalog rows provide the bounded discovery list; each
    value then passes the same publication/member/freshness gate as REST/SDK/MCP.
    """

    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")

    catalogs = sorted(
        get_indicator_catalog_repository().list_active(),
        key=lambda item: item.code,
    )[:limit]
    payloads: list[dict[str, Any]] = []
    for catalog in catalogs:
        published = query_published_macro_fact_series(catalog.code, limit=1)
        if bool(published.get("must_not_use_for_decision")):
            continue
        rows = published.get("rows")
        if not isinstance(rows, list) or not rows:
            continue
        row = rows[-1]
        if not isinstance(row, dict):
            continue
        payload = dict(row)
        for key in (
            "publication_id",
            "publication_key",
            "published_at",
            "as_of",
            "observed_at",
            "freshness_status",
            "must_not_use_for_decision",
            "blocked_reason",
        ):
            if key in published:
                payload[key] = published[key]
        payloads.append(payload)
    return payloads


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
    fact_pks: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Return canonical OHLCV facts, oldest to newest, for cross-app reads."""

    repository = get_price_bar_repository()
    if fact_pks is None:
        bars = repository.get_bars(
            asset_code,
            start=start_date,
            end=end_date,
            limit=limit,
        )
    else:
        bars = repository.get_bars(
            asset_code,
            start=start_date,
            end=end_date,
            limit=limit,
            fact_pks=fact_pks,
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
            "fetched_at": bar.fetched_at.isoformat(),
        }
        for bar in reversed(bars)
    ]
