"""Real ORM acceptance for the account-locked fee correction repository."""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import connection, models
from django.utils import timezone
from django.utils.functional import SimpleLazyObject

from apps.simulated_trading.application.fee_correction import (
    ApplySimulatedFeeCorrectionUseCase,
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
    FeeCorrectionRequest,
)
from apps.simulated_trading.application.fee_correction_evidence import (
    OPERATOR_FEE_CSV_SCHEMA,
    FeeCorrectionEvidenceUploadCommand,
    FeeCorrectionEvidenceUploadUseCase,
)
from apps.simulated_trading.application.ports import DailyNetValueWritePayload
from apps.simulated_trading.domain.fee_correction import CorrectableFeeComponents
from apps.simulated_trading.infrastructure import fee_correction_repository as repository_module
from apps.simulated_trading.infrastructure.account_mapper import SimulatedAccountMapper
from apps.simulated_trading.infrastructure.daily_net_value_repository import (
    DjangoDailyNetValueRepository,
)
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidenceArtifactModel,
    FeeCorrectionEvidenceBindingModel,
    FeeCorrectionEvidencePolicyModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_repository import (
    DjangoFeeCorrectionEvidenceRepository,
)
from apps.simulated_trading.infrastructure.fee_correction_repository import (
    DjangoFeeCorrectionRepository,
)
from apps.simulated_trading.infrastructure.fee_correction_runtime import (
    build_django_fee_correction_repository,
)
from apps.simulated_trading.infrastructure.models import (
    DailyNetValueModel,
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.position_mapper import PositionMapper
from apps.simulated_trading.infrastructure.position_repository import DjangoPositionRepository
from core.exceptions import BusinessLogicError

pytestmark = pytest.mark.django_db(transaction=True)

_CSV_HEADERS = (
    "schema_version",
    "currency_code",
    "source_account_ref",
    "source_trade_ref",
    "asset_code",
    "side",
    "quantity",
    "price",
    "amount",
    "execution_at",
    "source_observed_at",
    "commission",
    "transfer_fee",
    "stamp_duty",
)
_ASSET_CODE = "600000.SH"


@dataclass(frozen=True, slots=True)
class _LedgerRowsFixture:
    """Persisted owner, ledger rows, and real correction ports without evidence."""

    owner: AbstractBaseUser
    account: SimulatedAccountModel
    trade: SimulatedTradeModel
    position: PositionModel
    evidence_repository: DjangoFeeCorrectionEvidenceRepository
    repository: DjangoFeeCorrectionRepository
    raw_evidence: bytes
    fixture_key: str


@dataclass(frozen=True, slots=True)
class _LedgerFixture(_LedgerRowsFixture):
    """Persisted ledger rows plus the explicitly captured original evidence."""

    request: FeeCorrectionRequest


class _CountingClock:
    """Return one fixed lock-time and count any additional sampling."""

    def __init__(self, value: datetime) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


def _seed_ledger_rows(
    *,
    commission: Decimal,
    revised_commission: Decimal,
    amount: Decimal = Decimal("1000.00"),
    quantity: Decimal = Decimal("100.000000"),
    price: Decimal = Decimal("10.0000"),
    slippage: Decimal = Decimal("0.02"),
    initial_cash: Decimal = Decimal("10000.00"),
) -> _LedgerRowsFixture:
    """Create one exact BUY, matching cost basis, policy, and raw proof bytes."""

    now = timezone.now()
    suffix = uuid4().hex[:12]
    user_model = get_user_model()
    owner = cast(
        AbstractBaseUser,
        user_model.objects.create_user(username=f"fee-correction-{suffix}", password="unused"),
    )
    assert type(owner.pk) is int
    transfer_fee = Decimal("0.00")
    stamp_duty = Decimal("0.00")
    total_cost = amount + commission + transfer_fee + stamp_duty + slippage
    cash = initial_cash - total_cost
    account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name=f"fee-correction-{suffix}",
        account_type="simulated",
        initial_capital=initial_cash,
        current_cash=cash,
        current_market_value=amount,
        total_value=cash + amount,
        is_active=True,
    )
    execution_time = now - timedelta(minutes=30)
    trade = SimulatedTradeModel.objects.create(
        account=account,
        asset_code=_ASSET_CODE,
        asset_name="Fee correction fixture",
        asset_type="equity",
        action="buy",
        quantity=quantity,
        price=price,
        amount=amount,
        commission=commission,
        transfer_fee=transfer_fee,
        stamp_duty=stamp_duty,
        slippage=slippage,
        total_cost=total_cost,
        fee_amounts_known=True,
        cost_basis_known=True,
        realized_pnl=None,
        realized_pnl_pct=None,
        order_date=execution_time.date(),
        execution_date=execution_time.date(),
        execution_time=execution_time,
        status="executed",
    )
    average_cost = (total_cost / quantity).quantize(Decimal("0.0001"))
    position = PositionModel.objects.create(
        account=account,
        asset_code=_ASSET_CODE,
        asset_name="Fee correction fixture",
        asset_type="equity",
        quantity=quantity,
        available_quantity=quantity,
        avg_cost=average_cost,
        total_cost=total_cost,
        cost_basis_known=True,
        current_price=price,
        market_value=amount,
        valuation_known=True,
        unrealized_pnl=amount - total_cost,
        unrealized_pnl_pct=0.0,
        first_buy_date=execution_time.date(),
    )
    evidence_repository = DjangoFeeCorrectionEvidenceRepository()
    FeeCorrectionEvidencePolicyModel.objects.create(
        account=account,
        enabled=True,
        allow_operator_attested_upload=True,
        ledger_currency="CNY",
        version=1,
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=365),
        updated_by=owner,
    )
    raw_evidence = _csv_bytes(
        account_id=account.pk,
        trade=trade,
        source_observed_at=now - timedelta(hours=1),
        commission=revised_commission,
        transfer_fee=transfer_fee,
        stamp_duty=stamp_duty,
    )
    idempotency_key = f"fee-correction-{suffix}"
    repository = build_django_fee_correction_repository(
        evidence_repository=evidence_repository,
    )
    return _LedgerRowsFixture(
        owner=owner,
        account=account,
        trade=trade,
        position=position,
        evidence_repository=evidence_repository,
        repository=repository,
        raw_evidence=raw_evidence,
        fixture_key=idempotency_key,
    )


