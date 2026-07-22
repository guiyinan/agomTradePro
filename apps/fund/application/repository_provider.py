"""Fund repository provider for application consumers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from apps.fund.infrastructure.providers import DjangoFundAssetRepository, DjangoFundRepository

if TYPE_CHECKING:
    from apps.fund.infrastructure.adapters.akshare_fund_adapter import (
        AkShareFundAdapter as AkShareFundAdapter,
    )
    from apps.fund.infrastructure.adapters.hybrid_fund_adapter import (
        HybridFundAdapter as HybridFundAdapter,
    )
    from apps.fund.infrastructure.adapters.tushare_fund_adapter import (
        TushareFundAdapter as TushareFundAdapter,
    )


def get_fund_repository() -> DjangoFundRepository:
    """Return the default fund repository."""

    return DjangoFundRepository()


def resolve_fund_names(codes: list[str]) -> dict[str, str]:
    """Resolve fund display names through the fund repository."""

    return get_fund_repository().resolve_fund_names(codes)


def resolve_fund_holding_names(codes: list[str]) -> dict[str, str]:
    """Backfill stock names from fund holdings through the fund repository."""

    return get_fund_repository().resolve_stock_names_from_holdings(codes)


def get_fund_asset_repository() -> DjangoFundAssetRepository:
    """Return the default fund asset repository."""

    return DjangoFundAssetRepository()


def build_tushare_fund_adapter(*, token: str, http_url: str | None = None) -> TushareFundAdapter:
    """Build the Tushare fund adapter."""

    from apps.fund.infrastructure.adapters.tushare_fund_adapter import TushareFundAdapter

    return TushareFundAdapter(token=token, http_url=http_url)


def build_akshare_fund_adapter() -> AkShareFundAdapter:
    """Build the AKShare fund adapter."""

    from apps.fund.infrastructure.adapters.akshare_fund_adapter import AkShareFundAdapter

    return AkShareFundAdapter()


def build_hybrid_fund_adapter() -> HybridFundAdapter:
    """Build the hybrid fund adapter."""

    from apps.fund.infrastructure.adapters.hybrid_fund_adapter import HybridFundAdapter

    return HybridFundAdapter()
