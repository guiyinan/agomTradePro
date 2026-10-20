"""Fail-closed checks for V4 fill settlement-release evidence."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import cast

import pytest

from apps.simulated_trading.application.order_reservation import (
    ReserveSimulatedOrderUseCase,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.order_reservation_fill_release import (
    OrderFillSettlementReleaseProof,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    build_order_fill_settlement_proof,
)
from apps.simulated_trading.infrastructure.models import (
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_binding_codec import (
    encode_order_reservation_fill_binding,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_release_codec import (
    encode_order_fill_settlement_release_proof,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_row_reader import (
    DecodedOrderReservationFillRow,
    read_order_reservation_fill_row,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_snapshot_codec import (
    encode_order_reservation_fill_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _calendar,
    _Clock,
    _execute_use_case,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    _calendar_evidence,
    _reader_rows,
    _Rows,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)

_RELEASE_AT = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)
_RELEASE_SESSION = date(2026, 10, 21)


def _read(rows: _Rows) -> DecodedOrderReservationFillRow:
    """Call the public loaded-row reader with one fixture's exact rows."""

    return read_order_reservation_fill_row(
        reservation_row=rows.reservation,
        receipt_row=rows.receipt,
        trade_row=rows.trade,
    )


def _release_proof(
    rows: _Rows,
    *,
    released_at: datetime = _RELEASE_AT,
    release_session: date = _RELEASE_SESSION,
) -> OrderFillSettlementReleaseProof:
    """Construct a valid release claim for the fixture's exact V4 fill."""

    evidence = _calendar_evidence(rows.proof.settlement_exchange)
    return OrderFillSettlementReleaseProof(
        trade_id=cast(int, rows.trade.pk),
        reservation_id=cast(int, rows.reservation.pk),
        account_id=cast(int, rows.reservation.account_id),
        user_id=cast(int, rows.reservation.owner_user_id),
        receipt_hash=rows.receipt.receipt_hash,
        security_id=rows.reservation.security_id,
        settlement_exchange=rows.proof.settlement_exchange,
        fill_market_session=rows.proof.fill_market_session,
        settlement_lag_sessions=rows.proof.settlement_lag_sessions,
        released_at=released_at,
        release_session=release_session,
        calendar_evidence=evidence,
    )


def _set_release_calendar_mirrors(
    trade: SimulatedTradeModel,
    evidence: ExecutionCalendarEvidence,
) -> None:
    """Copy the full calendar identity into the Trade's checked mirror columns."""

    publication = evidence.publication
    assert publication is not None
    trade.settlement_release_calendar_snapshot_id = evidence.snapshot.snapshot_id
    trade.settlement_release_calendar_content_hash = evidence.snapshot.content_hash
    trade.settlement_release_calendar_record_digest = evidence.snapshot.record_digest
    trade.settlement_release_calendar_publication_id = publication.publication_id
    trade.settlement_release_calendar_publication_hash = publication.publication_hash
    trade.settlement_release_calendar_policy_hash = publication.policy_hash
    trade.settlement_release_calendar_evidence_hash = evidence.evidence_hash
    trade.settlement_release_calendar_timezone = publication.timezone_name


def _install_release_proof(
    rows: _Rows,
    proof: OrderFillSettlementReleaseProof,
) -> None:
    """Materialize the exact proof pair and its duplicated release mirrors."""

    trade = rows.trade
    encoded = encode_order_fill_settlement_release_proof(proof)
    trade.settlement_status = "released"
    trade.settlement_released_at = proof.released_at
    trade.settlement_release_session = proof.release_session
    _set_release_calendar_mirrors(trade, proof.calendar_evidence)
    trade.settlement_release_proof_payload = encoded.to_payload()
    trade.settlement_release_proof_hash = encoded.proof_hash


def _lag_zero_harness(harness: _Harness) -> _Harness:
    """Compose a reservation whose sealed calendar lag is genuinely zero."""

    account_id = cast(int, harness.account.pk)
    user_id = cast(int, harness.account.user_id)
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
    )
    preparer, rule_reader, _ = _execute_use_case(
        account_id=account_id,
        user_id=user_id,
        as_of=AS_OF,
        evidence=evidence,
        lag=0,
    )
    repository = DjangoSimulatedOrderReservationRepository(using="default")
    return replace(
        harness,
        repository=repository,
        preparer=preparer,
        reserve=ReserveSimulatedOrderUseCase(
            preparer=preparer,
            repository=repository,
            clock=_Clock(AS_OF),
        ),
        rule_reader=rule_reader,
    )


def _install_legacy_lag_zero_release(rows: _Rows) -> None:
    """Represent the existing same-session release with no new proof pair."""

    trade = rows.trade
    proof = rows.proof
    trade.settlement_status = "released"
    trade.settlement_released_at = AS_OF + timedelta(minutes=3)
    trade.settlement_release_session = proof.fill_market_session
    _set_release_calendar_mirrors(trade, proof.calendar_evidence)
    trade.settlement_release_proof_payload = None
    trade.settlement_release_proof_hash = None


