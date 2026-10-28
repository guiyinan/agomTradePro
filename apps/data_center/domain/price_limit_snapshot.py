"""Unpublished, exact provider-native per-security price-limit facts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from apps.data_center.domain.provider_response import ProviderResponseTransport

_DATASET_KEY = "equity.price.limit"
_API_NAME = "stk_limit"
_FIELDS = "ts_code,trade_date,down_limit,up_limit"
_ASSET_CODE = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PREFIXED_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_DECIMAL_DIGITS = 256
_MAX_DECIMAL_EXPONENT = 512
_PRICE_UNIT: Literal["provider_native_price"] = "provider_native_price"


class PriceLimitSnapshotError(ValueError):
    """Recognized invalid price-limit snapshot evidence with stable code."""

    def __init__(self, code: str, message: str) -> None:
        """Keep a machine-readable failure code without application imports."""

        self.code = code
        super().__init__(message)


def _invalid(code: str, message: str) -> PriceLimitSnapshotError:
    """Create one typed fail-closed Domain validation error."""

    return PriceLimitSnapshotError(code, message)


def _require_date(value: object, field_name: str) -> None:
    """Require a calendar date and reject datetime subclasses explicitly."""

    if type(value) is not date:
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_DATE_INVALID",
            f"{field_name} must be a date without a time component",
        )


def _require_utc(value: object, field_name: str) -> None:
    """Require a timezone-aware UTC timestamp."""

    if type(value) is not datetime or value.tzinfo is None:
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_TIME_INVALID",
            f"{field_name} must be timezone-aware UTC",
        )
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_TIME_INVALID",
            f"{field_name} must be timezone-aware UTC",
        )


def _require_text(value: object, field_name: str, maximum_length: int) -> None:
    """Require bounded, trimmed identity text without control characters."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum_length
        or any(ord(character) < 32 for character in value)
    ):
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_IDENTITY_INVALID",
            f"{field_name} must be bounded canonical text",
        )


def _require_provider_id(value: object) -> None:
    """Require an exact positive integer provider identity."""

    if type(value) is not int or value < 1:
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_SCOPE_INVALID",
            "provider_id must be a positive integer",
        )


def _require_asset_code(value: object) -> None:
    """Require one canonical six-digit Tushare security code."""

    if type(value) is not str or _ASSET_CODE.fullmatch(value) is None:
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_SCOPE_INVALID",
            "asset_code must be one canonical six-digit security code",
        )


def _require_digest(value: object, *, prefixed: bool, field_name: str) -> None:
    """Require a lowercase SHA-256 token in its declared namespace."""

    pattern = _PREFIXED_SHA256 if prefixed else _SHA256
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_HASH_INVALID",
            f"{field_name} must be a {'prefixed ' if prefixed else ''}SHA-256 digest",
        )


def _require_canonical_uuid(value: object, field_name: str) -> None:
    """Require a canonical lowercase UUID string."""

    if type(value) is not str:
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_UUID_INVALID",
            f"{field_name} must be a canonical UUID",
        )
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_UUID_INVALID",
            f"{field_name} must be a canonical UUID",
        ) from exc
    if str(parsed) != value:
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_UUID_INVALID",
            f"{field_name} must be a canonical UUID",
        )


def _require_decimal(value: object, field_name: str) -> Decimal:
    """Validate a finite, exact and bounded Decimal without quantization."""

    if type(value) is not Decimal or not value.is_finite():
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_PRICE_INVALID",
            f"{field_name} must be a finite Decimal",
        )
    parts = value.as_tuple()
    if (
        type(parts.exponent) is not int
        or len(parts.digits) > _MAX_DECIMAL_DIGITS
        or abs(parts.exponent) > _MAX_DECIMAL_EXPONENT
    ):
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_PRICE_INVALID",
            f"{field_name} exceeds the bounded Decimal representation",
        )
    if value <= 0:
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_PRICE_INVALID",
            f"{field_name} must be positive",
        )
    return value


