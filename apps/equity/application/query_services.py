"""Application-level query helpers for cross-app equity access."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from apps.data_center.application.public import (
    get_published_equity_context_payloads,
)
from apps.equity.application.repository_provider import (
    get_equity_asset_master_query_repository,
    get_equity_market_data_repository,
    get_equity_stock_repository,
    get_equity_valuation_repair_repository,
)
from shared.numeric import safe_float


def _resolved_financial_period_type(financial: Any) -> str:
    """Return canonical period type for Data Center and legacy financial records."""

    if financial.period_type:
        return str(financial.period_type)
    return {3: "quarterly", 6: "semi_annual", 9: "quarterly", 12: "annual"}.get(
        financial.report_date.month,
        "",
    )


def get_valuation_repair_snapshot_map(stock_codes: list[str]) -> dict[str, dict[str, Any]]:
    """Return valuation repair snapshots keyed by upper security code."""
    normalized_codes = [code for code in stock_codes if code]
    if not normalized_codes:
        return {}
    return get_equity_valuation_repair_repository().get_snapshot_map(normalized_codes)


def get_stock_context_map(stock_codes: list[str]) -> dict[str, dict[str, Any]]:
    """Return current stock context through the publication-gated query port."""

    normalized_codes = [str(code).upper() for code in stock_codes if code]
    if not normalized_codes:
        return {}
    return get_published_stock_context_map(normalized_codes)


def get_stock_name_map(stock_codes: list[str]) -> dict[str, str]:
    """Return display names without loading any market or fundamental facts."""

    master_rows = get_equity_stock_repository().get_stock_master_rows(stock_codes)
    return {
        code: str(row.get("name") or "")
        for code, row in master_rows.items()
        if str(row.get("name") or "")
    }


def _context_date(value: object) -> date | None:
    """Normalize a canonical fact date without accepting malformed values."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    """Extract mapping rows from a publication-gated payload."""

    if not isinstance(payload, Mapping) or payload.get("must_not_use_for_decision") is not False:
        return []
    rows = payload.get("rows")
    if not isinstance(rows, (list, tuple)):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def _payload_gate(payload: object) -> dict[str, object]:
    """Keep stable freshness/provenance evidence for a context row."""

    if not isinstance(payload, Mapping):
        return {
            "must_not_use_for_decision": True,
            "blocked_reason": "published_payload_invalid",
        }
    gate = {
        key: payload[key]
        for key in (
            "dataset_key",
            "publication_key",
            "publication_id",
            "publication_hash",
            "published_at",
            "as_of",
            "policy_identity",
            "policy_version",
            "selected_source",
            "publication_run_id",
            "publication_outcome",
            "coverage_requested_count",
            "coverage_eligible_count",
            "coverage_selected_count",
            "coverage_missing_count",
            "observed_at",
            "age_seconds",
            "max_age_seconds",
            "freshness_status",
            "must_not_use_for_decision",
            "blocked_reason",
        )
        if key in payload
    }
    scope_block = payload.get("scope_block")
    if isinstance(scope_block, Mapping):
        gate["scope_block"] = {
            key: scope_block[key]
            for key in (
                "asset_code",
                "reason_code",
                "target_trade_date",
                "publication_id",
                "source",
                "publication_run_id",
                "policy_version",
                "evidence_source",
            )
            if key in scope_block
        }
    return gate


def _published_financial_context(payload: object) -> dict[str, object]:
    """Aggregate one published financial fact payload by its newest period."""

    rows = _payload_rows(payload)
    grouped: dict[date, list[Mapping[str, object]]] = {}
    for row in rows:
        period_end = _context_date(row.get("period_end"))
        if period_end is not None:
            grouped.setdefault(period_end, []).append(row)
    if not grouped:
        return {}

    latest_period = max(grouped)
    metrics = {
        str(row.get("metric_code") or ""): row
        for row in grouped[latest_period]
        if str(row.get("metric_code") or "")
    }

    def metric_value(metric_code: str) -> float | None:
        row = metrics.get(metric_code)
        return safe_float(row.get("value"), default=None) if row else None

    roe_row = metrics.get("roe")
    raw_roe = roe_row.get("value") if roe_row is not None else None
    roe_value = None if isinstance(raw_roe, bool) else metric_value("roe")
    roe_missing_reason: str | None = None
    if roe_row is not None and isinstance(raw_roe, bool):
        roe_missing_reason = "roe_invalid"
    elif roe_value is None:
        if roe_row is None:
            roe_missing_reason = "roe_missing"
        else:
            if raw_roe is None or (
                isinstance(raw_roe, str)
                and raw_roe.strip().casefold() in {"", "-", "n/a", "na", "null", "none"}
            ):
                roe_missing_reason = "roe_missing"
            elif not isinstance(raw_roe, (str, int, float)):
                roe_missing_reason = "roe_invalid"
            else:
                try:
                    parsed_roe = float(raw_roe)
                except (TypeError, ValueError):
                    roe_missing_reason = "roe_invalid"
                except OverflowError:
                    roe_missing_reason = "roe_nonfinite"
                else:
                    roe_missing_reason = (
                        "roe_nonfinite" if not math.isfinite(parsed_roe) else "roe_invalid"
                    )

    report_date = next(
        (
            report_date
            for report_date in (
                _context_date(row.get("report_date")) for row in grouped[latest_period]
            )
            if report_date is not None
        ),
        latest_period,
    )
    return {
        "period_end": latest_period.isoformat(),
        "report_date": report_date,
        "roe": roe_value,
        "roe_missing_reason": roe_missing_reason,
        "debt_ratio": metric_value("debt_ratio"),
        "revenue_growth": metric_value("revenue_growth"),
        "profit_growth": metric_value("net_profit_growth"),
    }


def _published_price_context(payload: object) -> dict[str, object]:
    """Select the newest row from a published daily-price payload."""

    rows = _payload_rows(payload)
    if not rows:
        return {}
    latest = rows[-1]
    return {
        "trade_date": _context_date(latest.get("timestamp")),
        "close": safe_float(latest.get("close"), default=None),
        "volume": safe_float(latest.get("volume"), default=None),
    }


def _published_valuation_context(payload: object) -> dict[str, object]:
    """Select the newest row from a published valuation payload."""

    rows = _payload_rows(payload)
    if not rows or _valuation_source_observation_reason(payload) is not None:
        return {}
    latest = rows[-1]
    pe_value = latest.get("pe_ttm")
    context: dict[str, object] = {
        "valuation_trade_date": _context_date(latest.get("val_date")),
        "pe": safe_float(
            pe_value if pe_value is not None else latest.get("pe_static"),
            default=None,
        ),
        "pb": safe_float(latest.get("pb"), default=None),
        "ps": safe_float(latest.get("ps_ttm"), default=None),
        "dividend_yield": safe_float(latest.get("dv_ratio"), default=None),
    }
    source_updated_at = latest.get("observed_at")
    if source_updated_at not in (None, ""):
        context["valuation_source_updated_at"] = source_updated_at
    fetched_at = latest.get("fetched_at")
    if fetched_at not in (None, ""):
        context["valuation_fetched_at"] = fetched_at
    return context


def _fact_source_time_fields(row: Mapping[str, object]) -> dict[str, object]:
    """Preserve only raw fact clocks and their public source-time witness."""

    source_evidence = row.get("source_evidence")
    source_mapping = source_evidence if isinstance(source_evidence, Mapping) else {}
    decision_evidence = row.get("decision_evidence")
    decision_mapping = decision_evidence if isinstance(decision_evidence, Mapping) else {}
    if "source_time_witness" in row:
        witness = row.get("source_time_witness")
    else:
        witness = decision_mapping.get("source_time_witness")
    public_witness: dict[str, object] | None = None
    if isinstance(witness, Mapping):
        public_witness = {
            key: witness[key]
            for key in (
                "financial_announced_date",
                "source_timezone",
                "announced_at",
                "available_at",
                "availability_basis",
                "source_time_precision",
            )
            if key in witness
        }
    return {
        "period_end": row.get("period_end"),
        "report_date": row.get("report_date"),
        "val_date": row.get("val_date"),
        "timestamp": row.get("timestamp"),
        "observed_at": row.get("observed_at"),
        "available_at": row.get("available_at"),
        "fetched_at": row.get("fetched_at"),
        "announced_at": source_mapping.get("announced_at"),
        "source_time_witness": public_witness,
    }


def _published_financial_source_times(payload: object) -> dict[str, object]:
    """Return latest-period source clocks indexed by the published metric code."""

    grouped: dict[date, list[Mapping[str, object]]] = {}
    for row in _payload_rows(payload):
        period_end = _context_date(row.get("period_end"))
        if period_end is not None:
            grouped.setdefault(period_end, []).append(row)
    if not grouped:
        return {}
    latest_period = max(grouped)
    result: dict[str, object] = {}
    for row in grouped[latest_period]:
        metric_code = str(row.get("metric_code") or "")
        if metric_code:
            result[metric_code] = _fact_source_time_fields(row)
    return result


def _published_valuation_source_times(payload: object) -> dict[str, object]:
    """Return the selected valuation row clocks or explicit unknown clocks."""

    rows = _payload_rows(payload)
    if rows:
        return _fact_source_time_fields(rows[-1])
    scope_block = payload.get("scope_block") if isinstance(payload, Mapping) else None
    block = scope_block if isinstance(scope_block, Mapping) else {}
    return {
        "val_date": block.get("target_trade_date"),
        "observed_at": None,
        "available_at": None,
        "fetched_at": None,
    }


def _published_price_source_times(payload: object) -> dict[str, object]:
    """Return the selected published price row's raw source clocks."""

    rows = _payload_rows(payload)
    return _fact_source_time_fields(rows[-1]) if rows else {}