def _seed_ledger_without_evidence(
    *,
    commission: Decimal,
    revised_commission: Decimal,
    amount: Decimal = Decimal("1000.00"),
    quantity: Decimal = Decimal("100.000000"),
    price: Decimal = Decimal("10.0000"),
    slippage: Decimal = Decimal("0.02"),
    initial_cash: Decimal = Decimal("10000.00"),
) -> _LedgerRowsFixture:
    """Return the real ledger seed before any append-only evidence is captured."""

    return _seed_ledger_rows(
        commission=commission,
        revised_commission=revised_commission,
        amount=amount,
        quantity=quantity,
        price=price,
        slippage=slippage,
        initial_cash=initial_cash,
    )


def _seed_ledger(
    *,
    commission: Decimal,
    revised_commission: Decimal,
    amount: Decimal = Decimal("1000.00"),
    quantity: Decimal = Decimal("100.000000"),
    price: Decimal = Decimal("10.0000"),
    slippage: Decimal = Decimal("0.02"),
    initial_cash: Decimal = Decimal("10000.00"),
) -> _LedgerFixture:
    """Create the standard seed with its original immutable evidence binding."""

    rows = _seed_ledger_rows(
        commission=commission,
        revised_commission=revised_commission,
        amount=amount,
        quantity=quantity,
        price=price,
        slippage=slippage,
        initial_cash=initial_cash,
    )
    evidence_receipt = FeeCorrectionEvidenceUploadUseCase(rows.evidence_repository).execute(
        FeeCorrectionEvidenceUploadCommand(
            account_id=rows.account.pk,
            trade_id=rows.trade.pk,
            expected_revision=0,
            expected_predecessor_id=None,
            idempotency_key=rows.fixture_key,
            original_filename=f"{rows.fixture_key}.csv",
            content=rows.raw_evidence,
            attestation_acknowledged=True,
        ),
        principal=rows.owner,
    )
    request = FeeCorrectionRequest(
        account_id=rows.account.pk,
        trade_id=rows.trade.pk,
        idempotency_key=rows.fixture_key,
        expected_revision=0,
        source_locator=evidence_receipt.source_locator,
    )
    return _LedgerFixture(
        owner=rows.owner,
        account=rows.account,
        trade=rows.trade,
        position=rows.position,
        evidence_repository=rows.evidence_repository,
        repository=rows.repository,
        raw_evidence=rows.raw_evidence,
        fixture_key=rows.fixture_key,
        request=request,
    )


