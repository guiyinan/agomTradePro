"""Registered Account provider boundary for broker fact capabilities."""

from __future__ import annotations

from collections.abc import Callable

from apps.account.application.broker_trade_reconciliation_contracts import (
    BrokerTradeFactParser,
    BrokerTradeReconciliationRepository,
)

_ParserFactory = Callable[[object | None], BrokerTradeFactParser]
_RepositoryFactory = Callable[[], BrokerTradeReconciliationRepository]

_parser_factory: _ParserFactory | None = None
_repository_factory: _RepositoryFactory | None = None


def configure_broker_trade_fact_providers(
    *,
    parser_factory: _ParserFactory,
    repository_factory: _RepositoryFactory,
) -> None:
    """Register Infrastructure-owned implementations at the App composition root."""

    global _parser_factory
    global _repository_factory
    _parser_factory = parser_factory
    _repository_factory = repository_factory


def build_registered_normalized_broker_trade_file_parser(
    raw_parser: object | None = None,
) -> BrokerTradeFactParser:
    """Build the parser implementation registered by Account Infrastructure."""

    if _parser_factory is None:
        raise RuntimeError("Account broker parser provider is not configured")
    return _parser_factory(raw_parser)


def get_registered_broker_trade_reconciliation_repository() -> BrokerTradeReconciliationRepository:
    """Build the reconciliation repository registered by Account Infrastructure."""

    if _repository_factory is None:
        raise RuntimeError("Account broker reconciliation provider is not configured")
    return _repository_factory()


__all__ = [
    "build_registered_normalized_broker_trade_file_parser",
    "configure_broker_trade_fact_providers",
    "get_registered_broker_trade_reconciliation_repository",
]