def _sha256_payload(payload: dict[str, object]) -> str:
    """Hash canonical JSON with a stable, explicit SHA-256 namespace."""

    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def price_limit_request_scope_hash(
    *,
    provider_id: int,
    provider_name: str,
    asset_code: str,
    effective_trade_date: date,
) -> str:
    """Hash the exact normalized scope for one Tushare ``stk_limit`` request."""

    _require_provider_id(provider_id)
    _require_text(provider_name, "provider_name", 100)
    _require_asset_code(asset_code)
    _require_date(effective_trade_date, "effective_trade_date")
    material: dict[str, object] = {
        "provider_id": provider_id,
        "provider_name": provider_name,
        "dataset_key": _DATASET_KEY,
        "api_name": _API_NAME,
        "asset_code": asset_code,
        "trade_date": effective_trade_date.isoformat(),
        "request_params": {
            "provider_id": provider_id,
            "provider_name": provider_name,
            "api_name": _API_NAME,
            "fields": _FIELDS,
            "params": {
                "ts_code": asset_code,
                "trade_date": effective_trade_date.strftime("%Y%m%d"),
            },
        },
    }
    encoded = json.dumps(
        material,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PriceLimitRawReference:
    """Typed exact-body reference with the original provider request scope."""

    payload_id: str
    payload_hash: str
    record_digest: str
    body_sha256: str
    retained_content_sha256: str
    original_body_retained: bool
    retained_content_encoding: str
    body_size_bytes: int
    response_completed_at: datetime
    provider_name: str
    dataset_key: str
    transport: ProviderResponseTransport
    request_scope_sha256: str
    run_id: str = ""

    def __post_init__(self) -> None:
        """Require exact original response bytes and their complete identity."""

        _require_canonical_uuid(self.payload_id, "payload_id")
        _require_digest(self.payload_hash, prefixed=True, field_name="payload_hash")
        if str(uuid5(NAMESPACE_URL, self.payload_hash)) != self.payload_id:
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_RAW_REFERENCE_INVALID",
                "payload_id must be derived from payload_hash",
            )
        _require_digest(self.record_digest, prefixed=True, field_name="record_digest")
        _require_digest(self.body_sha256, prefixed=False, field_name="body_sha256")
        _require_digest(
            self.retained_content_sha256,
            prefixed=False,
            field_name="retained_content_sha256",
        )
        if self.retained_content_sha256 != self.body_sha256:
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_RAW_REFERENCE_INVALID",
                "price-limit fact requires exact retained original response bytes",
            )
        if type(self.original_body_retained) is not bool:
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_RAW_REFERENCE_INVALID",
                "original_body_retained must be a boolean",
            )
        if self.original_body_retained is not True:
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_RAW_BODY_NOT_RETAINED",
                "price-limit fact requires retained original response bytes",
            )
        if self.retained_content_encoding != "exact_original_utf8_json":
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_RAW_REFERENCE_INVALID",
                "retained content must be the exact original UTF-8 JSON body",
            )
        if type(self.body_size_bytes) is not int or self.body_size_bytes < 0:
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_RAW_REFERENCE_INVALID",
                "body_size_bytes must be a nonnegative integer",
            )
        _require_utc(self.response_completed_at, "response_completed_at")
        _require_text(self.provider_name, "provider_name", 100)
        _require_text(self.dataset_key, "dataset_key", 160)
        if self.dataset_key != _DATASET_KEY:
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_RAW_REFERENCE_INVALID",
                "raw response dataset does not identify price limits",
            )
        if not isinstance(self.transport, ProviderResponseTransport):
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_RAW_REFERENCE_INVALID",
                "transport must be a recognized response transport",
            )
        _require_digest(
            self.request_scope_sha256,
            prefixed=False,
            field_name="request_scope_sha256",
        )
        if type(self.run_id) is not str:
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_RAW_REFERENCE_INVALID",
                "run_id must be empty or a canonical UUID",
            )
        if self.run_id:
            _require_canonical_uuid(self.run_id, "run_id")

    def to_payload(self) -> dict[str, object]:
        """Serialize the application response reference plus request-scope hash."""

        payload: dict[str, object] = {
            "payload_id": self.payload_id,
            "payload_hash": self.payload_hash,
            "record_digest": self.record_digest,
            "body_sha256": self.body_sha256,
            "retained_content_sha256": self.retained_content_sha256,
            "original_body_retained": self.original_body_retained,
            "retained_content_encoding": self.retained_content_encoding,
            "body_size_bytes": self.body_size_bytes,
            "response_completed_at": self.response_completed_at.isoformat(),
            "provider_name": self.provider_name,
            "dataset_key": self.dataset_key,
            "transport": self.transport.value,
            "time_semantics": "local_response_body_completion",
        }
        if self.run_id:
            payload["run_id"] = self.run_id
        payload["request_scope_sha256"] = self.request_scope_sha256
        return payload


