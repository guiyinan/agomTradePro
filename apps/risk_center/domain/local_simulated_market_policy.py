"""Explicit source, clock, session, and paper-boundary policy for local simulation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import TypedDict, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.risk_center.domain.execution_trading_constraints import (
    PriceBoundaryMode,
    SessionState,
)
from apps.risk_center.domain.price_submission_range import PriceSubmissionStage

_POLICY_SCHEMA = "local-simulated-market-policy.v1"
_PURPOSE = "local_simulation_only"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class LocalSimulatedMarketPolicyError(ValueError):
    """Raised when a local simulation market policy is incomplete or inconsistent."""


class LocalSimulatedSessionWindowPayload(TypedDict):
    """One configured, local-time market phase window."""

    stage: str
    starts_at: str
    ends_at: str


class LocalSimulatedMarketPolicyPayload(TypedDict):
    """Exact JSON fields for one source- and security-scoped policy."""

    schema: str
    purpose: str
    policy_id: str
    policy_version: str
    security_id: str
    asset_code: str
    market: str
    board: str
    effective_from: str
    effective_until: str
    source_id: str
    source_name: str
    quote_ttl_seconds: int
    status_mapping_sha256: str
    trusted_vendor_status_codes: list[str]
    session_timezone: str
    session_windows: list[LocalSimulatedSessionWindowPayload]
    price_boundary_mode: str
    lower_boundary_factor: str | None
    upper_boundary_factor: str | None
    boundary_rule_source_id: str | None
    boundary_rule_version: str | None
    boundary_rule_source_hash: str | None
    unrestricted_reason_code: str | None
    content_hash: str


class LocalSimulatedCalendarPayload(TypedDict):
    """A published session/calendar context copied across the public app port."""

    calendar_id: str
    calendar_version: str
    calendar_source_hash: str
    calendar_observed_at: str
    calendar_available_at: str
    calendar_valid_until: str
    trading_date: str
    session_id: str
    session_timezone: str
    session_open_at: str
    session_close_at: str
    session_state: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class LocalSimulatedSessionWindow:
    """One explicitly configured continuous-trading time window."""

    stage: PriceSubmissionStage
    starts_at: time
    ends_at: time

    def __post_init__(self) -> None:
        """Reject unsupported phases and windows that cannot be compared locally."""

        if type(self.stage) is not PriceSubmissionStage:
            raise LocalSimulatedMarketPolicyError("session window stage is invalid")
        if self.stage is not PriceSubmissionStage.CONTINUOUS:
            raise LocalSimulatedMarketPolicyError("only continuous stage is supported by V2")
        for field_name, value in (("starts_at", self.starts_at), ("ends_at", self.ends_at)):
            if type(value) is not time or value.tzinfo is not None or value.microsecond != 0:
                raise LocalSimulatedMarketPolicyError(f"session window {field_name} is invalid")
        if self.starts_at >= self.ends_at:
            raise LocalSimulatedMarketPolicyError("session window interval is invalid")

    def to_payload(self) -> LocalSimulatedSessionWindowPayload:
        """Return the exact configured stage and local wall-clock interval."""

        self.__post_init__()
        return {
            "stage": self.stage.value,
            "starts_at": self.starts_at.strftime("%H:%M:%S"),
            "ends_at": self.ends_at.strftime("%H:%M:%S"),
        }

    @classmethod
    def from_payload(cls, payload: object) -> LocalSimulatedSessionWindow:
        """Decode one exact window without inserting a stage or time default."""

        values = _exact_object(payload, {"stage", "starts_at", "ends_at"}, "session window")
        if any(type(values[key]) is not str for key in values):
            raise LocalSimulatedMarketPolicyError("session window payload text is invalid")
        try:
            return cls(
                stage=PriceSubmissionStage(cast(str, values["stage"])),
                starts_at=_parse_time(cast(str, values["starts_at"])),
                ends_at=_parse_time(cast(str, values["ends_at"])),
            )
        except ValueError as error:
            if isinstance(error, LocalSimulatedMarketPolicyError):
                raise
            raise LocalSimulatedMarketPolicyError("session window payload is invalid") from error


@dataclass(frozen=True, slots=True)
class LocalSimulatedMarketPolicy:
    """Bind exact source, security, effective dates, session, and paper bounds.

    This policy explicitly scopes a local simulation only. It does not turn a
    Sina source state into an exchange guarantee or authorize live execution.
    """

    policy_id: str
    policy_version: str
    security_id: str
    asset_code: str
    market: str
    board: str
    effective_from: date
    effective_until: date
    source_id: str
    source_name: str
    quote_ttl_seconds: int
    status_mapping_sha256: str
    trusted_vendor_status_codes: tuple[str, ...]
    session_timezone: str
    session_windows: tuple[LocalSimulatedSessionWindow, ...]
    price_boundary_mode: PriceBoundaryMode
    lower_boundary_factor: Decimal | None
    upper_boundary_factor: Decimal | None
    boundary_rule_source_id: str | None
    boundary_rule_version: str | None
    boundary_rule_source_hash: str | None
    unrestricted_reason_code: str | None
    purpose: str = _PURPOSE
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate all required source policy fields and seal their content."""

        if type(self.purpose) is not str or self.purpose != _PURPOSE:
            raise LocalSimulatedMarketPolicyError("policy purpose must be local_simulation_only")
        for field_name in (
            "policy_id",
            "policy_version",
            "security_id",
            "asset_code",
            "market",
            "board",
            "source_id",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_display_text(self.source_name, "source_name")
        if type(self.effective_from) is not date or type(self.effective_until) is not date:
            raise LocalSimulatedMarketPolicyError("policy effective dates must be exact dates")
        if self.effective_from > self.effective_until:
            raise LocalSimulatedMarketPolicyError("policy effective date range is inverted")
        if type(self.quote_ttl_seconds) is not int or self.quote_ttl_seconds <= 0:
            raise LocalSimulatedMarketPolicyError("quote_ttl_seconds must be explicitly positive")
        _require_hash(self.status_mapping_sha256, "status_mapping_sha256")
        if type(self.trusted_vendor_status_codes) is not tuple:
            raise LocalSimulatedMarketPolicyError("trusted status codes must be a tuple")
        if len(set(self.trusted_vendor_status_codes)) != len(self.trusted_vendor_status_codes):
            raise LocalSimulatedMarketPolicyError("trusted status codes must be unique")
        for code in self.trusted_vendor_status_codes:
            _require_token(code, "trusted vendor status code")
        if type(self.session_timezone) is not str or self.session_timezone != "Asia/Shanghai":
            raise LocalSimulatedMarketPolicyError(
                "session timezone must be explicitly Asia/Shanghai"
            )
        try:
            ZoneInfo(self.session_timezone)
        except ZoneInfoNotFoundError as error:
            raise LocalSimulatedMarketPolicyError("session timezone is unknown") from error
        if type(self.session_windows) is not tuple:
            raise LocalSimulatedMarketPolicyError("session_windows must be a tuple")
        if any(type(window) is not LocalSimulatedSessionWindow for window in self.session_windows):
            raise LocalSimulatedMarketPolicyError("session window type is invalid")
        ordered_windows = sorted(self.session_windows, key=lambda window: window.starts_at)
        if tuple(ordered_windows) != self.session_windows:
            raise LocalSimulatedMarketPolicyError("session windows must be ordered")
        if any(
            previous.ends_at > current.starts_at
            for previous, current in zip(
                self.session_windows, self.session_windows[1:], strict=False
            )
        ):
            raise LocalSimulatedMarketPolicyError("session windows must not overlap")
        if type(self.price_boundary_mode) is not PriceBoundaryMode:
            raise LocalSimulatedMarketPolicyError("price boundary mode is invalid")
        self._validate_boundary_policy()
        computed_hash = _canonical_hash(self._content_payload())
        if self.content_hash and self.content_hash != computed_hash:
            raise LocalSimulatedMarketPolicyError("policy content hash does not match")
        object.__setattr__(self, "content_hash", computed_hash)

    def _validate_boundary_policy(self) -> None:
        """Require explicit paper-boundary derivation or explicit unknown state."""

        if self.price_boundary_mode is PriceBoundaryMode.LIMITED:
            lower_factor = self.lower_boundary_factor
            upper_factor = self.upper_boundary_factor
            if type(lower_factor) is not Decimal or type(upper_factor) is not Decimal:
                raise LocalSimulatedMarketPolicyError("limited policy factors must be Decimal")
            _require_positive_decimal(lower_factor, "lower_boundary_factor")
            _require_positive_decimal(upper_factor, "upper_boundary_factor")
            if lower_factor >= upper_factor:
                raise LocalSimulatedMarketPolicyError("paper boundary factors are inverted")
            _require_boundary_identity(self)
            if self.unrestricted_reason_code is not None:
                raise LocalSimulatedMarketPolicyError(
                    "limited policy cannot have an unrestricted reason"
                )
            return
        if self.price_boundary_mode is PriceBoundaryMode.UNRESTRICTED:
            if self.lower_boundary_factor is not None or self.upper_boundary_factor is not None:
                raise LocalSimulatedMarketPolicyError("unrestricted policy cannot carry factors")
            _require_boundary_identity(self)
            _require_token(self.unrestricted_reason_code, "unrestricted_reason_code")
            return
        if any(
            value is not None
            for value in (
                self.lower_boundary_factor,
                self.upper_boundary_factor,
                self.boundary_rule_source_id,
                self.boundary_rule_version,
                self.boundary_rule_source_hash,
                self.unrestricted_reason_code,
            )
        ):
            raise LocalSimulatedMarketPolicyError(
                "unknown boundary policy cannot carry derived values"
            )

    @property
    def purpose_value(self) -> str:
        """Return the immutable local-simulation purpose marker."""

        self.__post_init__()
        return self.purpose

    def derive_price_boundaries(
        self,
        *,
        previous_close: Decimal | None,
        price_tick: Decimal,
    ) -> tuple[Decimal | None, Decimal | None]:
        """Derive explicit paper bounds from this policy and the exact V2 tick."""

        self.__post_init__()
        if self.price_boundary_mode is PriceBoundaryMode.UNKNOWN:
            raise LocalSimulatedMarketPolicyError("paper boundary mode is unknown")
        if self.price_boundary_mode is PriceBoundaryMode.UNRESTRICTED:
            return None, None
        if self.price_boundary_mode is not PriceBoundaryMode.LIMITED:
            raise LocalSimulatedMarketPolicyError("paper boundary mode is unsupported")
        _require_positive_decimal(price_tick, "price_tick")
        if type(previous_close) is not Decimal:
            raise LocalSimulatedMarketPolicyError("same-day previous_close is missing")
        _require_positive_decimal(previous_close, "same-day previous_close")
        lower_factor = self.lower_boundary_factor
        upper_factor = self.upper_boundary_factor
        if type(lower_factor) is not Decimal or type(upper_factor) is not Decimal:
            raise LocalSimulatedMarketPolicyError("paper boundary factors are missing")
        lower = _round_to_tick(Fraction(previous_close) * Fraction(lower_factor), price_tick)
        upper = _round_to_tick(Fraction(previous_close) * Fraction(upper_factor), price_tick)
        if lower > upper:
            raise LocalSimulatedMarketPolicyError("paper price boundary is reversed")
        return lower, upper

    def is_same_continuous_window(self, *, observed_at: datetime, as_of: datetime) -> bool:
        """Reject quotes from an earlier session segment even with a long configured TTL."""
        self.__post_init__()
        _require_aware(observed_at, "observed_at")
        _require_aware(as_of, "as_of")
        zone = ZoneInfo(self.session_timezone)
        observed = observed_at.astimezone(zone)
        current = as_of.astimezone(zone)
        if observed.date() != current.date():
            return False
        observed_time = observed.timetz().replace(tzinfo=None)
        current_time = current.timetz().replace(tzinfo=None)
        return any(
            window.stage is PriceSubmissionStage.CONTINUOUS
            and window.starts_at <= observed_time <= current_time < window.ends_at
            for window in self.session_windows
        )

    def _content_payload(self) -> dict[str, object]:
        """Build the strict versioned content before adding its digest."""

        return {
            "schema": _POLICY_SCHEMA,
            "purpose": self.purpose,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "security_id": self.security_id,
            "asset_code": self.asset_code,
            "market": self.market,
            "board": self.board,
            "effective_from": self.effective_from.isoformat(),
            "effective_until": self.effective_until.isoformat(),
            "source_id": self.source_id,
            "source_name": self.source_name,
            "quote_ttl_seconds": self.quote_ttl_seconds,
            "status_mapping_sha256": self.status_mapping_sha256,
            "trusted_vendor_status_codes": list(self.trusted_vendor_status_codes),
            "session_timezone": self.session_timezone,
            "session_windows": [window.to_payload() for window in self.session_windows],
            "price_boundary_mode": self.price_boundary_mode.value,
            "lower_boundary_factor": _decimal_text(self.lower_boundary_factor),
            "upper_boundary_factor": _decimal_text(self.upper_boundary_factor),
            "boundary_rule_source_id": self.boundary_rule_source_id,
            "boundary_rule_version": self.boundary_rule_version,
            "boundary_rule_source_hash": self.boundary_rule_source_hash,
            "unrestricted_reason_code": self.unrestricted_reason_code,
        }

    def to_payload(self) -> LocalSimulatedMarketPolicyPayload:
        """Return the full exact policy and its canonical content hash."""

        self.__post_init__()
        payload = self._content_payload()
        payload["content_hash"] = self.content_hash
        return cast(LocalSimulatedMarketPolicyPayload, payload)

    @classmethod
    def from_payload(cls, payload: object) -> LocalSimulatedMarketPolicy:
        """Strictly decode a Config Center value or retained signed policy payload."""

        keys = {
            "schema",
            "purpose",
            "policy_id",
            "policy_version",
            "security_id",
            "asset_code",
            "market",
            "board",
            "effective_from",
            "effective_until",
            "source_id",
            "source_name",
            "quote_ttl_seconds",
            "status_mapping_sha256",
            "trusted_vendor_status_codes",
            "session_timezone",
            "session_windows",
            "price_boundary_mode",
            "lower_boundary_factor",
            "upper_boundary_factor",
            "boundary_rule_source_id",
            "boundary_rule_version",
            "boundary_rule_source_hash",
            "unrestricted_reason_code",
        }
        if type(payload) is not dict or frozenset(payload) not in {
            frozenset(keys),
            frozenset(keys | {"content_hash"}),
        }:
            raise LocalSimulatedMarketPolicyError(
                "local simulation policy fields are incomplete or unknown"
            )
        values = cast(dict[str, object], payload)
        if values.get("schema") != _POLICY_SCHEMA:
            raise LocalSimulatedMarketPolicyError("policy schema is unsupported")
        content_hash = values.get("content_hash", "")
        if type(content_hash) is not str:
            raise LocalSimulatedMarketPolicyError("policy content hash is invalid")
        text_names = (
            "purpose",
            "policy_id",
            "policy_version",
            "security_id",
            "asset_code",
            "market",
            "board",
            "source_id",
            "source_name",
            "status_mapping_sha256",
            "session_timezone",
            "price_boundary_mode",
        )
        if any(type(values[name]) is not str for name in text_names):
            raise LocalSimulatedMarketPolicyError("policy text field is invalid")
        optional_text_names = (
            "boundary_rule_source_id",
            "boundary_rule_version",
            "boundary_rule_source_hash",
            "unrestricted_reason_code",
        )
        if any(
            values[name] is not None and type(values[name]) is not str
            for name in optional_text_names
        ):
            raise LocalSimulatedMarketPolicyError("policy optional text field is invalid")
        if type(values["quote_ttl_seconds"]) is not int:
            raise LocalSimulatedMarketPolicyError("policy quote TTL is invalid")
        if type(values["trusted_vendor_status_codes"]) is not list or any(
            type(code) is not str
            for code in cast(list[object], values["trusted_vendor_status_codes"])
        ):
            raise LocalSimulatedMarketPolicyError("trusted status code list is invalid")
        raw_windows = values["session_windows"]
        if type(raw_windows) is not list:
            raise LocalSimulatedMarketPolicyError("session window list is invalid")
        try:
            policy = cls(
                policy_id=cast(str, values["policy_id"]),
                policy_version=cast(str, values["policy_version"]),
                security_id=cast(str, values["security_id"]),
                asset_code=cast(str, values["asset_code"]),
                market=cast(str, values["market"]),
                board=cast(str, values["board"]),
                effective_from=_parse_date(values["effective_from"]),
                effective_until=_parse_date(values["effective_until"]),
                source_id=cast(str, values["source_id"]),
                source_name=cast(str, values["source_name"]),
                quote_ttl_seconds=values["quote_ttl_seconds"],
                status_mapping_sha256=cast(str, values["status_mapping_sha256"]),
                trusted_vendor_status_codes=tuple(
                    cast(list[str], values["trusted_vendor_status_codes"])
                ),
                session_timezone=cast(str, values["session_timezone"]),
                session_windows=tuple(
                    LocalSimulatedSessionWindow.from_payload(window) for window in raw_windows
                ),
                price_boundary_mode=PriceBoundaryMode(cast(str, values["price_boundary_mode"])),
                lower_boundary_factor=_parse_optional_decimal(values["lower_boundary_factor"]),
                upper_boundary_factor=_parse_optional_decimal(values["upper_boundary_factor"]),
                boundary_rule_source_id=cast(str | None, values["boundary_rule_source_id"]),
                boundary_rule_version=cast(str | None, values["boundary_rule_version"]),
                boundary_rule_source_hash=cast(str | None, values["boundary_rule_source_hash"]),
                unrestricted_reason_code=cast(str | None, values["unrestricted_reason_code"]),
                purpose=cast(str, values["purpose"]),
                content_hash=content_hash,
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, LocalSimulatedMarketPolicyError):
                raise
            raise LocalSimulatedMarketPolicyError("policy payload is invalid") from error
        expected_payload = (
            policy.to_payload() if "content_hash" in values else policy._content_payload()
        )
        if expected_payload != values:
            raise LocalSimulatedMarketPolicyError("policy payload is not canonical")
        return policy


@dataclass(frozen=True, slots=True)
class LocalSimulatedCalendarContext:
    """Typed published calendar/session evidence for one local simulation read."""

    calendar_id: str
    calendar_version: str
    calendar_source_hash: str
    calendar_observed_at: datetime
    calendar_available_at: datetime
    calendar_valid_until: datetime
    trading_date: date
    session_id: str
    session_timezone: str
    session_open_at: datetime
    session_close_at: datetime
    session_state: SessionState

    def __post_init__(self) -> None:
        """Validate all actual calendar clocks and the exact published session."""

        for name in ("calendar_id", "calendar_version", "session_id"):
            _require_token(getattr(self, name), name)
        _require_hash(self.calendar_source_hash, "calendar_source_hash")
        if type(self.trading_date) is not date:
            raise LocalSimulatedMarketPolicyError("calendar trading_date must be exact")
        if type(self.session_timezone) is not str:
            raise LocalSimulatedMarketPolicyError("calendar session timezone is invalid")
        try:
            zone = ZoneInfo(self.session_timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise LocalSimulatedMarketPolicyError("calendar session timezone is unknown") from error
        for name in (
            "calendar_observed_at",
            "calendar_available_at",
            "calendar_valid_until",
            "session_open_at",
            "session_close_at",
        ):
            _require_aware(getattr(self, name), name)
        if not self.calendar_observed_at <= self.calendar_available_at < self.calendar_valid_until:
            raise LocalSimulatedMarketPolicyError("calendar evidence window is invalid")
        if self.session_open_at >= self.session_close_at:
            raise LocalSimulatedMarketPolicyError("published session interval is invalid")
        if (
            self.session_open_at.astimezone(zone).date() != self.trading_date
            or self.session_close_at.astimezone(zone).date() != self.trading_date
        ):
            raise LocalSimulatedMarketPolicyError("session clocks do not match trading_date")
        if type(self.session_state) is not SessionState:
            raise LocalSimulatedMarketPolicyError("calendar session state is invalid")

    @property
    def content_hash(self) -> str:
        """Return the canonical digest of exact published calendar evidence."""

        return _canonical_hash(self._content_payload())

    def _content_payload(self) -> dict[str, object]:
        """Build canonical calendar fields before adding the derived digest."""

        return {
            "calendar_id": self.calendar_id,
            "calendar_version": self.calendar_version,
            "calendar_source_hash": self.calendar_source_hash,
            "calendar_observed_at": _utc_text(self.calendar_observed_at),
            "calendar_available_at": _utc_text(self.calendar_available_at),
            "calendar_valid_until": _utc_text(self.calendar_valid_until),
            "trading_date": self.trading_date.isoformat(),
            "session_id": self.session_id,
            "session_timezone": self.session_timezone,
            "session_open_at": _utc_text(self.session_open_at),
            "session_close_at": _utc_text(self.session_close_at),
            "session_state": self.session_state.value,
        }

    def to_payload(self) -> LocalSimulatedCalendarPayload:
        """Return exact published calendar/session provenance."""

        payload = self._content_payload()
        payload["content_hash"] = self.content_hash
        return cast(LocalSimulatedCalendarPayload, payload)


def _require_boundary_identity(policy: LocalSimulatedMarketPolicy) -> None:
    """Require source identity and digest for an explicit boundary rule."""

    _require_token(policy.boundary_rule_source_id, "boundary_rule_source_id")
    _require_token(policy.boundary_rule_version, "boundary_rule_version")
    _require_hash(policy.boundary_rule_source_hash, "boundary_rule_source_hash")


def _require_token(value: object, field_name: str) -> None:
    """Require one bounded, nonempty canonical token without whitespace."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise LocalSimulatedMarketPolicyError(f"{field_name} must be a bounded token")


def _require_display_text(value: object, field_name: str) -> None:
    """Require bounded human-readable policy text without control characters."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(ord(character) < 32 for character in value)
    ):
        raise LocalSimulatedMarketPolicyError(f"{field_name} must be bounded nonempty text")


def _require_hash(value: object, field_name: str) -> None:
    """Require one bare lowercase SHA-256 digest."""

    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise LocalSimulatedMarketPolicyError(f"{field_name} must be SHA-256")


def _require_positive_decimal(value: Decimal | None, field_name: str) -> None:
    """Require an exact finite positive factor with bounded decimal shape."""

    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        raise LocalSimulatedMarketPolicyError(f"{field_name} must be an explicit positive Decimal")
    parts = value.as_tuple()
    if len(parts.digits) > 64 or type(parts.exponent) is not int or abs(parts.exponent) > 64:
        raise LocalSimulatedMarketPolicyError(f"{field_name} exceeds the decimal bound")


def _round_to_tick(value: Fraction, tick: Decimal) -> Decimal:
    """Round a positive exact fraction to the nearest policy tick using HALF_UP."""

    tick_fraction = Fraction(tick)
    if value <= 0 or tick_fraction <= 0:
        raise LocalSimulatedMarketPolicyError("paper boundary and price tick must be positive")
    raw_ticks = value / tick_fraction
    ticks = (2 * raw_ticks.numerator + raw_ticks.denominator) // (2 * raw_ticks.denominator)
    if ticks <= 0:
        raise LocalSimulatedMarketPolicyError("paper boundary rounds to zero")
    tick_parts = tick.as_tuple()
    coefficient = int("".join(str(digit) for digit in tick_parts.digits)) * ticks
    digits = tuple(int(character) for character in str(coefficient))
    return Decimal((0, digits, cast(int, tick_parts.exponent)))


def _decimal_text(value: Decimal | None) -> str | None:
    """Return a finite exact decimal without exponent notation."""

    if value is None:
        return None
    _require_positive_decimal(value, "policy factor")
    return format(value, "f")


def _parse_optional_decimal(value: object) -> Decimal | None:
    """Parse one canonical positive decimal or preserve its explicit absence."""

    if value is None:
        return None
    if type(value) is not str:
        raise LocalSimulatedMarketPolicyError("policy factor must be canonical text")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise LocalSimulatedMarketPolicyError("policy factor is not decimal") from error
    _require_positive_decimal(parsed, "policy factor")
    if format(parsed, "f") != value:
        raise LocalSimulatedMarketPolicyError("policy factor is not canonical")
    return parsed


def _exact_object(payload: object, keys: set[str], field_name: str) -> dict[str, object]:
    """Require one plain JSON object with an exact field allowlist."""

    if type(payload) is not dict or frozenset(payload) != frozenset(keys):
        raise LocalSimulatedMarketPolicyError(f"{field_name} fields are incomplete or unknown")
    return cast(dict[str, object], payload)


def _parse_date(value: object) -> date:
    """Parse one canonical ISO date."""

    if type(value) is not str:
        raise LocalSimulatedMarketPolicyError("policy date is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise LocalSimulatedMarketPolicyError("policy date is invalid") from error
    if parsed.isoformat() != value:
        raise LocalSimulatedMarketPolicyError("policy date is not canonical")
    return parsed


def _parse_time(value: str) -> time:
    """Parse one canonical local session time with whole-second precision."""

    try:
        parsed = time.fromisoformat(value)
    except ValueError as error:
        raise LocalSimulatedMarketPolicyError("session time is invalid") from error
    if parsed.tzinfo is not None or parsed.microsecond or parsed.strftime("%H:%M:%S") != value:
        raise LocalSimulatedMarketPolicyError("session time is not canonical")
    return parsed


def _require_aware(value: object, field_name: str) -> None:
    """Require one aware source/calendar instant."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise LocalSimulatedMarketPolicyError(f"{field_name} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    """Serialize an aware clock as canonical UTC."""

    _require_aware(value, "clock")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    """Return SHA-256 over strict canonical JSON policy fields."""

    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


__all__ = (
    "LocalSimulatedCalendarContext",
    "LocalSimulatedCalendarPayload",
    "LocalSimulatedMarketPolicy",
    "LocalSimulatedMarketPolicyError",
    "LocalSimulatedMarketPolicyPayload",
    "LocalSimulatedSessionWindow",
)
