"""Application boundary tests for immutable FeeConfig policy versions."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.admin import AdminSite
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest

from apps.simulated_trading.application.fee_policy_v2 import (
    CreateFeePolicyVersionUseCase,
    FeePolicyVersionCommand,
    FeePolicyVersionInputError,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeeApplicability,
    FeePolicyAccountScope,
    FeeTransactionCase,
    SimulatedFeePolicyV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionFeeSchedule,
    FeeCalculationPurpose,
    FeeRateStoragePrecision,
    FeeRoundingPolicy,
    SimulatedTradeSide,
)
from apps.simulated_trading.infrastructure.models import FeeConfigModel
from apps.simulated_trading.interface.admin import FeeConfigAdmin, FeeConfigAdminForm
from shared.infrastructure.django_admin import TypedModelAdmin, TypedModelForm


def _case(side: SimulatedTradeSide = SimulatedTradeSide.BUY) -> FeeTransactionCase:
    return FeeTransactionCase(
        asset_type="equity",
        market="SH",
        board="MAIN",
        side=side,
        commission=FeeApplicability.APPLIES,
        transfer_fee=FeeApplicability.NOT_APPLICABLE,
        stamp_duty=FeeApplicability.NOT_APPLICABLE,
        slippage=FeeApplicability.APPLIES,
    )


def _command(**changes: object) -> FeePolicyVersionCommand:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    values: dict[str, object] = {
        "config_name": "operator-set-fees-v1",
        "asset_type": "equity",
        "commission_rate_buy": 0.0003,
        "commission_rate_sell": 0.0003,
        "min_commission": 5.0,
        "stamp_duty_rate": 0.001,
        "transfer_fee_rate": 0.00002,
        "min_transfer_fee": 0.0,
        "slippage_rate": 0.001,
        "policy_id": "operator-equity-fees",
        "policy_version": 1,
        "account_scope": FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
        "effective_from": start,
        "valid_until": start + timedelta(days=30),
        "transaction_cases": (_case(), _case(SimulatedTradeSide.SELL)),
        "description": "operator supplied",
    }
    values.update(changes)
    return FeePolicyVersionCommand(**values)  # type: ignore[arg-type]


def _policy(command: FeePolicyVersionCommand) -> SimulatedFeePolicyV2:
    schedule = ExecutionFeeSchedule(
        config_id=9,
        asset_type=command.asset_type,
        commission_rate_buy=Decimal.from_float(command.commission_rate_buy),
        commission_rate_sell=Decimal.from_float(command.commission_rate_sell),
        min_commission=Decimal.from_float(command.min_commission),
        stamp_duty_rate=Decimal.from_float(command.stamp_duty_rate),
        transfer_fee_rate=Decimal.from_float(command.transfer_fee_rate),
        min_transfer_fee=Decimal.from_float(command.min_transfer_fee),
        slippage_rate=Decimal.from_float(command.slippage_rate),
        precision_basis=FeeRateStoragePrecision.DATABASE_BINARY64,
        calculation_purpose=FeeCalculationPurpose.NORMAL_SIM_ESTIMATED,
        rounding_policy=FeeRoundingPolicy.COMPONENT_HALF_EVEN_CENTS_V1,
    )
    return SimulatedFeePolicyV2(
        fee_schedule_v1=schedule,
        policy_id=command.policy_id,
        policy_version=command.policy_version,
        account_scope=command.account_scope,
        effective_from=command.effective_from,
        valid_until=command.valid_until,
        recorded_at=datetime(2026, 10, 1, tzinfo=UTC),
        transaction_cases=command.transaction_cases,
    )


class _Repository:
    def __init__(self) -> None:
        self.command: FeePolicyVersionCommand | None = None
        self.result: SimulatedFeePolicyV2 | None = None

    def create_fee_policy_version(self, command: FeePolicyVersionCommand) -> SimulatedFeePolicyV2:
        self.command = command
        result = self.result
        if result is None:
            result = _policy(command)
            self.result = result
        return result


def test_create_fee_policy_version_delegates_one_validated_exact_command() -> None:
    repository = _Repository()
    command = _command()

    result = CreateFeePolicyVersionUseCase(repository=repository).execute(command)

    assert repository.command is command
    assert result is repository.result


def test_create_fee_policy_version_rejects_decimal_that_does_not_match_binary64_source() -> None:
    command = _command()
    repository = _Repository()
    valid_policy = _policy(command)
    tampered_schedule = replace(
        valid_policy.fee_schedule_v1,
        commission_rate_buy=Decimal("0.0003"),
        content_hash="",
    )
    repository.result = replace(
        valid_policy,
        fee_schedule_v1=tampered_schedule,
        content_hash="",
    )

    with pytest.raises(FeePolicyVersionInputError):
        CreateFeePolicyVersionUseCase(repository=repository).execute(command)


@pytest.mark.parametrize(
    "changes",
    [
        {"commission_rate_buy": float("nan")},
        {"transfer_fee_rate": float("inf")},
        {"transaction_cases": (_case(), _case())},
        {"account_scope": None},
        {"valid_until": datetime(2026, 10, 1, tzinfo=UTC)},
        {"commission_rate_buy": 10**1000},
    ],
)
def test_create_fee_policy_version_rejects_unsafe_input_before_storage(
    changes: dict[str, object],
) -> None:
    repository = _Repository()

    with pytest.raises(FeePolicyVersionInputError):
        CreateFeePolicyVersionUseCase(repository=repository).execute(_command(**changes))

    assert repository.command is None


def test_feeconfig_admin_is_typed_and_keeps_strict_metadata_read_only() -> None:
    admin_instance = FeeConfigAdmin(FeeConfigModel, AdminSite())
    legacy_readonly = admin_instance.get_readonly_fields(HttpRequest())
    strict_row = FeeConfigModel(fee_policy_id="strict-policy")
    strict_readonly = admin_instance.get_readonly_fields(HttpRequest(), strict_row)

    assert issubclass(FeeConfigAdmin, TypedModelAdmin)
    assert issubclass(FeeConfigAdminForm, TypedModelForm)
    assert set(FeeConfigAdmin.strict_policy_readonly_fields).issubset(legacy_readonly)
    assert len(strict_readonly) == len(FeeConfigModel._meta.fields)


@pytest.mark.parametrize(
    "user",
    [
        AnonymousUser(),
        SimpleNamespace(is_authenticated=True, pk=None),
    ],
)
def test_feeconfig_admin_refuses_writes_without_persisted_operator_identity(user: object) -> None:
    admin_instance = FeeConfigAdmin(FeeConfigModel, AdminSite())
    request = HttpRequest()
    request.user = user
    obj = FeeConfigModel(
        config_name="admin-test",
        asset_type="equity",
        min_commission=1.0,
    )
    form = FeeConfigAdminForm(data={}, instance=obj)

    with pytest.raises(PermissionDenied):
        admin_instance.save_model(request, obj, form, change=False)


@pytest.mark.parametrize(
    ("method_name", "field_name", "rate", "expected"),
    [
        ("commission_rate_buy_display", "commission_rate_buy", 0.0003, "0.03%"),
        ("commission_rate_sell_display", "commission_rate_sell", 0.0003, "0.03%"),
        ("stamp_duty_rate_display", "stamp_duty_rate", 0.0005, "0.05%"),
        ("commission_rate_buy_display", "commission_rate_buy", 1e-12, "1e-10%"),
    ],
)
def test_feeconfig_admin_percentage_displays_preserve_the_declared_rate_scale(
    method_name: str,
    field_name: str,
    rate: float,
    expected: str,
) -> None:
    admin_instance = FeeConfigAdmin(FeeConfigModel, AdminSite())
    row = FeeConfigModel(config_name="display-test", asset_type="equity", min_commission=1.0)
    setattr(row, field_name, rate)

    display = getattr(admin_instance, method_name)

    assert display(row) == expected
