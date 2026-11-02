"""Close-snapshot policy contract and canonical payload validation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TypedDict, cast
from zoneinfo import ZoneInfo

from apps.data_center.domain.sina_quote_capture import (
    SINA_QUOTE_SOURCE_ID,
    SINA_VENDOR_STATUS_MAPPING_SHA256,
)
from apps.risk_center.domain.execution_trading_constraints import PriceBoundaryMode

_POLICY_SCHEMA = "close-snapshot-simulation-policy.v1"

_PURPOSE = "close_snapshot_simulation"

_PRICE_RULE = "exact_vendor_last_after_close.v1"

_SHANGHAI = ZoneInfo("Asia/Shanghai")

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

_MAX_DECIMAL_DIGITS = 64

_MAX_DECIMAL_EXPONENT = 64


class CloseSnapshotSimulationValidationError(ValueError):
    """Raised when a close-snapshot policy or evidence payload is malformed."""


class CloseSnapshotSimulationPolicyPayload(TypedDict):
    """Exact canonical wire shape for a close-only policy."""

    schema: str
    purpose: str
    policy_id: str
    policy_version: str
    account_id: int
    security_id: str
    asset_code: str
    market: str
    board: str
    trading_date: str
    source_id: str
    source_name: str
    usage_ttl_seconds: int
    status_mapping_sha256: str
    trusted_vendor_status_codes: list[str]
    available_from: str
    available_until: str
    price_rule: str
    price_rule_source_hash: str
    price_boundary_mode: str
    lower_boundary_factor: str | None
    upper_boundary_factor: str | None
    boundary_rule_source_id: str
    boundary_rule_version: str
    boundary_rule_source_hash: str
    unrestricted_reason_code: str | None
    content_hash: str


@dataclass(frozen=True, slots=True)
class CloseSnapshotSimulationPolicy:
    """Bind one account, security, trading date, source, and close-only price rule.

    This policy authorizes use only in a local close-snapshot simulation. It
    does not declare Sina's last quote to be an official closing price or grant
    intraday, live-trading, or broker-execution eligibility.
    """

    policy_id: str
    policy_version: str
    account_id: int
    security_id: str
    asset_code: str
    market: str
    board: str
    trading_date: date
    source_id: str
    source_name: str
    usage_ttl_seconds: int
    status_mapping_sha256: str
    trusted_vendor_status_codes: tuple[str, ...]
    available_from: datetime
    available_until: datetime
    price_rule: str
    price_rule_source_hash: str
    price_boundary_mode: PriceBoundaryMode
    lower_boundary_factor: Decimal | None
    upper_boundary_factor: Decimal | None
    boundary_rule_source_id: str
    boundary_rule_version: str
    boundary_rule_source_hash: str
    unrestricted_reason_code: str | None
    purpose: str = _PURPOSE
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate exact scope, clocks, trusted mapping, and explicit bounds."""

        if self.purpose != _PURPOSE:
            raise CloseSnapshotSimulationValidationError("policy purpose is not close-only")
        for name in (
            "policy_id",
            "policy_version",
            "security_id",
            "asset_code",
            "market",
            "board",
            "source_id",
            "boundary_rule_source_id",
            "boundary_rule_version",
        ):
            _token(getattr(self, name), name)
        if not _is_positive_int(self.account_id):
            raise CloseSnapshotSimulationValidationError("account_id must be positive")
        if type(self.trading_date) is not date:
            raise CloseSnapshotSimulationValidationError("trading_date must be an exact date")
        if (
            type(self.source_name) is not str
            or not self.source_name.strip()
            or len(self.source_name) > 192
            or any(ord(character) < 32 for character in self.source_name)
        ):
            raise CloseSnapshotSimulationValidationError("source_name is required")
        if (
            type(self.usage_ttl_seconds) is not int
            or self.usage_ttl_seconds <= 0
            or self.usage_ttl_seconds >= 86_400
        ):
            raise CloseSnapshotSimulationValidationError(
                "usage TTL must be positive and shorter than the policy day"
            )
        _digest(self.status_mapping_sha256, "status_mapping_sha256")
        _digest(self.price_rule_source_hash, "price_rule_source_hash")
        _digest(self.boundary_rule_source_hash, "boundary_rule_source_hash")
        if self.source_id != SINA_QUOTE_SOURCE_ID:
            raise CloseSnapshotSimulationValidationError(
                "only the captured Sina source is supported"
            )
        if self.status_mapping_sha256 != SINA_VENDOR_STATUS_MAPPING_SHA256:
            raise CloseSnapshotSimulationValidationError("vendor status mapping hash differs")
        if (
            type(self.trusted_vendor_status_codes) is not tuple
            or not self.trusted_vendor_status_codes
            or len(set(self.trusted_vendor_status_codes)) != len(self.trusted_vendor_status_codes)
        ):
            raise CloseSnapshotSimulationValidationError("trusted status codes must be explicit")
        for code in self.trusted_vendor_status_codes:
            _token(code, "trusted vendor status code")
        _aware(self.available_from, "available_from")
        _aware(self.available_until, "available_until")
        if self.available_from >= self.available_until:
            raise CloseSnapshotSimulationValidationError("policy availability window is empty")
        if (
            self.available_from.astimezone(_SHANGHAI).date() != self.trading_date
            or self.available_until.astimezone(_SHANGHAI).date() != self.trading_date
        ):
            raise CloseSnapshotSimulationValidationError(
                "policy availability must be bounded to its trading date"
            )
        if self.price_rule != _PRICE_RULE:
            raise CloseSnapshotSimulationValidationError("unsupported close snapshot price rule")
        if self.price_boundary_mode is PriceBoundaryMode.UNKNOWN:
            raise CloseSnapshotSimulationValidationError("unknown price boundary cannot qualify")
        if self.price_boundary_mode is PriceBoundaryMode.LIMITED:
            lower_factor = _positive_decimal(self.lower_boundary_factor, "lower_boundary_factor")
            upper_factor = _positive_decimal(self.upper_boundary_factor, "upper_boundary_factor")
            if lower_factor >= upper_factor:
                raise CloseSnapshotSimulationValidationError("paper boundary factors are reversed")
            if self.unrestricted_reason_code is not None:
                raise CloseSnapshotSimulationValidationError(
                    "limited boundary cannot carry unrestricted reason"
                )
        elif self.price_boundary_mode is PriceBoundaryMode.UNRESTRICTED:
            if self.lower_boundary_factor is not None or self.upper_boundary_factor is not None:
                raise CloseSnapshotSimulationValidationError(
                    "unrestricted boundary cannot carry factors"
                )
            _token(self.unrestricted_reason_code, "unrestricted_reason_code")
        else:
            raise CloseSnapshotSimulationValidationError("price boundary mode is invalid")
        object.__setattr__(
            self, "content_hash", _seal_hash(self._content_payload(), self.content_hash)
        )

    def _content_payload(self) -> dict[str, object]:
        """Build the exact policy content that is covered by its hash."""

        return {
            "schema": _POLICY_SCHEMA,
            "purpose": self.purpose,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "account_id": self.account_id,
            "security_id": self.security_id,
            "asset_code": self.asset_code,
            "market": self.market,
            "board": self.board,
            "trading_date": self.trading_date.isoformat(),
            "source_id": self.source_id,
            "source_name": self.source_name,
            "usage_ttl_seconds": self.usage_ttl_seconds,
            "status_mapping_sha256": self.status_mapping_sha256,
            "trusted_vendor_status_codes": list(self.trusted_vendor_status_codes),
            "available_from": _utc_text(self.available_from),
            "available_until": _utc_text(self.available_until),
            "price_rule": self.price_rule,
            "price_rule_source_hash": self.price_rule_source_hash,
            "price_boundary_mode": self.price_boundary_mode.value,
            "lower_boundary_factor": _decimal_text(self.lower_boundary_factor),
            "upper_boundary_factor": _decimal_text(self.upper_boundary_factor),
            "boundary_rule_source_id": self.boundary_rule_source_id,
            "boundary_rule_version": self.boundary_rule_version,
            "boundary_rule_source_hash": self.boundary_rule_source_hash,
            "unrestricted_reason_code": self.unrestricted_reason_code,
        }

    def to_payload(self) -> CloseSnapshotSimulationPolicyPayload:
        """Return strict JSON-safe policy fields and the canonical content hash."""

        self.__post_init__()
        return cast(
            CloseSnapshotSimulationPolicyPayload,
            {**self._content_payload(), "content_hash": self.content_hash},
        )

    @classmethod
    def from_payload(cls, payload: object) -> CloseSnapshotSimulationPolicy:
        """Rebuild an exact policy payload and reject unknown or changed fields."""

        if type(payload) is not dict:
            raise CloseSnapshotSimulationValidationError("policy must be a plain object")
        payload_keys = frozenset(payload)
        if payload_keys not in (_POLICY_KEYS, _POLICY_KEYS - {"content_hash"}):
            raise CloseSnapshotSimulationValidationError("policy fields are incomplete or unknown")
        values = cast(dict[str, object], payload)
        if values["schema"] != _POLICY_SCHEMA or values["purpose"] != _PURPOSE:
            raise CloseSnapshotSimulationValidationError("policy schema or purpose is invalid")
        codes = values["trusted_vendor_status_codes"]
        if type(codes) is not list or any(type(code) is not str for code in codes):
            raise CloseSnapshotSimulationValidationError("trusted status code payload is invalid")
        lower_factor = _parse_decimal_or_none(values["lower_boundary_factor"])
        upper_factor = _parse_decimal_or_none(values["upper_boundary_factor"])
        policy = cls(
            policy_id=_string(values["policy_id"], "policy_id"),
            policy_version=_string(values["policy_version"], "policy_version"),
            account_id=_integer(values["account_id"], "account_id"),
            security_id=_string(values["security_id"], "security_id"),
            asset_code=_string(values["asset_code"], "asset_code"),
            market=_string(values["market"], "market"),
            board=_string(values["board"], "board"),
            trading_date=_parse_date(values["trading_date"]),
            source_id=_string(values["source_id"], "source_id"),
            source_name=_string(values["source_name"], "source_name"),
            usage_ttl_seconds=_integer(values["usage_ttl_seconds"], "usage_ttl_seconds"),
            status_mapping_sha256=_string(values["status_mapping_sha256"], "status_mapping_sha256"),
            trusted_vendor_status_codes=tuple(codes),
            available_from=_parse_utc(values["available_from"]),
            available_until=_parse_utc(values["available_until"]),
            price_rule=_string(values["price_rule"], "price_rule"),
            price_rule_source_hash=_string(
                values["price_rule_source_hash"], "price_rule_source_hash"
            ),
            price_boundary_mode=_enum_value(PriceBoundaryMode, values["price_boundary_mode"]),
            lower_boundary_factor=lower_factor,
            upper_boundary_factor=upper_factor,
            boundary_rule_source_id=_string(
                values["boundary_rule_source_id"], "boundary_rule_source_id"
            ),
            boundary_rule_version=_string(values["boundary_rule_version"], "boundary_rule_version"),
            boundary_rule_source_hash=_string(
                values["boundary_rule_source_hash"], "boundary_rule_source_hash"
            ),
            unrestricted_reason_code=_optional_string(
                values["unrestricted_reason_code"], "unrestricted_reason_code"
            ),
            content_hash=(
                _string(values["content_hash"], "content_hash") if "content_hash" in values else ""
            ),
        )
        expected_payload = policy.to_payload()
        input_without_hash = {key: value for key, value in values.items() if key != "content_hash"}
        expected_without_hash = {
            key: value for key, value in expected_payload.items() if key != "content_hash"
        }
        supplied_hash = values.get("content_hash")
        if supplied_hash not in (None, "", policy.content_hash) or (
            input_without_hash != expected_without_hash
        ):
            raise CloseSnapshotSimulationValidationError("policy payload is not canonical")
        return policy


