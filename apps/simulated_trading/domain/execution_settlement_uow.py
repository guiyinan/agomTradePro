"""Exact simulated-ledger contracts for settlement-bound A-share trades.

The calendar values in this module describe complete date-level exchange
sessions. They do not establish an intraday phase, security tradability,
market-price validity, account authority, or broker execution permission.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from enum import StrEnum
from typing import Protocol, cast, runtime_checkable
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class SimulatedSettlementContractError(ValueError):
    """Raised when a simulated-settlement contract is malformed or incomplete."""


class CalendarEvidenceValidationError(SimulatedSettlementContractError):
    """Raised when exact calendar or publication evidence is invalid or unavailable."""


class SimulatedTradeIntentValidationError(SimulatedSettlementContractError):
    """Raised when an exact simulated order intent cannot be represented safely."""


class SimulatedTradeSide(StrEnum):
    """Supported sides for a simulated-ledger order."""

    BUY = "buy"
    SELL = "sell"


class FeeRateStoragePrecision(StrEnum):
    """Explicit precision basis for existing FeeConfig FloatField values."""

    DATABASE_BINARY64 = "database_binary64"


class FeeCalculationPurpose(StrEnum):
    """Name the simulated estimate path so it cannot be mistaken for a fill."""

    NORMAL_SIM_ESTIMATED = "normal_sim_estimated"


class FeeRoundingPolicy(StrEnum):
    """Version the explicit cent-rounding operation used by this calculation."""

    COMPONENT_HALF_EVEN_CENTS_V1 = "component_half_even_cents_v1"


_HASH_LENGTH = 64
_MAX_TOKEN_LENGTH = 192
_MAX_IDEMPOTENCY_LENGTH = 128
_SHARE_QUANTUM = Decimal("0.000001")
_PRICE_QUANTUM = Decimal("0.0001")
_MONEY_QUANTUM = Decimal("0.01")
_MAX_SHARE_VALUE = Decimal("100000000000000")
_MAX_PRICE_VALUE = Decimal("1000000")
_MAX_MONEY_VALUE = Decimal("10000000000000")


def _require_token(value: object, field_name: str, *, max_length: int = _MAX_TOKEN_LENGTH) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > max_length
        or any(character.isspace() for character in value)
    ):
        raise SimulatedSettlementContractError(f"{field_name} must be a bounded canonical token")


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != _HASH_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SimulatedSettlementContractError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_calendar_hash(value: object, field_name: str) -> None:
    """Require the data-center calendar's explicitly prefixed SHA-256 form."""

    if (
        type(value) is not str
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise CalendarEvidenceValidationError(
            f"{field_name} must be a prefixed lowercase SHA-256 digest"
        )


def _require_calendar_fact_hash(value: object, field_name: str) -> None:
    """Require a Data Center canonical row, publication, or policy digest."""

    try:
        _require_hash(value, field_name)
    except SimulatedSettlementContractError as error:
        raise CalendarEvidenceValidationError(str(error)) from error


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None:
        raise SimulatedSettlementContractError(f"{field_name} must be a timezone-aware datetime")
    try:
        if value.utcoffset() is None:
            raise SimulatedSettlementContractError(
                f"{field_name} must be a timezone-aware datetime"
            )
    except (OverflowError, TypeError, ValueError) as error:
        raise SimulatedSettlementContractError(
            f"{field_name} must be a timezone-aware datetime"
        ) from error


def _utc_text(value: datetime) -> str:
    """Return the canonical UTC text for one validated aware datetime."""

    _require_aware(value, "datetime")
    try:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except (OverflowError, TypeError, ValueError) as error:
        raise SimulatedSettlementContractError("datetime cannot be represented in UTC") from error


def _hash_payload(payload: dict[str, object]) -> str:
    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SimulatedSettlementContractError("payload is not canonical JSON") from error
    return hashlib.sha256(encoded).hexdigest()


def _hash_calendar_payload(payload: dict[str, object]) -> str:
    """Match the exact ASCII canonical hash used by the data-center snapshot DTO."""

    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise CalendarEvidenceValidationError(
            "calendar payload is not canonical ASCII JSON"
        ) from error
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _require_utc(value: object, field_name: str) -> None:
    """Require a timezone-aware UTC instant matching the data-center contract."""

    _require_aware(value, field_name)
    assert isinstance(value, datetime)
    try:
        offset = value.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise CalendarEvidenceValidationError(f"{field_name} must be timezone-aware UTC")
    except (OverflowError, TypeError, ValueError) as error:
        raise CalendarEvidenceValidationError(f"{field_name} must be timezone-aware UTC") from error


def _seal_hash(payload: dict[str, object], supplied: object, field_name: str) -> str:
    if type(supplied) is not str:
        raise SimulatedSettlementContractError(f"{field_name} must be a string")
    calculated = _hash_payload(payload)
    if supplied and supplied != calculated:
        raise SimulatedSettlementContractError(f"{field_name} does not match its payload")
    return calculated


def _require_decimal_storage(
    value: object,
    field_name: str,
    *,
    quantum: Decimal,
    exclusive_maximum: Decimal,
    allow_zero: bool = False,
) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise SimulatedTradeIntentValidationError(f"{field_name} must be an exact finite Decimal")
    decimal_parts = value.as_tuple()
    exponent = decimal_parts.exponent
    if not isinstance(exponent, int):
        raise SimulatedTradeIntentValidationError(f"{field_name} must be finite")
    if len(decimal_parts.digits) > 64 or abs(exponent) > 64:
        raise SimulatedTradeIntentValidationError(
            f"{field_name} exceeds the bounded database representation"
        )
    if value < 0 or (value == 0 and not allow_zero):
        raise SimulatedTradeIntentValidationError(f"{field_name} must be positive")
    try:
        with localcontext() as context:
            context.prec = 80
            quantized = value.quantize(quantum)
    except InvalidOperation as error:
        raise SimulatedTradeIntentValidationError(
            f"{field_name} cannot be represented by the ledger column"
        ) from error
    if quantized != value or value >= exclusive_maximum:
        raise SimulatedTradeIntentValidationError(
            f"{field_name} is outside the exact ledger representation"
        )
    return quantized


def _decimal_text(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite():
        raise SimulatedSettlementContractError("canonical decimal must be finite")
    decimal_parts = value.as_tuple()
    exponent = decimal_parts.exponent
    if not isinstance(exponent, int):
        raise SimulatedSettlementContractError("canonical decimal must be finite")
    if len(decimal_parts.digits) > 128 or abs(exponent) > 128:
        raise SimulatedSettlementContractError("canonical decimal exceeds its length bound")
    return format(value, "f")


def _decimal_numeric_text(value: Decimal) -> str:
    """Return a bounded decimal spelling that ignores insignificant scale."""

    if type(value) is not Decimal or not value.is_finite():
        raise SimulatedSettlementContractError("canonical decimal must be finite")
    decimal_parts = value.as_tuple()
    digits = list(decimal_parts.digits)
    exponent = decimal_parts.exponent
    if not isinstance(exponent, int):
        raise SimulatedSettlementContractError("canonical decimal must be finite")
    if len(digits) > 64 or abs(exponent) > 64:
        raise SimulatedSettlementContractError("canonical decimal exceeds its length bound")
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    normalized = Decimal((decimal_parts.sign, tuple(digits), exponent))
    return format(normalized, "f")


def _decimal_from_text(value: object, field_name: str) -> Decimal:
    """Parse one bounded canonical decimal without accepting alternate wire spellings."""

    if type(value) is not str or not value or len(value) > 257:
        raise SimulatedSettlementContractError(
            f"{field_name} must be a bounded canonical decimal string"
        )
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise SimulatedSettlementContractError(
            f"{field_name} must be a canonical decimal string"
        ) from error
    if not parsed.is_finite() or _decimal_text(parsed) != value:
        raise SimulatedSettlementContractError(
            f"{field_name} must use its canonical finite decimal spelling"
        )
    return parsed


def validate_ledger_money(
    value: object,
    field_name: str,
    *,
    allow_zero: bool = True,
) -> Decimal:
    """Validate one value against the ledger's exact cent/money column range."""

    return _require_decimal_storage(
        value,
        field_name,
        quantum=_MONEY_QUANTUM,
        exclusive_maximum=_MAX_MONEY_VALUE,
        allow_zero=allow_zero,
    )


def validate_ledger_quantity(
    value: object,
    field_name: str,
    *,
    allow_zero: bool = True,
) -> Decimal:
    """Validate one value against the ledger's six-decimal share column range."""

    return _require_decimal_storage(
        value,
        field_name,
        quantum=_SHARE_QUANTUM,
        exclusive_maximum=_MAX_SHARE_VALUE,
        allow_zero=allow_zero,
    )


def validate_ledger_price(value: object, field_name: str, *, allow_zero: bool = True) -> Decimal:
    """Validate one value against the ledger's four-decimal price column range."""

    return _require_decimal_storage(
        value,
        field_name,
        quantum=_PRICE_QUANTUM,
        exclusive_maximum=_MAX_PRICE_VALUE,
        allow_zero=allow_zero,
    )


@dataclass(frozen=True, slots=True)
class RawCalendarReference:
    """Exact raw-response identity attached to one parsed calendar snapshot."""

    payload_id: str
    payload_hash: str
    record_digest: str
    body_sha256: str
    retained_content_sha256: str
    request_scope_sha256: str
    original_body_retained: bool
    response_completed_at: datetime
    provider_name: str
    dataset_key: str
    transport: str

    def __post_init__(self) -> None:
        """Validate raw-response identity without treating fetch time as source time."""

        try:
            if str(UUID(self.payload_id)) != self.payload_id:
                raise ValueError
        except (AttributeError, TypeError, ValueError) as error:
            raise CalendarEvidenceValidationError(
                "raw calendar payload_id must be a canonical UUID"
            ) from error
        for field_name in ("provider_name", "dataset_key"):
            _require_token(getattr(self, field_name), field_name)
        for field_name in ("payload_hash", "record_digest"):
            _require_calendar_hash(getattr(self, field_name), field_name)
        for field_name in ("body_sha256", "retained_content_sha256", "request_scope_sha256"):
            _require_hash(getattr(self, field_name), field_name)
        if self.retained_content_sha256 != self.body_sha256:
            raise CalendarEvidenceValidationError(
                "calendar response must retain its exact original body"
            )
        if type(self.original_body_retained) is not bool or not self.original_body_retained:
            raise CalendarEvidenceValidationError(
                "execution calendar requires an exact retained original response body"
            )
        _require_utc(self.response_completed_at, "response_completed_at")
        if self.transport not in {"direct", "egress"}:
            raise CalendarEvidenceValidationError("calendar transport is unsupported")

    def to_payload(self) -> dict[str, object]:
        """Return all raw reference fields in their canonical form."""

        self.__post_init__()
        return {
            "payload_id": self.payload_id,
            "payload_hash": self.payload_hash,
            "record_digest": self.record_digest,
            "body_sha256": self.body_sha256,
            "retained_content_sha256": self.retained_content_sha256,
            "request_scope_sha256": self.request_scope_sha256,
            "original_body_retained": self.original_body_retained,
            "response_completed_at": self.response_completed_at.isoformat(),
            "response_time_semantics": "local_response_body_completion",
            "provider_name": self.provider_name,
            "dataset_key": self.dataset_key,
            "transport": self.transport,
        }


@dataclass(frozen=True, slots=True)
class ExchangeCalendarDay:
    """One explicit open/closed date from a complete exchange calendar snapshot."""

    exchange: str
    calendar_date: date
    is_open: bool
    previous_open_date: date

    def __post_init__(self) -> None:
        """Validate one date fact without deriving it from weekday arithmetic."""

        _require_token(self.exchange, "exchange")
        if type(self.calendar_date) is not date:
            raise CalendarEvidenceValidationError("calendar_date must be an exact date")
        if type(self.is_open) is not bool:
            raise CalendarEvidenceValidationError("is_open must be an explicit boolean fact")
        if type(self.previous_open_date) is not date:
            raise CalendarEvidenceValidationError("previous_open_date must be a date")
        if self.previous_open_date >= self.calendar_date:
            raise CalendarEvidenceValidationError("previous_open_date must precede calendar_date")

    def to_payload(self) -> dict[str, object]:
        """Return the explicit date fact for canonical hashing."""

        self.__post_init__()
        return {
            "exchange": self.exchange,
            "calendar_date": self.calendar_date.isoformat(),
            "is_open": self.is_open,
            "previous_open_date": self.previous_open_date.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ExchangeCalendarSnapshot:
    """Immutable full-day calendar facts and their local knowledge timestamps."""

    snapshot_id: str
    exchange: str
    coverage_start: date
    coverage_end: date
    days: tuple[ExchangeCalendarDay, ...]
    provider_name: str
    raw_reference: RawCalendarReference
    content_hash: str
    record_digest: str
    first_seen_at: datetime
    recorded_at: datetime
    source_published_at: datetime | None = None

    def __post_init__(self) -> None:
        """Revalidate the published candidate's exact hash and DB record digest."""

        try:
            if str(UUID(self.snapshot_id)) != self.snapshot_id:
                raise ValueError
        except (AttributeError, TypeError, ValueError) as error:
            raise CalendarEvidenceValidationError(
                "calendar snapshot_id must be a canonical UUID"
            ) from error
        _require_token(self.exchange, "exchange")
        _require_token(self.provider_name, "provider_name")
        if type(self.coverage_start) is not date or type(self.coverage_end) is not date:
            raise CalendarEvidenceValidationError("calendar coverage bounds must be dates")
        if self.coverage_start > self.coverage_end:
            raise CalendarEvidenceValidationError("calendar coverage range is reversed")
        if type(self.days) is not tuple or not self.days:
            raise CalendarEvidenceValidationError("calendar snapshot requires a nonempty day tuple")
        if any(type(day) is not ExchangeCalendarDay for day in self.days):
            raise CalendarEvidenceValidationError(
                "calendar days must contain exact ExchangeCalendarDay values"
            )
        if type(self.raw_reference) is not RawCalendarReference:
            raise CalendarEvidenceValidationError("raw_reference must be RawCalendarReference")
        RawCalendarReference.__post_init__(self.raw_reference)
        _require_utc(self.first_seen_at, "first_seen_at")
        _require_utc(self.recorded_at, "recorded_at")
        if self.source_published_at is not None:
            _require_utc(self.source_published_at, "source_published_at")
        if self.first_seen_at != self.raw_reference.response_completed_at:
            raise CalendarEvidenceValidationError(
                "first_seen_at must equal the raw response completion time"
            )
        if self.raw_reference.provider_name != self.provider_name:
            raise CalendarEvidenceValidationError(
                "calendar raw provider differs from the snapshot provider"
            )
        if self.recorded_at < self.first_seen_at:
            raise CalendarEvidenceValidationError(
                "calendar recorded_at cannot precede first_seen_at"
            )
        if self.days[0].calendar_date != self.coverage_start:
            raise CalendarEvidenceValidationError(
                "calendar coverage_start must equal the first explicit day"
            )
        if self.days[-1].calendar_date != self.coverage_end:
            raise CalendarEvidenceValidationError(
                "calendar coverage_end must equal the last explicit day"
            )
        previous_day: date | None = None
        last_open_day: date = self.days[0].previous_open_date
        expected_days = (self.coverage_end - self.coverage_start).days + 1
        if len(self.days) != expected_days:
            raise CalendarEvidenceValidationError(
                "calendar snapshot must explicitly cover every requested date"
            )
        for index, day in enumerate(self.days):
            try:
                ExchangeCalendarDay.__post_init__(day)
            except SimulatedSettlementContractError as error:
                raise CalendarEvidenceValidationError(str(error)) from error
            if day.exchange != self.exchange:
                raise CalendarEvidenceValidationError(
                    "calendar day exchange differs from its snapshot scope"
                )
            expected_date = self.coverage_start.fromordinal(self.coverage_start.toordinal() + index)
            if day.calendar_date != expected_date:
                raise CalendarEvidenceValidationError(
                    "calendar snapshot must explicitly cover every date in its range"
                )
            if day.previous_open_date != last_open_day:
                raise CalendarEvidenceValidationError(
                    "previous_open_date does not match the prior explicit open date"
                )
            previous_day = day.calendar_date
            if day.is_open:
                last_open_day = day.calendar_date
        if previous_day != self.coverage_end:
            raise CalendarEvidenceValidationError("calendar coverage_end does not match its days")
        expected_content_hash = _hash_calendar_payload(self._candidate_payload())
        if self.content_hash and self.content_hash != expected_content_hash:
            raise CalendarEvidenceValidationError(
                "calendar content_hash does not match the normalized source content"
            )
        object.__setattr__(self, "content_hash", expected_content_hash)
        expected_record_digest = _hash_calendar_payload(
            {
                "snapshot_id": self.snapshot_id,
                "candidate": self._candidate_payload(),
                "recorded_at": self.recorded_at.isoformat(),
                "content_hash": expected_content_hash,
            }
        )
        if self.record_digest and self.record_digest != expected_record_digest:
            raise CalendarEvidenceValidationError(
                "calendar record_digest does not match its persisted identity"
            )
        object.__setattr__(self, "record_digest", expected_record_digest)

    def _candidate_payload(self) -> dict[str, object]:
        """Return the exact content-only schema used by the calendar owner."""

        return {
            "schema": "exchange-calendar-snapshot-v1",
            "exchange": self.exchange,
            "coverage_start": self.coverage_start.isoformat(),
            "coverage_end": self.coverage_end.isoformat(),
            "days": [day.to_payload() for day in self.days],
            "provider_name": self.provider_name,
            "raw_reference": self.raw_reference.to_payload(),
            "first_seen_at": self.first_seen_at.isoformat(),
            "source_published_at": (
                self.source_published_at.isoformat()
                if self.source_published_at is not None
                else None
            ),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the exact persisted calendar fact and both hashes."""

        self.__post_init__()
        return {
            **self._candidate_payload(),
            "snapshot_id": self.snapshot_id,
            "recorded_at": self.recorded_at.isoformat(),
            "content_hash": self.content_hash,
            "record_digest": self.record_digest,
        }


@dataclass(frozen=True, slots=True)
class CalendarPublicationReference:
    """Explicit publication member, policy, and reference-validity binding."""

    publication_id: str
    member_id: str
    publication_hash: str
    fact_content_hash: str
    policy_hash: str
    published_at: datetime
    recorded_at: datetime
    reference_valid_from: datetime
    reference_valid_until: datetime
    timezone_name: str

    def __post_init__(self) -> None:
        """Validate publication identity, policy window, and exchange timezone."""

        _require_token(self.publication_id, "publication_id")
        _require_token(self.member_id, "member_id")
        _require_calendar_fact_hash(self.publication_hash, "publication_hash")
        _require_calendar_fact_hash(self.fact_content_hash, "fact_content_hash")
        _require_calendar_fact_hash(self.policy_hash, "policy_hash")
        for field_name in (
            "published_at",
            "recorded_at",
            "reference_valid_from",
            "reference_valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        if self.published_at > self.recorded_at:
            raise CalendarEvidenceValidationError(
                "publication recorded_at cannot precede published_at"
            )
        if self.reference_valid_from >= self.reference_valid_until:
            raise CalendarEvidenceValidationError("calendar reference validity window is invalid")
        _require_token(self.timezone_name, "timezone_name")
        try:
            ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as error:
            raise CalendarEvidenceValidationError(
                "calendar publication timezone is unknown"
            ) from error

    def to_payload(self) -> dict[str, object]:
        """Return all publication fields used to bind the calendar evidence."""

        self.__post_init__()
        return {
            "publication_id": self.publication_id,
            "member_id": self.member_id,
            "publication_hash": self.publication_hash,
            "fact_content_hash": self.fact_content_hash,
            "policy_hash": self.policy_hash,
            "published_at": _utc_text(self.published_at),
            "recorded_at": _utc_text(self.recorded_at),
            "reference_valid_from": _utc_text(self.reference_valid_from),
            "reference_valid_until": _utc_text(self.reference_valid_until),
            "timezone_name": self.timezone_name,
        }


@dataclass(frozen=True, slots=True)
class ExecutionCalendarEvidence:
    """Bind a complete calendar snapshot to an exact published reference."""

    snapshot: ExchangeCalendarSnapshot
    publication: CalendarPublicationReference | None

    def __post_init__(self) -> None:
        """Revalidate the snapshot and require exact publication-member binding."""

        if type(self.snapshot) is not ExchangeCalendarSnapshot:
            raise CalendarEvidenceValidationError("snapshot must be ExchangeCalendarSnapshot")
        try:
            ExchangeCalendarSnapshot.__post_init__(self.snapshot)
        except CalendarEvidenceValidationError:
            raise
        except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
            raise CalendarEvidenceValidationError("calendar snapshot failed validation") from error
        if self.publication is not None:
            if type(self.publication) is not CalendarPublicationReference:
                raise CalendarEvidenceValidationError(
                    "publication must be CalendarPublicationReference or None"
                )
            try:
                CalendarPublicationReference.__post_init__(self.publication)
            except CalendarEvidenceValidationError:
                raise
            except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
                raise CalendarEvidenceValidationError(
                    "publication reference failed validation"
                ) from error
            if self.publication.member_id != self.snapshot.snapshot_id:
                raise CalendarEvidenceValidationError(
                    "publication member ID must bind the exact calendar snapshot"
                )

    @property
    def evidence_hash(self) -> str:
        """Return a digest binding snapshot, publication, policy, and knowledge clocks."""

        self.__post_init__()
        return _hash_payload(
            {
                "snapshot": self.snapshot.to_payload(),
                "publication": (
                    self.publication.to_payload() if self.publication is not None else None
                ),
            }
        )

    @property
    def publication_reference(self) -> str:
        """Return the exact publication/member reference persisted on a pending trade."""

        self.__post_init__()
        if self.publication is None:
            raise CalendarEvidenceValidationError(
                "calendar snapshot has no formal publication reference"
            )
        return f"{self.publication.publication_id}/{self.snapshot.snapshot_id}"

    def validate_for(self, as_of: datetime) -> None:
        """Require a known, published, in-window reference at the requested cutoff."""

        self.__post_init__()
        _require_aware(as_of, "as_of")
        publication = self.publication
        if publication is None:
            raise CalendarEvidenceValidationError(
                "reference-only calendar snapshots cannot authorize settlement"
            )
        if (
            self.snapshot.first_seen_at > as_of
            or self.snapshot.recorded_at > as_of
            or publication.published_at > as_of
            or publication.recorded_at > as_of
        ):
            raise CalendarEvidenceValidationError(
                "calendar snapshot or publication was not known at the cutoff"
            )
        for source_time in (self.snapshot.source_published_at,):
            if source_time is not None and source_time > as_of:
                raise CalendarEvidenceValidationError(
                    "calendar source timestamp is later than the knowledge cutoff"
                )
        if not publication.reference_valid_from <= as_of < publication.reference_valid_until:
            raise CalendarEvidenceValidationError(
                "calendar publication reference is outside its validity window"
            )

    def current_open_session(self, as_of: datetime) -> date:
        """Resolve the explicit open session for the cutoff's published exchange timezone."""

        self.validate_for(as_of)
        publication = self.publication
        if publication is None:
            raise CalendarEvidenceValidationError("calendar publication is unavailable")
        try:
            local_date = as_of.astimezone(ZoneInfo(publication.timezone_name)).date()
        except (OverflowError, TypeError, ValueError, ZoneInfoNotFoundError) as error:
            raise CalendarEvidenceValidationError(
                "cutoff cannot be mapped to the published exchange timezone"
            ) from error
        day = next(
            (row for row in self.snapshot.days if row.calendar_date == local_date),
            None,
        )
        if day is None:
            raise CalendarEvidenceValidationError(
                "calendar snapshot does not cover the cutoff's exchange-local date"
            )
        if not day.is_open:
            raise CalendarEvidenceValidationError(
                "settlement-bound simulated trades require an explicit open session"
            )
        return local_date

    def release_session(self, trade_session: date, lag_sessions: int) -> date:
        """Advance by an explicit number of open sessions without weekday inference."""

        self.__post_init__()
        if type(trade_session) is not date:
            raise CalendarEvidenceValidationError("trade_session must be an exact date")
        if type(lag_sessions) is not int or lag_sessions < 0:
            raise CalendarEvidenceValidationError(
                "lag_sessions must be an explicit nonnegative integer"
            )
        dates = {row.calendar_date: row for row in self.snapshot.days}
        trade_day = dates.get(trade_session)
        if trade_day is None or not trade_day.is_open:
            raise CalendarEvidenceValidationError(
                "settlement trade date is not an explicitly open covered session"
            )
        if lag_sessions == 0:
            return trade_session
        elapsed = 0
        for row in self.snapshot.days:
            if row.calendar_date <= trade_session or not row.is_open:
                continue
            elapsed += 1
            if elapsed == lag_sessions:
                return row.calendar_date
        raise CalendarEvidenceValidationError(
            "calendar snapshot does not cover enough future open sessions"
        )

    def elapsed_open_sessions(self, trade_session: date, through_session: date) -> int:
        """Count actual current-calendar open sessions after the stored trade date."""

        self.__post_init__()
        if type(trade_session) is not date or type(through_session) is not date:
            raise CalendarEvidenceValidationError("settlement boundaries must be exact dates")
        if trade_session > through_session:
            raise CalendarEvidenceValidationError("settlement through-date precedes trade date")
        if (
            trade_session < self.snapshot.coverage_start
            or through_session > self.snapshot.coverage_end
        ):
            raise CalendarEvidenceValidationError(
                "current calendar does not cover the complete settlement interval"
            )
        days = {row.calendar_date: row for row in self.snapshot.days}
        trade_day = days.get(trade_session)
        through_day = days.get(through_session)
        if trade_day is None or not trade_day.is_open:
            raise CalendarEvidenceValidationError(
                "stored trade date is not an explicitly open calendar session"
            )
        if through_day is None or not through_day.is_open:
            raise CalendarEvidenceValidationError(
                "current date is not an explicitly open calendar session"
            )
        return sum(
            1
            for row in self.snapshot.days
            if trade_session < row.calendar_date <= through_session and row.is_open
        )


@dataclass(frozen=True, slots=True)
class SimulatedTradeIntent:
    """Exact caller intent to apply to a simulated account's local ledger."""

    account_id: int
    user_id: int
    idempotency_key: str
    side: SimulatedTradeSide
    security_id: str
    asset_code: str
    asset_name: str
    asset_type: str
    market: str
    board: str
    quantity: Decimal
    price: Decimal
    reason: str
    signal_id: int | None

    def __post_init__(self) -> None:
        """Validate stable identity and exact values before any I/O."""

        if type(self.account_id) is not int or self.account_id <= 0:
            raise SimulatedTradeIntentValidationError("account_id must be a positive integer")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise SimulatedTradeIntentValidationError("user_id must be a positive integer")
        _require_token(
            self.idempotency_key,
            "idempotency_key",
            max_length=_MAX_IDEMPOTENCY_LENGTH,
        )
        if type(self.side) is not SimulatedTradeSide:
            raise SimulatedTradeIntentValidationError("side must be a recognized trade side")
        for field_name in (
            "security_id",
            "asset_code",
            "asset_type",
            "market",
            "board",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.asset_name) is not str or not self.asset_name or len(self.asset_name) > 100:
            raise SimulatedTradeIntentValidationError(
                "asset_name must be nonempty text of at most 100 chars"
            )
        _require_decimal_storage(
            self.quantity,
            "quantity",
            quantum=_SHARE_QUANTUM,
            exclusive_maximum=_MAX_SHARE_VALUE,
        )
        _require_decimal_storage(
            self.price,
            "price",
            quantum=_PRICE_QUANTUM,
            exclusive_maximum=_MAX_PRICE_VALUE,
        )
        if type(self.reason) is not str or len(self.reason) > 200:
            raise SimulatedTradeIntentValidationError("reason must be text of at most 200 chars")
        if self.signal_id is not None and type(self.signal_id) is not int:
            raise SimulatedTradeIntentValidationError("signal_id must be an integer or None")

    @property
    def request_payload_hash(self) -> str:
        """Return a deterministic hash of all intent fields except the idempotency key."""

        self.__post_init__()
        return _hash_payload(
            {
                "account_id": self.account_id,
                "user_id": self.user_id,
                "side": self.side.value,
                "security_id": self.security_id,
                "asset_code": self.asset_code,
                "asset_name": self.asset_name,
                "asset_type": self.asset_type,
                "market": self.market,
                "board": self.board,
                "quantity": _decimal_numeric_text(self.quantity),
                "price": _decimal_numeric_text(self.price),
                "reason": self.reason,
                "signal_id": self.signal_id,
            }
        )


@runtime_checkable
class SimulatedFeePolicyContract(Protocol):
    """Runtime-checkable V2 fee snapshot boundary used by the execution plan."""

    @property
    def fee_schedule_v1(self) -> ExecutionFeeSchedule:
        """Return the immutable V1 numeric schedule nested in this snapshot."""

    @property
    def content_hash(self) -> str:
        """Return the canonical hash of the complete V2 policy snapshot."""

    def __post_init__(self) -> None:
        """Revalidate the complete exact policy snapshot."""

    def validate_at(self, as_of: datetime) -> None:
        """Require recorded and effective policy clocks at one instant."""

    def to_payload(self) -> dict[str, object]:
        """Return the complete immutable V2 snapshot payload."""

    def calculate_for(
        self,
        *,
        asset_type: str,
        market: str,
        board: str,
        side: SimulatedTradeSide,
        amount: Decimal,
        as_of: datetime,
    ) -> TradeFeeBreakdown:
        """Calculate exact fee components for one transaction case."""


@dataclass(frozen=True, slots=True)
class SettlementExecutionPlan:
    """Bind an exact intent to one V3 bundle and one published calendar reference."""

    intent: SimulatedTradeIntent
    market_session: date
    pre_read_at: datetime
    settlement_lag_sessions: int
    settlement_release_date: date | None
    settlement_bundle_id: str
    settlement_bundle_version: str
    settlement_bundle_hash: str
    settlement_policy_id: str
    settlement_policy_version: str
    settlement_policy_hash: str
    execution_rule_v2_hash: str
    bundle_source_observed_at: datetime
    bundle_source_available_at: datetime
    bundle_effective_from: datetime
    bundle_valid_until: datetime
    calendar_evidence: ExecutionCalendarEvidence
    fee_policy_v2: SimulatedFeePolicyContract

    @property
    def _expected_calendar_exchange(self) -> str:
        """Return the exchange required by this plan's versioned identity contract."""

        return self.intent.market

    def __post_init__(self) -> None:
        """Validate settlement scope, source clocks, and the computed release session."""

        if type(self.intent) is not SimulatedTradeIntent:
            raise SimulatedTradeIntentValidationError("intent must be SimulatedTradeIntent")
        try:
            SimulatedTradeIntent.__post_init__(self.intent)
        except SimulatedTradeIntentValidationError:
            raise
        except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeIntentValidationError("intent failed revalidation") from error
        if type(self.market_session) is not date:
            raise SimulatedSettlementContractError("market_session must be an exact date")
        _require_aware(self.pre_read_at, "pre_read_at")
        if type(self.settlement_lag_sessions) is not int or self.settlement_lag_sessions < 0:
            raise SimulatedSettlementContractError(
                "settlement_lag_sessions must be an explicit nonnegative integer"
            )
        for field_name in (
            "settlement_bundle_id",
            "settlement_bundle_version",
            "settlement_policy_id",
            "settlement_policy_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        for field_name in (
            "settlement_bundle_hash",
            "settlement_policy_hash",
            "execution_rule_v2_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)
        for field_name in (
            "bundle_source_observed_at",
            "bundle_source_available_at",
            "bundle_effective_from",
            "bundle_valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        if not (
            self.bundle_source_observed_at <= self.bundle_source_available_at
            and self.bundle_source_available_at < self.bundle_valid_until
            and self.bundle_effective_from < self.bundle_valid_until
        ):
            raise SimulatedSettlementContractError("settlement bundle time window is invalid")
        if type(self.calendar_evidence) is not ExecutionCalendarEvidence:
            raise CalendarEvidenceValidationError(
                "calendar_evidence must be ExecutionCalendarEvidence"
            )
        self.calendar_evidence.__post_init__()
        if not isinstance(self.fee_policy_v2, SimulatedFeePolicyContract):
            raise SimulatedSettlementContractError(
                "fee_policy_v2 must implement the exact fee-policy contract"
            )
        self.fee_policy_v2.__post_init__()
        if type(self.fee_policy_v2.fee_schedule_v1) is not ExecutionFeeSchedule:
            raise SimulatedSettlementContractError("fee policy has no exact V1 numeric schedule")
        self.fee_policy_v2.fee_schedule_v1.__post_init__()
        if self.calendar_evidence.snapshot.exchange != self._expected_calendar_exchange:
            raise CalendarEvidenceValidationError(
                "calendar exchange differs from the order market scope"
            )
        try:
            self.calendar_evidence.validate_for(self.pre_read_at)
            if self.calendar_evidence.current_open_session(self.pre_read_at) != self.market_session:
                raise CalendarEvidenceValidationError(
                    "market_session differs from the pre-lock calendar cutoff"
                )
        except CalendarEvidenceValidationError:
            raise
        except (ArithmeticError, TypeError, ValueError) as error:
            raise CalendarEvidenceValidationError(
                "calendar is not valid at the pre-lock evidence cutoff"
            ) from error
        if not (
            self.bundle_source_observed_at <= self.pre_read_at
            and self.bundle_source_available_at <= self.pre_read_at
            and self.bundle_effective_from <= self.pre_read_at < self.bundle_valid_until
        ):
            raise SimulatedSettlementContractError(
                "settlement bundle was not valid at the pre-lock evidence cutoff"
            )
        if self.intent.side is SimulatedTradeSide.BUY:
            if type(self.settlement_release_date) is not date:
                raise SimulatedSettlementContractError(
                    "BUY intent requires a source-derived settlement release date"
                )
            expected_release = self.calendar_evidence.release_session(
                self.market_session,
                self.settlement_lag_sessions,
            )
            if self.settlement_release_date != expected_release:
                raise SimulatedSettlementContractError(
                    "settlement release date differs from explicit calendar advancement"
                )
        elif self.settlement_release_date is not None:
            raise SimulatedSettlementContractError(
                "SELL intent cannot create a pending buy-settlement date"
            )

    @property
    def settlement_calendar_reference(self) -> str:
        """Return the exact formal calendar publication/member reference."""

        return self.calendar_evidence.publication_reference

    @property
    def settlement_calendar_evidence_hash(self) -> str:
        """Return the digest over the exact calendar snapshot and publication binding."""

        return self.calendar_evidence.evidence_hash

    @property
    def amount(self) -> Decimal:
        """Return the ledger-cent amount under the explicit V1 fee rounding policy."""

        self.__post_init__()
        try:
            with localcontext() as context:
                context.prec = 80
                value = (self.intent.quantity * self.intent.price).quantize(
                    _MONEY_QUANTUM,
                    rounding=ROUND_HALF_EVEN,
                )
        except (InvalidOperation, OverflowError) as error:
            raise SimulatedTradeIntentValidationError(
                "trade amount cannot be represented at ledger precision"
            ) from error
        return _require_decimal_storage(
            value,
            "amount",
            quantum=_MONEY_QUANTUM,
            exclusive_maximum=_MAX_MONEY_VALUE,
        )

    @property
    def fee_breakdown(self) -> TradeFeeBreakdown:
        """Return the explicit estimated fee components for this exact intent."""

        self.__post_init__()
        return self.fee_policy_v2.calculate_for(
            asset_type=self.intent.asset_type,
            market=self.intent.market,
            board=self.intent.board,
            side=self.intent.side,
            amount=self.amount,
            as_of=self.pre_read_at,
        )

    def validate_at(self, as_of: datetime) -> None:
        """Revalidate immutable evidence after the repository has acquired row locks."""

        self.__post_init__()
        _require_aware(as_of, "as_of")
        if as_of < self.pre_read_at:
            raise SimulatedSettlementContractError(
                "locked execution clock cannot precede the pre-lock evidence cutoff"
            )
        self.calendar_evidence.validate_for(as_of)
        self.fee_policy_v2.validate_at(as_of)
        if not (
            self.bundle_source_observed_at <= as_of
            and self.bundle_source_available_at <= as_of
            and self.bundle_effective_from <= as_of < self.bundle_valid_until
        ):
            raise SimulatedSettlementContractError(
                "settlement bundle is unavailable or outside its window after row locking"
            )
        if self.calendar_evidence.current_open_session(as_of) != self.market_session:
            raise CalendarEvidenceValidationError(
                "exchange-local session changed while the order waited for row locks"
            )


@dataclass(frozen=True, slots=True)
class ExecutionFeeSchedule:
    """Explicit database-backed fee terms, including their stored precision basis."""

    config_id: int
    asset_type: str
    commission_rate_buy: Decimal
    commission_rate_sell: Decimal
    min_commission: Decimal
    stamp_duty_rate: Decimal
    transfer_fee_rate: Decimal
    min_transfer_fee: Decimal
    slippage_rate: Decimal
    precision_basis: FeeRateStoragePrecision
    calculation_purpose: FeeCalculationPurpose
    rounding_policy: FeeRoundingPolicy
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Reject missing or nonfinite persisted fee terms without adding defaults."""

        if type(self.config_id) is not int or self.config_id <= 0:
            raise SimulatedSettlementContractError("config_id must be a positive integer")
        _require_token(self.asset_type, "asset_type")
        if type(self.precision_basis) is not FeeRateStoragePrecision:
            raise SimulatedSettlementContractError("fee precision basis must be explicit")
        if type(self.calculation_purpose) is not FeeCalculationPurpose:
            raise SimulatedSettlementContractError("fee calculation purpose must be explicit")
        if type(self.rounding_policy) is not FeeRoundingPolicy:
            raise SimulatedSettlementContractError("fee rounding policy must be explicit")
        if self.asset_type not in {"equity", "fund", "bond", "all"}:
            raise SimulatedSettlementContractError("fee asset_type is unsupported")
        for field_name in (
            "commission_rate_buy",
            "commission_rate_sell",
            "min_commission",
            "stamp_duty_rate",
            "transfer_fee_rate",
            "min_transfer_fee",
            "slippage_rate",
        ):
            value = getattr(self, field_name)
            decimal_exponent = value.as_tuple().exponent if type(value) is Decimal else None
            if (
                type(value) is not Decimal
                or not value.is_finite()
                or value < 0
                or len(value.as_tuple().digits) > 128
                or not isinstance(decimal_exponent, int)
                or abs(decimal_exponent) > 128
            ):
                raise SimulatedSettlementContractError(
                    f"{field_name} must be a bounded nonnegative exact Decimal"
                )
            if field_name.endswith("_rate") and value > Decimal("1"):
                raise SimulatedSettlementContractError(
                    f"{field_name} cannot exceed the persisted FeeConfig range"
                )
        payload = self._content_payload()
        object.__setattr__(
            self,
            "content_hash",
            _seal_hash(payload, self.content_hash, "fee_schedule.content_hash"),
        )

    def _content_payload(self) -> dict[str, object]:
        return {
            "config_id": self.config_id,
            "asset_type": self.asset_type,
            "commission_rate_buy": _decimal_text(self.commission_rate_buy),
            "commission_rate_sell": _decimal_text(self.commission_rate_sell),
            "min_commission": _decimal_text(self.min_commission),
            "stamp_duty_rate": _decimal_text(self.stamp_duty_rate),
            "transfer_fee_rate": _decimal_text(self.transfer_fee_rate),
            "min_transfer_fee": _decimal_text(self.min_transfer_fee),
            "slippage_rate": _decimal_text(self.slippage_rate),
            "precision_basis": self.precision_basis.value,
            "calculation_purpose": self.calculation_purpose.value,
            "rounding_policy": self.rounding_policy.value,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete immutable fee snapshot used for the trade."""

        self.__post_init__()
        return {**self._content_payload(), "content_hash": self.content_hash}

    @classmethod
    def from_payload(cls, payload: object) -> ExecutionFeeSchedule:
        """Rebuild and revalidate one persisted exact fee snapshot."""

        expected_keys = {
            "config_id",
            "asset_type",
            "commission_rate_buy",
            "commission_rate_sell",
            "min_commission",
            "stamp_duty_rate",
            "transfer_fee_rate",
            "min_transfer_fee",
            "slippage_rate",
            "precision_basis",
            "calculation_purpose",
            "rounding_policy",
            "content_hash",
        }
        if type(payload) is not dict:
            raise SimulatedSettlementContractError("fee snapshot must be an object")
        fields = cast(dict[str, object], payload)
        if set(fields) != expected_keys:
            raise SimulatedSettlementContractError("fee snapshot fields are incomplete or unknown")
        if type(fields["config_id"]) is not int or type(fields["asset_type"]) is not str:
            raise SimulatedSettlementContractError("fee snapshot identity fields are invalid")
        if any(
            type(fields[name]) is not str
            for name in (
                "precision_basis",
                "calculation_purpose",
                "rounding_policy",
                "content_hash",
            )
        ):
            raise SimulatedSettlementContractError("fee snapshot policy fields are invalid")
        try:
            return cls(
                config_id=fields["config_id"],
                asset_type=fields["asset_type"],
                commission_rate_buy=_decimal_from_text(
                    fields["commission_rate_buy"], "commission_rate_buy"
                ),
                commission_rate_sell=_decimal_from_text(
                    fields["commission_rate_sell"], "commission_rate_sell"
                ),
                min_commission=_decimal_from_text(fields["min_commission"], "min_commission"),
                stamp_duty_rate=_decimal_from_text(fields["stamp_duty_rate"], "stamp_duty_rate"),
                transfer_fee_rate=_decimal_from_text(
                    fields["transfer_fee_rate"], "transfer_fee_rate"
                ),
                min_transfer_fee=_decimal_from_text(fields["min_transfer_fee"], "min_transfer_fee"),
                slippage_rate=_decimal_from_text(fields["slippage_rate"], "slippage_rate"),
                precision_basis=FeeRateStoragePrecision(cast(str, fields["precision_basis"])),
                calculation_purpose=FeeCalculationPurpose(cast(str, fields["calculation_purpose"])),
                rounding_policy=FeeRoundingPolicy(cast(str, fields["rounding_policy"])),
                content_hash=cast(str, fields["content_hash"]),
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, SimulatedSettlementContractError):
                raise
            raise SimulatedSettlementContractError("fee snapshot fields are invalid") from error


@dataclass(frozen=True, slots=True)
class TradeFeeBreakdown:
    """Rounded fee components calculated from one explicit stored fee schedule."""

    commission: Decimal
    transfer_fee: Decimal
    stamp_duty: Decimal
    slippage: Decimal
    total_fee: Decimal


def calculate_trade_fees(
    schedule: ExecutionFeeSchedule,
    *,
    side: SimulatedTradeSide,
    amount: Decimal,
    market: str,
) -> TradeFeeBreakdown:
    """Apply exact stored-rate formulas and sum individually rounded fee components.

    FloatField values use their exact binary64 value. Fees are calculated solely
    for normal simulated orders; imported actual execution facts never use this
    estimate path.
    """

    if type(schedule) is not ExecutionFeeSchedule:
        raise SimulatedSettlementContractError("schedule must be ExecutionFeeSchedule")
    schedule.__post_init__()
    if type(side) is not SimulatedTradeSide:
        raise SimulatedSettlementContractError("side must be a recognized trade side")
    _require_token(market, "market")
    _require_decimal_storage(
        amount,
        "amount",
        quantum=_MONEY_QUANTUM,
        exclusive_maximum=_MAX_MONEY_VALUE,
    )
    try:
        with localcontext() as context:
            context.prec = 160
            if side is SimulatedTradeSide.BUY:
                commission = max(
                    amount * schedule.commission_rate_buy,
                    schedule.min_commission,
                )
                stamp_duty = Decimal("0")
            else:
                commission = max(
                    amount * schedule.commission_rate_sell,
                    schedule.min_commission,
                )
                stamp_duty = (
                    amount * schedule.stamp_duty_rate
                    if schedule.asset_type == "equity"
                    else Decimal("0")
                )
            transfer_fee = Decimal("0")
            if market == "SH" and schedule.asset_type == "equity":
                transfer_fee = max(
                    amount * schedule.transfer_fee_rate,
                    schedule.min_transfer_fee,
                )
            slippage = amount * schedule.slippage_rate
            rounded_commission = commission.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
            rounded_transfer = transfer_fee.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
            rounded_stamp = stamp_duty.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
            rounded_slippage = slippage.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
            total_fee = rounded_commission + rounded_transfer + rounded_stamp + rounded_slippage
    except (InvalidOperation, OverflowError) as error:
        raise SimulatedSettlementContractError(
            "configured fee values cannot be represented at ledger precision"
        ) from error
    return TradeFeeBreakdown(
        commission=rounded_commission,
        transfer_fee=rounded_transfer,
        stamp_duty=rounded_stamp,
        slippage=rounded_slippage,
        total_fee=total_fee,
    )


@dataclass(frozen=True, slots=True)
class SimulatedTradeExecutionReceipt:
    """Exact persisted result returned by the settlement-bound ledger UoW."""

    trade_id: int
    account_id: int
    idempotency_key: str
    request_payload_hash: str
    side: SimulatedTradeSide
    asset_code: str
    quantity: Decimal
    price: Decimal
    amount: Decimal
    commission: Decimal
    transfer_fee: Decimal
    stamp_duty: Decimal
    slippage: Decimal
    total_cost: Decimal
    settlement_status: str | None
    settlement_release_date: date | None
    replayed: bool

    def __post_init__(self) -> None:
        """Validate the exact saved result and its optional settlement relation."""

        if type(self.trade_id) is not int or self.trade_id <= 0:
            raise SimulatedSettlementContractError("trade_id must be positive")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise SimulatedSettlementContractError("account_id must be positive")
        _require_token(self.idempotency_key, "idempotency_key", max_length=_MAX_IDEMPOTENCY_LENGTH)
        _require_hash(self.request_payload_hash, "request_payload_hash")
        if type(self.side) is not SimulatedTradeSide:
            raise SimulatedSettlementContractError("receipt side is invalid")
        _require_token(self.asset_code, "asset_code")
        for field_name, value, quantum, maximum in (
            ("quantity", self.quantity, _SHARE_QUANTUM, _MAX_SHARE_VALUE),
            ("price", self.price, _PRICE_QUANTUM, _MAX_PRICE_VALUE),
            ("amount", self.amount, _MONEY_QUANTUM, _MAX_MONEY_VALUE),
            ("commission", self.commission, _MONEY_QUANTUM, _MAX_MONEY_VALUE),
            ("transfer_fee", self.transfer_fee, _MONEY_QUANTUM, _MAX_MONEY_VALUE),
            ("stamp_duty", self.stamp_duty, _MONEY_QUANTUM, _MAX_MONEY_VALUE),
            ("slippage", self.slippage, _MONEY_QUANTUM, _MAX_MONEY_VALUE),
            ("total_cost", self.total_cost, _MONEY_QUANTUM, _MAX_MONEY_VALUE),
        ):
            _require_decimal_storage(
                value,
                field_name,
                quantum=quantum,
                exclusive_maximum=maximum,
                allow_zero=field_name
                in {
                    "commission",
                    "transfer_fee",
                    "stamp_duty",
                    "slippage",
                    "total_cost",
                },
            )
        if self.side is SimulatedTradeSide.BUY:
            if self.settlement_status not in {"pending", "released"}:
                raise SimulatedSettlementContractError("BUY receipt requires settlement status")
            if type(self.settlement_release_date) is not date:
                raise SimulatedSettlementContractError("BUY receipt requires a release date")
            expected_total_cost = (
                self.amount + self.commission + self.transfer_fee + self.stamp_duty + self.slippage
            )
        elif self.settlement_status is not None or self.settlement_release_date is not None:
            raise SimulatedSettlementContractError("SELL receipt cannot carry buy settlement state")
        else:
            expected_total_cost = (
                self.commission + self.transfer_fee + self.stamp_duty + self.slippage
            )
        if self.total_cost != expected_total_cost:
            raise SimulatedSettlementContractError(
                "receipt total_cost must reconcile to its stored fee components"
            )
        if type(self.replayed) is not bool:
            raise SimulatedSettlementContractError("replayed must be a boolean")


__all__: tuple[str, ...] = (
    "CalendarEvidenceValidationError",
    "CalendarPublicationReference",
    "ExecutionCalendarEvidence",
    "ExecutionFeeSchedule",
    "FeeCalculationPurpose",
    "FeeRoundingPolicy",
    "ExchangeCalendarDay",
    "ExchangeCalendarSnapshot",
    "FeeRateStoragePrecision",
    "RawCalendarReference",
    "SettlementExecutionPlan",
    "SimulatedFeePolicyContract",
    "SimulatedSettlementContractError",
    "SimulatedTradeExecutionReceipt",
    "SimulatedTradeIntent",
    "SimulatedTradeIntentValidationError",
    "SimulatedTradeSide",
    "TradeFeeBreakdown",
    "calculate_trade_fees",
    "validate_ledger_money",
    "validate_ledger_price",
    "validate_ledger_quantity",
)
