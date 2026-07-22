"""Business-module bridges used by data_center."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from apps.macro.domain.entities import MacroIndicator

if TYPE_CHECKING:
    from apps.equity.application.repository_provider import (
        TushareFinancialGateway,
        TushareStockAdapter,
        TushareValuationGateway,
    )
    from apps.fund.application.repository_provider import (
        AkShareFundAdapter,
        HybridFundAdapter,
        TushareFundAdapter,
    )
    from apps.sector.application.repository_provider import AKShareSectorAdapter


def get_legacy_macro_series(
    *, code: str, start_date: date | None, end_date: date | None, source: str | None
) -> list[MacroIndicator]:
    from apps.macro.application.query_services import (
        get_legacy_macro_series as _get_legacy_macro_series,
    )

    rows: list[MacroIndicator] = _get_legacy_macro_series(
        code=code,
        start_date=start_date,
        end_date=end_date,
        source=source,
    )
    return rows


def build_tushare_fund_adapter(*, token: str, http_url: str | None = None) -> TushareFundAdapter:
    from apps.fund.application.repository_provider import (
        build_tushare_fund_adapter as _build_tushare_fund_adapter,
    )

    return _build_tushare_fund_adapter(token=token, http_url=http_url)


def build_akshare_fund_adapter() -> AkShareFundAdapter:
    from apps.fund.application.repository_provider import (
        build_akshare_fund_adapter as _build_akshare_fund_adapter,
    )

    return _build_akshare_fund_adapter()


def build_hybrid_fund_adapter() -> HybridFundAdapter:
    from apps.fund.application.repository_provider import (
        build_hybrid_fund_adapter as _build_hybrid_fund_adapter,
    )

    return _build_hybrid_fund_adapter()


def build_tushare_financial_gateway(
    *, token: str, http_url: str | None = None
) -> TushareFinancialGateway:
    from apps.equity.application.repository_provider import (
        build_tushare_financial_gateway as _build_tushare_financial_gateway,
    )

    return _build_tushare_financial_gateway(token=token, http_url=http_url)


def build_tushare_valuation_gateway(
    *, token: str, http_url: str | None = None
) -> TushareValuationGateway:
    from apps.equity.application.repository_provider import (
        build_tushare_valuation_gateway as _build_tushare_valuation_gateway,
    )

    return _build_tushare_valuation_gateway(token=token, http_url=http_url)


def build_tushare_stock_adapter() -> TushareStockAdapter:
    from apps.equity.application.repository_provider import get_tushare_stock_adapter

    return get_tushare_stock_adapter()


def build_akshare_sector_adapter() -> AKShareSectorAdapter:
    from apps.sector.application.repository_provider import get_sector_adapter

    return get_sector_adapter()


def collect_asset_master_candidate_codes() -> list[str]:
    from apps.asset_analysis.application.query_services import (
        list_asset_master_pool_candidate_codes,
    )
    from apps.equity.application.query_services import list_asset_master_stock_candidate_codes
    from apps.fund.application.query_services import list_asset_master_fund_candidate_codes
    from apps.rotation.application.query_services import (
        list_asset_master_rotation_candidate_codes,
    )

    codes: list[str] = []
    codes.extend(list_asset_master_stock_candidate_codes())
    codes.extend(list_asset_master_fund_candidate_codes())
    codes.extend(list_asset_master_rotation_candidate_codes())
    codes.extend(list_asset_master_pool_candidate_codes())
    return list(codes)


def load_asset_master_local_rows(
    *, lookup_codes: list[str], base_codes: list[str]
) -> dict[str, list[dict[str, Any]]]:
    from apps.asset_analysis.application.query_services import list_asset_master_pool_rows
    from apps.equity.application.query_services import list_asset_master_stock_rows
    from apps.fund.application.query_services import (
        list_asset_master_fund_rows,
        list_asset_master_holding_rows,
    )
    from apps.rotation.application.query_services import list_asset_master_rotation_rows

    return {
        "stock_rows": list_asset_master_stock_rows(lookup_codes),
        "fund_rows": list_asset_master_fund_rows(base_codes),
        "holding_rows": list_asset_master_holding_rows(lookup_codes),
        "rotation_rows": list_asset_master_rotation_rows(base_codes),
        "pool_rows": list_asset_master_pool_rows(lookup_codes),
    }
