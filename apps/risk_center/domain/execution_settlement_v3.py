"""Immutable v3 composition for execution rules and settlement parameters.

This contract stores explicit, source-backed settlement input. It does not
calculate a trading session, release a position, or grant execution authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2
from apps.risk_center.domain.execution_trading_constraints import (
    ExecutionContractValidationError,
)

# This is a resource guard for downstream calendar expansion, not an exchange
# rule or a default lag. Policies must always supply their own explicit value.
MAX_SETTLEMENT_LAG_SESSIONS: int = 10_000
_MAX_TOKEN_LENGTH: int = 192


class ExecutionSettlementV3ValidationError(ExecutionContractValidationError):
    """Raised when the v3 settlement contract is malformed or inconsistent."""


class SettlementBasis(StrEnum):
    """Supported interpretation for an explicit settlement-session lag."""

    CN_OPEN_MARKET_SESSIONS = "CN_OPEN_MARKET_SESSIONS"


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > _MAX_TOKEN_LENGTH
        or any(character.isspace() for character in value)
    ):
        raise ExecutionSettlementV3ValidationError(
            f"{field_name} must be a bounded canonical token"
        )


def _require_digest(value: object, field_name: str) -> None:
    if type(value) is not str or len(value) != 64:
        raise ExecutionSettlementV3ValidationError(f"{field_name} must be a SHA-256 digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise ExecutionSettlementV3ValidationError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )


def _require_aware_datetime(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None:
        raise ExecutionSettlementV3ValidationError(
            f"{field_name} must be a timezone-aware datetime"
        )
    try:
        is_aware = value.utcoffset() is not None
    except (OverflowError, TypeError, ValueError) as error:
        raise ExecutionSettlementV3ValidationError(
            f"{field_name} must be a timezone-aware datetime"
        ) from error
    if not is_aware:
        raise ExecutionSettlementV3ValidationError(
            f"{field_name} must be a timezone-aware datetime"
        )


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ExecutionSettlementV3ValidationError(
            "settlement content is not canonical JSON"
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def _seal_content_hash(payload: dict[str, object], supplied: object) -> str:
    if type(supplied) is not str:
        raise ExecutionSettlementV3ValidationError("content_hash must be a string")
    expected = _canonical_hash(payload)
    if supplied and supplied != expected:
        raise ExecutionSettlementV3ValidationError("content_hash does not match payload")
    return expected


@dataclass(frozen=True, slots=True)
class SettlementPolicyV1:
    """Source-backed settlement input bound to one security and v2 rule hash.

    ``settlement_lag_sessions`` is required operator configuration. The upper
    bound only limits downstream calendar expansion; it is not an exchange
    parameter, instrument default, or implied settlement period.
    """

    policy_id: str
    policy_version: str
    security_id: str
    market: str
    board: str
    settlement_basis: SettlementBasis
    settlement_lag_sessions: int
    bound_execution_rule_v2_hash: str
    source_id: str
    source_version: str
    source_hash: str
    source_observed_at: datetime
    source_available_at: datetime
    effective_from: datetime
    valid_until: datetime
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate scope, provenance, time windows, and the canonical hash."""

        for field_name in (
            "policy_id",
            "policy_version",
            "security_id",
            "market",
            "board",
            "source_id",
            "source_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.settlement_basis) is not SettlementBasis:
            raise ExecutionSettlementV3ValidationError(
                "settlement_basis must be a recognized SettlementBasis"
            )
        if (
            type(self.settlement_lag_sessions) is not int
            or not 0 <= self.settlement_lag_sessions <= MAX_SETTLEMENT_LAG_SESSIONS
        ):
            raise ExecutionSettlementV3ValidationError(
                "settlement_lag_sessions must be a bounded nonnegative integer"
            )
        _require_digest(self.bound_execution_rule_v2_hash, "bound_execution_rule_v2_hash")
        _require_digest(self.source_hash, "source_hash")
        for field_name in (
            "source_observed_at",
            "source_available_at",
            "effective_from",
            "valid_until",
        ):
            _require_aware_datetime(getattr(self, field_name), field_name)
        if self.source_observed_at > self.source_available_at:
            raise ExecutionSettlementV3ValidationError(
                "settlement source observed_at must not follow available_at"
            )
        if self.source_available_at >= self.valid_until:
            raise ExecutionSettlementV3ValidationError(
                "settlement source must be available before valid_until"
            )
        if self.effective_from >= self.valid_until:
            raise ExecutionSettlementV3ValidationError("settlement effective window is invalid")
        object.__setattr__(
            self,
            "content_hash",
            _seal_content_hash(self._content_payload(), self.content_hash),
        )

    def _content_payload(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "security_id": self.security_id,
            "market": self.market,
            "board": self.board,
            "settlement_basis": self.settlement_basis.value,
            "settlement_lag_sessions": self.settlement_lag_sessions,
            "bound_execution_rule_v2_hash": self.bound_execution_rule_v2_hash,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "source_hash": self.source_hash,
            "source_observed_at": _utc_text(self.source_observed_at),
            "source_available_at": _utc_text(self.source_available_at),
            "effective_from": _utc_text(self.effective_from),
            "valid_until": _utc_text(self.valid_until),
        }

    def to_payload(self) -> dict[str, object]:
        """Return all policy fields and revalidate their immutable content hash."""

        self.__post_init__()
        return {**self._content_payload(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class ExecutionSettlementBundleV3:
    """Bind one exact v2 rule to one explicit settlement policy configuration."""

    bundle_id: str
    bundle_version: str
    execution_submission_v2: ExecutionSubmissionRuleV2
    settlement_policy_v1: SettlementPolicyV1
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Revalidate nested hashes and exact security, market, and rule binding."""

        _require_token(self.bundle_id, "bundle_id")
        _require_token(self.bundle_version, "bundle_version")
        if type(self.execution_submission_v2) is not ExecutionSubmissionRuleV2:
            raise ExecutionSettlementV3ValidationError(
                "execution_submission_v2 must be ExecutionSubmissionRuleV2"
            )
        if type(self.settlement_policy_v1) is not SettlementPolicyV1:
            raise ExecutionSettlementV3ValidationError(
                "settlement_policy_v1 must be SettlementPolicyV1"
            )
        try:
            self.execution_submission_v2.__post_init__()
            self.settlement_policy_v1.__post_init__()
        except ExecutionSettlementV3ValidationError:
            raise
        except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
            raise ExecutionSettlementV3ValidationError(
                "nested execution or settlement contract is invalid"
            ) from error

        base = self.execution_submission_v2.execution_rule_v1
        policy = self.settlement_policy_v1
        if (
            policy.security_id != base.security_id
            or policy.market != base.market
            or policy.board != base.board
        ):
            raise ExecutionSettlementV3ValidationError(
                "settlement policy security, market, and board must match nested v2 rule"
            )
        if policy.bound_execution_rule_v2_hash != self.execution_submission_v2.content_hash:
            raise ExecutionSettlementV3ValidationError(
                "settlement policy must bind the exact nested v2 content hash"
            )
        if policy.effective_from < base.effective_from or policy.valid_until > base.valid_until:
            raise ExecutionSettlementV3ValidationError(
                "settlement policy window must be contained in the nested v1 rule window"
            )
        if max(base.source_available_at, policy.source_available_at) >= min(
            base.valid_until, policy.valid_until
        ):
            raise ExecutionSettlementV3ValidationError(
                "all bundle sources must be available before the intersected expiry"
            )
        object.__setattr__(
            self,
            "content_hash",
            _seal_content_hash(self._content_payload(), self.content_hash),
        )

    @property
    def effective_from(self) -> datetime:
        """Return when both nested v2 terms and settlement policy are effective."""

        self.__post_init__()
        return max(
            self.execution_submission_v2.execution_rule_v1.effective_from,
            self.settlement_policy_v1.effective_from,
        )

    @property
    def valid_until(self) -> datetime:
        """Return the first expiry among nested v2 terms and settlement policy."""

        self.__post_init__()
        return min(
            self.execution_submission_v2.execution_rule_v1.valid_until,
            self.settlement_policy_v1.valid_until,
        )

    @property
    def source_available_at(self) -> datetime:
        """Return when all source-backed terms in this bundle are available."""

        self.__post_init__()
        return max(
            self.execution_submission_v2.execution_rule_v1.source_available_at,
            self.settlement_policy_v1.source_available_at,
        )

    @property
    def latest_source_observed_at(self) -> datetime:
        """Return the newest source observation; this is not local recorded_at."""

        self.__post_init__()
        return max(
            self.execution_submission_v2.execution_rule_v1.source_observed_at,
            self.settlement_policy_v1.source_observed_at,
        )

    @property
    def oldest_source_observed_at(self) -> datetime:
        """Return the oldest source observation while preserving each nested clock."""

        self.__post_init__()
        return min(
            self.execution_submission_v2.execution_rule_v1.source_observed_at,
            self.settlement_policy_v1.source_observed_at,
        )

    def _content_payload(self) -> dict[str, object]:
        return {
            "bundle_id": self.bundle_id,
            "bundle_version": self.bundle_version,
            "execution_submission_v2": self.execution_submission_v2.to_payload(),
            "settlement_policy_v1": self.settlement_policy_v1.to_payload(),
        }

    def to_payload(self) -> dict[str, object]:
        """Return exact nested v2 bytes, settlement parameters, and the v3 hash."""

        self.__post_init__()
        return {**self._content_payload(), "content_hash": self.content_hash}


__all__: tuple[str, ...] = (
    "MAX_SETTLEMENT_LAG_SESSIONS",
    "ExecutionSettlementBundleV3",
    "ExecutionSettlementV3ValidationError",
    "SettlementBasis",
    "SettlementPolicyV1",
)
