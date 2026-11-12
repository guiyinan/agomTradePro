"""Read verified simulated V4 history and revalidate every exact local fill event."""

from __future__ import annotations

from datetime import date, datetime

from django.db import DEFAULT_DB_ALIAS, transaction

from apps.simulated_trading.application.corporate_action_tax_settlement_history import (
    RecordDateOwnershipHistoryRead,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventReader,
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.domain.simulated_tax_settlement_history import (
    SimulatedTaxSettlementFillSource,
)
from apps.simulated_trading.infrastructure.corporate_action_ownership_history_repository import (
    DjangoCorporateActionOwnershipHistoryRepository,
)
from apps.simulated_trading.infrastructure.local_daily_match_event_reader import (
    DjangoLocalDailyMatchEventReader,
)


def _blocked(message: str, code: str) -> SimulatedTradeExecutionBlocked:
    """Return one stable fail-closed history/source error."""

    return SimulatedTradeExecutionBlocked(message, code=code)


class DjangoSimulatedTaxSettlementHistoryRepository:
    """Join one same-alias ownership replay with exact current local source reads."""

    def __init__(
        self,
        *,
        using: str = DEFAULT_DB_ALIAS,
        ownership_history_reader: DjangoCorporateActionOwnershipHistoryRepository,
        source_event_reader: LocalSimulatedFillEventReader,
    ) -> None:
        """Require the existing V4 owner replay and concrete local event reader."""

        if (
            type(using) is not str
            or not using
            or type(ownership_history_reader) is not DjangoCorporateActionOwnershipHistoryRepository
            or ownership_history_reader.database_alias != using
            or type(source_event_reader) is not DjangoLocalDailyMatchEventReader
            or getattr(source_event_reader, "_using", None) != using
        ):
            raise _blocked(
                "tax settlement source readers must be the exact same-alias adapters",
                "TAX_SETTLEMENT_HISTORY_ALIAS_MISMATCH",
            )
        self._using = using
        self._ownership_history_reader = ownership_history_reader
        self._source_event_reader = source_event_reader

    @property
    def database_alias(self) -> str:
        """Return the alias used for account, receipt, action, and source-event reads."""

        return self._using

    def read_record_date_history(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        security_id: str,
        asset_code: str,
        record_date: date,
        as_of: datetime,
    ) -> RecordDateOwnershipHistoryRead:
        """Return complete retained history after full event-to-receipt comparison."""

        if (
            type(account_id) is not int
            or account_id <= 0
            or type(owner_user_id) is not int
            or owner_user_id <= 0
            or type(security_id) is not str
            or not security_id
            or type(asset_code) is not str
            or not asset_code
            or type(record_date) is not date
            or type(as_of) is not datetime
            or as_of.tzinfo is None
            or as_of.utcoffset() is None
        ):
            raise _blocked(
                "simulated tax history source scope is invalid",
                "TAX_SETTLEMENT_HISTORY_SCOPE_INVALID",
            )
        verified: list[SimulatedTaxSettlementFillSource] = []
        with transaction.atomic(using=self._using):
            raw = self._ownership_history_reader.read_record_date_ownership_source_history(
                account_id=account_id,
                owner_user_id=owner_user_id,
                security_id=security_id,
                asset_code=asset_code,
                record_date=record_date,
                evidence_cutoff_at=as_of,
            )
            raw.__post_init__()
            for source in raw.source_fills:
                fact = source.ownership_fill
                if fact.recorded_at > as_of or fact.occurred_at > as_of:
                    raise _blocked(
                        "ownership reader returned a fill outside its requested cutoff",
                        "TAX_SETTLEMENT_HISTORY_SOURCE_MISMATCH",
                    )
                event = source.source_event
                current = self._source_event_reader.read_event(
                    account_id=account_id,
                    user_id=owner_user_id,
                    order_idempotency_key=source.order_idempotency_key,
                    source_namespace=event.source_namespace,
                    fill_event_id=event.source_event_id,
                    as_of=as_of,
                )
                if current is None or current != event:
                    raise _blocked(
                        "retained V4 fill no longer matches its exact source event",
                        "TAX_SETTLEMENT_HISTORY_SOURCE_MISMATCH",
                    )
                trade_observed_at = _trade_observed_at(event)
                verified.append(
                    SimulatedTaxSettlementFillSource(
                        ownership_fill=fact,
                        source_namespace=event.source_namespace,
                        source_version=event.source_version,
                        source_event_id=event.source_event_id,
                        event_payload_sha256=event.event_payload_hash,
                        source_snapshot_id=event.source_snapshot_id,
                        source_snapshot_sha256=event.source_snapshot_hash,
                        order_idempotency_key=source.order_idempotency_key,
                        observation_basis=event.observation_basis,
                        source_observed_at=event.source_observed_at,
                        source_available_at=event.source_available_at,
                        local_known_at=event.local_known_at,
                        interval_end_at=event.interval_end_at,
                        source_recorded_at=event.recorded_at,
                        trade_observed_at=trade_observed_at,
                    )
                )
        return RecordDateOwnershipHistoryRead(
            proof=raw.proof,
            opening_anchor=raw.opening_anchor,
            source_fills=tuple(verified),
            corporate_action_evidence=raw.corporate_action_evidence,
        )


def _trade_observed_at(event: LocalSimulatedFillEventV1) -> datetime:
    """Select only the event contract's explicit source or local-known clock."""

    if type(event) is not LocalSimulatedFillEventV1:
        raise _blocked("local source event is untyped", "TAX_SETTLEMENT_HISTORY_SOURCE_MISMATCH")
    if event.observation_basis == "legacy_source_observed":
        selected = event.source_observed_at
    elif event.observation_basis == "daily_interval_end":
        selected = event.local_known_at
    else:
        selected = None
    if type(selected) is not datetime or selected.tzinfo is None or selected.utcoffset() is None:
        raise _blocked(
            "local source event lacks its explicit observation clock",
            "TAX_SETTLEMENT_HISTORY_SOURCE_MISMATCH",
        )
    return selected


__all__ = ["DjangoSimulatedTaxSettlementHistoryRepository"]
