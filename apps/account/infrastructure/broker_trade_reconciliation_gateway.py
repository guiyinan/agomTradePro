"""Infrastructure registration for Account broker fact providers."""

from __future__ import annotations

from apps.account.application.broker_trade_reconciliation_contracts import (
    BrokerTradeFactParser,
    BrokerTradeReconciliationRepository,
)


def _build_normalized_parser(raw_parser: object | None) -> BrokerTradeFactParser:
    """Construct the normalized parser owned by Account Infrastructure."""

    from apps.account.infrastructure.broker_import_parser import (
        build_normalized_broker_trade_file_parser,
    )

    return build_normalized_broker_trade_file_parser(raw_parser=raw_parser)


def _build_reconciliation_repository() -> BrokerTradeReconciliationRepository:
    """Construct Account storage with Simulated Trading's public projection port."""

    from apps.account.application.simulated_trading_gateway import (
        get_broker_trade_projection_service,
    )
    from apps.account.infrastructure.broker_trade_reconciliation_repository import (
        DjangoBrokerTradeReconciliationRepository,
    )

    return DjangoBrokerTradeReconciliationRepository(get_broker_trade_projection_service())


def register_broker_trade_fact_providers() -> None:
    """Register typed Account fact providers during App initialization."""

    from apps.account.application.broker_trade_reconciliation_gateway import (
        configure_broker_trade_fact_providers,
    )

    configure_broker_trade_fact_providers(
        parser_factory=_build_normalized_parser,
        repository_factory=_build_reconciliation_repository,
    )


__all__ = ["register_broker_trade_fact_providers"]
