"""Typed application read boundary for effective v3 settlement configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.risk_center.domain.execution_settlement_v3 import (
    ExecutionSettlementBundleV3,
)
from core.exceptions import InvalidInputError, MissingConfigError


class ExecutionSettlementV3InputError(InvalidInputError):
    """The v3 settlement lookup key or cutoff is invalid."""

    default_message = "A-share settlement lookup input is invalid"
    default_code = "A_SHARE_SETTLEMENT_V3_INPUT_INVALID"


class ExecutionSettlementV3Unavailable(MissingConfigError):
    """No v3 settlement configuration is available for the requested cutoff."""

    default_message = "A-share settlement configuration is unavailable"
    default_code = "A_SHARE_SETTLEMENT_V3_UNAVAILABLE"


class ExecutionSettlementV3Corruption(MissingConfigError):
    """A returned v3 settlement record failed integrity or scope validation."""

    default_message = "A-share settlement configuration is inconsistent"
    default_code = "A_SHARE_SETTLEMENT_V3_CORRUPT"


def _is_aware_datetime(value: object) -> bool:
    if type(value) is not datetime or value.tzinfo is None:
        return False
    try:
        return value.utcoffset() is not None
    except (OverflowError, TypeError, ValueError):
        return False


@dataclass(frozen=True, slots=True)
class ExecutionSettlementV3ReadRecord:
    """Pair an immutable rule bundle with its database knowledge timestamp."""

    bundle: ExecutionSettlementBundleV3
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Require a sealed v3 bundle and an aware local recorded-at timestamp."""

        if type(self.bundle) is not ExecutionSettlementBundleV3:
            raise ExecutionSettlementV3Corruption(
                "settlement read record must contain an exact v3 bundle"
            )
        if not _is_aware_datetime(self.recorded_at):
            raise ExecutionSettlementV3Corruption(
                "settlement read record recorded_at must be timezone-aware"
            )
        try:
            ExecutionSettlementBundleV3.__post_init__(self.bundle)
        except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
            raise ExecutionSettlementV3Corruption(
                "settlement read record contains an invalid bundle"
            ) from error


class ExecutionSettlementV3ReadPort(Protocol):
    """Read one immutable v3 bundle plus the local time it entered storage."""

    def get_effective_settlement_bundle(
        self, *, security_id: str, as_of: datetime
    ) -> ExecutionSettlementV3ReadRecord | None:
        """Return one locally known, source-available, effective settlement bundle."""


class ReadEffectiveExecutionSettlementV3UseCase:
    """Read a source-backed settlement bundle at one exact knowledge cutoff."""

    def __init__(self, repository: ExecutionSettlementV3ReadPort) -> None:
        """Require the Risk-owned typed read port explicitly."""

        self._repository = repository

    def execute(self, *, security_id: str, as_of: datetime) -> ExecutionSettlementBundleV3:
        """Return one matching v3 bundle or fail closed on missing or corrupt data."""

        if (
            type(security_id) is not str
            or not security_id
            or security_id.strip() != security_id
            or len(security_id) > 192
            or any(character.isspace() for character in security_id)
        ):
            raise ExecutionSettlementV3InputError("security_id must be a bounded canonical token")
        if not _is_aware_datetime(as_of):
            raise ExecutionSettlementV3InputError(
                "settlement lookup requires an aware knowledge cutoff"
            )

        record = self._repository.get_effective_settlement_bundle(
            security_id=security_id,
            as_of=as_of,
        )
        if record is None:
            raise ExecutionSettlementV3Unavailable(
                "no effective v3 settlement configuration exists"
            )
        if type(record) is not ExecutionSettlementV3ReadRecord:
            raise ExecutionSettlementV3Corruption(
                "settlement repository returned an invalid record type"
            )
        try:
            ExecutionSettlementV3ReadRecord.__post_init__(record)
            bundle = record.bundle
            ExecutionSettlementBundleV3.__post_init__(bundle)
        except ExecutionSettlementV3Corruption:
            raise
        except (
            AttributeError,
            ArithmeticError,
            TypeError,
            ValueError,
        ) as error:
            raise ExecutionSettlementV3Corruption(
                "settlement repository returned an invalid sealed bundle"
            ) from error

        policy = bundle.settlement_policy_v1
        base = bundle.execution_submission_v2.execution_rule_v1
        if policy.security_id != security_id or base.security_id != security_id:
            raise ExecutionSettlementV3Corruption(
                "settlement repository returned a different security"
            )
        try:
            valid_at_cutoff = (
                record.recorded_at <= as_of
                and bundle.latest_source_observed_at <= as_of
                and bundle.source_available_at <= as_of
                and bundle.effective_from <= as_of < bundle.valid_until
            )
        except (OverflowError, TypeError, ValueError) as error:
            raise ExecutionSettlementV3Corruption(
                "settlement record contains incomparable timestamps"
            ) from error
        if not valid_at_cutoff:
            raise ExecutionSettlementV3Corruption(
                "settlement repository returned data outside its knowledge or effective window"
            )
        return bundle


__all__: tuple[str, ...] = (
    "ExecutionSettlementV3Corruption",
    "ExecutionSettlementV3InputError",
    "ExecutionSettlementV3ReadPort",
    "ExecutionSettlementV3ReadRecord",
    "ExecutionSettlementV3Unavailable",
    "ReadEffectiveExecutionSettlementV3UseCase",
)