@dataclass(frozen=True, slots=True)
class PriceLimitSnapshotCandidate:
    """Exact provider-native lower/upper limits before first persistence."""

    asset_code: str
    effective_trade_date: date
    provider_id: int
    provider_name: str
    lower_limit_price: Decimal
    upper_limit_price: Decimal
    raw_reference: PriceLimitRawReference

    def __post_init__(self) -> None:
        """Bind positive exact prices to one canonical request and raw response."""

        _require_asset_code(self.asset_code)
        _require_date(self.effective_trade_date, "effective_trade_date")
        _require_provider_id(self.provider_id)
        _require_text(self.provider_name, "provider_name", 100)
        lower = _require_decimal(self.lower_limit_price, "lower_limit_price")
        upper = _require_decimal(self.upper_limit_price, "upper_limit_price")
        if lower > upper:
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_PRICE_INVALID",
                "lower_limit_price cannot exceed upper_limit_price",
            )
        if type(self.raw_reference) is not PriceLimitRawReference:
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_RAW_REFERENCE_INVALID",
                "raw_reference must be a typed exact-body reference",
            )
        if (
            self.raw_reference.provider_name != self.provider_name
            or self.raw_reference.dataset_key != _DATASET_KEY
        ):
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_SOURCE_MISMATCH",
                "raw response provider or dataset does not match candidate",
            )
        expected_scope = price_limit_request_scope_hash(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            asset_code=self.asset_code,
            effective_trade_date=self.effective_trade_date,
        )
        if self.raw_reference.request_scope_sha256 != expected_scope:
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_SCOPE_MISMATCH",
                "raw request scope does not match candidate identity",
            )

    @property
    def response_completed_at(self) -> datetime:
        """Return local response-body completion, not a market observation time."""

        return self.raw_reference.response_completed_at

    @property
    def request_scope_sha256(self) -> str:
        """Return the exact normalized ``stk_limit`` request scope digest."""

        return self.raw_reference.request_scope_sha256

    @property
    def price_unit(self) -> Literal["provider_native_price"]:
        """Return the deliberately provider-native, currency-unknown unit."""

        return _PRICE_UNIT

    @property
    def currency(self) -> None:
        """Return unknown currency; provider-native values imply no currency."""

        return None

    @property
    def observed_at(self) -> None:
        """Return unknown upstream observation time."""

        return None

    @property
    def source_published_at(self) -> None:
        """Return unknown upstream publication time."""

        return None

    @property
    def source_available_at(self) -> None:
        """Return unknown upstream availability time."""

        return None

    @property
    def content_hash(self) -> str:
        """Hash exact normalized values, scope, response time, and raw reference."""

        return _sha256_payload(self.to_content_payload())

    def to_content_payload(self) -> dict[str, object]:
        """Return the immutable source fact, preserving Decimal scale exactly."""

        return {
            "schema": "price-limit-snapshot.v1",
            "asset_code": self.asset_code,
            "effective_trade_date": self.effective_trade_date.isoformat(),
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "dataset_key": _DATASET_KEY,
            "api_name": _API_NAME,
            "request_scope_sha256": self.request_scope_sha256,
            "lower_limit_price": str(self.lower_limit_price),
            "upper_limit_price": str(self.upper_limit_price),
            "price_unit": self.price_unit,
            "currency": self.currency,
            "observed_at": self.observed_at,
            "source_published_at": self.source_published_at,
            "source_available_at": self.source_available_at,
            "response_completed_at": self.response_completed_at.isoformat(),
            "response_time_semantics": "local_response_body_completion",
            "raw_reference": self.raw_reference.to_payload(),
        }


