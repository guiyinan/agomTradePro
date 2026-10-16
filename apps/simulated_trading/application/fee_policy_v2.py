"""Application contract for operator-created simulated fee policy versions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import isfinite
from typing import Protocol

from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeePolicyAccountScope,
    FeeTransactionCase,
    SimulatedFeePolicyV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionFeeSchedule,
    FeeCalculationPurpose,
    FeeRateStoragePrecision,
    FeeRoundingPolicy,
    SimulatedSettlementContractError,
)
from core.exceptions import DuplicateResourceError, InvalidInputError, MissingConfigError


class FeePolicyVersionInputError(InvalidInputError):
    """Raised when an operator's exact fee policy definition is invalid."""

    default_message = "模拟费率版本输入无效"
    default_code = "SIMULATED_FEE_POLICY_INPUT_INVALID"


class FeePolicyVersionConflict(DuplicateResourceError):
    """Raised when an identity is rewritten or its exact case window overlaps."""

    default_message = "模拟费率版本身份或适用窗口冲突"
    default_code = "SIMULATED_FEE_POLICY_VERSION_CONFLICT"


class FeePolicyVersionStorageUnavailable(MissingConfigError):
    """Raised when policy storage cannot establish a safe, owned write/read."""

    default_message = "模拟费率版本存储暂不可用"
    default_code = "SIMULATED_FEE_POLICY_STORAGE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class FeePolicyVersionCommand:
    """Carry all rates, window, identity, and exact transaction cases explicitly."""

    config_name: str
    asset_type: str
    commission_rate_buy: float
    commission_rate_sell: float
    min_commission: float
    stamp_duty_rate: float
    transfer_fee_rate: float
    min_transfer_fee: float
    slippage_rate: float
    policy_id: str
    policy_version: int
    account_scope: FeePolicyAccountScope
    effective_from: datetime
    valid_until: datetime
    transaction_cases: tuple[FeeTransactionCase, ...]
    description: str = ""

    def __post_init__(self) -> None:
        """Reject incomplete, non-finite, or unscoped operator input."""

        for field_name, value, maximum in (
            ("commission_rate_buy", self.commission_rate_buy, 1.0),
            ("commission_rate_sell", self.commission_rate_sell, 1.0),
            ("stamp_duty_rate", self.stamp_duty_rate, 1.0),
            ("transfer_fee_rate", self.transfer_fee_rate, 1.0),
            ("slippage_rate", self.slippage_rate, 1.0),
        ):
            if type(value) not in (float, int) or isinstance(value, bool):
                raise FeePolicyVersionInputError(f"{field_name} must be a numeric input")
            try:
                numeric_value = float(value)
            except OverflowError as error:
                raise FeePolicyVersionInputError(
                    f"{field_name} cannot be represented as a database binary64 value"
                ) from error
            if not isfinite(numeric_value) or not 0 <= numeric_value <= maximum:
                raise FeePolicyVersionInputError(f"{field_name} must be finite and between 0 and 1")
        for field_name, value in (
            ("min_commission", self.min_commission),
            ("min_transfer_fee", self.min_transfer_fee),
        ):
            if type(value) not in (float, int) or isinstance(value, bool):
                raise FeePolicyVersionInputError(f"{field_name} must be a numeric input")
            try:
                numeric_value = float(value)
            except OverflowError as error:
                raise FeePolicyVersionInputError(
                    f"{field_name} cannot be represented as a database binary64 value"
                ) from error
            if not isfinite(numeric_value) or numeric_value < 0:
                raise FeePolicyVersionInputError(f"{field_name} must be a nonnegative finite value")
        if type(self.config_name) is not str or not self.config_name.strip():
            raise FeePolicyVersionInputError("config_name is required")
        if len(self.config_name) > 100 or self.config_name.strip() != self.config_name:
            raise FeePolicyVersionInputError("config_name must be a bounded canonical value")
        if (
            type(self.asset_type) is not str
            or not self.asset_type
            or self.asset_type.strip() != self.asset_type
            or len(self.asset_type) > 20
            or any(character.isspace() for character in self.asset_type)
        ):
            raise FeePolicyVersionInputError("asset_type must be a bounded canonical value")
        if (
            type(self.policy_id) is not str
            or not self.policy_id
            or self.policy_id.strip() != self.policy_id
            or len(self.policy_id) > 192
            or any(character.isspace() for character in self.policy_id)
        ):
            raise FeePolicyVersionInputError("policy_id must be a canonical token")
        if type(self.policy_version) is not int or not 1 <= self.policy_version <= 2_147_483_647:
            raise FeePolicyVersionInputError("policy_version must be a positive bounded integer")
        if type(self.account_scope) is not FeePolicyAccountScope:
            raise FeePolicyVersionInputError("account_scope must be explicit")
        for field_name, date_value in (
            ("effective_from", self.effective_from),
            ("valid_until", self.valid_until),
        ):
            if type(date_value) is not datetime or date_value.tzinfo is None:
                raise FeePolicyVersionInputError(f"{field_name} must be timezone-aware")
            try:
                if date_value.utcoffset() is None:
                    raise FeePolicyVersionInputError(f"{field_name} must be timezone-aware")
            except (OverflowError, TypeError, ValueError) as error:
                raise FeePolicyVersionInputError(f"{field_name} must be timezone-aware") from error
        if self.effective_from >= self.valid_until:
            raise FeePolicyVersionInputError("fee policy effective window must be nonempty")
        if type(self.transaction_cases) is not tuple or not self.transaction_cases:
            raise FeePolicyVersionInputError("at least one exact transaction case is required")
        try:
            for case in self.transaction_cases:
                if type(case) is not FeeTransactionCase:
                    raise FeePolicyVersionInputError("transaction cases must be exact typed values")
                case.__post_init__()
            if len({case.key for case in self.transaction_cases}) != len(self.transaction_cases):
                raise FeePolicyVersionInputError(
                    "duplicate exact transaction cases are not allowed"
                )
        except SimulatedSettlementContractError as error:
            raise FeePolicyVersionInputError("transaction case is invalid") from error
        object.__setattr__(
            self,
            "transaction_cases",
            tuple(sorted(self.transaction_cases, key=lambda case: case.key)),
        )
        if type(self.description) is not str or len(self.description) > 4000:
            raise FeePolicyVersionInputError("description must be a bounded string")


