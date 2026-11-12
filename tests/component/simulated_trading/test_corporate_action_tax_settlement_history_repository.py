"""Component checks for the exact V4-to-local-event tax history adapter."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.simulated_trading.application.corporate_action_tax_settlement_history import (
    OwnershipHistoryFillSource,
    RecordDateOwnershipSourceRead,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.local_daily_match import (
    LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    OwnershipAnchorKind,
    OwnershipFillFact,
    OwnershipFillSide,
    OwnershipOpeningAnchor,
    RecordDateOwnershipProof,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.infrastructure.corporate_action_ownership_history_repository import (
    DjangoCorporateActionOwnershipHistoryRepository,
    QualifiedExchangeTimezone,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_settlement_history_repository import (
    DjangoSimulatedTaxSettlementHistoryRepository,
)
from apps.simulated_trading.infrastructure.local_daily_match_event_reader import (
    DjangoLocalDailyMatchEventReader,
)

pytestmark = pytest.mark.django_db

_ACCOUNT_ID = 70
_OWNER_ID = 17
_SECURITY = "SYNTHETIC.SEC"
_ASSET = "SYNTHETIC.ASSET"
_ORDER_KEY = "synthetic-order-70"
_OCCURRED_AT = datetime(2026, 4, 8, 2, tzinfo=UTC)
_KNOWN_AT = _OCCURRED_AT + timedelta(minutes=1)
_RECORDED_AT = _OCCURRED_AT + timedelta(minutes=2)
_AS_OF = datetime(2026, 4, 15, 8, tzinfo=UTC)


class _TimezonePolicyReader:
    """Provide a valid constructor dependency; history reads do not re-resolve it."""

    def read_exchange_timezone_policy(
        self,
        *,
        exchange: str,
        as_of: datetime,
    ) -> QualifiedExchangeTimezone:
        """Return one explicit synthetic exchange timezone policy."""

        del as_of
        return QualifiedExchangeTimezone(
            exchange=exchange,
            timezone_name="Asia/Shanghai",
            policy_id="synthetic-timezone-policy.v1",
            policy_sha256="1" * 64,
        )


def _source_pair() -> tuple[LocalSimulatedFillEventV1, OwnershipHistoryFillSource]:
    """Build matching decoded matcher and immutable V4 receipt projections."""

    event = LocalSimulatedFillEventV1(
        source_namespace=LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
        source_version=LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
        source_event_id="synthetic-match-event-70",
        event_payload_hash="2" * 64,
        source_snapshot_id="synthetic-match-snapshot-70",
        source_snapshot_hash="3" * 64,
        reservation_id=117,
        account_id=_ACCOUNT_ID,
        user_id=_OWNER_ID,
        order_idempotency_key=_ORDER_KEY,
        intent_payload_hash="4" * 64,
        reservation_request_hash="5" * 64,
        plan_snapshot_hash="6" * 64,
        security_id=_SECURITY,
        asset_code=_ASSET,
        side=SimulatedTradeSide.BUY,
        event_kind=LocalSimulatedFillEventKind.FILL,
        quantity=Decimal("10.000000"),
        price=Decimal("20.000000"),
        occurred_at=_OCCURRED_AT,
        source_observed_at=None,
        source_available_at=None,
        recorded_at=_RECORDED_AT,
        observation_basis="daily_interval_end",
        interval_end_at=_OCCURRED_AT,
        local_known_at=_KNOWN_AT,
    )
    fact = OwnershipFillFact(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id=_SECURITY,
        asset_code=_ASSET,
        trade_id=91,
        reservation_id=117,
        fill_sequence=1,
        side=OwnershipFillSide.BUY,
        quantity=Decimal("10.000000"),
        execution_date=date(2026, 4, 8),
        occurred_at=_OCCURRED_AT,
        recorded_at=_RECORDED_AT,
        binding_version=4,
        receipt_version=2,
        receipt_sha256="7" * 64,
    )
    return event, OwnershipHistoryFillSource(
        ownership_fill=fact,
        source_event=event,
        order_idempotency_key=_ORDER_KEY,
    )


def _raw_source_read(source: OwnershipHistoryFillSource) -> RecordDateOwnershipSourceRead:
    """Bind one source pair to a complete, exact physical ownership scope."""

    record_date = date(2026, 4, 10)
    proof = RecordDateOwnershipProof(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id=_SECURITY,
        asset_code=_ASSET,
        record_date=record_date,
        ownership_snapshot_as_of_date=record_date,
        record_date_end_exclusive=datetime(2026, 4, 10, 16, tzinfo=UTC),
        exchange="SYNTHETIC",
        exchange_timezone_name="Asia/Shanghai",
        cutoff_policy_id="synthetic-record-cutoff.v1",
        cutoff_policy_sha256="8" * 64,
        eligible_quantity=Decimal("10.000000"),
        ownership_snapshot_id="synthetic-ownership-proof.v1",
        ownership_snapshot_sha256="9" * 64,
        ownership_snapshot_observed_at=datetime(2026, 4, 11, tzinfo=UTC),
    )
    anchor = OwnershipOpeningAnchor(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        anchor_id="synthetic-zero-origin.v1",
        anchor_kind=OwnershipAnchorKind.ZERO_ORIGIN,
        quantity=Decimal("0.000000"),
        effective_at=datetime(2026, 4, 1, tzinfo=UTC),
        observed_at=datetime(2026, 4, 1, tzinfo=UTC),
        evidence_sha256="a" * 64,
    )
    return RecordDateOwnershipSourceRead(
        proof=proof,
        opening_anchor=anchor,
        source_fills=(source,),
        corporate_action_evidence=(),
    )


def _repository(
    monkeypatch: pytest.MonkeyPatch,
    *,
    raw: RecordDateOwnershipSourceRead,
    current_event: LocalSimulatedFillEventV1 | None,
) -> DjangoSimulatedTaxSettlementHistoryRepository:
    """Use concrete adapters while replacing only their external read results."""

    ownership_reader = DjangoCorporateActionOwnershipHistoryRepository(
        exchange_timezone_policy_reader=_TimezonePolicyReader(),
        using="default",
    )
    monkeypatch.setattr(
        ownership_reader,
        "read_record_date_ownership_source_history",
        lambda **scope: raw,
    )
    event_reader = DjangoLocalDailyMatchEventReader(using="default")
    monkeypatch.setattr(event_reader, "read_event", lambda **scope: current_event)
    return DjangoSimulatedTaxSettlementHistoryRepository(
        using="default",
        ownership_history_reader=ownership_reader,
        source_event_reader=event_reader,
    )


def test_adapter_returns_only_an_exact_current_event_with_its_original_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event, source = _source_pair()
    repository = _repository(
        monkeypatch,
        raw=_raw_source_read(source),
        current_event=event,
    )

    result = repository.read_record_date_history(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id=_SECURITY,
        asset_code=_ASSET,
        record_date=date(2026, 4, 10),
        as_of=_AS_OF,
    )

    assert result.source_fills[0].source_event_id == event.source_event_id
    assert result.source_fills[0].trade_observed_at == _KNOWN_AT
    assert result.source_fills[0].source_recorded_at == _RECORDED_AT


def test_adapter_blocks_changed_current_event_instead_of_using_receipt_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event, source = _source_pair()
    altered_event = replace(event, event_payload_hash="b" * 64)
    repository = _repository(
        monkeypatch,
        raw=_raw_source_read(source),
        current_event=altered_event,
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as caught:
        repository.read_record_date_history(
            account_id=_ACCOUNT_ID,
            owner_user_id=_OWNER_ID,
            security_id=_SECURITY,
            asset_code=_ASSET,
            record_date=date(2026, 4, 10),
            as_of=_AS_OF,
        )

    assert caught.value.code == "TAX_SETTLEMENT_HISTORY_SOURCE_MISMATCH"


def test_adapter_rejects_a_source_reader_row_outside_the_requested_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event, source = _source_pair()
    repository = _repository(
        monkeypatch,
        raw=_raw_source_read(source),
        current_event=event,
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as caught:
        repository.read_record_date_history(
            account_id=_ACCOUNT_ID,
            owner_user_id=_OWNER_ID,
            security_id=_SECURITY,
            asset_code=_ASSET,
            record_date=date(2026, 4, 10),
            as_of=_OCCURRED_AT + timedelta(seconds=30),
        )

    assert caught.value.code == "TAX_SETTLEMENT_HISTORY_SOURCE_MISMATCH"
