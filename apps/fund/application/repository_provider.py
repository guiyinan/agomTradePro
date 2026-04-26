"""Fund repository provider for application consumers."""

from __future__ import annotations

from apps.fund.infrastructure.providers import DjangoFundAssetRepository, DjangoFundRepository


def get_fund_repository() -> DjangoFundRepository:
    """Return the default fund repository."""

    return DjangoFundRepository()


def get_fund_asset_repository() -> DjangoFundAssetRepository:
    """Return the default fund asset repository."""

    return DjangoFundAssetRepository()