def _canonical_hash(payload: dict[str, object]) -> str:
    """Hash one JSON-safe canonical contract payload."""

    try:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CloseSnapshotSimulationValidationError("payload is not canonical JSON") from error
    return hashlib.sha256(encoded).hexdigest()


def _seal_hash(payload: dict[str, object], supplied: object) -> str:
    """Validate a supplied hash or compute it for a new immutable value."""

    if type(supplied) is not str:
        raise CloseSnapshotSimulationValidationError("content hash must be a string")
    actual = _canonical_hash(payload)
    if supplied and supplied != actual:
        raise CloseSnapshotSimulationValidationError("content hash does not match payload")
    return actual


def _token(value: object, name: str) -> str:
    """Require one bounded canonical token without whitespace."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise CloseSnapshotSimulationValidationError(f"{name} must be a canonical token")
    return value


def _is_token(value: object) -> bool:
    """Return whether a value is safe to place in a blocked decision identity."""

    try:
        _token(value, "token")
    except CloseSnapshotSimulationValidationError:
        return False
    return True


def _digest(value: object, name: str) -> str:
    """Require a bare lowercase SHA-256 digest."""

    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise CloseSnapshotSimulationValidationError(f"{name} must be SHA-256")
    return value


def _safe_digest(value: object) -> str | None:
    """Retain a digest only when the untrusted input is already canonical."""

    try:
        return _digest(value, "digest")
    except CloseSnapshotSimulationValidationError:
        return None


def _aware(value: object, name: str) -> datetime:
    """Require an exact timezone-aware datetime."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise CloseSnapshotSimulationValidationError(f"{name} must be timezone-aware")
    return value