class FeePolicyVersionRepository(Protocol):
    """Persist immutable operator policy versions and their exact rate snapshot."""

    def create_fee_policy_version(
        self,
        command: FeePolicyVersionCommand,
    ) -> SimulatedFeePolicyV2:
        """Create or idempotently return one unchanged policy identity/version."""


class CreateFeePolicyVersionUseCase:
    """Validate and persist one complete normal-simulation fee policy version."""

    def __init__(self, *, repository: FeePolicyVersionRepository) -> None:
        """Require an explicit repository; no rates or policy are selected implicitly."""

        self._repository = repository

    def execute(self, command: FeePolicyVersionCommand) -> SimulatedFeePolicyV2:
        """Create one immutable exact-case version after validating the full command."""

        if type(command) is not FeePolicyVersionCommand:
            raise FeePolicyVersionInputError("fee policy command has an invalid type")
        try:
            FeePolicyVersionCommand.__post_init__(command)
            policy = self._repository.create_fee_policy_version(command)
            if type(policy) is not SimulatedFeePolicyV2:
                raise FeePolicyVersionInputError("fee policy repository returned an invalid type")
            SimulatedFeePolicyV2.__post_init__(policy)
            expected_rates = tuple(
                Decimal.from_float(float(value))
                for value in (
                    command.commission_rate_buy,
                    command.commission_rate_sell,
                    command.min_commission,
                    command.stamp_duty_rate,
                    command.transfer_fee_rate,
                    command.min_transfer_fee,
                    command.slippage_rate,
                )
            )
            actual_schedule = policy.fee_schedule_v1
            if type(actual_schedule) is not ExecutionFeeSchedule:
                raise FeePolicyVersionInputError("repository returned an invalid rate snapshot")
            actual_schedule.__post_init__()
            actual_rates = (
                actual_schedule.commission_rate_buy,
                actual_schedule.commission_rate_sell,
                actual_schedule.min_commission,
                actual_schedule.stamp_duty_rate,
                actual_schedule.transfer_fee_rate,
                actual_schedule.min_transfer_fee,
                actual_schedule.slippage_rate,
            )
            if (
                policy.policy_id != command.policy_id
                or policy.policy_version != command.policy_version
                or policy.account_scope is not command.account_scope
                or policy.effective_from != command.effective_from
                or policy.valid_until != command.valid_until
                or policy.transaction_cases != command.transaction_cases
                or actual_schedule.asset_type != command.asset_type
                or actual_schedule.config_id <= 0
                or actual_schedule.precision_basis is not FeeRateStoragePrecision.DATABASE_BINARY64
                or actual_schedule.calculation_purpose
                is not FeeCalculationPurpose.NORMAL_SIM_ESTIMATED
                or actual_schedule.rounding_policy
                is not FeeRoundingPolicy.COMPONENT_HALF_EVEN_CENTS_V1
                or any(
                    actual != requested
                    for actual, requested in zip(actual_rates, expected_rates, strict=True)
                )
            ):
                raise FeePolicyVersionInputError(
                    "repository result differs from the exact operator command"
                )
            return policy
        except FeePolicyVersionInputError:
            raise
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise FeePolicyVersionInputError("fee policy creation failed validation") from error


__all__: tuple[str, ...] = (
    "CreateFeePolicyVersionUseCase",
    "FeePolicyVersionCommand",
    "FeePolicyVersionConflict",
    "FeePolicyVersionInputError",
    "FeePolicyVersionRepository",
    "FeePolicyVersionStorageUnavailable",
)
