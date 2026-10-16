"""Transport-only evidence for an opt-in non-financial provider response."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, DecimalException
from enum import StrEnum
from typing import cast

_MAX_JSON_INTEGER_DIGITS = 256


class ProviderResponseTransport(StrEnum):
    """Network path that delivered the captured application response body."""

    DIRECT = "direct"
    EGRESS = "egress"


@dataclass(frozen=True, slots=True)
class ProviderResponseCapture:
    """A successful JSON response with its exact body bytes and local receipt time.

    ``response_completed_at`` is sampled by this application after it consumes
    the response body. It is an acquisition/completion time, never a provider
    observation, publication, or source-effective time. The parsed payload may
    later be redacted before persistence; ``body_sha256`` always covers the
    original bytes supplied by the transport.
    """

    body: bytes = field(repr=False)
    payload: object = field(repr=False)
    body_sha256: str
    body_size_bytes: int
    response_completed_at: datetime
    status_code: int
    content_type: str | None
    transport: ProviderResponseTransport

    def __post_init__(self) -> None:
        """Reject captures whose success, byte digest, or clock is unverifiable."""

        if type(self.body) is not bytes:
            raise ValueError("ProviderResponseCapture.body must be bytes")
        if not isinstance(self.body_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.body_sha256
        ):
            raise ValueError("ProviderResponseCapture.body_sha256 is invalid")
        if hashlib.sha256(self.body).hexdigest() != self.body_sha256:
            raise ValueError("ProviderResponseCapture.body_sha256 does not match body")
        if (
            isinstance(self.body_size_bytes, bool)
            or not isinstance(self.body_size_bytes, int)
            or self.body_size_bytes != len(self.body)
        ):
            raise ValueError("ProviderResponseCapture.body_size_bytes does not match body")
        try:
            parsed_payload = parse_provider_response_json(self.body)
            exposed_bytes = _canonical_json_bytes(self.payload)
            parsed_bytes = _canonical_json_bytes(parsed_payload)
            if exposed_bytes != parsed_bytes or not _same_json_value(self.payload, parsed_payload):
                raise ValueError("ProviderResponseCapture.payload does not match body")
        except (RecursionError, TypeError, ValueError) as exc:
            raise ValueError("ProviderResponseCapture.body is not bound to payload") from exc
        if (
            not isinstance(self.response_completed_at, datetime)
            or self.response_completed_at.tzinfo is None
            or self.response_completed_at.utcoffset() is None
            or _utc_offset_seconds(self.response_completed_at) != 0
        ):
            raise ValueError("ProviderResponseCapture.response_completed_at must be UTC-aware")
        if (
            isinstance(self.status_code, bool)
            or not isinstance(self.status_code, int)
            or not 200 <= self.status_code < 300
        ):
            raise ValueError("ProviderResponseCapture.status_code must be successful")
        if self.content_type is not None and (
            not isinstance(self.content_type, str)
            or len(self.content_type) > 512
            or any(ord(character) < 32 for character in self.content_type)
        ):
            raise ValueError("ProviderResponseCapture.content_type is invalid")
        if not isinstance(self.transport, ProviderResponseTransport):
            raise ValueError("ProviderResponseCapture.transport must be typed")

    @property
    def acquired_at(self) -> datetime:
        """Return the local time at which the response body was fully acquired."""

        return self.response_completed_at

    def payload_from_body(self) -> object:
        """Parse a fresh strict JSON value from the immutable response bytes."""

        return parse_provider_response_json(self.body)

    def payload_matches_body(self) -> bool:
        """Check that the exposed parsed object still matches the exact body."""

        try:
            parsed_payload = parse_provider_response_json(self.body)
            return _canonical_json_bytes(self.payload) == _canonical_json_bytes(
                parsed_payload
            ) and _same_json_value(self.payload, parsed_payload)
        except (RecursionError, TypeError, ValueError):
            return False


def parse_provider_response_json(body: bytes) -> object:
    """Decode strict UTF-8 JSON, rejecting ambiguous and oversized scalars."""

    if type(body) is not bytes:
        raise ValueError("provider_response_body_must_be_bytes")
    try:
        return json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_int=_parse_json_integer,
            parse_float=_parse_json_float,
            parse_constant=_reject_json_constant,
        )
    except (
        DecimalException,
        RecursionError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError("provider_response_body_is_not_strict_json") from exc


def canonical_provider_response_json(value: object) -> str:
    """Serialize validated JSON while preserving exact Decimal number values."""

    return _canonical_json_bytes(value).decode("utf-8")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON object keys rather than silently overwriting."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("provider_response_duplicate_json_key")
        result[key] = value
    return result


def _parse_json_integer(value: str) -> int:
    """Parse a bounded integer token to keep hostile JSON values finite."""

    digits = value[1:] if value.startswith("-") else value
    if len(digits) > _MAX_JSON_INTEGER_DIGITS:
        raise ValueError("provider_response_integer_too_large")
    return int(value)


def _parse_json_float(value: str) -> Decimal:
    """Parse JSON fractional numbers exactly, rejecting non-finite values."""

    parsed = Decimal(value)
    if not parsed.is_finite():
        raise ValueError("provider_response_float_not_finite")
    return parsed


def _reject_json_constant(value: str) -> None:
    """Reject non-standard NaN and Infinity JSON constants."""

    raise ValueError(f"provider_response_json_constant_invalid:{value}")


def _canonical_json_bytes(value: object) -> bytes:
    """Return a type-sensitive canonical encoding for strict JSON values."""

    normalized = _normalize_json_value(value)
    return _encode_json_value(normalized).encode("utf-8")


def _same_json_value(left: object, right: object) -> bool:
    """Compare strict parser values without merging JSON number representations."""

    if type(left) is not type(right):
        return False
    if type(left) is dict:
        left_dict = cast(dict[str, object], left)
        right_dict = cast(dict[str, object], right)
        return left_dict.keys() == right_dict.keys() and all(
            _same_json_value(left_dict[key], right_dict[key]) for key in left_dict
        )
    if type(left) is list:
        left_list = cast(list[object], left)
        right_list = cast(list[object], right)
        return len(left_list) == len(right_list) and all(
            _same_json_value(left_item, right_item)
            for left_item, right_item in zip(left_list, right_list, strict=True)
        )
    if type(left) is Decimal:
        return left.as_tuple() == cast(Decimal, right).as_tuple()
    if left is None:
        return right is None
    if type(left) is bool:
        return left is right
    if type(left) is int:
        return left == right
    if type(left) is float:
        return left == right
    if type(left) is str:
        return left == right
    return False


def _normalize_json_value(value: object) -> object:
    """Validate exact built-in JSON types before canonical comparison."""

    if value is None or type(value) is bool or type(value) is str:
        return value
    if type(value) is int:
        if value.bit_length() > 850 or len(str(abs(value))) > _MAX_JSON_INTEGER_DIGITS:
            raise ValueError("provider_response_integer_too_large")
        return value
    if type(value) is Decimal:
        if not value.is_finite():
            raise ValueError("provider_response_decimal_not_finite")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("provider_response_float_not_finite")
        return value
    if type(value) is list:
        return [_normalize_json_value(item) for item in value]
    if type(value) is dict:
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("provider_response_json_key_not_string")
            normalized[key] = _normalize_json_value(item)
        return normalized
    raise ValueError("provider_response_value_not_json")


def _encode_json_value(value: object) -> str:
    """Encode one already validated JSON value without rounding Decimals."""

    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is str:
        return json.dumps(value, ensure_ascii=False)
    if type(value) is int or type(value) is Decimal:
        return str(value)
    if type(value) is float:
        return json.dumps(value, allow_nan=False, separators=(",", ":"))
    if type(value) is list:
        return "[" + ",".join(_encode_json_value(item) for item in value) + "]"
    if type(value) is dict:
        pairs = (
            f"{json.dumps(key, ensure_ascii=False)}:{_encode_json_value(item)}"
            for key, item in sorted(value.items(), key=lambda pair: pair[0])
        )
        return "{" + ",".join(pairs) + "}"
    raise ValueError("provider_response_value_not_json")


def _utc_offset_seconds(value: datetime) -> float:
    """Return a non-optional UTC offset after the caller checked awareness."""

    offset = value.utcoffset()
    if offset is None:
        return float("nan")
    return offset.total_seconds()


__all__ = [
    "ProviderResponseCapture",
    "ProviderResponseTransport",
    "canonical_provider_response_json",
    "parse_provider_response_json",
]
