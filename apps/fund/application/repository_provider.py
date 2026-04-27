"""Fund repository provider for application consumers."""

from __future__ import annotations

from apps.fund.infrastructure.providers import DjangoFundAssetRepository, DjangoFundRepository


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
