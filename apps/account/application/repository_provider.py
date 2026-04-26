"""Account repository providers for application consumers."""

from __future__ import annotations

from apps.account.infrastructure.providers import (
    AccountClassificationRepository,
    AccountInterfaceRepository,
    AccountRepository,
    AssetMetadataRepository,
    MacroSizingConfigRepository,
    PortfolioRepository,
    PortfolioSnapshotRepository,
    PositionRepository,
    StopLossRepository,
    SystemSettingsRepository,
    TakeProfitRepository,
    TransactionCostConfigRepository,
    TransactionRepository,
)


def get_account_interface_repository() -> AccountInterfaceRepository:
    """Return the account interface repository."""

    return AccountInterfaceRepository()


def get_account_repository() -> AccountRepository:
    """Return the account repository."""

    return AccountRepository()


def get_account_position_repository() -> PositionRepository:
    """Return the account position repository."""

    return PositionRepository()


def get_portfolio_repository() -> PortfolioRepository:
    """Return the account portfolio repository."""

    return PortfolioRepository()


def build_market_price_service():
    """Build the default market price service lazily."""

    from apps.account.infrastructure.market_price_service import MarketPriceService

    return MarketPriceService()


def build_in_memory_stop_loss_notification_service():
    """Build the default in-memory stop-loss notification service lazily."""

    from apps.account.infrastructure.notification_service import (
        InMemoryStopLossNotificationService,
    )

    return InMemoryStopLossNotificationService()


def build_backup_download_url(token: str) -> str:
    """Build a backup download URL lazily."""

    from apps.account.infrastructure.backup_service import build_backup_download_url as _impl

    return _impl(token)


def describe_backup_package() -> dict:
    """Describe the backup package lazily."""

    from apps.account.infrastructure.backup_service import describe_backup_package as _impl

    return _impl()


def generate_download_token(config) -> str:
    """Generate a backup download token lazily."""

    from apps.account.infrastructure.backup_service import generate_download_token as _impl

    return _impl(config)


def generate_backup_archive(config):
    """Generate the backup archive lazily."""

    from apps.account.infrastructure.backup_service import generate_backup_archive as _impl

    return _impl(config)


def get_backup_email_connection(config):
    """Build the backup email connection lazily."""

    from apps.account.infrastructure.backup_service import get_backup_email_connection as _impl

    return _impl(config)


__all__ = [
    "AccountClassificationRepository",
    "AccountInterfaceRepository",
    "AccountRepository",
    "AssetMetadataRepository",
    "MacroSizingConfigRepository",
    "PortfolioRepository",
    "PortfolioSnapshotRepository",
    "PositionRepository",
    "StopLossRepository",
    "SystemSettingsRepository",
    "TakeProfitRepository",
    "TransactionCostConfigRepository",
    "TransactionRepository",
    "build_in_memory_stop_loss_notification_service",
    "build_market_price_service",
    "build_backup_download_url",
    "describe_backup_package",
    "generate_backup_archive",
    "generate_download_token",
    "get_account_interface_repository",
    "get_account_position_repository",
    "get_account_repository",
    "get_backup_email_connection",
    "get_portfolio_repository",
]