def test_reader_accepts_pending_and_lagged_release_after_expected_forecast(
    reservation_harness: _Harness,
) -> None:
    """A valid later release session is accepted without rewriting the fill seal."""

    rows = _reader_rows(reservation_harness)
    pending = _read(rows)
    assert pending.release_proof is None
    assert rows.trade.settlement_release_proof_payload is None
    assert rows.trade.settlement_release_proof_hash is None

    proof = _release_proof(rows)
    assert proof.release_session != rows.proof.expected_release_session
    _install_release_proof(rows, proof)

    released = _read(rows)
    assert released.release_proof == proof
    assert released.proof == rows.proof
    assert rows.trade.settlement_release_date == rows.proof.expected_release_session


def test_reader_rejects_release_before_durably_recorded_event_after_full_reseal(
    reservation_harness: _Harness,
) -> None:
    """An otherwise valid release cannot predate a fully resealed event record."""

    rows = _reader_rows(reservation_harness)
    delayed_event = replace(
        rows.event,
        recorded_at=_RELEASE_AT + timedelta(minutes=1),
    )
    encoded = encode_order_reservation_fill_snapshot(
        event=delayed_event,
        economics=rows.economics,
        reservation_id=cast(int, rows.reservation.pk),
        fill_sequence=rows.encoded_snapshot.fill_sequence,
        plan_snapshot_hash=rows.reservation.plan_snapshot_hash,
    )
    binding = encode_order_reservation_fill_binding(
        snapshot=encoded,
        proof=rows.proof,
    )
    receipt = rows.receipt
    receipt.event_kind = delayed_event.event_kind.value
    receipt.source_event_payload = cast(
        dict[str, object],
        json.loads(encoded.source_event_snapshot_json),
    )
    receipt.source_event_payload_hash = encoded.source_event_payload_hash
    receipt.source_event_snapshot_hash = encoded.source_event_snapshot_hash
    receipt.economic_request_hash = encoded.economic_request_hash
    receipt.economics_snapshot_hash = encoded.economics_snapshot_hash
    receipt.plan_snapshot_hash = encoded.plan_snapshot_hash
    receipt.economics_payload = cast(
        dict[str, object],
        json.loads(encoded.economics_snapshot_json),
    )
    receipt.receipt_hash = encoded.receipt_hash
    rows.trade.request_payload_hash = encoded.receipt_hash
    rows.trade.settlement_plan_binding_payload = binding.to_payload()
    rows.trade.settlement_plan_binding_hash = binding.settlement_plan_binding_hash
    resealed_rows = replace(rows, event=delayed_event, encoded_snapshot=encoded)

    release = _release_proof(resealed_rows, released_at=_RELEASE_AT)
    _install_release_proof(resealed_rows, release)

    assert receipt.receipt_hash == encoded.receipt_hash
    assert resealed_rows.trade.settlement_plan_binding_hash == binding.settlement_plan_binding_hash
    assert release.released_at < delayed_event.recorded_at
    assert release.released_at >= delayed_event.occurred_at
    assert release.released_at >= resealed_rows.trade.execution_time
    assert release.released_at >= resealed_rows.proof.calendar_read_cutoff

    with pytest.raises(SimulatedSettlementContractError):
        _read(resealed_rows)


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_pair",
        "half_pair",
        "bad_hash",
        "wrong_identity",
        "wrong_release_clock",
        "wrong_release_session",
        "early_cutoff",
    ),
)
def test_reader_rejects_lagged_release_without_a_complete_matching_proof(
    reservation_harness: _Harness,
    mutation: str,
) -> None:
    """Every proof pair and mirror is checked against the loaded receipt and fill."""

    rows = _reader_rows(reservation_harness)
    proof = _release_proof(rows)
    _install_release_proof(rows, proof)

    if mutation == "missing_pair":
        rows.trade.settlement_release_proof_payload = None
        rows.trade.settlement_release_proof_hash = None
    elif mutation == "half_pair":
        rows.trade.settlement_release_proof_hash = None
    elif mutation == "bad_hash":
        rows.trade.settlement_release_proof_hash = "0" * 64
    elif mutation == "wrong_identity":
        _install_release_proof(rows, replace(proof, account_id=proof.account_id + 1))
    elif mutation == "wrong_release_clock":
        rows.trade.settlement_released_at = proof.released_at + timedelta(seconds=1)
    elif mutation == "wrong_release_session":
        rows.trade.settlement_release_session = date(2026, 10, 20)
    elif mutation == "early_cutoff":
        late_fill_cutoff = build_order_fill_settlement_proof(
            calendar_evidence=rows.proof.calendar_evidence,
            calendar_read_cutoff=proof.released_at + timedelta(days=1),
            fill_occurred_at=rows.event.occurred_at,
            settlement_exchange=rows.proof.settlement_exchange,
            settlement_lag_sessions=rows.proof.settlement_lag_sessions,
        )
        binding = encode_order_reservation_fill_binding(
            snapshot=rows.encoded_snapshot,
            proof=late_fill_cutoff,
        )
        rows.trade.settlement_plan_binding_payload = binding.to_payload()
        rows.trade.settlement_plan_binding_hash = binding.settlement_plan_binding_hash
    else:
        raise AssertionError(f"unknown test mutation: {mutation}")

    with pytest.raises(SimulatedSettlementContractError):
        _read(rows)


