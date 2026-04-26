"""Business-module bridges used by data_center."""

from __future__ import annotations

from datetime import date
from typing import Any


def build_tushare_macro_adapter(*, token: str, http_url: str | None = None):
    from apps.macro.infrastructure.adapters.tushare_adapter import TushareAdapter

    return TushareAdapter(token=token, http_url=http_url)


def build_akshare_macro_adapter():
    from apps.macro.infrastructure.adapters import AKShareAdapter

    return AKShareAdapter()


def get_legacy_macro_series(*, code: str, start_date: date | None, end_date: date | None, source: str | None):
    from apps.macro.infrastructure.repositories import DjangoMacroRepository

    return DjangoMacroRepository().get_series(
        code=code,
        start_date=start_date,
        end_date=end_date,
        source=source,
    )


def build_tushare_fund_adapter(*, token: str, http_url: str | None = None):
    from apps.fund.infrastructure.adapters.tushare_fund_adapter import TushareFundAdapter

    return TushareFundAdapter(token=token, http_url=http_url)


def build_akshare_fund_adapter():
    from apps.fund.infrastructure.adapters.akshare_fund_adapter import AkShareFundAdapter

    return AkShareFundAdapter()


def build_hybrid_fund_adapter():
    from apps.fund.infrastructure.adapters.hybrid_fund_adapter import HybridFundAdapter

    return HybridFundAdapter()


def build_tushare_financial_gateway(*, token: str, http_url: str | None = None):
    from apps.equity.infrastructure.financial_source_gateway import TushareFinancialGateway

    return TushareFinancialGateway(token=token, http_url=http_url)


def build_tushare_valuation_gateway(*, token: str, http_url: str | None = None):
    from apps.equity.infrastructure.valuation_source_gateways import (
        TushareValuationGateway,
    )

    return TushareValuationGateway(token=token, http_url=http_url)


def build_tushare_stock_adapter():
    from apps.equity.infrastructure.adapters import TushareStockAdapter

    return TushareStockAdapter()


def build_akshare_sector_adapter():
    from apps.sector.infrastructure.adapters.akshare_sector_adapter import (
        AKShareSectorAdapter,
    )

    return AKShareSectorAdapter()


def collect_asset_master_candidate_codes() -> list[str]:
    from apps.asset_analysis.infrastructure.models import AssetPoolEntry
    from apps.equity.infrastructure.models import StockInfoModel
    from apps.fund.infrastructure.models import FundHoldingModel, FundInfoModel
    from apps.rotation.infrastructure.models import AssetClassModel

    codes: list[str] = []
    codes.extend(
        StockInfoModel._default_manager.exclude(stock_code__isnull=True).values_list(
            "stock_code",
            flat=True,
        )
    )
    codes.extend(
        FundInfoModel._default_manager.exclude(fund_code__isnull=True).values_list(
            "fund_code",
            flat=True,
        )
    )
    codes.extend(
        FundHoldingModel._default_manager.exclude(stock_code__isnull=True).values_list(
            "stock_code",
            flat=True,
        )
    )
    codes.extend(
        AssetClassModel._default_manager.filter(is_active=True).exclude(
            code__isnull=True
        ).values_list("code", flat=True)
    )
    codes.extend(
        AssetPoolEntry._default_manager.exclude(asset_code__isnull=True).values_list(
            "asset_code",
            flat=True,
        )
    )
    return list(codes)


def load_asset_master_local_rows(*, lookup_codes: list[str], base_codes: list[str]) -> dict[str, list[dict[str, Any]]]:
    from apps.asset_analysis.infrastructure.models import AssetPoolEntry
    from apps.equity.infrastructure.models import StockInfoModel
    from apps.fund.infrastructure.models import FundHoldingModel, FundInfoModel
    from apps.rotation.infrastructure.models import AssetClassModel

    return {
        "stock_rows": list(
            StockInfoModel._default_manager.filter(stock_code__in=lookup_codes).values(
                "stock_code",
                "name",
                "sector",
                "market",
            )
        ),
        "fund_rows": list(
            FundInfoModel._default_manager.filter(fund_code__in=base_codes).values(
                "fund_code",
                "fund_name",
                "fund_type",
                "investment_style",
            )
        ),
        "holding_rows": list(
            FundHoldingModel._default_manager.filter(stock_code__in=lookup_codes)
            .order_by("stock_code", "-report_date")
            .values("stock_code", "stock_name")
        ),
        "rotation_rows": list(
            AssetClassModel._default_manager.filter(
                code__in=base_codes,
                is_active=True,
            ).values(
                "code",
                "name",
                "category",
                "currency",
            )
        ),
        "pool_rows": list(
            AssetPoolEntry._default_manager.filter(asset_code__in=lookup_codes)
            .order_by("asset_code", "-entry_date")
            .values("asset_code", "asset_name", "asset_category")
        ),
    }
