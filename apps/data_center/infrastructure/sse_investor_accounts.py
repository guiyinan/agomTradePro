"""SSE monthly investor-account fallback for market thermometer inputs."""

from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, datetime
from typing import Any

import requests

from apps.data_center.domain.entities import MacroFact
from apps.data_center.domain.enums import DataQualityStatus
from shared.numeric import safe_float

logger = logging.getLogger(__name__)

SSE_MONTHLY_QUERY_URL = "https://query.sse.com.cn/commonQuery.do"
SSE_INVESTOR_PAGE_URL = "https://www.sse.com.cn/aboutus/publication/monthly/investor/"
SSE_ALL_ACCOUNT_SQL_ID = "COMMON_SSE_TZZ_M_ALL_ACCT_C"


def fetch_investor_account_facts(
    *,
    start_date: date,
    end_date: date,
    provider_source: str,
    provider_name: str,
) -> list[MacroFact]:
    """Fetch investor/account-opening facts from AKShare, then SSE fallback."""

    facts = _fetch_akshare_investor_accounts(
        start_date=start_date,
        end_date=end_date,
        provider_source=provider_source,
        provider_name=provider_name,
    )
    covered_periods = {fact.reporting_period for fact in facts}
    for fact in fetch_sse_account_opening_fallback(
        start_date=start_date,
        end_date=end_date,
        provider_source=provider_source,
        provider_name=provider_name,
    ):
        if fact.reporting_period not in covered_periods:
            facts.append(fact)
    return sorted(facts, key=lambda item: item.reporting_period)


def _fetch_akshare_investor_accounts(
    *,
    start_date: date,
    end_date: date,
    provider_source: str,
    provider_name: str,
) -> list[MacroFact]:
    from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
        _eastmoney_direct_network,
    )
    from apps.data_center.infrastructure.legacy_sdk_bridge import get_akshare_module

    try:
        ak = get_akshare_module()
        with _eastmoney_direct_network():
            df = ak.stock_account_statistics_em()
    except Exception as exc:
        logger.warning("AKShare investor-account sync failed: %s", exc)
        return []
    if df is None or df.empty:
        return []

    facts: list[MacroFact] = []
    for row in df.to_dict("records"):
        observed_at = _month_end_date(_first_present(row, "数据日期", "date", "month"))
        if observed_at is None or observed_at < start_date or observed_at > end_date:
            continue
        value_wan = safe_float(
            _first_present(row, "新增投资者-数量", "新增投资者数量", "new_investors", "new_accounts")
        )
        if value_wan is None:
            continue
        facts.append(
            MacroFact(
                indicator_code="CN_A_NEW_INVESTOR_ACCOUNTS",
                reporting_period=observed_at,
                value=value_wan * 10_000.0,
                unit="户",
                source=provider_source,
                quality=DataQualityStatus.VALID,
                extra={
                    "proxy": "stock_account_statistics_em",
                    "original_unit": "万户",
                    "raw_new_investor_count": value_wan,
                    "provider_name": provider_name,
                    "source_type": provider_source,
                },
            )
        )
    return sorted(facts, key=lambda item: item.reporting_period)


def fetch_sse_account_opening_fallback(
    *,
    start_date: date,
    end_date: date,
    provider_source: str,
    provider_name: str,
) -> list[MacroFact]:
    """Fetch official SSE monthly account-opening rows as audited proxy facts."""

    facts: list[MacroFact] = []
    seen_periods: set[date] = set()
    for query_month in _query_months(start_date=start_date, end_date=end_date):
        try:
            response = requests.get(
                SSE_MONTHLY_QUERY_URL,
                params={
                    "sqlId": SSE_ALL_ACCOUNT_SQL_ID,
                    "isPagination": "false",
                    "MDATE": query_month,
                },
                headers={
                    "Referer": SSE_INVESTOR_PAGE_URL,
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json,text/javascript,*/*;q=0.01",
                },
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("SSE investor-account fallback failed for %s: %s", query_month, exc)
            continue

        for row in payload.get("result") or []:
            observed_at = _month_end_date(row.get("TERM"))
            if (
                observed_at is None
                or observed_at < start_date
                or observed_at > end_date
                or observed_at in seen_periods
            ):
                continue
            total_wan = safe_float(row.get("TOTAL"))
            if total_wan is None or total_wan <= 0:
                continue
            seen_periods.add(observed_at)
            facts.append(
                MacroFact(
                    indicator_code="CN_A_NEW_INVESTOR_ACCOUNTS",
                    reporting_period=observed_at,
                    value=total_wan * 10_000.0,
                    unit="户",
                    source=provider_source,
                    quality=DataQualityStatus.VALID,
                    extra={
                        "proxy": "sse_monthly_all_account_openings",
                        "original_unit": "万户",
                        "raw_total_account_openings": total_wan,
                        "sse_query_month": query_month,
                        "source_url": SSE_INVESTOR_PAGE_URL,
                        "source_sql_id": SSE_ALL_ACCOUNT_SQL_ID,
                        "provider_name": provider_name,
                        "source_type": provider_source,
                    },
                )
            )
    return sorted(facts, key=lambda item: item.reporting_period)


def _query_months(*, start_date: date, end_date: date) -> list[str]:
    """Return SSE MDATE query months, allowing current-year publication lag."""

    query_months = [f"{end_date.year}{month:02d}" for month in range(end_date.month, 0, -1)]
    query_months.extend(f"{year}12" for year in range(end_date.year - 1, start_date.year - 1, -1))
    return query_months


def _month_end_date(value: Any) -> date | None:
    raw_value = str(value or "").strip().replace(".", "-")
    try:
        parsed_month = datetime.strptime(raw_value[:7], "%Y-%m").date()
    except (TypeError, ValueError):
        return None
    return date(
        parsed_month.year,
        parsed_month.month,
        monthrange(parsed_month.year, parsed_month.month)[1],
    )


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None
