"""Owner-scoped broker fact reads and matcher-savepoint persistence."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.account.application.broker_trade_projection_contracts import (
    BrokerTradeProjectionGateway,
)
from apps.account.application.broker_trade_reconciliation_contracts import (
    BrokerExecutionMatchResult,
    BrokerFactRecord,
    JsonValue,
    PendingBrokerFactQuery,
)
from apps.account.domain.broker_trade_reconciliation import BrokerReconciliationState
from apps.account.infrastructure.models import PortfolioModel, TransactionModel
from core.exceptions import InvalidInputError

from .broker_trade_reconciliation_codec import BrokerFactRecordCodecMixin, _details


class BrokerFactAccessMixin(BrokerFactRecordCodecMixin):
    """Read broker facts and store independent matcher attempts under row locks."""

    _projection_service: BrokerTradeProjectionGateway

    def get_fact_by_stable_key(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        broker_trade_key: str,
    ) -> BrokerFactRecord | None:
        """Read one broker fact inside its exact owner and portfolio scope."""

        model = (
            TransactionModel._default_manager.select_related("portfolio", "import_batch")
            .filter(
                portfolio_id=portfolio_id,
                portfolio__user_id=owner_user_id,
                broker_trade_key=broker_trade_key,
            )
            .first()
        )
        return self._record(model) if model is not None else None

    def get_existing_real_account_id(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
    ) -> int | None:
        """Read an existing real-account mapping through Simulated Trading's port."""

        return self._projection_service.get_existing_real_account_id(
            owner_user_id=owner_user_id,
            portfolio_id=portfolio_id,
        )

    def persist_matching_result(
        self,
        *,
        transaction_id: int,
        result: BrokerExecutionMatchResult,
    ) -> BrokerFactRecord:
        """Store a recommendation-link attempt separately from the immutable fact."""

        with transaction.atomic():
            row = (
                TransactionModel._default_manager.select_for_update(of=("self",))
                .select_related("portfolio", "import_batch")
                .filter(pk=transaction_id)
                .first()
            )
            if row is None or row.broker_trade_key is None:
                raise InvalidInputError("transaction is not a persisted broker fact")
            details = _details(row)
            existing_attempt = self._matching_view(details.get("matching_attempt"))
            if existing_attempt is not None and existing_attempt.outcome in {
                "matched",
                "manual_only",
            }:
                return self._record(row)
            attempt: dict[str, JsonValue] = {
                "attempted_at": timezone.now().isoformat(),
                "outcome": result.outcome,
                "link_id": result.link_id,
                "reason_code": result.reason_code,
            }
            attempts_value = details.get("matching_attempts")
            attempts = attempts_value if isinstance(attempts_value, list) else []
            attempts.append(attempt)
            details["matching_attempts"] = attempts
            details["matching_attempt"] = attempt
            row.broker_reconciliation_details = details
            row.save(update_fields=["broker_reconciliation_details"])
            return self._record(row)

    def matching_attempt_scope(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        transaction_id: int,
    ) -> AbstractContextManager[BrokerFactRecord]:
        """Open a fact-scoped savepoint and lock owner before matcher-side writes."""

        @contextmanager
        def _scope() -> Iterator[BrokerFactRecord]:
            with transaction.atomic():
                portfolio = (
                    PortfolioModel._default_manager.select_for_update()
                    .filter(pk=portfolio_id, user_id=owner_user_id)
                    .first()
                )
                if portfolio is None:
                    raise InvalidInputError("portfolio is not owned by the matcher owner")
                row = (
                    TransactionModel._default_manager.select_for_update(of=("self",))
                    .select_related("portfolio", "import_batch")
                    .filter(
                        pk=transaction_id,
                        portfolio_id=portfolio_id,
                        portfolio__user_id=owner_user_id,
                    )
                    .first()
                )
                if row is None or row.broker_trade_key is None:
                    raise InvalidInputError("transaction is not a persisted broker fact")
                yield self._record(row)

        return _scope()

    def list_pending_facts(self, query: PendingBrokerFactQuery) -> tuple[BrokerFactRecord, ...]:
        """List owner-scoped facts awaiting baseline, projection retry, or match retry."""

        states = [
            BrokerReconciliationState.LEGACY_UNVERIFIED.value,
            BrokerReconciliationState.AWAITING_BASELINE.value,
            BrokerReconciliationState.PROJECTION_PENDING.value,
            BrokerReconciliationState.PROJECTION_BLOCKED.value,
        ]
        queryset = (
            TransactionModel._default_manager.select_related("portfolio", "import_batch")
            .filter(portfolio__user_id=query.owner_user_id)
            .filter(
                Q(broker_reconciliation_state__in=states)
                | Q(broker_reconciliation_details__matching_attempt__outcome="failed")
                | Q(broker_reconciliation_details__matching_attempt__outcome="deferred")
            )
        )
        if query.portfolio_id is not None:
            queryset = queryset.filter(portfolio_id=query.portfolio_id)
        result: list[BrokerFactRecord] = []
        for row in queryset.order_by("created_at", "pk")[: query.limit]:
            result.append(self._record(row))
        return tuple(result)
