"""Private candidate tests for known transaction-cost application behavior.

These tests exercise application math and argument forwarding through a typed fake.
They do not claim database locking, owner revalidation, or persistence behavior.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from inspect import Parameter, signature
from typing import TypedDict, cast
from unittest.mock import Mock

import pytest

from apps.account.application.manual_trade_sync import ManualTradeImportUseCase
from apps.account.application.transaction_cost_use_cases import (
    RecordTransactionCostUseCase,
    TransactionCostAnalysis,
    TransactionCostAnalysisUseCase,
)
from apps.account.application.transaction_record_use_cases import (
    CreateTransactionUseCase,
)
from apps.account.domain.transaction_cost_contracts import TransactionCostRecord
from apps.account.domain.transaction_record_contracts import (
    CreateTransactionInput,
    NewTransactionRecord,
    TransactionRecordRepositoryProtocol,
)
from core.exceptions import AuthorizationError, InvalidInputError

FeeAmounts = tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]
FeeStates = tuple[bool | None, bool | None, bool | None, bool | None]


class _KnownFeeTransactionRecord(TypedDict):
    """Complete typed record fixture, including all four persisted availability states."""

    id: int
    portfolio_id: int
    position_id: int | None
    asset_code: str
    action: str
    notional: Decimal
    commission: Decimal | None
    slippage: Decimal | None
    stamp_duty: Decimal | None
    transfer_fee: Decimal | None
    commission_known: bool | None
    slippage_known: bool | None
    stamp_duty_known: bool | None
    transfer_fee_known: bool | None
    estimated_cost: Decimal | None
    cost_variance: Decimal | None
    cost_variance_pct: float | None
    traded_at: datetime


class _UpdateCall(TypedDict):
    transaction_id: int
    actor_user_id: int
    commission: Decimal | None
    slippage: Decimal | None
    stamp_duty: Decimal | None
    transfer_fee: Decimal | None


def _record(
    *,
    transaction_id: int,
    notional: Decimal,
    fees: FeeAmounts,
    known: FeeStates,
    estimated_cost: Decimal | None,
    cost_variance: Decimal | None = None,
    cost_variance_pct: float | None = None,
) -> _KnownFeeTransactionRecord:
    """Build one explicit four-fee, four-state record fixture."""

    commission, slippage, stamp_duty, transfer_fee = fees
    commission_known, slippage_known, stamp_duty_known, transfer_fee_known = known
    return {
        "id": transaction_id,
        "portfolio_id": 11,
        "position_id": None,
        "asset_code": "600000.SH",
        "action": "sell",
        "notional": notional,
        "commission": commission,
        "slippage": slippage,
        "stamp_duty": stamp_duty,
        "transfer_fee": transfer_fee,
        "commission_known": commission_known,
        "slippage_known": slippage_known,
        "stamp_duty_known": stamp_duty_known,
        "transfer_fee_known": transfer_fee_known,
        "estimated_cost": estimated_cost,
        "cost_variance": cost_variance,
        "cost_variance_pct": cost_variance_pct,
        "traded_at": datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
    }


class _TransactionCostRepository:
    """Parameter-capturing fake; it does not model a database or owner lock."""

    def __init__(
        self,
        *,
        rows: list[_KnownFeeTransactionRecord] | None = None,
        update_result: _KnownFeeTransactionRecord | None = None,
    ) -> None:
        self.rows = rows if rows is not None else []
        self.update_result = update_result
        self.update_call: _UpdateCall | None = None
        self.list_call: tuple[int, int | None, datetime | None, datetime | None] | None = None

    def update_transaction_costs(
        self,
        transaction_id: int,
        *,
        actor_user_id: int,
        commission: Decimal | None = None,
        slippage: Decimal | None = None,
        stamp_duty: Decimal | None = None,
        transfer_fee: Decimal | None = None,
    ) -> TransactionCostRecord | None:
        self.update_call = {
            "transaction_id": transaction_id,
            "actor_user_id": actor_user_id,
            "commission": commission,
            "slippage": slippage,
            "stamp_duty": stamp_duty,
            "transfer_fee": transfer_fee,
        }
        return cast(TransactionCostRecord | None, self.update_result)

    def list_user_transaction_costs(
        self,
        user_id: int,
        *,
        portfolio_id: int | None = None,
        since_date: datetime | None = None,
        until_date: datetime | None = None,
    ) -> list[TransactionCostRecord]:
        self.list_call = (user_id, portfolio_id, since_date, until_date)
        return cast(list[TransactionCostRecord], self.rows)


def _analyze(
    repository: _TransactionCostRepository,
) -> TransactionCostAnalysis:
    """Run the public analysis use case with a fixed user and portfolio scope."""

    return TransactionCostAnalysisUseCase(
        transaction_repo=repository,
    ).analyze_user_transaction_costs(
        user_id=7,
        portfolio_id=11,
        days=30,
    )


def test_analysis_uses_one_clock_for_both_traded_time_bounds() -> None:
    """The fixed lookback ends at its captured as-of and never includes future rows."""

    repository = _TransactionCostRepository()
    started_at = datetime.now(UTC)

    analysis = _analyze(repository)

    finished_at = datetime.now(UTC)
    assert analysis.total_transactions == 0
    assert repository.list_call is not None
    user_id, portfolio_id, since_date, until_date = repository.list_call
    assert (user_id, portfolio_id) == (7, 11)
    assert since_date is not None
    assert until_date is not None
    assert started_at <= until_date <= finished_at
    assert until_date - since_date == timedelta(days=30)


def test_derived_actual_variance_uses_the_whole_current_fee_row() -> None:
    # Import inside the test so the base tree can collect every other candidate
    # before this missing proposed pure Domain helper produces its RED.
    from apps.account.domain.transaction_cost_calculations import (
        derive_actual_cost_variance,
    )

    updated_record = _record(
        transaction_id=13,
        notional=Decimal("1000"),
        fees=(
            Decimal("12"),
            Decimal("2"),
            Decimal("3"),
            Decimal("1"),
        ),
        known=(True, True, True, True),
        estimated_cost=Decimal("10"),
        cost_variance=Decimal("2"),
        cost_variance_pct=0.2,
    )

    result = derive_actual_cost_variance(cast(TransactionCostRecord, updated_record))

    assert result.cost_variance == Decimal("8")
    assert result.cost_variance_pct == 0.8


def test_derived_variance_requires_four_known_amounts_and_an_estimate() -> None:
    from apps.account.domain.transaction_cost_calculations import (
        derive_actual_cost_variance,
    )

    complete_fees: FeeAmounts = (
        Decimal("12"),
        Decimal("2"),
        Decimal("3"),
        Decimal("1"),
    )
    complete_states: FeeStates = (True, True, True, True)
    expected_variances = (
        Decimal("-4"),
        Decimal("6"),
        Decimal("5"),
        Decimal("7"),
    )

    for component_index in range(4):
        for unavailable_state in (False, None):
            states = list(complete_states)
            states[component_index] = unavailable_state
            record = _record(
                transaction_id=14 + component_index,
                notional=Decimal("1000"),
                fees=complete_fees,
                known=cast(FeeStates, tuple(states)),
                estimated_cost=Decimal("10"),
                cost_variance=Decimal("2"),
                cost_variance_pct=0.2,
            )
            result = derive_actual_cost_variance(cast(TransactionCostRecord, record))
            assert result.cost_variance is None
            assert result.cost_variance_pct is None

        missing_amounts = list(complete_fees)
        missing_amounts[component_index] = None
        missing_record = _record(
            transaction_id=18 + component_index,
            notional=Decimal("1000"),
            fees=cast(FeeAmounts, tuple(missing_amounts)),
            known=complete_states,
            estimated_cost=Decimal("10"),
            cost_variance=Decimal("2"),
            cost_variance_pct=0.2,
        )
        missing_result = derive_actual_cost_variance(cast(TransactionCostRecord, missing_record))
        assert missing_result.cost_variance is None
        assert missing_result.cost_variance_pct is None

        explicit_zero_amounts = list(complete_fees)
        explicit_zero_amounts[component_index] = Decimal("0")
        zero_record = _record(
            transaction_id=22 + component_index,
            notional=Decimal("1000"),
            fees=cast(FeeAmounts, tuple(explicit_zero_amounts)),
            known=complete_states,
            estimated_cost=Decimal("10"),
            cost_variance=Decimal("99"),
            cost_variance_pct=9.9,
        )
        zero_result = derive_actual_cost_variance(cast(TransactionCostRecord, zero_record))
        assert zero_result.cost_variance == expected_variances[component_index]
        assert zero_result.cost_variance_pct == float(
            expected_variances[component_index] / Decimal("10")
        )

    missing_estimate_record = _record(
        transaction_id=26,
        notional=Decimal("1000"),
        fees=complete_fees,
        known=complete_states,
        estimated_cost=None,
        cost_variance=Decimal("2"),
        cost_variance_pct=0.2,
    )
    missing_estimate_result = derive_actual_cost_variance(
        cast(TransactionCostRecord, missing_estimate_record)
    )
    assert missing_estimate_result.cost_variance is None
    assert missing_estimate_result.cost_variance_pct is None


def test_zero_estimate_keeps_absolute_variance_but_has_no_fraction() -> None:
    from apps.account.domain.transaction_cost_calculations import (
        derive_actual_cost_variance,
    )

    record = _record(
        transaction_id=18,
        notional=Decimal("1000"),
        fees=(Decimal("12"), Decimal("2"), Decimal("3"), Decimal("1")),
        known=(True, True, True, True),
        estimated_cost=Decimal("0"),
        cost_variance=Decimal("99"),
        cost_variance_pct=9.9,
    )

    result = derive_actual_cost_variance(cast(TransactionCostRecord, record))

    assert result.cost_variance == Decimal("18")
    assert result.cost_variance_pct is None


def test_analysis_keeps_complete_actual_and_estimate_cohorts_separate() -> None:
    repository = _TransactionCostRepository(
        rows=[
            _record(
                transaction_id=1,
                notional=Decimal("1000"),
                fees=(
                    Decimal("4"),
                    Decimal("2"),
                    Decimal("3"),
                    Decimal("1"),
                ),
                known=(True, True, True, True),
                estimated_cost=Decimal("10"),
                cost_variance=Decimal("999"),
                cost_variance_pct=0.99,
            ),
            _record(
                transaction_id=2,
                notional=Decimal("1000"),
                fees=(
                    Decimal("8"),
                    Decimal("4"),
                    Decimal("5"),
                    Decimal("3"),
                ),
                known=(True, True, True, True),
                estimated_cost=None,
                cost_variance=Decimal("-88"),
                cost_variance_pct=-0.88,
            ),
        ]
    )

    analysis = _analyze(repository)

    assert analysis.total_transactions == 2
    assert analysis.total_traded_value == Decimal("2000")
    assert analysis.total_actual_cost == Decimal("30")
    assert analysis.actual_sample_count == 2
    assert analysis.paired_actual_cost == Decimal("10")
    assert analysis.total_estimated_cost == Decimal("10")
    assert analysis.paired_sample_count == 1
    assert analysis.cost_variance == Decimal("0")
    assert analysis.cost_variance_pct == 0.0
    assert analysis.estimation_accuracy == 1.0
    assert analysis.accuracy_sample_count == 1
    assert analysis.avg_cost_ratio == pytest.approx(0.015)
    assert analysis.cost_ratio_sample_count == 2
    assert [row["id"] for row in analysis.high_cost_transactions] == [2]


def test_analysis_does_not_turn_unknown_false_or_partial_actuals_into_zero() -> None:
    repository = _TransactionCostRepository(
        rows=[
            _record(
                transaction_id=1,
                notional=Decimal("1000"),
                fees=(
                    Decimal("12"),
                    Decimal("2"),
                    Decimal("3"),
                    Decimal("1"),
                ),
                known=(None, None, None, None),
                estimated_cost=Decimal("10"),
                cost_variance=Decimal("77"),
                cost_variance_pct=0.77,
            ),
            _record(
                transaction_id=2,
                notional=Decimal("1000"),
                fees=(
                    Decimal("0"),
                    Decimal("0"),
                    Decimal("0"),
                    Decimal("0"),
                ),
                known=(False, False, False, False),
                estimated_cost=Decimal("5"),
            ),
            _record(
                transaction_id=3,
                notional=Decimal("1000"),
                fees=(
                    Decimal("4"),
                    Decimal("0"),
                    Decimal("0"),
                    Decimal("0"),
                ),
                known=(True, False, None, False),
                estimated_cost=Decimal("4"),
            ),
        ]
    )

    analysis = _analyze(repository)

    assert analysis.total_transactions == 3
    assert analysis.total_traded_value == Decimal("3000")
    assert analysis.total_actual_cost is None
    assert analysis.actual_sample_count == 0
    assert analysis.paired_actual_cost is None
    assert analysis.total_estimated_cost is None
    assert analysis.paired_sample_count == 0
    assert analysis.cost_variance is None
    assert analysis.cost_variance_pct is None
    assert analysis.estimation_accuracy is None
    assert analysis.accuracy_sample_count == 0
    assert analysis.avg_cost_ratio is None
    assert analysis.cost_ratio_sample_count == 0


def test_explicit_zero_estimate_is_a_pair_without_relative_or_accuracy_denominator() -> None:
    repository = _TransactionCostRepository(
        rows=[
            _record(
                transaction_id=4,
                notional=Decimal("1000"),
                fees=(
                    Decimal("0"),
                    Decimal("0"),
                    Decimal("0"),
                    Decimal("0"),
                ),
                known=(True, True, True, True),
                estimated_cost=Decimal("0"),
            )
        ]
    )

    analysis = _analyze(repository)

    assert analysis.total_actual_cost == Decimal("0")
    assert analysis.actual_sample_count == 1
    assert analysis.paired_actual_cost == Decimal("0")
    assert analysis.total_estimated_cost == Decimal("0")
    assert analysis.paired_sample_count == 1
    assert analysis.cost_variance == Decimal("0")
    assert analysis.cost_variance_pct is None
    assert analysis.estimation_accuracy is None
    assert analysis.accuracy_sample_count == 0
    assert analysis.avg_cost_ratio == 0.0
    assert analysis.cost_ratio_sample_count == 1


def test_cost_ratio_denominator_counts_only_complete_rows_with_positive_notional() -> None:
    repository = _TransactionCostRepository(
        rows=[
            _record(
                transaction_id=5,
                notional=Decimal("1000"),
                fees=(
                    Decimal("4"),
                    Decimal("2"),
                    Decimal("3"),
                    Decimal("1"),
                ),
                known=(True, True, True, True),
                estimated_cost=None,
            ),
            _record(
                transaction_id=6,
                notional=Decimal("1000"),
                fees=(
                    Decimal("8"),
                    Decimal("4"),
                    Decimal("5"),
                    Decimal("3"),
                ),
                known=(True, True, True, True),
                estimated_cost=None,
            ),
            _record(
                transaction_id=7,
                notional=Decimal("0"),
                fees=(
                    Decimal("2"),
                    Decimal("1"),
                    Decimal("2"),
                    Decimal("1"),
                ),
                known=(True, True, True, True),
                estimated_cost=None,
            ),
        ]
    )

    analysis = _analyze(repository)

    assert analysis.total_actual_cost == Decimal("36")
    assert analysis.actual_sample_count == 3
    assert analysis.avg_cost_ratio == pytest.approx(0.015)
    assert analysis.cost_ratio_sample_count == 2
    assert [row["id"] for row in analysis.high_cost_transactions] == [6]


def test_empty_analysis_has_zero_inventory_and_null_cost_metrics() -> None:
    analysis = _analyze(_TransactionCostRepository())

    assert analysis.total_transactions == 0
    assert analysis.total_traded_value == Decimal("0")
    assert analysis.total_actual_cost is None
    assert analysis.actual_sample_count == 0
    assert analysis.paired_actual_cost is None
    assert analysis.total_estimated_cost is None
    assert analysis.paired_sample_count == 0
    assert analysis.cost_variance is None
    assert analysis.cost_variance_pct is None
    assert analysis.estimation_accuracy is None
    assert analysis.accuracy_sample_count == 0
    assert analysis.avg_cost_ratio is None
    assert analysis.cost_ratio_sample_count == 0
    assert analysis.high_cost_transactions == []


def test_record_actual_cost_passes_actor_and_nullable_patch_values_to_repository() -> None:
    # The fake is preloaded with a result and does not implement correction math.
    updated_record = _record(
        transaction_id=8,
        notional=Decimal("1000"),
        fees=(
            Decimal("12"),
            Decimal("2"),
            Decimal("3"),
            Decimal("1"),
        ),
        known=(True, True, True, True),
        estimated_cost=Decimal("10"),
    )
    repository = _TransactionCostRepository(update_result=updated_record)
    use_case = RecordTransactionCostUseCase(transaction_repo=repository)

    result = use_case.record_actual_cost(
        42,
        8,
        actual_commission=Decimal("12"),
        actual_slippage=None,
        actual_stamp_duty=None,
        actual_transfer_fee=None,
    )

    assert repository.update_call == {
        "transaction_id": 8,
        "actor_user_id": 42,
        "commission": Decimal("12"),
        "slippage": None,
        "stamp_duty": None,
        "transfer_fee": None,
    }
    assert result is not None
    assert result == cast(TransactionCostRecord, updated_record)


def test_recording_explicit_zero_is_not_treated_as_an_omitted_correction() -> None:
    updated_record = _record(
        transaction_id=9,
        notional=Decimal("1000"),
        fees=(
            Decimal("0"),
            Decimal("2"),
            Decimal("3"),
            Decimal("1"),
        ),
        known=(True, True, True, True),
        estimated_cost=Decimal("10"),
        cost_variance=Decimal("-4"),
        cost_variance_pct=-0.4,
    )
    repository = _TransactionCostRepository(update_result=updated_record)

    result = RecordTransactionCostUseCase(
        transaction_repo=repository,
    ).record_actual_cost(
        42,
        9,
        actual_commission=Decimal("0"),
    )

    assert repository.update_call == {
        "transaction_id": 9,
        "actor_user_id": 42,
        "commission": Decimal("0"),
        "slippage": None,
        "stamp_duty": None,
        "transfer_fee": None,
    }
    assert result == cast(TransactionCostRecord, updated_record)


def test_recording_without_a_trusted_actor_is_rejected_before_repository_call() -> None:
    repository = _TransactionCostRepository(
        update_result=_record(
            transaction_id=10,
            notional=Decimal("1000"),
            fees=(
                Decimal("5"),
                Decimal("2"),
                Decimal("3"),
                Decimal("1"),
            ),
            known=(True, True, True, True),
            estimated_cost=Decimal("10"),
            cost_variance=Decimal("1"),
            cost_variance_pct=0.1,
        )
    )
    use_case = RecordTransactionCostUseCase(transaction_repo=repository)
    record_actual_cost = cast(Callable[..., TransactionCostRecord], use_case.record_actual_cost)
    parameters = signature(RecordTransactionCostUseCase.record_actual_cost).parameters

    assert "actor_user_id" in parameters
    assert parameters["actor_user_id"].default is Parameter.empty

    with pytest.raises(TypeError):
        record_actual_cost(
            transaction_id=10,
            actual_commission=Decimal("5"),
        )

    assert repository.update_call is None


def test_empty_correction_is_rejected_before_repository_call() -> None:
    repository = _TransactionCostRepository()
    use_case = RecordTransactionCostUseCase(transaction_repo=repository)

    with pytest.raises(InvalidInputError):
        use_case.record_actual_cost(
            42,
            11,
        )

    assert repository.update_call is None


def test_missing_or_non_owned_record_is_a_non_enumerating_denial() -> None:
    repository = _TransactionCostRepository(update_result=None)
    use_case = RecordTransactionCostUseCase(transaction_repo=repository)

    with pytest.raises(AuthorizationError):
        use_case.record_actual_cost(
            42,
            12,
            actual_commission=Decimal("5"),
        )

    assert repository.update_call == {
        "transaction_id": 12,
        "actor_user_id": 42,
        "commission": Decimal("5"),
        "slippage": None,
        "stamp_duty": None,
        "transfer_fee": None,
    }


class _NoOffsetTimezone(tzinfo):
    """Timezone object whose datetime reports no usable UTC offset."""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None


def _create_transaction_input(traded_at: datetime) -> CreateTransactionInput:
    """Build a valid direct-Application input with the supplied trade time."""

    return CreateTransactionInput(
        actor_user_id=42,
        portfolio_id=11,
        position_id=None,
        action="buy",
        asset_code="600000.SH",
        shares=100.0,
        price=Decimal("10.00"),
        notes="direct-usecase-time-contract",
        traded_at=traded_at,
    )


@pytest.mark.parametrize(
    "traded_at",
    [
        datetime(2026, 10, 18, 10, 0),
        datetime(2026, 10, 18, 10, 0, tzinfo=_NoOffsetTimezone()),
        None,
    ],
    ids=("naive", "missing_offset", "not_datetime"),
)
def test_create_transaction_rejects_unaware_or_non_datetime_before_repository_call(
    traded_at: object,
) -> None:
    repository = Mock(spec=TransactionRecordRepositoryProtocol)
    use_case = CreateTransactionUseCase(
        repository=cast(TransactionRecordRepositoryProtocol, repository)
    )

    with pytest.raises(InvalidInputError) as exc_info:
        use_case.execute(_create_transaction_input(cast(datetime, traded_at)))

    assert exc_info.value.details == {"field": "traded_at"}
    repository.create_transaction.assert_not_called()


@pytest.mark.parametrize(
    "traded_at",
    [
        datetime(2026, 10, 18, 10, 0, tzinfo=UTC),
        datetime(2026, 10, 18, 18, 0, tzinfo=timezone(timedelta(hours=8))),
    ],
    ids=("utc", "non_utc"),
)
def test_create_transaction_passes_the_original_aware_time_to_repository(
    traded_at: datetime,
) -> None:
    repository = Mock(spec=TransactionRecordRepositoryProtocol)
    use_case = CreateTransactionUseCase(
        repository=cast(TransactionRecordRepositoryProtocol, repository)
    )

    use_case.execute(_create_transaction_input(traded_at))

    repository.create_transaction.assert_called_once()
    record = cast(NewTransactionRecord, repository.create_transaction.call_args.args[0])
    assert record.traded_at is traded_at


@pytest.mark.parametrize(
    ("fee_field", "value"),
    [
        pytest.param("commission", True, id="bool-is-not-money"),
        pytest.param("slippage", Decimal("NaN"), id="decimal-nan"),
        pytest.param("stamp_duty", Decimal("Infinity"), id="decimal-infinity"),
        pytest.param("transfer_fee", Decimal("-0.01"), id="negative-fee"),
        pytest.param("commission", float("nan"), id="float-nan-is-not-decimal"),
        pytest.param("slippage", float("inf"), id="float-inf-is-not-decimal"),
        pytest.param("commission", Decimal("100000000.00"), id="commission-field-overflow"),
        pytest.param("slippage", Decimal("100000000.00"), id="slippage-field-overflow"),
        pytest.param("stamp_duty", Decimal("100000000.00"), id="stamp-duty-field-overflow"),
        pytest.param("transfer_fee", Decimal("100000000.00"), id="transfer-fee-field-overflow"),
    ],
)
def test_direct_create_and_correction_reject_invalid_fee_inputs_before_repository_calls(
    fee_field: str,
    value: object,
) -> None:
    """Both public Application paths reject invalid fees before handing off to a port."""

    create_repository = Mock(spec=TransactionRecordRepositoryProtocol)
    command = replace(
        _create_transaction_input(datetime(2026, 10, 18, 10, 0, tzinfo=UTC)),
        **{fee_field: cast(Decimal | None, value)},
    )

    with pytest.raises(InvalidInputError) as create_error:
        CreateTransactionUseCase(
            repository=cast(TransactionRecordRepositoryProtocol, create_repository)
        ).execute(command)

    assert create_error.value.details == {"field": fee_field}
    create_repository.create_transaction.assert_not_called()

    actual_repository = _TransactionCostRepository()
    actual_field = f"actual_{fee_field}"
    record_actual_cost = cast(
        Callable[..., TransactionCostRecord],
        RecordTransactionCostUseCase(
            transaction_repo=actual_repository,
        ).record_actual_cost,
    )
    with pytest.raises(InvalidInputError) as correction_error:
        record_actual_cost(
            42,
            81,
            **{actual_field: cast(Decimal | None, value)},
        )

    assert correction_error.value.details == {"field": fee_field}
    assert actual_repository.update_call is None


@pytest.mark.parametrize(
    ("field", "value", "expected_error_field"),
    [
        pytest.param("shares", True, "shares", id="boolean-quantity"),
        pytest.param("shares", float("nan"), "shares", id="nan-quantity"),
        pytest.param("shares", float("inf"), "shares", id="infinite-quantity"),
        pytest.param("shares", -1.0, "shares", id="negative-quantity"),
        pytest.param("price", Decimal("NaN"), "price", id="nan-price"),
        pytest.param("price", Decimal("Infinity"), "price", id="infinite-price"),
        pytest.param("price", Decimal("-0.01"), "price", id="negative-price"),
        pytest.param(
            "price",
            Decimal("10000000000000000.0000"),
            "price",
            id="decimal-price-field-overflow",
        ),
    ],
)
def test_direct_create_rejects_invalid_quantity_or_price_before_repository_call(
    field: str,
    value: object,
    expected_error_field: str,
) -> None:
    """Unsafe quantity and price values cannot cross the Application port."""

    repository = Mock(spec=TransactionRecordRepositoryProtocol)
    replacement = {field: cast(float, value) if field == "shares" else cast(Decimal, value)}
    command = replace(
        _create_transaction_input(datetime(2026, 10, 18, 10, 0, tzinfo=UTC)),
        **replacement,
    )

    with pytest.raises(InvalidInputError) as exc_info:
        CreateTransactionUseCase(
            repository=cast(TransactionRecordRepositoryProtocol, repository)
        ).execute(command)

    assert exc_info.value.details == {"field": expected_error_field}
    repository.create_transaction.assert_not_called()


def test_direct_create_rejects_computed_notional_above_decimal_field_before_repository_call() -> (
    None
):
    """A valid maximum price cannot overflow the persisted notional through quantity."""

    repository = Mock(spec=TransactionRecordRepositoryProtocol)
    command = replace(
        _create_transaction_input(datetime(2026, 10, 18, 10, 0, tzinfo=UTC)),
        shares=100.0001,
        price=Decimal("9999999999999999.9999"),
    )

    with pytest.raises(InvalidInputError) as exc_info:
        CreateTransactionUseCase(
            repository=cast(TransactionRecordRepositoryProtocol, repository)
        ).execute(command)

    assert exc_info.value.details == {"field": "shares"}
    repository.create_transaction.assert_not_called()


def test_direct_applications_accept_exact_storage_limits_and_explicit_zero() -> None:
    """Legitimate Decimal(20,4)/(20,2)/(10,2) boundaries remain usable."""

    repository = Mock(spec=TransactionRecordRepositoryProtocol)
    use_case = CreateTransactionUseCase(
        repository=cast(TransactionRecordRepositoryProtocol, repository)
    )
    base_time = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
    maximum_notional_command = replace(
        _create_transaction_input(base_time),
        shares=100.0,
        price=Decimal("9999999999999999.9999"),
        commission=Decimal("99999999.99"),
        slippage=Decimal("0"),
        stamp_duty=Decimal("0.00"),
        transfer_fee=None,
    )
    use_case.execute(maximum_notional_command)

    maximum_notional_record = cast(
        NewTransactionRecord,
        repository.create_transaction.call_args_list[0].args[0],
    )
    assert maximum_notional_record.price == Decimal("9999999999999999.9999")
    assert maximum_notional_record.notional == Decimal("999999999999999999.99")
    assert maximum_notional_record.commission == Decimal("99999999.99")
    assert maximum_notional_record.slippage == Decimal("0.00")
    assert maximum_notional_record.stamp_duty == Decimal("0.00")
    assert maximum_notional_record.transfer_fee is None

    maximum_shares_command = replace(
        _create_transaction_input(base_time),
        shares=1_000_000_000_000.0,
        price=Decimal("0.01"),
    )
    use_case.execute(maximum_shares_command)
    maximum_shares_record = cast(
        NewTransactionRecord,
        repository.create_transaction.call_args_list[1].args[0],
    )
    assert maximum_shares_record.shares == 1_000_000_000_000.0
    assert maximum_shares_record.notional == Decimal("10000000000.00")
    assert repository.create_transaction.call_count == 2

    maximum_fee_result = _record(
        transaction_id=81,
        notional=Decimal("999999999999999999.99"),
        fees=(
            Decimal("99999999.99"),
            Decimal("0.00"),
            Decimal("0.00"),
            Decimal("0.00"),
        ),
        known=(True, True, True, True),
        estimated_cost=None,
    )
    actual_repository = _TransactionCostRepository(update_result=maximum_fee_result)
    recorded = RecordTransactionCostUseCase(
        transaction_repo=actual_repository,
    ).record_actual_cost(
        42,
        81,
        actual_commission=Decimal("99999999.99"),
        actual_slippage=Decimal("0"),
        actual_stamp_duty=Decimal("0.00"),
        actual_transfer_fee=None,
    )

    assert actual_repository.update_call == {
        "transaction_id": 81,
        "actor_user_id": 42,
        "commission": Decimal("99999999.99"),
        "slippage": Decimal("0.00"),
        "stamp_duty": Decimal("0.00"),
        "transfer_fee": None,
    }
    assert recorded == cast(TransactionCostRecord, maximum_fee_result)


@pytest.mark.parametrize(
    ("raw_fee", "expected_valid_rows", "expected_preview"),
    [
        pytest.param(None, 1, None, id="missing"),
        pytest.param("", 1, None, id="blank"),
        pytest.param("  ", 1, None, id="whitespace-blank"),
        pytest.param(0, 1, "0", id="integer-zero-preserves-format"),
        pytest.param("0", 1, "0", id="string-zero-preserves-format"),
        pytest.param("0.00", 1, "0.00", id="scaled-zero-preserves-format"),
        pytest.param("0.005", 1, "0.01", id="half-up-to-cent"),
        pytest.param("0.004", 1, "0.00", id="below-half-to-cent"),
        pytest.param("1.230", 1, "1.230", id="cent-exact-extra-scale-is-accepted"),
        pytest.param("99999999.994", 1, "99999999.99", id="rounds-into-field-limit"),
        pytest.param("99999999.995", 0, None, id="rounds-past-field-limit"),
        pytest.param("NaN", 0, None, id="nan-is-a-row-error"),
        pytest.param("Infinity", 0, None, id="infinity-is-a-row-error"),
        pytest.param("-0.01", 0, None, id="negative-fee-is-a-row-error"),
    ],
)
def test_manual_import_preview_uses_actual_fee_cents_policy_and_preserves_exact_format(
    raw_fee: object,
    expected_valid_rows: int,
    expected_preview: str | None,
) -> None:
    """Preview uses cents rounding and preserves exact-cent source formatting."""

    sync_repo = Mock()
    sync_repo.get_owned_portfolio.return_value = object()
    sync_repo.broker_trade_key_exists.return_value = False
    parser = Mock(spec=["parse"])
    raw_rows = [
        {
            "traded_at": datetime(2026, 10, 18, 10, 0, tzinfo=UTC),
            "action": "buy",
            "asset_code": "600000.SH",
            "shares": "100",
            "price": "10.50",
            "commission": raw_fee,
        }
    ]
    parser.parse.return_value = raw_rows
    use_case = ManualTradeImportUseCase(
        sync_repo=sync_repo,
        portfolio_repo=Mock(),
        parser=parser,
        position_service=Mock(),
        execution_matcher=Mock(),
    )

    result = use_case.preview(
        user_id=7,
        portfolio_id=11,
        broker_name="fixture-broker",
        filename="trades.csv",
        content=b"synthetic fixture only",
    )

    assert result.valid_rows == expected_valid_rows
    assert result.error_rows == 1 - expected_valid_rows
    assert raw_rows[0]["commission"] == raw_fee
    if expected_valid_rows:
        assert result.rows[0]["commission"] == expected_preview
    else:
        assert "commission" in result.errors[0]["error"]
