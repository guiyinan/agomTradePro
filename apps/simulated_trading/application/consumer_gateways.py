"""Register Simulated Trading providers with Realtime and Strategy consumers."""

from __future__ import annotations

from apps.realtime.application.simulated_trading_gateway import (
    register_simulated_position_providers,
)
from apps.strategy.application.simulated_trading_gateway import (
    register_simulated_trading_providers,
)

from . import facade, interface_services, query_services, repository_provider


def register_simulated_trading_consumer_gateways() -> None:
    """Register position, facade, and trade-query providers."""

    register_simulated_position_providers(
        repository_factory=repository_provider.get_simulated_position_repository,
        held_asset_codes_provider=query_services.list_held_asset_codes,
    )
    register_simulated_trading_providers(
        facade_factory=facade.get_simulated_trading_facade,
        trade_payload_provider=interface_services.list_account_trade_payloads,
    )


__all__ = ["register_simulated_trading_consumer_gateways"]
