"""Typed contracts for creating one new SimulatedAccount physical row."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from typing import Protocol, cast

from apps.simulated_trading.application.simulated_account_raw_observation import (
    SimulatedAccountPhysicalRowMutation,
)
from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount
from core.exceptions import (
    DataValidationError,
    DuplicateResourceError,
    ExternalServiceError,
    InvalidInputError,
)


class CanonicalAccountCreationRowInvalid(InvalidInputError):
    """The caller supplied a malformed or already-saved account input."""

    default_message = "模拟账户创建输入无效"
    default_code = "CANONICAL_ACCOUNT_CREATION_ROW_INVALID"


class CanonicalAccountCreationRowUnavailable(ExternalServiceError):
    """The required same-alias transaction or user row is unavailable."""

    default_message = "模拟账户创建行暂不可用"
    default_code = "CANONICAL_ACCOUNT_CREATION_ROW_UNAVAILABLE"


class CanonicalAccountCreationRowConflict(DuplicateResourceError):
    """A new-only creation row conflicts with an immutable existing identity."""

    default_message = "模拟账户创建行发生冲突"
    default_code = "CANONICAL_ACCOUNT_CREATION_ROW_CONFLICT"


class CanonicalAccountCreationRowCorruption(DataValidationError):
    """A saved row or server clock could not be mapped without rewriting facts."""

    default_message = "模拟账户创建行证据无效"
    default_code = "CANONICAL_ACCOUNT_CREATION_ROW_CORRUPTION"


class CanonicalAccountCreationRowClock(Protocol):
    """Provide the authoritative server time for the physical-row observation."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""
        ...


def _require_token(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise CanonicalAccountCreationRowInvalid(f"{field_name} must be a bounded canonical token")
    return value


def _require_exact_positive_integer(value: object, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise CanonicalAccountCreationRowInvalid(f"{field_name} must be an exact positive integer")
    return value


def _require_finite_number(value: object, field_name: str) -> None:
    if type(value) not in (int, float):
        raise CanonicalAccountCreationRowInvalid(f"{field_name} must be a finite number")
    try:
        finite = isfinite(float(cast(int | float, value)))
    except (OverflowError, ValueError):
        finite = False
    if not finite:
        raise CanonicalAccountCreationRowInvalid(f"{field_name} must be a finite number")


def _validate_account(value: object, *, require_unsaved: bool) -> SimulatedAccount:
    if type(value) is not SimulatedAccount:
        raise CanonicalAccountCreationRowInvalid("account must be an exact SimulatedAccount")
    account = value
    if type(account.account_id) is not int:
        raise CanonicalAccountCreationRowInvalid("account_id must be an exact integer")
    if require_unsaved:
        if account.account_id != 0:
            raise CanonicalAccountCreationRowConflict(
                "new-only writer refuses an existing account_id"
            )
    elif account.account_id <= 0:
        raise CanonicalAccountCreationRowCorruption(
            "persisted account must have a positive account_id"
        )

    if (
        type(account.account_name) is not str
        or not account.account_name
        or account.account_name.strip() != account.account_name
        or len(account.account_name) > 100
    ):
        raise CanonicalAccountCreationRowInvalid("account_name is invalid")
    if type(account.account_type) is not AccountType:
        raise CanonicalAccountCreationRowInvalid("account_type must be an exact AccountType")

    for field_name in (
        "initial_capital",
        "current_cash",
        "current_market_value",
        "total_value",
        "total_return",
        "annual_return",
        "max_drawdown",
        "sharpe_ratio",
        "win_rate",
        "max_position_pct",
        "max_total_position_pct",
        "commission_rate",
        "slippage_rate",
    ):
        _require_finite_number(getattr(account, field_name), field_name)
    if account.stop_loss_pct is not None:
        _require_finite_number(account.stop_loss_pct, "stop_loss_pct")

    for field_name in ("total_trades", "winning_trades"):
        if type(getattr(account, field_name)) is not int:
            raise CanonicalAccountCreationRowInvalid(f"{field_name} must be an exact integer")
    if type(account.start_date) is not date:
        raise CanonicalAccountCreationRowInvalid("start_date must be an exact date")
    if account.last_trade_date is not None and type(account.last_trade_date) is not date:
        raise CanonicalAccountCreationRowInvalid("last_trade_date must be null or an exact date")
    for field_name in ("is_active", "auto_trading_enabled"):
        if type(getattr(account, field_name)) is not bool:
            raise CanonicalAccountCreationRowInvalid(f"{field_name} must be an exact boolean")
    return account


@dataclass(frozen=True, slots=True)
class CanonicalAccountCreationRowCommand:
    """Select one trusted requester and one unsaved exact account payload."""

    requester_user_id: int
    account: SimulatedAccount
    observation_id: str
    mutation_version: str

    def __post_init__(self) -> None:
        _require_exact_positive_integer(self.requester_user_id, "requester_user_id")
        _validate_account(self.account, require_unsaved=True)
        _require_token(self.observation_id, "observation_id")
        _require_token(self.mutation_version, "mutation_version")


@dataclass(frozen=True, slots=True)
class CanonicalAccountCreationRowResult:
    """Return the refreshed persisted account and its exact physical-row mutation."""

    account: SimulatedAccount
    mutation: SimulatedAccountPhysicalRowMutation

    def __post_init__(self) -> None:
        account = _validate_account(self.account, require_unsaved=False)
        if type(self.mutation) is not SimulatedAccountPhysicalRowMutation:
            raise CanonicalAccountCreationRowCorruption(
                "mutation must be an exact SimulatedAccountPhysicalRowMutation"
            )
        try:
            SimulatedAccountPhysicalRowMutation.__post_init__(self.mutation)
        except (TypeError, ValueError) as error:
            raise CanonicalAccountCreationRowCorruption("mutation facts are invalid") from error
        if (
            self.mutation.row_pk != account.account_id
            or self.mutation.raw_account_type != account.account_type.value
            or self.mutation.is_active != account.is_active
        ):
            raise CanonicalAccountCreationRowCorruption(
                "mutation does not correspond to the persisted account"
            )


class CanonicalAccountCreationRowWriter(Protocol):
    """Create one new account row and return its physical source facts."""

    def execute(
        self, command: CanonicalAccountCreationRowCommand
    ) -> CanonicalAccountCreationRowResult:
        """Persist the new-only command inside the caller's transaction."""
        ...


__all__ = [
    "CanonicalAccountCreationRowClock",
    "CanonicalAccountCreationRowCommand",
    "CanonicalAccountCreationRowConflict",
    "CanonicalAccountCreationRowCorruption",
    "CanonicalAccountCreationRowInvalid",
    "CanonicalAccountCreationRowResult",
    "CanonicalAccountCreationRowUnavailable",
    "CanonicalAccountCreationRowWriter",
]