def _unresolved_master_context(*, include_price: bool) -> dict[str, object]:
    """Return a blocked context when a request lacks one canonical master row."""

    missing_datasets = ["financial", "valuation"]
    if include_price:
        missing_datasets.append("price")
    source_times: dict[str, object] = {dataset: {} for dataset in missing_datasets}
    return {
        "asset_code": None,
        "name": "",
        "sector": "",
        "market": "",
        "publication_gates": {},
        "must_not_use_for_decision": True,
        "blocked_reason": "canonical_asset_master_identity_missing",
        "missing_datasets": missing_datasets,
        "source_times": source_times,
        "roe": None,
        "debt_ratio": None,
        "revenue_growth": None,
        "profit_growth": None,
        "pe": None,
        "pb": None,
        "ps": None,
        "dividend_yield": None,
        "close": None,
        "volume": None,
        "report_date": None,
        "valuation_trade_date": None,
        "trade_date": None,
    }


def _valuation_source_observation_reason(payload: object) -> str | None:
    """Return a stable gate reason when the selected valuation lacks source time."""

    rows = _payload_rows(payload)
    if not rows:
        return None
    observed_at = rows[-1].get("observed_at")
    if observed_at in (None, ""):
        return "missing_source_observation"
    if isinstance(observed_at, datetime):
        return (
            None
            if observed_at.tzinfo is not None and observed_at.utcoffset() is not None
            else "invalid_source_observation"
        )
    if isinstance(observed_at, str):
        normalized = observed_at.strip()
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return "invalid_source_observation"
        return (
            None
            if parsed.tzinfo is not None and parsed.utcoffset() is not None
            else "invalid_source_observation"
        )
    return "invalid_source_observation"


