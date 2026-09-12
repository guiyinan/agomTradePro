"""Stable request identity and explicit behavior for idempotent account creation."""

import json
from dataclasses import dataclass
from datetime import date
from hashlib import sha256

from apps.account.application.canonical_account_creation import (
    AllocateCanonicalAccountCreationCommand,
)
from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount
from core.exceptions import InvalidInputError
from shared.numeric import safe_float


class CanonicalAccountCreationRequestInvalid(InvalidInputError):
    """A creation request cannot be sealed without coercion or missing behavior."""

    default_code = "CANONICAL_ACCOUNT_CREATION_REQUEST_INVALID"


def _token(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise CanonicalAccountCreationRequestInvalid(f"{label} must be a canonical token")
    return value


def _number(value: object, label: str) -> float:
    if type(value) not in (int, float):
        raise CanonicalAccountCreationRequestInvalid(f"{label} must be a finite number")
    number = safe_float(value)
    if number is None:
        raise CanonicalAccountCreationRequestInvalid(f"{label} must be a finite number")
    return 0.0 if number == 0 else number


def _hash(payload: dict[str, object]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class CanonicalAccountCreationRequest:
    """Resolved creation behavior bound to an authenticated caller's request key.

    The caller must obtain actor/user from its authentication boundary and
    resolve existing business defaults before constructing this value.
    This DTO itself supplies neither authentication nor business defaults.
    """

    actor_id: str
    user_id: int
    request_key: str
    account_name: str
    account_type: AccountType
    initial_capital: float
    auto_trading_enabled: bool
    max_position_pct: float
    stop_loss_pct: float | None
    commission_rate: float
    slippage_rate: float

    def __post_init__(self) -> None:
        """Reject invalid selectors and normalize finite numeric representations."""

        _token(self.actor_id, "actor_id")
        _token(self.request_key, "request_key")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise CanonicalAccountCreationRequestInvalid("user_id must be a positive integer")
        if (
            type(self.account_name) is not str
            or not self.account_name
            or len(self.account_name) > 100
            or self.account_name.strip() != self.account_name
        ):
            raise CanonicalAccountCreationRequestInvalid("account_name is invalid")
        if type(self.account_type) is not AccountType:
            raise CanonicalAccountCreationRequestInvalid(
                "account_type must be an exact AccountType"
            )
        if type(self.auto_trading_enabled) is not bool:
            raise CanonicalAccountCreationRequestInvalid("auto_trading_enabled must be a boolean")
        for name in ("initial_capital", "max_position_pct", "commission_rate", "slippage_rate"):
            object.__setattr__(self, name, _number(getattr(self, name), name))
        if self.stop_loss_pct is not None:
            object.__setattr__(self, "stop_loss_pct", _number(self.stop_loss_pct, "stop_loss_pct"))

    @property
    def identity_hash(self) -> str:
        """Return the identity held constant when the same caller changes payload."""

        return _hash(
            {
                "schema": "canonical-account-create-request-identity.v1",
                "actor_id": self.actor_id,
                "user_id": self.user_id,
                "request_key": self.request_key,
            }
        )

    @property
    def fingerprint_hash(self) -> str:
        """Seal request identity and every explicitly resolved behavior field."""

        return _hash(
            {
                "schema": "canonical-account-create-request-payload.v1",
                "request_identity_hash": self.identity_hash,
                "account_name": self.account_name,
                "account_type": self.account_type.value,
                "initial_capital": self.initial_capital.hex(),
                "auto_trading_enabled": self.auto_trading_enabled,
                "max_position_pct": self.max_position_pct.hex(),
                "stop_loss_pct": None if self.stop_loss_pct is None else self.stop_loss_pct.hex(),
                "commission_rate": self.commission_rate.hex(),
                "slippage_rate": self.slippage_rate.hex(),
            }
        )

    @property
    def binding_id(self) -> str:
        """Return the server-derived durable Binding selector for this request."""

        return f"create-binding-{self.identity_hash}"

    @property
    def binding_version(self) -> str:
        """Return the fixed technical generation of this Binding selector."""

        return "v1"

    def allocation_command(self) -> AllocateCanonicalAccountCreationCommand:
        """Build selectors that conflict on changed content under the same key."""

        return AllocateCanonicalAccountCreationCommand(
            allocation_id=f"create-allocation-{self.identity_hash}",
            allocation_version="v1",
            request_fingerprint_hash=self.fingerprint_hash,
            requested_raw_account_type=self.account_type.value,
        )

    def to_account(self, *, start_date: date) -> SimulatedAccount:
        """Materialize a new row input with the caller's current server date."""

        if type(start_date) is not date:
            raise CanonicalAccountCreationRequestInvalid("start_date must be an exact date")
        return SimulatedAccount(
            account_id=0,
            account_name=self.account_name,
            account_type=self.account_type,
            initial_capital=self.initial_capital,
            current_cash=self.initial_capital,
            current_market_value=0.0,
            total_value=self.initial_capital,
            start_date=start_date,
            auto_trading_enabled=self.auto_trading_enabled,
            max_position_pct=self.max_position_pct,
            stop_loss_pct=self.stop_loss_pct,
            commission_rate=self.commission_rate,
            slippage_rate=self.slippage_rate,
        )


__all__ = ["CanonicalAccountCreationRequest", "CanonicalAccountCreationRequestInvalid"]