def _upload_command(ledger: _LedgerFixture) -> FeeCorrectionEvidenceUploadCommand:
    """Rebuild the exact idempotent source upload already bound by the fixture."""

    return FeeCorrectionEvidenceUploadCommand(
        account_id=ledger.account.pk,
        trade_id=ledger.trade.pk,
        expected_revision=ledger.request.expected_revision,
        expected_predecessor_id=None,
        idempotency_key=ledger.request.idempotency_key,
        original_filename=f"{ledger.fixture_key}.csv",
        content=ledger.raw_evidence,
        attestation_acknowledged=True,
    )


def _csv_bytes(
    *,
    account_id: int,
    trade: SimulatedTradeModel,
    source_observed_at: datetime,
    commission: Decimal,
    transfer_fee: Decimal,
    stamp_duty: Decimal,
) -> bytes:
    """Encode one explicit owner-attested source row with its claimed source time."""

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(_CSV_HEADERS)
    writer.writerow(
        (
            OPERATOR_FEE_CSV_SCHEMA,
            "CNY",
            f"account-{account_id}",
            f"trade-{trade.pk}",
            trade.asset_code,
            trade.action,
            format(trade.quantity, "f"),
            format(trade.price, "f"),
            format(trade.amount, "f"),
            trade.execution_time.isoformat(timespec="microseconds"),
            source_observed_at.isoformat(timespec="microseconds"),
            format(commission, ".2f"),
            format(transfer_fee, ".2f"),
            format(stamp_duty, ".2f"),
        )
    )
    return output.getvalue().encode("utf-8")


def _run_apply(ledger: _LedgerFixture, clock: _CountingClock) -> ApplySimulatedFeeCorrectionUseCase:
    """Return the real use case with the real proof ports and supplied test clock."""

    return ApplySimulatedFeeCorrectionUseCase(
        repository=ledger.repository,
        evidence_verifier=ledger.evidence_repository,
        authority=ledger.evidence_repository,
        clock=clock,
    )


def _upload_binding(ledger: _LedgerFixture) -> FeeCorrectionEvidenceBindingModel:
    """Read the persisted source binding and its immutable artifact bytes."""

    return FeeCorrectionEvidenceBindingModel.objects.select_related("artifact").get(
        public_id=UUID(ledger.request.source_locator)
    )


def _daily_payload(
    *,
    cash: Decimal,
    market_value: Decimal,
    total_value: Decimal,
    trade_count: int,
    position_count: int,
) -> DailyNetValueWritePayload:
    """Build the exact write shape expected by the existing daily-value repository."""

    return {
        "net_value": float(total_value),
        "cash": float(cash),
        "market_value": float(market_value),
        "daily_return": 0.0,
        "cumulative_return": 0.0,
        "drawdown": 0.0,
        "total_trades": trade_count,
        "positions_count": position_count,
    }


def _create_active_buy_hold(ledger: _LedgerFixture) -> SimulatedOrderReservationModel:
    """Persist a constraint-valid live cash hold after a correction commits."""

    now = timezone.now()
    return SimulatedOrderReservationModel.objects.create(
        account=ledger.account,
        owner_user_id=cast(int, ledger.owner.pk),
        idempotency_key=f"later-active-hold-{uuid4().hex[:8]}",
        intent_payload_hash="a" * 64,
        reservation_request_hash="b" * 64,
        security_id="SH.TEST.FEE.CORRECTION",
        asset_code=_ASSET_CODE,
        asset_name="Active hold fixture",
        side="buy",
        asset_type="equity",
        market="SH",
        board="MAIN",
        quantity=Decimal("1.000000"),
        limit_price=Decimal("10.0000"),
        notional=Decimal("10.00"),
        fee_estimate=Decimal("0.50"),
        fee_budget=Decimal("1.00"),
        commission_estimate=Decimal("0.50"),
        transfer_fee_estimate=Decimal("0.00"),
        stamp_duty_estimate=Decimal("0.00"),
        slippage_estimate=Decimal("0.00"),
        cash_reserved=Decimal("11.00"),
        shares_reserved=Decimal("0.000000"),
        filled_quantity=Decimal("0.000000"),
        cash_consumed=Decimal("0.00"),
        shares_consumed=Decimal("0.000000"),
        cash_released=Decimal("0.00"),
        shares_released=Decimal("0.000000"),
        fee_policy_id="test-fee-policy",
        fee_policy_version=1,
        fee_config_id=1,
        fee_policy_hash="c" * 64,
        plan_snapshot_version=1,
        plan_snapshot={"schema": "fixture"},
        plan_snapshot_hash="d" * 64,
        source_book_cash=ledger.account.current_cash,
        source_sellable_quantity=Decimal("0.000000"),
        source_snapshot_at=now,
        market_session=now.date(),
        settlement_lag_sessions=1,
        settlement_release_date=now.date() + timedelta(days=1),
        reserved_at=now,
        status=SimulatedOrderReservationModel.STATUS_ACTIVE,
    )