def get_published_stock_context_map(
    stock_codes: list[str],
    *,
    publication_key: str = "current",
    include_price: bool = True,
    include_financial: bool = True,
    include_valuation: bool = True,
) -> dict[str, dict[str, object]]:
    """Return stock context using only publication-gated canonical facts.

    Asset metadata is read from the canonical master table, while price,
    financial, and valuation values are read through Data Center Public Ports.
    A blocked dataset contributes no values and its stable gate evidence is
    retained in the row so callers can fail closed instead of mistaking an
    empty payload for a valid zero.
    """

    normalized_codes = [str(code).strip().upper() for code in stock_codes if code]
    if not normalized_codes:
        return {}

    requested_codes = list(dict.fromkeys(normalized_codes))
    master_map = get_equity_stock_repository().get_stock_master_rows(requested_codes)
    canonical_codes: dict[str, str] = {}
    for requested_code in requested_codes:
        master = master_map.get(requested_code)
        if not isinstance(master, Mapping):
            continue
        raw_asset_code = master.get("asset_code")
        if not isinstance(raw_asset_code, str):
            continue
        canonical_code = raw_asset_code.strip().upper()
        if canonical_code:
            canonical_codes[requested_code] = canonical_code

    payloads = (
        get_published_equity_context_payloads(
            list(canonical_codes.values()),
            publication_key=publication_key,
            include_price=include_price,
            include_financial=include_financial,
            include_valuation=include_valuation,
        )
        if canonical_codes
        else {}
    )
    context: dict[str, dict[str, object]] = {}
    for requested_code in requested_codes:
        asset_code = canonical_codes.get(requested_code)
        master = master_map.get(requested_code)
        if asset_code is None or not isinstance(master, Mapping):
            context[requested_code] = _unresolved_master_context(include_price=include_price)
            continue
        selected_payloads = payloads.get(asset_code, {})
        price_payload: object = selected_payloads.get("price", {})
        financial_payload: object = selected_payloads.get("financial", {})
        valuation_payload: object = selected_payloads.get("valuation", {})
        gates: dict[str, dict[str, object]] = {}
        if include_financial:
            gates["financial"] = _payload_gate(financial_payload)
        if include_valuation:
            valuation_gate = _payload_gate(valuation_payload)
            source_observation_reason = _valuation_source_observation_reason(valuation_payload)
            if (
                source_observation_reason is not None
                and valuation_gate.get("must_not_use_for_decision") is False
            ):
                valuation_gate = {
                    **valuation_gate,
                    "must_not_use_for_decision": True,
                    "blocked_reason": source_observation_reason,
                }
            gates["valuation"] = valuation_gate
        if include_price:
            gates["price"] = _payload_gate(price_payload)
        blocked_gates = [
            gate for gate in gates.values() if gate.get("must_not_use_for_decision") is not False
        ]
        blocked_reason = next(
            (
                str(gate.get("blocked_reason") or "")
                for gate in blocked_gates
                if str(gate.get("blocked_reason") or "")
            ),
            "",
        )
        source_times: dict[str, object] = {}
        if include_financial:
            source_times["financial"] = _published_financial_source_times(financial_payload)
        if include_valuation:
            source_times["valuation"] = _published_valuation_source_times(valuation_payload)
        if include_price:
            source_times["price"] = _published_price_source_times(price_payload)
        row: dict[str, object] = {
            "requested_code": requested_code,
            "asset_code": asset_code,
            "name": str(master.get("name") or ""),
            "sector": str(master.get("sector") or ""),
            "market": str(master.get("market") or ""),
            "publication_gates": gates,
            "must_not_use_for_decision": bool(blocked_gates),
            "blocked_reason": blocked_reason or None,
            "source_times": source_times,
        }
        missing_datasets = [
            dataset_name
            for dataset_name, payload in (
                ([("financial", financial_payload)] if include_financial else [])
                + ([("valuation", valuation_payload)] if include_valuation else [])
                + ([("price", price_payload)] if include_price else [])
            )
            if not _payload_rows(payload)
        ]
        if missing_datasets:
            row["missing_datasets"] = missing_datasets
        if missing_datasets and not blocked_gates:
            row["must_not_use_for_decision"] = True
            row["blocked_reason"] = "canonical_publication_members_missing"
            row["missing_datasets"] = missing_datasets
        if include_price:
            row.update(_published_price_context(price_payload))
        row.update(_published_financial_context(financial_payload))
        row.update(_published_valuation_context(valuation_payload))
        context[requested_code] = row
    return context