@dataclass(frozen=True, slots=True)
class PriceLimitSnapshot:
    """Immutable first-recorded limit fact that remains unpublished."""

    snapshot_id: str
    candidate: PriceLimitSnapshotCandidate
    recorded_at: datetime
    content_hash: str
    record_digest: str

    def __post_init__(self) -> None:
        """Verify persisted identity, chronology, content hash, and record digest."""

        _require_canonical_uuid(self.snapshot_id, "snapshot_id")
        if type(self.candidate) is not PriceLimitSnapshotCandidate:
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_INVALID",
                "candidate must be a typed price-limit snapshot candidate",
            )
        _require_utc(self.recorded_at, "recorded_at")
        if self.recorded_at < self.candidate.response_completed_at:
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_KNOWLEDGE_TIME_INVALID",
                "recorded_at cannot precede response_completed_at",
            )
        if self.content_hash != self.candidate.content_hash:
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_CONTENT_HASH_MISMATCH",
                "snapshot content_hash does not match candidate source content",
            )
        _require_digest(self.record_digest, prefixed=True, field_name="record_digest")
        if self.record_digest != price_limit_snapshot_record_digest(self):
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_RECORD_DIGEST_MISMATCH",
                "snapshot record_digest does not match persisted fields",
            )

    @property
    def publication_status(self) -> Literal["unpublished"]:
        """Return the fixed unpublished status of this first-recorded fact."""

        return "unpublished"

    @property
    def must_not_use_for_decision(self) -> bool:
        """Mark this unpublished fact as blocked for decision use."""

        return True

    @property
    def must_not_execute(self) -> bool:
        """Mark this unpublished fact as blocked for execution use."""

        return True

    def to_payload(self) -> dict[str, object]:
        """Serialize the immutable fact plus explicit non-publication markers."""

        return {
            **self.candidate.to_content_payload(),
            "snapshot_id": self.snapshot_id,
            "recorded_at": self.recorded_at.isoformat(),
            "content_hash": self.content_hash,
            "record_digest": self.record_digest,
            "publication_status": "unpublished",
            "must_not_use_for_decision": True,
            "must_not_execute": True,
            "blocked_reason": "price_limit_snapshot_unpublished_reference",
        }

    def reference(self) -> PriceLimitSnapshotReference:
        """Return an immutable exact lookup identity without a publication claim."""

        candidate = self.candidate
        raw_reference = candidate.raw_reference
        return PriceLimitSnapshotReference(
            snapshot_id=self.snapshot_id,
            asset_code=candidate.asset_code,
            effective_trade_date=candidate.effective_trade_date,
            provider_id=candidate.provider_id,
            provider_name=candidate.provider_name,
            dataset_key=_DATASET_KEY,
            api_name=_API_NAME,
            request_scope_sha256=raw_reference.request_scope_sha256,
            content_hash=self.content_hash,
            record_digest=self.record_digest,
            raw_payload_id=raw_reference.payload_id,
            raw_payload_hash=raw_reference.payload_hash,
            raw_record_digest=raw_reference.record_digest,
        )


