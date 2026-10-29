"""Sealed current mark evidence used only when a first BUY creates a Position.

This proof describes the apply-time valuation mark. It is independent of a
fill event's price and economics, and its existence does not qualify a source
adapter or authorize any source to be used by a composition root.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final, Literal

from .execution_settlement_primitives import (
    SimulatedSettlementContractError,
    _decimal_numeric_text,
    _hash_payload,
    _require_aware,
    _require_hash,
    _require_token,
    _utc_text,
    validate_ledger_price,
)
from .execution_settlement_uow import SimulatedTradeIntent

_MARK_SCHEMA = "simulated-initial-position-mark.v1"
_DAILY_INTERVAL_MARK_SCHEMA = "simulated-initial-position-mark.daily-interval.v1"
_MARK_PURPOSE = "apply_time_initial_position_mark"
_LEGACY_SOURCE_OBSERVED: Final = "legacy_source_observed"
_DAILY_INTERVAL_END: Final = "daily_interval_end"


class InitialPositionMarkValidationError(SimulatedSettlementContractError):
    """Raised when one initial-position mark or its intent binding is invalid."""


def _require_mark_token(value: object, field_name: str) -> None:
    """Validate one required source, policy, or instrument token."""

    try:
        _require_token(value, field_name)
    except SimulatedSettlementContractError as error:
        raise InitialPositionMarkValidationError(
            f"initial-position mark {field_name} is invalid"
        ) from error


def _require_mark_hash(value: object, field_name: str) -> None:
    """Validate one required canonical source, publication, or policy digest."""

    try:
        _require_hash(value, field_name)
    except SimulatedSettlementContractError as error:
        raise InitialPositionMarkValidationError(
            f"initial-position mark {field_name} is invalid"
        ) from error


def _require_mark_clock(value: object, field_name: str) -> None:
    """Require one exact timezone-aware clock while preserving its original value."""

    try:
        _require_aware(value, field_name)
    except SimulatedSettlementContractError as error:
        raise InitialPositionMarkValidationError(
            f"initial-position mark {field_name} is invalid"
        ) from error


@dataclass(frozen=True, slots=True)
class InitialPositionMarkProof:
    """Bind an exact instrument's positive current mark to source and policy evidence.

    ``source_available_at`` remains ``None`` when the provider did not supply
    that clock. ``read_at`` and ``published_at`` are separate system clocks;
    neither is substituted for provider availability. ``valid_until`` is the
    policy-produced deadline and must agree with the explicit policy window.
    """

    security_id: str
    asset_code: str
    asset_type: str
    market: str
    board: str
    price: Decimal
    source_observed_at: datetime | None
    source_available_at: datetime | None
    read_at: datetime
    publication_as_of: datetime
    published_at: datetime
    valid_until: datetime
    freshness_window_seconds: int
    source_identity: str
    source_record_id: str
    source_content_hash: str
    publication_id: str
    publication_hash: str
    policy_identity: str
    policy_content_hash: str
    observation_basis: Literal["legacy_source_observed", "daily_interval_end"] = (
        _LEGACY_SOURCE_OBSERVED
    )
    interval_end_at: datetime | None = None
    local_known_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate fields and all known chronology when the proof is created."""

        self.validate()

    def validate(self) -> None:
        """Check exact values, source seals, and the explicit policy deadline."""

        for field_name in (
            "security_id",
            "asset_code",
            "asset_type",
            "market",
            "board",
            "source_identity",
            "source_record_id",
            "publication_id",
            "policy_identity",
        ):
            _require_mark_token(getattr(self, field_name), field_name)
        for field_name in (
            "source_content_hash",
            "publication_hash",
            "policy_content_hash",
        ):
            _require_mark_hash(getattr(self, field_name), field_name)
        try:
            validate_ledger_price(self.price, "initial_position_mark_price", allow_zero=False)
        except SimulatedSettlementContractError as error:
            raise InitialPositionMarkValidationError(
                "initial-position mark price is not exactly representable"
            ) from error

        for field_name in ("read_at", "publication_as_of", "published_at", "valid_until"):
            _require_mark_clock(getattr(self, field_name), field_name)
        if self.source_available_at is not None:
            _require_mark_clock(self.source_available_at, "source_available_at")
        if type(self.observation_basis) is not str or self.observation_basis not in (
            _LEGACY_SOURCE_OBSERVED,
            _DAILY_INTERVAL_END,
        ):
            raise InitialPositionMarkValidationError(
                "initial-position mark observation basis is unsupported"
            )
        if type(self.freshness_window_seconds) is not int or self.freshness_window_seconds <= 0:
            raise InitialPositionMarkValidationError(
                "initial-position mark freshness window must be a positive exact integer"
            )

        freshness_anchor: datetime
        if self.observation_basis == _LEGACY_SOURCE_OBSERVED:
            freshness_anchor = self._validate_legacy_source_observed_clocks()
        else:
            freshness_anchor = self._validate_daily_interval_clocks()
        if self.valid_until <= self.read_at:
            raise InitialPositionMarkValidationError(
                "initial-position mark has expired at its read time"
            )
        try:
            expected_deadline = freshness_anchor.astimezone(UTC) + timedelta(
                seconds=self.freshness_window_seconds
            )
        except (OverflowError, TypeError, ValueError) as error:
            raise InitialPositionMarkValidationError(
                "initial-position mark policy deadline cannot be represented"
            ) from error
        if self.valid_until != expected_deadline:
            raise InitialPositionMarkValidationError(
                "initial-position mark deadline differs from its sealed policy window"
            )

    def _validate_legacy_source_observed_clocks(self) -> datetime:
        """Preserve v1 observation, availability, and freshness semantics exactly."""

        if (
            self.source_observed_at is None
            or self.interval_end_at is not None
            or (self.local_known_at is not None)
        ):
            raise InitialPositionMarkValidationError(
                "legacy initial-position mark requires only its source-observed clock"
            )
        _require_mark_clock(self.source_observed_at, "source_observed_at")
        if self.source_observed_at > self.read_at:
            raise InitialPositionMarkValidationError(
                "initial-position mark observation is after its read time"
            )
        if (
            self.source_available_at is not None
            and self.source_available_at < self.source_observed_at
        ):
            raise InitialPositionMarkValidationError(
                "initial-position mark availability is before its source observation"
            )
        if self.source_available_at is not None and self.source_available_at > self.read_at:
            raise InitialPositionMarkValidationError(
                "initial-position mark availability is after its read time"
            )
        if not self.source_observed_at <= self.publication_as_of <= self.published_at:
            raise InitialPositionMarkValidationError(
                "initial-position mark publication chronology is invalid"
            )
        if self.published_at > self.read_at:
            raise InitialPositionMarkValidationError(
                "initial-position mark was published after its read time"
            )
        return self.source_observed_at

    def _validate_daily_interval_clocks(self) -> datetime:
        """Validate a daily interval end separately from unknown supplier observation."""

        if self.source_observed_at is not None:
            raise InitialPositionMarkValidationError(
                "daily interval mark cannot claim a supplier observation time"
            )
        if self.interval_end_at is None or self.local_known_at is None:
            raise InitialPositionMarkValidationError(
                "daily interval mark requires interval-end and local-known clocks"
            )
        _require_mark_clock(self.interval_end_at, "interval_end_at")
        _require_mark_clock(self.local_known_at, "local_known_at")
        if not (self.interval_end_at <= self.local_known_at <= self.published_at <= self.read_at):
            raise InitialPositionMarkValidationError(
                "daily interval mark local knowledge chronology is invalid"
            )
        if not self.interval_end_at <= self.publication_as_of <= self.published_at:
            raise InitialPositionMarkValidationError(
                "daily interval mark publication chronology is invalid"
            )
        if self.source_available_at is not None and not (
            self.interval_end_at <= self.source_available_at <= self.local_known_at
        ):
            raise InitialPositionMarkValidationError(
                "daily interval mark source availability is outside known interval clocks"
            )
        return self.interval_end_at

    def validate_for_instrument(
        self,
        *,
        security_id: str,
        asset_code: str,
        asset_type: str,
        market: str,
        board: str,
        read_at: datetime,
    ) -> None:
        """Bind the proof to five exact instrument fields and its recorded read time."""

        self.validate()
        for field_name, value in (
            ("security_id", security_id),
            ("asset_code", asset_code),
            ("asset_type", asset_type),
            ("market", market),
            ("board", board),
        ):
            _require_mark_token(value, field_name)
            if getattr(self, field_name) != value:
                raise InitialPositionMarkValidationError(
                    f"initial-position mark {field_name} differs from the sealed instrument"
                )
        _require_mark_clock(read_at, "requested_read_at")
        if self.read_at != read_at:
            raise InitialPositionMarkValidationError(
                "initial-position mark read time differs from the requested cutoff"
            )

    def validate_for(self, *, intent: SimulatedTradeIntent, read_at: datetime) -> None:
        """Bind this proof to an exact trade intent without changing its fill price."""

        if type(intent) is not SimulatedTradeIntent:
            raise InitialPositionMarkValidationError("initial-position mark intent is invalid")
        try:
            intent.__post_init__()
        except (ArithmeticError, TypeError, ValueError) as error:
            raise InitialPositionMarkValidationError(
                "initial-position mark intent is invalid"
            ) from error
        self.validate_for_instrument(
            security_id=intent.security_id,
            asset_code=intent.asset_code,
            asset_type=intent.asset_type,
            market=intent.market,
            board=intent.board,
            read_at=read_at,
        )

    def to_payload(self) -> dict[str, object]:
        """Return a canonical, JSON-compatible representation of the proof."""

        self.validate()
        payload: dict[str, object] = {
            "schema": (
                _MARK_SCHEMA
                if self.observation_basis == _LEGACY_SOURCE_OBSERVED
                else _DAILY_INTERVAL_MARK_SCHEMA
            ),
            "purpose": _MARK_PURPOSE,
            "security_id": self.security_id,
            "asset_code": self.asset_code,
            "asset_type": self.asset_type,
            "market": self.market,
            "board": self.board,
            "price": _decimal_numeric_text(self.price),
            "source_observed_at": (
                _utc_text(self.source_observed_at) if self.source_observed_at is not None else None
            ),
            "source_available_at": (
                _utc_text(self.source_available_at)
                if self.source_available_at is not None
                else None
            ),
            "read_at": _utc_text(self.read_at),
            "publication_as_of": _utc_text(self.publication_as_of),
            "published_at": _utc_text(self.published_at),
            "valid_until": _utc_text(self.valid_until),
            "freshness_window_seconds": self.freshness_window_seconds,
            "source_identity": self.source_identity,
            "source_record_id": self.source_record_id,
            "source_content_hash": self.source_content_hash,
            "publication_id": self.publication_id,
            "publication_hash": self.publication_hash,
            "policy_identity": self.policy_identity,
            "policy_content_hash": self.policy_content_hash,
        }
        if self.observation_basis == _DAILY_INTERVAL_END:
            if self.interval_end_at is None or self.local_known_at is None:
                raise InitialPositionMarkValidationError(
                    "daily interval mark requires interval-end and local-known clocks"
                )
            payload.update(
                {
                    "observation_basis": _DAILY_INTERVAL_END,
                    "interval_end_at": _utc_text(self.interval_end_at),
                    "local_known_at": _utc_text(self.local_known_at),
                }
            )
        return payload

    @property
    def proof_hash(self) -> str:
        """Return the canonical SHA-256 seal over all mark and policy fields."""

        return _hash_payload(self.to_payload())


__all__ = (
    "InitialPositionMarkProof",
    "InitialPositionMarkValidationError",
)