def list_asset_master_stock_candidate_codes() -> list[str]:
    """Return stock codes that can seed data-center asset master rows."""

    return get_equity_asset_master_query_repository().list_candidate_codes()


def list_asset_master_stock_rows(lookup_codes: list[str]) -> list[dict[str, Any]]:
    """Return local stock rows for data-center asset master backfill."""

    return get_equity_asset_master_query_repository().list_stock_rows(lookup_codes)


def fetch_index_daily_returns(
    *,
    index_code: str,
    start_date: date,
    end_date: date,
    hydrate: bool = True,
) -> dict[date, float]:
    """Return daily index returns through the equity application boundary."""

    return get_equity_market_data_repository().get_index_daily_returns(
        index_code=index_code,
        start_date=start_date,
        end_date=end_date,
        hydrate=hydrate,
    )


def list_stock_financial_payloads(
    *,
    stock_code: str,
    report_type: str = "all",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return persisted financial snapshots through the equity application boundary."""

    financials = get_equity_stock_repository().get_financial_data(
        stock_code,
        limit=max(limit * 4, limit),
        hydrate=False,
    )
    if report_type != "all":
        financials = [
            item for item in financials if _resolved_financial_period_type(item) == report_type
        ]
    financials = financials[:limit]
    return [
        {
            "stock_code": item.stock_code,
            "report_date": item.report_date.isoformat(),
            "period_type": _resolved_financial_period_type(item),
            "revenue": str(item.revenue),
            "net_profit": str(item.net_profit),
            "revenue_growth": item.revenue_growth,
            "net_profit_growth": item.net_profit_growth,
            "total_assets": str(item.total_assets),
            "total_liabilities": str(item.total_liabilities),
            "equity": str(item.equity),
            "roe": item.roe,
            "roa": item.roa,
            "debt_ratio": item.debt_ratio,
            "source": item.source,
        }
        for item in financials
    ]