@dataclass(frozen=True, slots=True)
class PriceLimitSnapshotReference:
    """Exact fact identity and source binding used by a public point read."""

    snapshot_id: str
    asset_code: str
    effective_trade_date: date
    provider_id: int
    provider_name: str
    dataset_key: str
    api_name: str
    request_scope_sha256: str
    content_hash: str
    record_digest: str
    raw_payload_id: str
    raw_payload_hash: str
    raw_record_digest: str

    def __post_init__(self) -> None:
        """Reject references that could select another source fact."""

        _require_canonical_uuid(self.snapshot_id, "snapshot_id")
        _require_asset_code(self.asset_code)
        _require_date(self.effective_trade_date, "effective_trade_date")
        _require_provider_id(self.provider_id)
        _require_text(self.provider_name, "provider_name", 100)
        if self.dataset_key != _DATASET_KEY or self.api_name != _API_NAME:
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_REFERENCE_INVALID",
                "reference dataset and API must identify price limits",
            )
        expected_scope = price_limit_request_scope_hash(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            asset_code=self.asset_code,
            effective_trade_date=self.effective_trade_date,
        )
        if self.request_scope_sha256 != expected_scope:
            raise _invalid(
                "PRICE_LIMIT_SNAPSHOT_REFERENCE_INVALID",
                "reference request scope does not match its identity",
            )
        for field_name, value in (
            ("content_hash", self.content_hash),
            ("record_digest", self.record_digest),
            ("raw_payload_hash", self.raw_payload_hash),
            ("raw_record_digest", self.raw_record_digest),
        ):
            _require_digest(value, prefixed=True, field_name=field_name)
        _require_canonical_uuid(self.raw_payload_id, "raw_payload_id")

    def to_payload(self) -> dict[str, object]:
        """Serialize exact fact and retained source identity for point reads."""

        return {
            "snapshot_id": self.snapshot_id,
            "asset_code": self.asset_code,
            "effective_trade_date": self.effective_trade_date.isoformat(),
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "dataset_key": self.dataset_key,
            "api_name": self.api_name,
            "request_scope_sha256": self.request_scope_sha256,
            "content_hash": self.content_hash,
            "record_digest": self.record_digest,
            "raw_payload_id": self.raw_payload_id,
            "raw_payload_hash": self.raw_payload_hash,
            "raw_record_digest": self.raw_record_digest,
        }


def _snapshot_record_material(
    *,
    snapshot_id: str,
    candidate: PriceLimitSnapshotCandidate,
    recorded_at: datetime,
) -> dict[str, object]:
    """Return all persisted snapshot fields except its record digest."""

    return {
        "snapshot_id": snapshot_id,
        "candidate": candidate.to_content_payload(),
        "recorded_at": recorded_at.isoformat(),
        "content_hash": candidate.content_hash,
    }


def price_limit_snapshot_record_digest(snapshot: PriceLimitSnapshot) -> str:
    """Hash a snapshot's exact source fact, UUID, and first-recorded time."""

    if type(snapshot) is not PriceLimitSnapshot:
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_INVALID",
            "snapshot must be a typed price-limit snapshot",
        )
    return _sha256_payload(
        _snapshot_record_material(
            snapshot_id=snapshot.snapshot_id,
            candidate=snapshot.candidate,
            recorded_at=snapshot.recorded_at,
        )
    )


def make_price_limit_snapshot(
    candidate: PriceLimitSnapshotCandidate,
    *,
    snapshot_id: str,
    recorded_at: datetime,
) -> PriceLimitSnapshot:
    """Build one first-recorded snapshot after persistence assigns identity/time."""

    if type(candidate) is not PriceLimitSnapshotCandidate:
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_INVALID",
            "candidate must be a typed price-limit snapshot candidate",
        )
    _require_canonical_uuid(snapshot_id, "snapshot_id")
    _require_utc(recorded_at, "recorded_at")
    if recorded_at < candidate.response_completed_at:
        raise _invalid(
            "PRICE_LIMIT_SNAPSHOT_KNOWLEDGE_TIME_INVALID",
            "recorded_at cannot precede response_completed_at",
        )
    partial = _snapshot_record_material(
        snapshot_id=snapshot_id,
        candidate=candidate,
        recorded_at=recorded_at,
    )
    return PriceLimitSnapshot(
        snapshot_id=snapshot_id,
        candidate=candidate,
        recorded_at=recorded_at,
        content_hash=candidate.content_hash,
        record_digest=_sha256_payload(partial),
    )


__all__ = [
    "PriceLimitRawReference",
    "PriceLimitSnapshot",
    "PriceLimitSnapshotCandidate",
    "PriceLimitSnapshotError",
    "PriceLimitSnapshotReference",
    "make_price_limit_snapshot",
    "price_limit_request_scope_hash",
    "price_limit_snapshot_record_digest",
]
