"""Exact applicability and historic-snapshot contracts for fee policy V2."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeeApplicability,
    FeePolicyAccountScope,
    FeeTransactionCase,
    SimulatedFeePolicyV2,
    calculate_trade_fees_v2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionFeeSchedule,
    FeeCalculationPurpose,
    FeeRateStoragePrecision,
    FeeRoundingPolicy,
    SimulatedSettlementContractError,
    SimulatedTradeSide,
    calculate_trade_fees,
)


def _schedule() -> ExecutionFeeSchedule:
    return ExecutionFeeSchedule(
        config_id=9,
        asset_type="all",
        commission_rate_buy=Decimal("0.01"),
        commission_rate_sell=Decimal("0.02"),
        min_commission=Decimal("0.50"),
        stamp_duty_rate=Decimal("0.03"),
        transfer_fee_rate=Decimal("0.04"),
        min_transfer_fee=Decimal("0.60"),
        slippage_rate=Decimal("0.05"),
        precision_basis=FeeRateStoragePrecision.DATABASE_BINARY64,
        calculation_purpose=FeeCalculationPurpose.NORMAL_SIM_ESTIMATED,
        rounding_policy=FeeRoundingPolicy.COMPONENT_HALF_EVEN_CENTS_V1,
    )


def _case(
    *,
    asset_type: str = "fund",
    market: str = "BJ",
    board: str = "STAR",
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    commission: FeeApplicability = FeeApplicability.APPLIES,
    transfer_fee: FeeApplicability = FeeApplicability.APPLIES,
    stamp_duty: FeeApplicability = FeeApplicability.APPLIES,
    slippage: FeeApplicability = FeeApplicability.APPLIES,
) -> FeeTransactionCase:
    return FeeTransactionCase(
        asset_type=asset_type,
        market=market,
        board=board,
        side=side,
        commission=commission,
        transfer_fee=transfer_fee,
        stamp_duty=stamp_duty,
        slippage=slippage,
    )


def _policy(*cases: FeeTransactionCase) -> SimulatedFeePolicyV2:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    return SimulatedFeePolicyV2(
        fee_schedule_v1=_schedule(),
        policy_id="operator-fee-policy",
        policy_version=1,
        effective_from=start,
        valid_until=start + timedelta(days=30),
        recorded_at=start - timedelta(days=1),
        account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
        transaction_cases=tuple(cases),
    )


def test_fee_policy_v2_round_trip_keeps_the_v1_snapshot_hash_unchanged() -> None:
    schedule = _schedule()
    case = _case()
    policy = _policy(case)

    restored = SimulatedFeePolicyV2.from_payload(policy.to_payload())

    assert restored == policy
    assert restored.fee_schedule_v1.to_payload() == schedule.to_payload()
    assert restored.fee_schedule_v1.content_hash == schedule.content_hash


def test_fee_calculation_uses_explicit_case_for_all_components_without_market_rules() -> None:
    policy = _policy(_case())

    fees = calculate_trade_fees_v2(
        policy,
        asset_type="fund",
        market="BJ",
        board="STAR",
        side=SimulatedTradeSide.BUY,
        amount=Decimal("100.00"),
        as_of=datetime(2026, 10, 2, tzinfo=UTC),
    )

    assert fees.commission == Decimal("1.00")
    assert fees.transfer_fee == Decimal("4.00")
    assert fees.stamp_duty == Decimal("3.00")
    assert fees.slippage == Decimal("5.00")
    assert fees.total_fee == Decimal("13.00")


def test_fee_calculation_returns_zero_only_for_explicit_not_applicable_components() -> None:
    policy = _policy(
        _case(
            commission=FeeApplicability.NOT_APPLICABLE,
            transfer_fee=FeeApplicability.NOT_APPLICABLE,
            stamp_duty=FeeApplicability.NOT_APPLICABLE,
            slippage=FeeApplicability.NOT_APPLICABLE,
        )
    )

    fees = calculate_trade_fees_v2(
        policy,
        asset_type="fund",
        market="BJ",
        board="STAR",
        side=SimulatedTradeSide.BUY,
        amount=Decimal("100.00"),
        as_of=datetime(2026, 10, 2, tzinfo=UTC),
    )

    assert fees.total_fee == Decimal("0.00")
    assert (fees.commission, fees.transfer_fee, fees.stamp_duty, fees.slippage) == (
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    )


def test_fee_policy_v2_never_falls_back_from_a_missing_exact_case() -> None:
    policy = _policy(_case(market="SH", board="MAIN"))

    with pytest.raises(SimulatedSettlementContractError):
        calculate_trade_fees_v2(
            policy,
            asset_type="fund",
            market="SZ",
            board="MAIN",
            side=SimulatedTradeSide.BUY,
            amount=Decimal("100.00"),
            as_of=datetime(2026, 10, 2, tzinfo=UTC),
        )


@pytest.mark.parametrize("dimension", ["asset_type", "market", "board", "side"])
def test_fee_policy_v2_does_not_support_wildcard_case_dimensions(dimension: str) -> None:
    values: dict[str, object] = {
        "asset_type": "fund",
        "market": "BJ",
        "board": "STAR",
        "side": SimulatedTradeSide.BUY,
        "commission": FeeApplicability.APPLIES,
        "transfer_fee": FeeApplicability.APPLIES,
        "stamp_duty": FeeApplicability.APPLIES,
        "slippage": FeeApplicability.APPLIES,
    }
    values[dimension] = "*"

    with pytest.raises(SimulatedSettlementContractError):
        FeeTransactionCase(**values)  # type: ignore[arg-type]


def test_fee_policy_v2_rejects_duplicate_exact_transaction_cases() -> None:
    case = _case()

    with pytest.raises(SimulatedSettlementContractError):
        _policy(case, case)


def test_fee_case_decoder_rejects_invalid_shape_wildcards_and_unknown_enums() -> None:
    case = _case()
    payload = case.to_payload()

    with pytest.raises(SimulatedSettlementContractError):
        replace(case, commission="APPLIES")  # type: ignore[arg-type]
    with pytest.raises(SimulatedSettlementContractError):
        FeeTransactionCase.from_payload(None)
    with pytest.raises(SimulatedSettlementContractError):
        FeeTransactionCase.from_payload({**payload, "unknown": "value"})
    with pytest.raises(SimulatedSettlementContractError):
        FeeTransactionCase.from_payload({**payload, "slippage": 1})
    with pytest.raises(SimulatedSettlementContractError):
        FeeTransactionCase.from_payload({**payload, "asset_type": "*"})
    with pytest.raises(SimulatedSettlementContractError):
        FeeTransactionCase.from_payload({**payload, "side": "unrecognized"})


def test_fee_policy_constructor_rejects_non_exact_nested_types() -> None:
    policy = _policy(_case())

    with pytest.raises(SimulatedSettlementContractError):
        replace(policy, fee_schedule_v1=object())  # type: ignore[arg-type]
    with pytest.raises(SimulatedSettlementContractError):
        replace(policy, policy_version=0)
    with pytest.raises(SimulatedSettlementContractError):
        replace(policy, account_scope="ALL_SIMULATED_ACCOUNTS")  # type: ignore[arg-type]
    with pytest.raises(SimulatedSettlementContractError):
        replace(policy, transaction_cases=())
    with pytest.raises(SimulatedSettlementContractError):
        replace(policy, transaction_cases=(object(),))  # type: ignore[arg-type]


def test_fee_policy_payload_rejects_wrong_shape_fields_and_bad_timestamps() -> None:
    payload = _policy(_case()).to_payload()

    with pytest.raises(SimulatedSettlementContractError):
        SimulatedFeePolicyV2.from_payload(None)
    with pytest.raises(SimulatedSettlementContractError):
        SimulatedFeePolicyV2.from_payload({**payload, "policy_version": True})
    with pytest.raises(SimulatedSettlementContractError):
        SimulatedFeePolicyV2.from_payload({**payload, "account_scope": "UNKNOWN"})
    with pytest.raises(SimulatedSettlementContractError):
        SimulatedFeePolicyV2.from_payload(
            {**payload, "effective_from": "2026-10-01T00:00:00+00:00"}
        )
    with pytest.raises(SimulatedSettlementContractError):
        SimulatedFeePolicyV2.from_payload({**payload, "effective_from": "not-a-dateZ"})
    with pytest.raises(SimulatedSettlementContractError):
        SimulatedFeePolicyV2.from_payload({**payload, "effective_from": "2026-10-01T00:00:00.0Z"})


def test_fee_policy_calculate_method_is_typed_and_rejects_non_policy_input() -> None:
    policy = _policy(_case())
    calculated = policy.calculate_for(
        asset_type="fund",
        market="BJ",
        board="STAR",
        side=SimulatedTradeSide.BUY,
        amount=Decimal("100.00"),
        as_of=datetime(2026, 10, 2, tzinfo=UTC),
    )

    assert calculated.total_fee == Decimal("13.00")
    with pytest.raises(SimulatedSettlementContractError):
        calculate_trade_fees_v2(
            object(),  # type: ignore[arg-type]
            asset_type="fund",
            market="BJ",
            board="STAR",
            side=SimulatedTradeSide.BUY,
            amount=Decimal("100.00"),
            as_of=datetime(2026, 10, 2, tzinfo=UTC),
        )


def test_fee_policy_v2_rejects_unknown_and_missing_snapshot_fields() -> None:
    payload = _policy(_case()).to_payload()

    with pytest.raises(SimulatedSettlementContractError):
        SimulatedFeePolicyV2.from_payload({**payload, "unexpected": True})
    with pytest.raises(SimulatedSettlementContractError):
        SimulatedFeePolicyV2.from_payload(
            {key: value for key, value in payload.items() if key != "content_hash"}
        )


def test_fee_policy_v2_content_hash_binds_the_exact_applicability_case() -> None:
    first = _policy(_case(commission=FeeApplicability.APPLIES))
    second = _policy(_case(commission=FeeApplicability.NOT_APPLICABLE))

    assert first.content_hash != second.content_hash


def test_fee_policy_v2_rejects_expiry_and_a_knowledge_cutoff_before_recorded_time() -> None:
    policy = _policy(_case())

    with pytest.raises(SimulatedSettlementContractError):
        policy.validate_at(policy.valid_until)
    with pytest.raises(SimulatedSettlementContractError):
        policy.validate_at(policy.recorded_at - timedelta(microseconds=1))


def test_fee_policy_v2_rejects_recorded_time_equal_to_expiry() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)

    with pytest.raises(SimulatedSettlementContractError):
        SimulatedFeePolicyV2(
            fee_schedule_v1=_schedule(),
            policy_id="unavailable-policy",
            policy_version=1,
            account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
            effective_from=start - timedelta(days=1),
            valid_until=start,
            recorded_at=start,
            transaction_cases=(_case(),),
        )


def test_legacy_v1_fee_payload_hash_and_formula_remain_golden() -> None:
    schedule = ExecutionFeeSchedule(
        config_id=3,
        asset_type="equity",
        commission_rate_buy=Decimal("0.0003"),
        commission_rate_sell=Decimal("0.0003"),
        min_commission=Decimal("5"),
        stamp_duty_rate=Decimal("0.001"),
        transfer_fee_rate=Decimal("0.00002"),
        min_transfer_fee=Decimal("0"),
        slippage_rate=Decimal("0.001"),
        precision_basis=FeeRateStoragePrecision.DATABASE_BINARY64,
        calculation_purpose=FeeCalculationPurpose.NORMAL_SIM_ESTIMATED,
        rounding_policy=FeeRoundingPolicy.COMPONENT_HALF_EVEN_CENTS_V1,
    )
    historic_payload = {
        "config_id": 3,
        "asset_type": "equity",
        "commission_rate_buy": "0.0003",
        "commission_rate_sell": "0.0003",
        "min_commission": "5",
        "stamp_duty_rate": "0.001",
        "transfer_fee_rate": "0.00002",
        "min_transfer_fee": "0",
        "slippage_rate": "0.001",
        "precision_basis": "database_binary64",
        "calculation_purpose": "normal_sim_estimated",
        "rounding_policy": "component_half_even_cents_v1",
        "content_hash": "823d03ff29da6c850130ff8b10459ac592642acb02d7be39413d364853c32293",
    }

    assert schedule.to_payload() == historic_payload
    assert ExecutionFeeSchedule.from_payload(historic_payload).to_payload() == historic_payload
    buy = calculate_trade_fees(
        schedule,
        side=SimulatedTradeSide.BUY,
        amount=Decimal("1000.00"),
        market="SH",
    )
    sell = calculate_trade_fees(
        schedule,
        side=SimulatedTradeSide.SELL,
        amount=Decimal("1000.00"),
        market="SH",
    )

    assert buy.total_fee == Decimal("6.02")
    assert sell.total_fee == Decimal("7.02")