def _is_positive_int(value: object) -> bool:
    """Return whether a value is a bounded positive integer identity."""

    return type(value) is int and 0 < value.bit_length() <= 63


def _positive_decimal(value: object, name: str) -> Decimal:
    """Require one exact finite positive Decimal with bounded shape."""

    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        raise CloseSnapshotSimulationValidationError(f"{name} must be a positive Decimal")
    parts = value.as_tuple()
    if len(parts.digits) > _MAX_DECIMAL_DIGITS or type(parts.exponent) is not int:
        raise CloseSnapshotSimulationValidationError(f"{name} exceeds decimal bounds")
    if abs(parts.exponent) > _MAX_DECIMAL_EXPONENT:
        raise CloseSnapshotSimulationValidationError(f"{name} exceeds decimal bounds")
    return value


def _decimal_text(value: Decimal | None) -> str | None:
    """Render an optional exact decimal without exponent notation."""

    if value is None:
        return None
    _positive_decimal(value, "decimal payload")
    return format(value, "f")


def _parse_decimal_or_none(value: object) -> Decimal | None:
    """Parse an optional canonical positive Decimal string."""

    if value is None:
        return None
    if type(value) is not str:
        raise CloseSnapshotSimulationValidationError("decimal payload must be canonical text")
    try:
        parsed = Decimal(value)
    except ArithmeticError as error:
        raise CloseSnapshotSimulationValidationError("decimal payload is invalid") from error
    _positive_decimal(parsed, "decimal payload")
    if _decimal_text(parsed) != value:
        raise CloseSnapshotSimulationValidationError("decimal payload is not canonical")
    return parsed


