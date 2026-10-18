"""Legacy batch and pending broker-fact review summaries."""

from __future__ import annotations

import logging

from apps.account.application.broker_trade_reconciliation_contracts import (
    BrokerFactRecord,
    BrokerTradeReconciliationRepository,
    PendingBrokerFactQuery,
)
from apps.account.application.manual_trade_compatibility import _optional_method
from apps.account.application.repository_provider import (
    get_broker_trade_reconciliation_repository,
    get_manual_trade_sync_repository,
)

logger = logging.getLogger(__name__)


class ManualTradeReviewSummaryUseCase:
    """Build imported-trade review from summary batches and persisted fact states."""

    def __init__(
        self,
        *,
        sync_repo: object | None = None,
        reconciliation_repo: BrokerTradeReconciliationRepository | None = None,
    ) -> None:
        """Inject the batch-summary and direct fact-state repositories."""
        self.sync_repo = sync_repo or get_manual_trade_sync_repository()
        self.reconciliation_repo = (
            reconciliation_repo or get_broker_trade_reconciliation_repository()
        )

    def execute(self, *, user_id: int) -> dict[str, object]:
        """Return summary rows and unresolved facts from their durable stores."""
        recent_batches = self._optional_sequence(
            "list_recent_import_batches",
            user_id=user_id,
            limit=20,
        )
        imported_transactions = self._optional_sequence(
            "list_imported_transactions",
            user_id=user_id,
            limit=50,
        )
        pending = self.reconciliation_repo.list_pending_facts(
            PendingBrokerFactQuery(owner_user_id=user_id, portfolio_id=None, limit=100)
        )
        return {
            "batches": [_batch_summary(batch) for batch in recent_batches],
            "transactions": [
                _transaction_summary(transaction) for transaction in imported_transactions
            ],
            "pending_facts": [_pending_fact_summary(fact) for fact in pending],
        }

    def _optional_sequence(self, name: str, **kwargs: object) -> tuple[object, ...]:
        """Read a legacy summary list while safely handling old injected ports."""
        method = _optional_method(self.sync_repo, name)
        if method is None:
            return ()
        try:
            result = method(**kwargs)
        except Exception:
            logger.exception("Broker review summary query failed", extra={"method": name})
            return ()
        if isinstance(result, (list, tuple)):
            return tuple(result)
        return ()


def _batch_summary(batch: object) -> dict[str, object]:
    """Project legacy batch fields without making them reconciliation truth."""
    portfolio = getattr(batch, "portfolio", None)
    return {
        "id": getattr(batch, "id", None),
        "portfolio_id": getattr(batch, "portfolio_id", None),
        "portfolio_name": getattr(portfolio, "name", ""),
        "broker_name": getattr(batch, "broker_name", ""),
        "source_filename": getattr(batch, "source_filename", ""),
        "status": getattr(batch, "status", ""),
        "total_rows": getattr(batch, "total_rows", 0),
        "imported_rows": getattr(batch, "imported_rows", 0),
        "skipped_rows": getattr(batch, "skipped_rows", 0),
        "error_rows": getattr(batch, "error_rows", 0),
        "created_at": getattr(batch, "created_at", None),
    }


def _transaction_summary(transaction: object) -> dict[str, object]:
    """Project the established imported-transaction review fields."""
    portfolio = getattr(transaction, "portfolio", None)
    return {
        "id": getattr(transaction, "id", None),
        "portfolio_id": getattr(transaction, "portfolio_id", None),
        "portfolio_name": getattr(portfolio, "name", ""),
        "asset_code": getattr(transaction, "asset_code", ""),
        "action": getattr(transaction, "action", ""),
        "shares": getattr(transaction, "shares", None),
        "price": getattr(transaction, "price", None),
        "notional": getattr(transaction, "notional", None),
        "traded_at": getattr(transaction, "traded_at", None),
        "created_at": getattr(transaction, "created_at", None),
        "broker_name": getattr(transaction, "broker_name", ""),
        "external_trade_id": getattr(transaction, "external_trade_id", ""),
        "broker_trade_key": getattr(transaction, "broker_trade_key", None),
        "import_batch_id": getattr(transaction, "import_batch_id", None),
    }


def _pending_fact_summary(fact: BrokerFactRecord) -> dict[str, object]:
    """Show unresolved state directly from the persisted broker fact."""
    projection = fact.reconciliation.last_projection
    reason_code = (
        projection.reason_code
        if projection is not None and projection.reason_code is not None
        else fact.reconciliation.last_reason_code
    )
    return {
        "transaction_id": fact.transaction_id,
        "portfolio_id": fact.portfolio_id,
        "asset_code": fact.asset_code,
        "action": fact.action,
        "shares": fact.shares,
        "price": fact.price,
        "traded_at": fact.traded_at,
        "created_at": fact.created_at,
        "broker_name": fact.broker_name,
        "external_trade_id": fact.external_trade_id,
        "broker_trade_key": fact.broker_trade_key,
        "import_batch_id": fact.first_import_batch_id,
        "state": fact.reconciliation.state.value,
        "reason_code": reason_code,
    }
