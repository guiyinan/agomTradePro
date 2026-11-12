"""Explicit simulation-only tax dates; never evidence of real custody settlement."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, NoReturn
from zoneinfo import ZoneInfo

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
    _require_account_id,
    _require_date,
    _require_digest,
    _require_token,
)
from apps.simulated_trading.domain.execution_settlement_calendar import ExecutionCalendarEvidence
from apps.simulated_trading.domain.execution_settlement_primitives import (
    CalendarEvidenceValidationError,
)

_INVALID = "DEFERRED_DIVIDEND_TAX_SIMULATED_DATE_INVALID"


def _reject(message: str) -> NoReturn:
    """Reject invalid modeled dates using the existing typed tax error."""
    raise DeferredDividendTaxValidationError(message, _INVALID)


def _aware(value: datetime, field: str) -> None:
    """Require an actual aware original clock rather than a calendar date."""
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        _reject(f"{field} must be an explicit timezone-aware datetime")


def _sha(payload: dict[str, object]) -> str:
    """Hash a canonical versioned payload without observation-time defaults."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class SimulatedDividendTaxDateConvention:
    """Explicit configured hypothesis for one simulated owner's historical fills.

    No offset, date interval, activation window or approval is inferred. A trusted
    composition must bind this value to the actual physical/canonical account,
    current Config Center evidence and original immutable fill receipts.
    """

    convention_id: str
    version: str
    physical_account_id: int
    canonical_account_id: str
    owner_user_id: int
    exchange: str
    purchase_open_session_offset: int
    sale_open_session_offset: int
    trade_window_start: date
    trade_window_end: date
    valid_from: datetime
    valid_until: datetime
    known_at: datetime
    approval_ref: str

    def __post_init__(self) -> None:
        """Validate all explicitly configured scope, session offsets and windows."""
        for name in (
            "convention_id",
            "version",
            "canonical_account_id",
            "exchange",
            "approval_ref",
        ):
            _require_token(getattr(self, name), name)
        for name in ("physical_account_id", "owner_user_id"):
            _require_account_id(getattr(self, name), name)
        for name in ("purchase_open_session_offset", "sale_open_session_offset"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                _reject(f"{name} must be an explicit nonnegative integer")
        _require_date(self.trade_window_start, "trade_window_start")
        _require_date(self.trade_window_end, "trade_window_end")
        if self.trade_window_start > self.trade_window_end:
            _reject("modeled trade-date applicability interval is reversed")
        for name in ("valid_from", "valid_until", "known_at"):
            _aware(getattr(self, name), name)
        if self.valid_from >= self.valid_until:
            _reject("simulation convention activation window must be finite and ordered")

    def semantic_payload(self) -> dict[str, object]:
        """Describe the modeling rule independently of its read/authority clocks."""
        self.__post_init__()
        return {
            "schema": "simulated-dividend-tax-date-convention.v1",
            "convention_id": self.convention_id,
            "version": self.version,
            "physical_account_id": self.physical_account_id,
            "canonical_account_id": self.canonical_account_id,
            "owner_user_id": self.owner_user_id,
            "exchange": self.exchange,
            "purchase_open_session_offset": self.purchase_open_session_offset,
            "sale_open_session_offset": self.sale_open_session_offset,
            "trade_window_start": self.trade_window_start.isoformat(),
            "trade_window_end": self.trade_window_end.isoformat(),
            "approval_ref": self.approval_ref,
            "basis": "simulated_open_session_offset",
        }

    @property
    def semantic_sha256(self) -> str:
        """Identify the exact configured simulation hypothesis without renewing it."""
        return _sha(self.semantic_payload())


@dataclass(frozen=True, slots=True)
class SimulatedDividendTaxDateEvidence:
    """Derived simulation date and separate full-observation provenance.

    This result does not authenticate a fill, a Config Center selection or a
    publication. It cannot supply real custody proof or grant posting authority.
    """

    trade_id: str
    trade_payload_sha256: str
    side: Literal["buy", "sell"]
    trade_occurred_at: datetime
    trade_observed_at: datetime
    trade_session: date
    modeled_tax_date: date
    convention_sha256: str
    calendar_evidence_sha256: str
    semantic_sha256: str
    observation_sha256: str
    convention_known_at: datetime
    convention_valid_from: datetime
    convention_valid_until: datetime
    read_at: datetime
    basis: Literal["simulated_open_session_offset"] = "simulated_open_session_offset"
    must_not_use_as_real_custody_proof: Literal[True] = True

    def __post_init__(self) -> None:
        """Keep the simulation label and immutable provenance fields mandatory."""
        _require_token(self.trade_id, "trade_id")
        for name in (
            "trade_payload_sha256",
            "convention_sha256",
            "calendar_evidence_sha256",
            "semantic_sha256",
            "observation_sha256",
        ):
            _require_digest(getattr(self, name), name)
        _require_date(self.trade_session, "trade_session")
        _require_date(self.modeled_tax_date, "modeled_tax_date")
        _aware(self.trade_occurred_at, "trade_occurred_at")
        _aware(self.trade_observed_at, "trade_observed_at")
        for name in (
            "convention_known_at",
            "convention_valid_from",
            "convention_valid_until",
            "read_at",
        ):
            _aware(getattr(self, name), name)
        if (
            self.must_not_use_as_real_custody_proof is not True
            or type(self.basis) is not str
            or self.basis != "simulated_open_session_offset"
            or type(self.side) is not str
            or self.side not in {"buy", "sell"}
            or self.modeled_tax_date < self.trade_session
            or self.trade_observed_at < self.trade_occurred_at
            or self.trade_observed_at > self.read_at
            or self.convention_known_at > self.read_at
            or not self.convention_valid_from <= self.read_at < self.convention_valid_until
        ):
            _reject("modeled tax-date evidence cannot claim real custody or reverse time")
        expected_observation = _sha(
            {
                "semantic_sha256": self.semantic_sha256,
                "calendar_evidence_sha256": self.calendar_evidence_sha256,
                "trade_observed_at": self.trade_observed_at.isoformat(),
                "rule_known_at": self.convention_known_at.isoformat(),
                "rule_valid_from": self.convention_valid_from.isoformat(),
                "rule_valid_until": self.convention_valid_until.isoformat(),
                "read_at": self.read_at.isoformat(),
            }
        )
        if self.observation_sha256 != expected_observation:
            _reject("modeled tax-date original observation clocks do not match their digest")


def derive_simulated_dividend_tax_date(
    *,
    convention: SimulatedDividendTaxDateConvention,
    calendar: ExecutionCalendarEvidence,
    account_kind: str,
    physical_account_id: int,
    canonical_account_id: str,
    owner_user_id: int,
    trade_id: str,
    trade_payload_sha256: str,
    side: Literal["buy", "sell"],
    trade_occurred_at: datetime,
    trade_observed_at: datetime,
    as_of: datetime,
) -> SimulatedDividendTaxDateEvidence:
    """Map an original simulated fill using an explicit rule and published calendar."""
    if type(convention) is not SimulatedDividendTaxDateConvention:
        _reject("an exact explicitly configured simulation convention is required")
    convention.__post_init__()
    _require_account_id(physical_account_id, "physical_account_id")
    _require_account_id(owner_user_id, "owner_user_id")
    _require_token(canonical_account_id, "canonical_account_id")
    if (
        type(account_kind) is not str
        or account_kind != "simulated"
        or physical_account_id != convention.physical_account_id
        or canonical_account_id != convention.canonical_account_id
        or owner_user_id != convention.owner_user_id
    ):
        _reject("simulation date convention cannot cross account kind or owner scope")
    if type(side) is not str or side not in {"buy", "sell"}:
        _reject("the original fill side must be buy or sell")
    _require_token(trade_id, "trade_id")
    _require_digest(trade_payload_sha256, "trade_payload_sha256")
    for value, name in (
        (as_of, "as_of"),
        (trade_occurred_at, "trade_occurred_at"),
        (trade_observed_at, "trade_observed_at"),
    ):
        _aware(value, name)
    if not trade_occurred_at <= trade_observed_at <= as_of:
        _reject("original trade clocks are reversed or later than the read cutoff")
    if (
        not convention.known_at <= as_of
        or not convention.valid_from <= as_of < convention.valid_until
    ):
        _reject("simulation date convention was unknown or inactive at the cutoff")
    if type(calendar) is not ExecutionCalendarEvidence:
        _reject("an exact published exchange calendar is required")
    try:
        calendar.validate_for(as_of)
        if calendar.snapshot.exchange != convention.exchange:
            _reject("simulation convention and calendar exchange differ")
        # This method uses the publication's timezone and validates an explicit
        # open day. It must not validate the current reference at the old fill
        # clock: this is a declared historical simulation at the read cutoff.
        publication = calendar.publication
        if publication is None:
            _reject("simulation date calendar has no publication")
        trade_session = trade_occurred_at.astimezone(ZoneInfo(publication.timezone_name)).date()
        if not convention.trade_window_start <= trade_session <= convention.trade_window_end:
            _reject("trade date lies outside the explicitly modeled historical interval")
        offset = (
            convention.purchase_open_session_offset
            if side == "buy"
            else convention.sale_open_session_offset
        )
        modeled_date = calendar.release_session(trade_session, offset)
        calendar_hash = calendar.evidence_hash
    except (CalendarEvidenceValidationError, OverflowError, ValueError) as error:
        raise DeferredDividendTaxValidationError(str(error), _INVALID) from error
    semantic: dict[str, object] = {
        "schema": "simulated-dividend-tax-date.v1",
        "convention_sha256": convention.semantic_sha256,
        "trade_id": trade_id,
        "trade_payload_sha256": trade_payload_sha256,
        "trade_occurred_at": trade_occurred_at.astimezone(UTC).isoformat(),
        "side": side,
        "trade_session": trade_session.isoformat(),
        "modeled_tax_date": modeled_date.isoformat(),
        "exchange": convention.exchange,
        "timezone_name": publication.timezone_name,
        "covered_calendar_days": [
            row.to_payload()
            for row in calendar.snapshot.days
            if trade_session <= row.calendar_date <= modeled_date
        ],
        "must_not_use_as_real_custody_proof": True,
    }
    semantic_hash = _sha(semantic)
    observation_hash = _sha(
        {
            "semantic_sha256": semantic_hash,
            "calendar_evidence_sha256": calendar_hash,
            "trade_observed_at": trade_observed_at.isoformat(),
            "rule_known_at": convention.known_at.isoformat(),
            "rule_valid_from": convention.valid_from.isoformat(),
            "rule_valid_until": convention.valid_until.isoformat(),
            "read_at": as_of.isoformat(),
        }
    )
    return SimulatedDividendTaxDateEvidence(
        trade_id,
        trade_payload_sha256,
        side,
        trade_occurred_at,
        trade_observed_at,
        trade_session,
        modeled_date,
        convention.semantic_sha256,
        calendar_hash,
        semantic_hash,
        observation_hash,
        convention.known_at,
        convention.valid_from,
        convention.valid_until,
        as_of,
    )