def _utc_text(value: datetime) -> str:
    """Render an aware time as canonical UTC with a literal Z suffix."""

    return (
        _aware(value, "datetime")
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _parse_utc(value: object) -> datetime:
    """Parse one canonical UTC string and reject offsets or precision drift."""

    if type(value) is not str or not value.endswith("Z"):
        raise CloseSnapshotSimulationValidationError("timestamp must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise CloseSnapshotSimulationValidationError("timestamp is invalid") from error
    if _utc_text(parsed) != value:
        raise CloseSnapshotSimulationValidationError("timestamp is not canonical")
    return parsed


def _parse_date(value: object) -> date:
    """Parse one canonical ISO calendar date."""

    if type(value) is not str:
        raise CloseSnapshotSimulationValidationError("trading date must be text")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise CloseSnapshotSimulationValidationError("trading date is invalid") from error
    if parsed.isoformat() != value:
        raise CloseSnapshotSimulationValidationError("trading date is not canonical")
    return parsed


def _string(value: object, name: str) -> str:
    """Narrow one JSON string field before construction."""

    if type(value) is not str:
        raise CloseSnapshotSimulationValidationError(f"{name} must be text")
    return value


def _optional_string(value: object, name: str) -> str | None:
    """Narrow one nullable JSON string field."""

    if value is None:
        return None
    return _string(value, name)


def _integer(value: object, name: str) -> int:
    """Narrow one exact JSON integer field."""

    if type(value) is not int:
        raise CloseSnapshotSimulationValidationError(f"{name} must be an integer")
    return value


def _enum_value(enum_type: type[PriceBoundaryMode], value: object) -> PriceBoundaryMode:
    """Parse a recognized price-boundary enum token."""

    if type(value) is not str:
        raise CloseSnapshotSimulationValidationError("price boundary mode must be text")
    try:
        return enum_type(value)
    except ValueError as error:
        raise CloseSnapshotSimulationValidationError("price boundary mode is unknown") from error


_POLICY_KEYS = frozenset(
    {
        "schema",
        "purpose",
        "policy_id",
        "policy_version",
        "account_id",
        "security_id",
        "asset_code",
        "market",
        "board",
        "trading_date",
        "source_id",
        "source_name",
        "usage_ttl_seconds",
        "status_mapping_sha256",
        "trusted_vendor_status_codes",
        "available_from",
        "available_until",
        "price_rule",
        "price_rule_source_hash",
        "price_boundary_mode",
        "lower_boundary_factor",
        "upper_boundary_factor",
        "boundary_rule_source_id",
        "boundary_rule_version",
        "boundary_rule_source_hash",
        "unrestricted_reason_code",
        "content_hash",
    }
)
