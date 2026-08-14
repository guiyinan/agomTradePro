"""Immutable Risk-owned policy contract for future Broker order execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

BROKER_ORDER_EXECUTION_POLICY_OWNER = "risk_center"
BROKER_ORDER_EXECUTION_POLICY_CAPABILITY = "broker_order_execution_risk_policy"
BROKER_ORDER_EXECUTION_POLICY_SCHEMA = "broker-order-execution-risk-policy.v1"


def _token(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _digest(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class BrokerOrderExecutionRiskControls:
    """Complete finite controls sealed into one execution policy version."""

    max_total_position_pct: Decimal
    max_single_position_pct: Decimal
    max_daily_loss_pct: Decimal
    max_drawdown_pct: Decimal
    max_stop_loss_pct: Decimal
    take_profit_pct: Decimal
    min_cash_pct: Decimal
    force_stop_loss: bool
    hard_exclusions: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "max_total_position_pct",
            "max_single_position_pct",
            "max_daily_loss_pct",
            "max_drawdown_pct",
            "max_stop_loss_pct",
            "take_profit_pct",
            "min_cash_pct",
        ):
            value = getattr(self, field_name)
            if type(value) is not Decimal or not value.is_finite():
                raise ValueError(f"{field_name} must be an exact finite Decimal")
            if value < 0 or value > 1:
                raise ValueError(f"{field_name} must be between zero and one")
        if type(self.force_stop_loss) is not bool:
            raise TypeError("force_stop_loss must be bool")
        if type(self.hard_exclusions) is not tuple:
            raise TypeError("hard_exclusions must be an exact tuple")
        normalized = tuple(sorted(_token(item, "hard_exclusion") for item in self.hard_exclusions))
        if normalized != self.hard_exclusions or len(set(normalized)) != len(normalized):
            raise ValueError("hard_exclusions must be sorted unique canonical tokens")

    def to_payload(self) -> dict[str, object]:
        """Return the canonical control projection."""

        return {
            "max_total_position_pct": _decimal_text(self.max_total_position_pct),
            "max_single_position_pct": _decimal_text(self.max_single_position_pct),
            "max_daily_loss_pct": _decimal_text(self.max_daily_loss_pct),
            "max_drawdown_pct": _decimal_text(self.max_drawdown_pct),
            "max_stop_loss_pct": _decimal_text(self.max_stop_loss_pct),
            "take_profit_pct": _decimal_text(self.take_profit_pct),
            "min_cash_pct": _decimal_text(self.min_cash_pct),
            "force_stop_loss": self.force_stop_loss,
            "hard_exclusions": list(self.hard_exclusions),
        }


@dataclass(frozen=True, slots=True)
class BrokerOrderExecutionRiskPolicy:
    """Content-addressed policy contract; no production activator exists yet."""

    policy_id: str
    policy_version: str
    account_id: int
    controls: BrokerOrderExecutionRiskControls
    source_snapshot_id: str
    source_snapshot_version: str
    source_snapshot_hash: str
    recorded_at: datetime
    activated_at: datetime
    valid_until: datetime
    supersedes_policy_hash: str | None = None
    content_hash: str = ""
    owner: str = BROKER_ORDER_EXECUTION_POLICY_OWNER
    capability: str = BROKER_ORDER_EXECUTION_POLICY_CAPABILITY
    schema: str = BROKER_ORDER_EXECUTION_POLICY_SCHEMA
    permission_cap: str = "execution_eligible"

    def __post_init__(self) -> None:
        for field_name in (
            "policy_id",
            "policy_version",
            "source_snapshot_id",
            "source_snapshot_version",
        ):
            _token(getattr(self, field_name), field_name)
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be a positive integer")
        if type(self.controls) is not BrokerOrderExecutionRiskControls:
            raise TypeError("controls must be exact BrokerOrderExecutionRiskControls")
        BrokerOrderExecutionRiskControls.__post_init__(self.controls)
        _digest(self.source_snapshot_hash, "source_snapshot_hash")
        for field_name in ("recorded_at", "activated_at", "valid_until"):
            _aware(getattr(self, field_name), field_name)
        if not self.recorded_at <= self.activated_at < self.valid_until:
            raise ValueError("policy clock sequence is invalid")
        if self.supersedes_policy_hash is not None:
            _digest(self.supersedes_policy_hash, "supersedes_policy_hash")
        if (
            self.owner != BROKER_ORDER_EXECUTION_POLICY_OWNER
            or self.capability != BROKER_ORDER_EXECUTION_POLICY_CAPABILITY
            or self.schema != BROKER_ORDER_EXECUTION_POLICY_SCHEMA
            or self.permission_cap != "execution_eligible"
        ):
            raise ValueError("policy authority, schema, or permission is invalid")
        expected = _hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        else:
            _digest(self.content_hash, "content_hash")
            if self.content_hash != expected:
                raise ValueError("policy content_hash is invalid")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this exact policy is knowable and active."""

        _aware(as_of, "as_of")
        return bool(self.recorded_at <= self.activated_at <= as_of < self.valid_until)

    def _content_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "capability": self.capability,
            "schema": self.schema,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "account_id": self.account_id,
            "controls": self.controls.to_payload(),
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_version": self.source_snapshot_version,
            "source_snapshot_hash": self.source_snapshot_hash,
            "recorded_at": _utc_text(self.recorded_at),
            "activated_at": _utc_text(self.activated_at),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_policy_hash": self.supersedes_policy_hash,
            "permission_cap": self.permission_cap,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the sealed policy without implying a production provider."""

        return {**self._content_payload(), "content_hash": self.content_hash}


def validate_broker_order_execution_policy_successor(
    previous: BrokerOrderExecutionRiskPolicy,
    successor: BrokerOrderExecutionRiskPolicy,
) -> None:
    """Validate one adjacent policy link; persistence must prevent forks."""

    if type(previous) is not BrokerOrderExecutionRiskPolicy:
        raise TypeError("previous must be an exact policy")
    if type(successor) is not BrokerOrderExecutionRiskPolicy:
        raise TypeError("successor must be an exact policy")
    if successor.supersedes_policy_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous policy")
    if successor.account_id != previous.account_id:
        raise ValueError("policy successor changed account identity")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("policy successor clock must advance")


__all__ = [
    "BROKER_ORDER_EXECUTION_POLICY_CAPABILITY",
    "BROKER_ORDER_EXECUTION_POLICY_OWNER",
    "BrokerOrderExecutionRiskControls",
    "BrokerOrderExecutionRiskPolicy",
    "validate_broker_order_execution_policy_successor",
]