def test_real_apply_uses_one_posting_clock_and_preserves_originals_and_daily_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply, as-of read, and daily overlay share one event without rewriting originals."""

    ledger = _seed_ledger(
        commission=Decimal("0.05"),
        revised_commission=Decimal("0.03"),
    )
    binding_before = _upload_binding(ledger)
    original_artifact_bytes = bytes(binding_before.artifact.raw_bytes)
    original_trade_fields = (
        ledger.trade.commission,
        ledger.trade.transfer_fee,
        ledger.trade.stamp_duty,
        ledger.trade.slippage,
        ledger.trade.total_cost,
    )
    clock = _CountingClock(timezone.now() + timedelta(minutes=5))
    # Readers and server-side verification share this explicit synthetic clock.
    monkeypatch.setattr(timezone, "now", lambda: clock.value)
    observed_as_of: list[datetime] = []
    real_effective_fee_map = repository_module._effective_fee_map

    def observe_as_of(
        *,
        trade_rows: Sequence[SimulatedTradeModel],
        events_by_trade: Mapping[int, tuple[SimulatedFeeCorrectionEventModel, ...]],
        as_of: datetime,
    ) -> dict[int, CorrectableFeeComponents]:
        observed_as_of.append(as_of)
        return real_effective_fee_map(
            trade_rows=trade_rows,
            events_by_trade=events_by_trade,
            as_of=as_of,
        )

    monkeypatch.setattr(repository_module, "_effective_fee_map", observe_as_of)

    snapshot_date = timezone.localdate(clock.value)
    daily_repository = DjangoDailyNetValueRepository(correction_history=ledger.repository)
    assert (
        daily_repository.upsert_daily_record(
            account_id=ledger.account.pk,
            record_date=snapshot_date,
            payload=_daily_payload(
                cash=ledger.account.current_cash,
                market_value=ledger.account.current_market_value,
                total_value=ledger.account.total_value,
                trade_count=1,
                position_count=1,
            ),
            expected_account=SimulatedAccountMapper.to_entity(ledger.account),
        )
        is True
    )
    pre_correction_snapshot = DailyNetValueModel.objects.get(
        account=ledger.account,
        record_date=snapshot_date,
    )
    assert pre_correction_snapshot.correction_event_watermark == 0

    receipt = _run_apply(ledger, clock).execute(ledger.request, principal=ledger.owner)
    assert receipt.replayed is False
    assert clock.calls == 1
    assert observed_as_of == [clock.value]
    event = SimulatedFeeCorrectionEventModel.objects.get(pk=receipt.event_id)
    assert event.posted_at == clock.value
    assert event.cash_delta == Decimal("0.02")
    assert event.account_revision == 1

    ledger.account.refresh_from_db()
    ledger.position.refresh_from_db()
    ledger.trade.refresh_from_db()
    binding_after = _upload_binding(ledger)
    assert bytes(binding_after.artifact.raw_bytes) == original_artifact_bytes
    assert (
        ledger.trade.commission,
        ledger.trade.transfer_fee,
        ledger.trade.stamp_duty,
        ledger.trade.slippage,
        ledger.trade.total_cost,
    ) == original_trade_fields
    assert ledger.account.current_cash == Decimal("8999.95")
    assert ledger.account.total_value == Decimal("9999.95")
    assert ledger.position.total_cost == Decimal("1000.05")
    assert ledger.position.avg_cost == Decimal("10.0005")

    prior = ledger.repository.get_account_history(
        account_id=ledger.account.pk,
        as_of=clock.value - timedelta(microseconds=1),
    )
    current = ledger.repository.get_account_history(
        account_id=ledger.account.pk,
        as_of=clock.value,
    )
    assert prior.trades[0].commission == 0.05
    assert prior.trades[0].current_commission == 0.05
    assert prior.trades[0].effective_commission is None
    assert prior.trades[0].fee_correction_overlay_applied is False
    assert prior.trades[0].fee_correction_revision is None
    assert prior.cash_events == ()
    assert current.trades[0].effective_commission == 0.03
    assert len(current.cash_events) == 1
    assert current.cash_events[0].cash_delta == Decimal("0.02")

    daily_rows = daily_repository.list_daily_records(ledger.account.pk)
    assert len(daily_rows) == 1
    assert daily_rows[0]["cash"] == Decimal("8999.95")
    assert daily_rows[0]["net_value"] == Decimal("9999.95")
    assert daily_rows[0]["correction_coverage_known"] is True

    next_date = snapshot_date + timedelta(days=1)
    assert (
        daily_repository.upsert_daily_record(
            account_id=ledger.account.pk,
            record_date=next_date,
            payload=_daily_payload(
                cash=ledger.account.current_cash,
                market_value=ledger.account.current_market_value,
                total_value=ledger.account.total_value,
                trade_count=1,
                position_count=1,
            ),
            expected_account=SimulatedAccountMapper.to_entity(ledger.account),
        )
        is True
    )
    next_snapshot = DailyNetValueModel.objects.get(
        account=ledger.account,
        record_date=next_date,
    )
    assert next_snapshot.correction_event_watermark == 1
    daily_rows = daily_repository.list_daily_records(ledger.account.pk)
    assert daily_rows[1]["cash"] == Decimal("8999.95")
    assert daily_rows[1]["net_value"] == Decimal("9999.95")


def test_corrupt_predecessor_blocks_a_later_apply_without_financial_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source proof cannot turn a malformed prior event into a second posting."""

    ledger = _seed_ledger(
        commission=Decimal("7.00"),
        revised_commission=Decimal("9.00"),
    )
    first_receipt = _run_apply(
        ledger,
        _CountingClock(timezone.now() + timedelta(minutes=5)),
    ).execute(ledger.request, principal=ledger.owner)
    first_event = SimulatedFeeCorrectionEventModel.objects.get(pk=first_receipt.event_id)
    after_first = first_event.posted_at + timedelta(seconds=1)
    monkeypatch.setattr(timezone, "now", lambda: after_first)
    ledger.account.refresh_from_db()
    ledger.position.refresh_from_db()
    account_before = (ledger.account.current_cash, ledger.account.total_value)
    position_before = (
        ledger.position.total_cost,
        ledger.position.avg_cost,
        ledger.position.quantity,
    )

    idempotency_key = f"fee-correction-reversal-{uuid4().hex}"
    content = _csv_bytes(
        account_id=ledger.account.pk,
        trade=ledger.trade,
        source_observed_at=timezone.now() - timedelta(minutes=1),
        commission=Decimal("7.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    )
    uploaded = FeeCorrectionEvidenceUploadUseCase(ledger.evidence_repository).execute(
        FeeCorrectionEvidenceUploadCommand(
            account_id=ledger.account.pk,
            trade_id=ledger.trade.pk,
            expected_revision=1,
            expected_predecessor_id=first_event.pk,
            idempotency_key=idempotency_key,
            original_filename="fee-correction-reversal.csv",
            content=content,
            attestation_acknowledged=True,
        ),
        principal=ledger.owner,
    )
    request = FeeCorrectionRequest(
        account_id=ledger.account.pk,
        trade_id=ledger.trade.pk,
        idempotency_key=idempotency_key,
        expected_revision=1,
        source_locator=uploaded.source_locator,
    )

    table = connection.ops.quote_name(SimulatedFeeCorrectionEventModel._meta.db_table)
    column = connection.ops.quote_name("revised_commission")
    primary_key = connection.ops.quote_name(SimulatedFeeCorrectionEventModel._meta.pk.column)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET {column} = %s WHERE {primary_key} = %s",
            [Decimal("8.00"), first_event.pk],
        )

    with pytest.raises(FeeCorrectionBlockedError) as blocked:
        ApplySimulatedFeeCorrectionUseCase(
            repository=ledger.repository,
            evidence_verifier=ledger.evidence_repository,
            authority=ledger.evidence_repository,
            clock=_CountingClock(first_event.posted_at + timedelta(minutes=5)),
        ).execute(request, principal=ledger.owner)

    assert blocked.value.code == "FEE_CORRECTION_HISTORY_INVALID"
    assert SimulatedFeeCorrectionEventModel.objects.filter(account=ledger.account).count() == 1
    ledger.account.refresh_from_db()
    ledger.position.refresh_from_db()
    assert (ledger.account.current_cash, ledger.account.total_value) == account_before
    assert (
        ledger.position.total_cost,
        ledger.position.avg_cost,
        ledger.position.quantity,
    ) == position_before


def test_same_idempotency_replay_returns_before_rejecting_a_later_active_hold() -> None:
    """A completed correction replay is read-only even when a later order owns cash."""

    ledger = _seed_ledger(
        commission=Decimal("0.05"),
        revised_commission=Decimal("0.03"),
    )
    clock = _CountingClock(timezone.now() + timedelta(minutes=5))
    use_case = _run_apply(ledger, clock)
    original = use_case.execute(ledger.request, principal=ledger.owner)
    ledger.account.refresh_from_db()
    ledger.position.refresh_from_db()
    _create_active_buy_hold(ledger)
    cash_before_replay = ledger.account.current_cash
    position_before_replay = (
        ledger.position.total_cost,
        ledger.position.avg_cost,
        ledger.position.quantity,
    )

    replay = use_case.execute(ledger.request, principal=ledger.owner)

    assert replay.replayed is True
    assert replay.event_id == original.event_id
    assert replay.payload_hash == original.payload_hash
    assert clock.calls == 1
    assert SimulatedFeeCorrectionEventModel.objects.filter(account=ledger.account).count() == 1
    ledger.account.refresh_from_db()
    ledger.position.refresh_from_db()
    assert ledger.account.current_cash == cash_before_replay
    assert (
        ledger.position.total_cost,
        ledger.position.avg_cost,
        ledger.position.quantity,
    ) == position_before_replay


def test_active_hold_still_blocks_a_new_fee_cash_posting() -> None:
    """A live hold allows only exact replay and blocks a new economic mutation."""

    ledger = _seed_ledger(
        commission=Decimal("0.05"),
        revised_commission=Decimal("0.03"),
    )
    _create_active_buy_hold(ledger)
    cash_before = ledger.account.current_cash
    position_before = ledger.position.total_cost
    clock = _CountingClock(timezone.now() + timedelta(minutes=5))

    with pytest.raises(FeeCorrectionBlockedError) as raised:
        _run_apply(ledger, clock).execute(ledger.request, principal=ledger.owner)

    assert raised.value.code == "ORDER_RESERVATION_ACTIVE"
    assert clock.calls == 0
    assert SimulatedFeeCorrectionEventModel.objects.filter(account=ledger.account).count() == 0
    ledger.account.refresh_from_db()
    ledger.position.refresh_from_db()
    assert ledger.account.current_cash == cash_before
    assert ledger.position.total_cost == position_before


def test_posting_time_cash_replay_accepts_a_refund_before_a_later_buy() -> None:
    """A proven refund posted between two BUY cash postings is applied exactly once."""

    ledger = _seed_ledger(
        commission=Decimal("5.00"),
        revised_commission=Decimal("0.00"),
        amount=Decimal("90.00"),
        quantity=Decimal("9.000000"),
        price=Decimal("10.0000"),
        slippage=Decimal("0.00"),
        initial_cash=Decimal("100.00"),
    )
    clock = _CountingClock(timezone.now() + timedelta(minutes=5))
    receipt = _run_apply(ledger, clock).execute(ledger.request, principal=ledger.owner)
    event = SimulatedFeeCorrectionEventModel.objects.get(pk=receipt.event_id)
    assert event.cash_delta == Decimal("5.00")

    next_execution = event.posted_at + timedelta(seconds=2)
    next_trade = SimulatedTradeModel.objects.create(
        account=ledger.account,
        asset_code=_ASSET_CODE,
        asset_name="Later BUY after fee refund",
        asset_type="equity",
        action="buy",
        quantity=Decimal("1.000000"),
        price=Decimal("10.0000"),
        amount=Decimal("10.00"),
        commission=Decimal("0.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
        slippage=Decimal("0.00"),
        total_cost=Decimal("10.00"),
        fee_amounts_known=True,
        cost_basis_known=True,
        realized_pnl=None,
        realized_pnl_pct=None,
        order_date=next_execution.date(),
        execution_date=next_execution.date(),
        execution_time=next_execution,
        status="executed",
    )
    models.QuerySet.update(
        SimulatedTradeModel._base_manager.filter(pk=next_trade.pk),
        created_at=event.posted_at + timedelta(seconds=1),
    )
    models.QuerySet.update(
        PositionModel._base_manager.filter(pk=ledger.position.pk),
        quantity=Decimal("10.000000"),
        available_quantity=Decimal("10.000000"),
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("100.00"),
        current_price=Decimal("10.0000"),
        market_value=Decimal("100.00"),
        unrealized_pnl=Decimal("0.00"),
        cost_basis_known=True,
    )
    models.QuerySet.update(
        SimulatedAccountModel._base_manager.filter(pk=ledger.account.pk),
        current_cash=Decimal("0.00"),
        current_market_value=Decimal("100.00"),
        total_value=Decimal("100.00"),
    )

    history = ledger.repository.get_account_history(
        account_id=ledger.account.pk,
        as_of=next_execution + timedelta(seconds=1),
    )

    assert len(history.trades) == 2
    assert len(history.cash_events) == 1
    assert history.cash_events[0].cash_delta == Decimal("5.00")


def test_repository_transaction_rolls_back_event_cash_and_position_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure after the cash save leaves every original row and projection intact."""

    ledger = _seed_ledger(
        commission=Decimal("0.05"),
        revised_commission=Decimal("0.03"),
    )
    artifact_before = bytes(_upload_binding(ledger).artifact.raw_bytes)
    account_cash_before = ledger.account.current_cash
    account_total_before = ledger.account.total_value
    position_cost_before = ledger.position.total_cost
    trade_economics_before = (
        ledger.trade.commission,
        ledger.trade.transfer_fee,
        ledger.trade.stamp_duty,
        ledger.trade.slippage,
        ledger.trade.total_cost,
    )
    clock = _CountingClock(timezone.now() + timedelta(minutes=5))

    def fail_position_save(
        *,
        position: PositionModel | None,
        replay: object,
        using: str,
    ) -> None:
        del position, replay, using
        raise RuntimeError("injected after event and account writes")

    monkeypatch.setattr(ledger.repository, "_save_corrected_position", fail_position_save)
    with pytest.raises(RuntimeError, match="injected after event"):
        _run_apply(ledger, clock).execute(ledger.request, principal=ledger.owner)

    ledger.account.refresh_from_db()
    ledger.position.refresh_from_db()
    ledger.trade.refresh_from_db()
    assert SimulatedFeeCorrectionEventModel.objects.filter(account=ledger.account).count() == 0
    assert ledger.account.current_cash == account_cash_before
    assert ledger.account.total_value == account_total_before
    assert ledger.position.total_cost == position_cost_before
    assert (
        ledger.trade.commission,
        ledger.trade.transfer_fee,
        ledger.trade.stamp_duty,
        ledger.trade.slippage,
        ledger.trade.total_cost,
    ) == trade_economics_before
    assert bytes(_upload_binding(ledger).artifact.raw_bytes) == artifact_before


def test_real_user_boundary_rejects_duck_types_and_accepts_lazy_request_user() -> None:
    """Apply and evidence ports accept Django users, not claimed pk attributes."""

    ledger = _seed_ledger(
        commission=Decimal("0.05"),
        revised_commission=Decimal("0.03"),
    )
    repository = ledger.evidence_repository
    lazy_owner = cast(
        AuthenticatedFeeCorrectionPrincipalProtocol,
        SimpleLazyObject(lambda: ledger.owner),
    )
    forged_principal = cast(
        AuthenticatedFeeCorrectionPrincipalProtocol,
        SimpleNamespace(pk=ledger.owner.pk, is_authenticated=True),
    )
    artifact_count = FeeCorrectionEvidenceArtifactModel.objects.count()
    binding_count = FeeCorrectionEvidenceBindingModel.objects.count()

    with pytest.raises(FeeCorrectionBlockedError) as capture_error:
        repository.capture(_upload_command(ledger), principal=forged_principal)
    assert capture_error.value.code == "FEE_CORRECTION_PRINCIPAL_INVALID"
    assert (
        repository.authorize(
            account_id=ledger.account.pk,
            principal=forged_principal,
        )
        is None
    )
    assert FeeCorrectionEvidenceArtifactModel.objects.count() == artifact_count
    assert FeeCorrectionEvidenceBindingModel.objects.count() == binding_count

    assert repository.capture(_upload_command(ledger), principal=lazy_owner).source_locator == (
        ledger.request.source_locator
    )
    assert (
        repository.authorize(
            account_id=ledger.account.pk,
            principal=lazy_owner,
        )
        is not None
    )

    evidence = repository.verify(ledger.request)
    authorization = repository.authorize(
        account_id=ledger.account.pk,
        principal=ledger.owner,
    )
    assert evidence is not None
    assert authorization is not None
    clock = _CountingClock(timezone.now() + timedelta(minutes=5))
    with pytest.raises(FeeCorrectionBlockedError) as apply_error:
        ledger.repository.apply_fee_correction(
            request=ledger.request,
            principal=forged_principal,
            evidence=evidence,
            authorization=authorization,
            clock=clock,
        )
    assert apply_error.value.code == "FEE_CORRECTION_PRINCIPAL_INVALID"
    assert clock.calls == 0
    assert SimulatedFeeCorrectionEventModel.objects.filter(account=ledger.account).count() == 0
    assert FeeCorrectionEvidenceArtifactModel.objects.count() == artifact_count
    assert FeeCorrectionEvidenceBindingModel.objects.count() == binding_count

    lazy_apply_clock = _CountingClock(timezone.now() + timedelta(minutes=5))
    lazy_receipt = _run_apply(ledger, lazy_apply_clock).execute(
        ledger.request,
        principal=lazy_owner,
    )
    assert lazy_receipt.replayed is False
    assert lazy_apply_clock.calls == 1
    assert SimulatedFeeCorrectionEventModel.objects.filter(account=ledger.account).count() == 1


def test_owner_authorization_rejects_foreign_and_disabled_real_users() -> None:
    """Real model instances still need current owner scope and an enabled account."""

    ledger = _seed_ledger(
        commission=Decimal("0.05"),
        revised_commission=Decimal("0.03"),
    )
    user_model = get_user_model()
    other_owner = user_model.objects.create_user(
        username=f"fee-correction-other-{uuid4().hex[:12]}",
        password="unused",
    )
    repository = ledger.evidence_repository
    command = _upload_command(ledger)
    artifact_count = FeeCorrectionEvidenceArtifactModel.objects.count()
    binding_count = FeeCorrectionEvidenceBindingModel.objects.count()

    assert (
        repository.authorize(
            account_id=ledger.account.pk,
            principal=other_owner,
        )
        is None
    )
    with pytest.raises(FeeCorrectionBlockedError) as foreign_capture_error:
        repository.capture(command, principal=other_owner)
    assert foreign_capture_error.value.code == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"

    user_model._base_manager.filter(pk=ledger.owner.pk).update(is_active=False)
    assert (
        repository.authorize(
            account_id=ledger.account.pk,
            principal=ledger.owner,
        )
        is None
    )
    with pytest.raises(FeeCorrectionBlockedError) as disabled_capture_error:
        repository.capture(command, principal=ledger.owner)
    assert disabled_capture_error.value.code == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"
    assert FeeCorrectionEvidenceArtifactModel.objects.count() == artifact_count
    assert FeeCorrectionEvidenceBindingModel.objects.count() == binding_count


def test_stale_position_save_cannot_overwrite_applied_fee_correction() -> None:
    """A snapshot read before a real correction cannot restore its older cost basis."""

    ledger = _seed_ledger(
        commission=Decimal("0.05"),
        revised_commission=Decimal("0.03"),
    )
    stale_position = PositionMapper.to_entity(ledger.position)
    original_trade_fields = (
        ledger.trade.commission,
        ledger.trade.transfer_fee,
        ledger.trade.stamp_duty,
        ledger.trade.slippage,
        ledger.trade.total_cost,
    )
    clock = _CountingClock(timezone.now() + timedelta(minutes=5))

    receipt = _run_apply(ledger, clock).execute(ledger.request, principal=ledger.owner)
    assert receipt.replayed is False
    assert clock.calls == 1
    event_before = SimulatedFeeCorrectionEventModel.objects.get(pk=receipt.event_id)
    event_snapshot = (
        event_before.pk,
        event_before.revision,
        event_before.account_revision,
        event_before.cash_delta,
        event_before.posting_date,
        event_before.account_prefix_hash,
    )

    with pytest.raises(BusinessLogicError) as rejected:
        DjangoPositionRepository().save(stale_position)

    assert rejected.value.code == "SIMULATED_POSITION_ATOMIC_WRITE_REQUIRED"
    ledger.account.refresh_from_db()
    ledger.position.refresh_from_db()
    ledger.trade.refresh_from_db()
    assert ledger.account.current_cash == Decimal("8999.95")
    assert ledger.account.total_value == Decimal("9999.95")
    assert ledger.position.total_cost == Decimal("1000.05")
    assert ledger.position.avg_cost == Decimal("10.0005")
    assert (
        ledger.trade.commission,
        ledger.trade.transfer_fee,
        ledger.trade.stamp_duty,
        ledger.trade.slippage,
        ledger.trade.total_cost,
    ) == original_trade_fields
    event_after = SimulatedFeeCorrectionEventModel.objects.get(pk=receipt.event_id)
    assert (
        event_after.pk,
        event_after.revision,
        event_after.account_revision,
        event_after.cash_delta,
        event_after.posting_date,
        event_after.account_prefix_hash,
    ) == event_snapshot
    assert SimulatedFeeCorrectionEventModel.objects.filter(account=ledger.account).count() == 1