@pytest.mark.parametrize(
    "identity_field",
    (
        "trade_id",
        "reservation_id",
        "account_id",
        "user_id",
        "receipt_hash",
        "security_id",
        "settlement_exchange",
        "fill_market_session",
        "settlement_lag_sessions",
    ),
)
def test_reader_rejects_release_proof_detached_from_any_fill_identity(
    reservation_harness: _Harness,
    identity_field: str,
) -> None:
    """A self-valid proof cannot point to a different fill or sealed parent."""

    rows = _reader_rows(reservation_harness)
    proof = _release_proof(rows)
    if identity_field == "trade_id":
        altered = replace(proof, trade_id=proof.trade_id + 1)
    elif identity_field == "reservation_id":
        altered = replace(proof, reservation_id=proof.reservation_id + 1)
    elif identity_field == "account_id":
        altered = replace(proof, account_id=proof.account_id + 1)
    elif identity_field == "user_id":
        altered = replace(proof, user_id=proof.user_id + 1)
    elif identity_field == "receipt_hash":
        altered = replace(proof, receipt_hash="9" * 64)
    elif identity_field == "security_id":
        altered = replace(proof, security_id="OTHER.SECURITY")
    elif identity_field == "settlement_exchange":
        altered = replace(
            proof,
            settlement_exchange="SZ",
            calendar_evidence=_calendar_evidence("SZ"),
        )
    elif identity_field == "fill_market_session":
        altered = replace(proof, fill_market_session=date(2026, 10, 15))
    elif identity_field == "settlement_lag_sessions":
        altered = replace(proof, settlement_lag_sessions=1)
    else:
        raise AssertionError(f"unknown identity field: {identity_field}")
    _install_release_proof(rows, altered)

    with pytest.raises(SimulatedSettlementContractError):
        _read(rows)


@pytest.mark.parametrize(
    "mirror_field",
    (
        "settlement_release_calendar_snapshot_id",
        "settlement_release_calendar_content_hash",
        "settlement_release_calendar_record_digest",
        "settlement_release_calendar_publication_id",
        "settlement_release_calendar_publication_hash",
        "settlement_release_calendar_policy_hash",
        "settlement_release_calendar_evidence_hash",
        "settlement_release_calendar_timezone",
    ),
)
def test_reader_rejects_each_release_calendar_mirror_detached_from_proof(
    reservation_harness: _Harness,
    mirror_field: str,
) -> None:
    """Every release-time calendar mirror remains bound to the proof payload."""

    rows = _reader_rows(reservation_harness)
    _install_release_proof(rows, _release_proof(rows))
    setattr(rows.trade, mirror_field, "changed-release-mirror")

    with pytest.raises(SimulatedSettlementContractError):
        _read(rows)


def test_reader_rejects_pending_buy_with_release_proof_or_mirrors(
    reservation_harness: _Harness,
) -> None:
    """A pending lagged BUY has neither a proof pair nor release mirror state."""

    rows = _reader_rows(reservation_harness)
    encoded = encode_order_fill_settlement_release_proof(_release_proof(rows))
    rows.trade.settlement_release_proof_payload = encoded.to_payload()
    rows.trade.settlement_release_proof_hash = encoded.proof_hash

    with pytest.raises(SimulatedSettlementContractError):
        _read(rows)


def test_reader_accepts_legacy_lag_zero_release_but_checks_fill_calendar_mirrors(
    reservation_harness: _Harness,
) -> None:
    """Legacy same-session rows may omit the proof pair, not their calendar mirrors."""

    rows = _reader_rows(_lag_zero_harness(reservation_harness))
    assert rows.proof.settlement_lag_sessions == 0
    _install_legacy_lag_zero_release(rows)

    result = _read(rows)
    assert result.release_proof is None

    rows.trade.settlement_release_calendar_snapshot_id = "other-calendar"
    with pytest.raises(SimulatedSettlementContractError):
        _read(rows)


def test_reader_accepts_lag_zero_release_with_a_strict_optional_proof(
    reservation_harness: _Harness,
) -> None:
    """A present lag-zero pair receives the same typed identity and mirror checks."""

    rows = _reader_rows(_lag_zero_harness(reservation_harness))
    proof = _release_proof(
        rows,
        released_at=AS_OF + timedelta(minutes=3),
        release_session=rows.proof.fill_market_session,
    )
    _install_release_proof(rows, proof)

    result = _read(rows)
    assert result.release_proof == proof


def test_reader_requires_release_proof_pair_to_remain_absent_for_sell(
    reservation_harness: _Harness,
) -> None:
    """SELL rows never acquire a BUY settlement-release proof."""

    rows = _reader_rows(reservation_harness, side=SimulatedTradeSide.SELL)
    assert _read(rows).release_proof is None
    rows.trade.settlement_release_proof_payload = {"schema": "unexpected"}
    rows.trade.settlement_release_proof_hash = "0" * 64
    with pytest.raises(SimulatedSettlementContractError):
        _read(rows)
