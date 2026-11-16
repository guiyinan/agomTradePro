"""Isolated, unactivated boundary for a one-security Balance3 raw response.

This module checks a caller-supplied static candidate contract. A parsed
candidate is not provider-body-verified evidence and is not an approved
financial fact.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Literal, TypeAlias, cast

from apps.data_center.infrastructure.financial_response_capture import decode_json_bytes

BalanceCandidateOutcome = Literal["candidate_parsed", "blocked"]
BalanceCandidateEvidenceState = Literal["static_candidate_unverified"]
JsonStatusValue = bool | int | str
BalanceRawJsonValue: TypeAlias = (
    str
    | int
    | bool
    | Decimal
    | None
    | tuple["BalanceRawJsonValue", ...]
    | Mapping[str, "BalanceRawJsonValue"]
)
BalanceValueBindingTriple = tuple[
    "BalanceValueBinding",
    "BalanceValueBinding",
    "BalanceValueBinding",
]


@dataclass(frozen=True, slots=True)
class BalanceValueBinding:
    """Map one already-validated metric and unit to its provider raw key."""

    metric_code: str
    raw_key: str
    unit_code: str

    def __post_init__(self) -> None:
        """Reject missing or padded contract dimensions without normalization."""

        _required_text(self.metric_code, "metric_code")
        _required_text(self.raw_key, "raw_key")
        _required_text(self.unit_code, "unit_code")


@dataclass(frozen=True, slots=True)
class BalanceCandidateContract:
    """Caller-supplied schema candidate; it carries no provider approval."""

    contract_id: str
    evidence_state: BalanceCandidateEvidenceState
    endpoint_url: str
    report_name: str
    base_filter_terms: tuple[str, ...]
    security_filter_key: str
    report_date_filter_key: str
    result_key: str
    success_key: str
    success_value: JsonStatusValue
    code_key: str
    success_code: JsonStatusValue
    count_key: str
    pages_key: str
    data_key: str
    row_security_code_key: str
    row_report_date_key: str
    row_notice_date_key: str
    value_bindings: BalanceValueBindingTriple

    def __post_init__(self) -> None:
        """Validate an explicit candidate schema without filling unknown keys."""

        _required_text(self.contract_id, "contract_id")
        _required_text(self.endpoint_url, "endpoint_url")
        _required_text(self.report_name, "report_name")
        if self.evidence_state != "static_candidate_unverified":
            raise ValueError("candidate contract must remain statically unverified")
        if not isinstance(self.base_filter_terms, tuple) or not self.base_filter_terms:
            raise ValueError("base_filter_terms must be a non-empty tuple")
        for term in self.base_filter_terms:
            _required_text(term, "base_filter_term")
            if not term.startswith("(") or not term.endswith(")"):
                raise ValueError("each base filter term must be parenthesized")
        for name in (
            "security_filter_key",
            "report_date_filter_key",
            "result_key",
            "success_key",
            "code_key",
            "count_key",
            "pages_key",
            "data_key",
            "row_security_code_key",
            "row_report_date_key",
            "row_notice_date_key",
        ):
            _required_text(getattr(self, name), name)
        if not isinstance(self.value_bindings, tuple) or len(self.value_bindings) != 3:
            raise ValueError("value_bindings must contain exactly three typed fields")
        if not all(isinstance(item, BalanceValueBinding) for item in self.value_bindings):
            raise ValueError("value_bindings must contain BalanceValueBinding values")
        metric_codes = tuple(item.metric_code for item in self.value_bindings)
        raw_keys = tuple(item.raw_key for item in self.value_bindings)
        if len(set(metric_codes)) != len(metric_codes):
            raise ValueError("metric codes must be unique")
        if len(set(raw_keys)) != len(raw_keys):
            raise ValueError("value raw keys must be unique")
        if len(
            {
                self.row_security_code_key,
                self.row_report_date_key,
                self.row_notice_date_key,
                *raw_keys,
            }
        ) != 3 + len(raw_keys):
            raise ValueError("identity and value raw keys must be distinct")
        if type(self.success_value) not in {bool, int, str}:
            raise ValueError("success_value must be a JSON scalar")
        if type(self.success_code) not in {bool, int, str}:
            raise ValueError("success_code must be a JSON scalar")


@dataclass(frozen=True, slots=True)
class BalanceCandidateRequest:
    """One explicit exchange-qualified security and report period."""

    symbol: str
    security_code: str
    report_date: date

    def __post_init__(self) -> None:
        """Reject unqualified symbols and datetimes at the period boundary."""

        _required_text(self.symbol, "symbol")
        if re.fullmatch(r"[0-9]{6}\.(?:SH|SZ)", self.symbol) is None:
            raise ValueError("symbol must be a six-digit SH or SZ code")
        if not isinstance(self.security_code, str) or self.security_code != self.symbol[:6]:
            raise ValueError("security_code must match the symbol's six-digit code")
        if isinstance(self.report_date, datetime) or not isinstance(self.report_date, date):
            raise ValueError("report_date must be a date, not a datetime")


@dataclass(frozen=True, slots=True)
class BalanceCandidateQuery:
    """Unsent one-row query projection; the security filter is unverified."""

    endpoint_url: str
    parameters: tuple[tuple[str, str], ...]
    security_filter_evidence: Literal["static_unverified"]

    def __post_init__(self) -> None:
        """Keep the unsent request immutable and visibly unverified."""

        _required_text(self.endpoint_url, "endpoint_url")
        if not isinstance(self.parameters, tuple) or not self.parameters:
            raise ValueError("query parameters must be a non-empty tuple")
        if not all(
            isinstance(pair, tuple)
            and len(pair) == 2
            and isinstance(pair[0], str)
            and isinstance(pair[1], str)
            for pair in self.parameters
        ):
            raise ValueError("query parameters must be string pairs")
        parameter_names = tuple(pair[0] for pair in self.parameters)
        if len(set(parameter_names)) != len(parameter_names):
            raise ValueError("query parameter names must be unique")
        if self.security_filter_evidence != "static_unverified":
            raise ValueError("security-code filter must remain unverified")


@dataclass(frozen=True, slots=True)
class BalanceRawProjectionField:
    """One selected provider field as a raw-key and exact parsed-text pair."""

    raw_key: str
    raw_value_text: str

    def __post_init__(self) -> None:
        """Reject missing projection labels and values."""

        _required_text(self.raw_key, "raw_key")
        if not isinstance(self.raw_value_text, str):
            raise ValueError("raw_value_text must be text")


@dataclass(frozen=True, slots=True)
class BalanceCandidateNativeValue:
    """One exact Decimal value labelled only by its supplied typed contract."""

    metric_code: str
    raw_key: str
    unit_code: str
    value: Decimal

    def __post_init__(self) -> None:
        """Keep metric and unit labels contract-bound and require finite Decimal."""

        _required_text(self.metric_code, "metric_code")
        _required_text(self.raw_key, "raw_key")
        _required_text(self.unit_code, "unit_code")
        if not isinstance(self.value, Decimal) or not self.value.is_finite():
            raise ValueError("candidate native value must be a finite Decimal")


@dataclass(frozen=True, slots=True)
class BalanceCandidateSourceRowIdentity:
    """Candidate source-row identity, with date precision and no ANN time."""

    contract_id: str
    report_name: str
    symbol: str
    security_code: str
    report_date: date
    notice_date: date
    row_index: int
    row_projection_sha256: str

    def __post_init__(self) -> None:
        """Require date-only identity fields and a bound projection digest."""

        _required_text(self.contract_id, "contract_id")
        _required_text(self.report_name, "report_name")
        _required_text(self.symbol, "symbol")
        _required_text(self.security_code, "security_code")
        if (
            isinstance(self.report_date, datetime)
            or not isinstance(self.report_date, date)
            or isinstance(self.notice_date, datetime)
            or not isinstance(self.notice_date, date)
        ):
            raise ValueError("candidate row identity dates must have date precision")
        if type(self.row_index) is not int or self.row_index != 0:
            raise ValueError("candidate row identity must refer to the unique first row")
        if re.fullmatch(r"[0-9a-f]{64}", self.row_projection_sha256) is None:
            raise ValueError("row_projection_sha256 must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class BalanceCandidateParseResult:
    """Exact bytes plus either a blocked result or an unverified parsed candidate."""

    outcome: BalanceCandidateOutcome
    raw_body: bytes = field(repr=False)
    body_sha256: str
    body_size_bytes: int
    row_index: int | None
    raw_row_projection: tuple[BalanceRawProjectionField, ...]
    raw_row_context: Mapping[str, BalanceRawJsonValue]
    row_projection_sha256: str | None
    source_row_identity: BalanceCandidateSourceRowIdentity | None
    values: tuple[BalanceCandidateNativeValue, ...]
    blocked_reason: str | None

    def __post_init__(self) -> None:
        """Bind the result to exact response bytes and preserve candidate-only state."""

        if self.outcome not in {"candidate_parsed", "blocked"}:
            raise ValueError("unsupported candidate outcome")
        if type(self.raw_body) is not bytes:
            raise ValueError("raw_body must be exact bytes")
        if self.body_size_bytes != len(self.raw_body):
            raise ValueError("body_size_bytes does not match raw_body")
        if self.body_sha256 != hashlib.sha256(self.raw_body).hexdigest():
            raise ValueError("body_sha256 does not match raw_body")
        if self.outcome == "candidate_parsed":
            if (
                self.blocked_reason is not None
                or self.row_index != 0
                or self.source_row_identity is None
                or self.row_projection_sha256 is None
                or len(self.raw_row_projection) != 6
                or not isinstance(self.raw_row_context, Mapping)
                or not self.raw_row_context
                or any(type(key) is not str for key in self.raw_row_context)
                or len(self.values) != 3
            ):
                raise ValueError("candidate_parsed result is incomplete")
            if self.source_row_identity.row_projection_sha256 != self.row_projection_sha256:
                raise ValueError("row projection identity does not match")
            if self.source_row_identity.row_index != self.row_index:
                raise ValueError("row projection index does not match")
            projection_digest = _projection_sha256(
                contract_id=self.source_row_identity.contract_id,
                body_sha256=self.body_sha256,
                row_index=self.row_index,
                fields=self.raw_row_projection,
            )
            if projection_digest != self.row_projection_sha256:
                raise ValueError("row projection digest does not match its fields")
        elif (
            self.blocked_reason is None
            or self.values
            or self.source_row_identity is not None
            or self.row_projection_sha256 is not None
            or self.raw_row_projection
            or self.raw_row_context
        ):
            raise ValueError("blocked result must not expose a partial row projection")


def build_balance_candidate_query(
    request: BalanceCandidateRequest,
    contract: BalanceCandidateContract,
) -> BalanceCandidateQuery:
    """Build an unsent, explicitly unverified one-security/one-period request."""

    if not isinstance(request, BalanceCandidateRequest):
        raise ValueError("request must be typed")
    if not isinstance(contract, BalanceCandidateContract):
        raise ValueError("contract must be typed")
    security_filter = f'({contract.security_filter_key}="{request.security_code}")'
    report_filter = f"({contract.report_date_filter_key}='{request.report_date.isoformat()}')"
    filter_text = "".join((*contract.base_filter_terms, security_filter, report_filter))
    parameters = (
        ("sortColumns", f"{contract.row_notice_date_key},{contract.row_security_code_key}"),
        ("sortTypes", "-1,-1"),
        ("pageSize", "500"),
        ("pageNumber", "1"),
        ("reportName", contract.report_name),
        ("columns", "ALL"),
        ("filter", filter_text),
    )
    return BalanceCandidateQuery(
        endpoint_url=contract.endpoint_url,
        parameters=parameters,
        security_filter_evidence="static_unverified",
    )


def parse_balance_candidate_body(
    raw_body: bytes,
    *,
    request: BalanceCandidateRequest,
    contract: BalanceCandidateContract,
) -> BalanceCandidateParseResult:
    """Strictly parse one candidate row without promoting source verification."""

    if type(raw_body) is not bytes:
        raise TypeError("raw_body must be bytes")
    if not isinstance(request, BalanceCandidateRequest):
        raise ValueError("request must be typed")
    if not isinstance(contract, BalanceCandidateContract):
        raise ValueError("contract must be typed")
    body_sha256 = hashlib.sha256(raw_body).hexdigest()
    body_size_bytes = len(raw_body)
    try:
        payload = decode_json_bytes(raw_body)
    except ValueError:
        return _blocked(raw_body, body_sha256, body_size_bytes, "invalid_json")
    payload_mapping = _mapping(payload)
    if payload_mapping is None:
        return _blocked(raw_body, body_sha256, body_size_bytes, "envelope_not_object")
    if not _same_json_scalar(payload_mapping.get(contract.success_key), contract.success_value):
        return _blocked(raw_body, body_sha256, body_size_bytes, "provider_success_marker_invalid")
    if not _same_json_scalar(payload_mapping.get(contract.code_key), contract.success_code):
        return _blocked(raw_body, body_sha256, body_size_bytes, "provider_code_invalid")
    result_mapping = _mapping(payload_mapping.get(contract.result_key))
    if result_mapping is None:
        return _blocked(raw_body, body_sha256, body_size_bytes, "result_object_missing")
    if contract.count_key not in result_mapping or contract.pages_key not in result_mapping:
        return _blocked(raw_body, body_sha256, body_size_bytes, "count_or_pages_missing")
    count = result_mapping.get(contract.count_key)
    pages = result_mapping.get(contract.pages_key)
    if isinstance(pages, bool) or not isinstance(pages, int) or pages != 1:
        return _blocked(raw_body, body_sha256, body_size_bytes, "pages_not_one")
    if isinstance(count, bool) or not isinstance(count, int) or count != 1:
        return _blocked(raw_body, body_sha256, body_size_bytes, "count_not_one")
    raw_rows = result_mapping.get(contract.data_key)
    if not isinstance(raw_rows, list) or len(raw_rows) != 1:
        return _blocked(raw_body, body_sha256, body_size_bytes, "rows_not_unique")
    row = _mapping(raw_rows[0])
    if row is None:
        return _blocked(raw_body, body_sha256, body_size_bytes, "row_not_object")

    required_keys = (
        contract.row_security_code_key,
        contract.row_report_date_key,
        contract.row_notice_date_key,
        *(binding.raw_key for binding in contract.value_bindings),
    )
    if any(key not in row for key in required_keys):
        return _blocked(raw_body, body_sha256, body_size_bytes, "required_row_key_missing")
    raw_security_code = row.get(contract.row_security_code_key)
    if not isinstance(raw_security_code, str):
        return _blocked(raw_body, body_sha256, body_size_bytes, "security_code_not_text")
    raw_period = row.get(contract.row_report_date_key)
    report_date = _strict_date(raw_period)
    if report_date is None:
        return _blocked(raw_body, body_sha256, body_size_bytes, "report_date_invalid")
    raw_notice = row.get(contract.row_notice_date_key)
    notice_date = _strict_date(raw_notice)
    if notice_date is None:
        return _blocked(raw_body, body_sha256, body_size_bytes, "notice_date_invalid")

    projected_values: list[BalanceCandidateNativeValue] = []
    projection_pairs: list[tuple[str, str]] = [
        (contract.row_security_code_key, raw_security_code),
        (contract.row_report_date_key, cast(str, raw_period)),
        (contract.row_notice_date_key, cast(str, raw_notice)),
    ]
    for binding in contract.value_bindings:
        numeric_value = _strict_decimal(row.get(binding.raw_key))
        if numeric_value is None:
            return _blocked(raw_body, body_sha256, body_size_bytes, "native_value_invalid")
        projected_values.append(
            BalanceCandidateNativeValue(
                metric_code=binding.metric_code,
                raw_key=binding.raw_key,
                unit_code=binding.unit_code,
                value=numeric_value,
            )
        )
        projection_pairs.append((binding.raw_key, str(numeric_value)))

    projection = tuple(
        BalanceRawProjectionField(raw_key=key, raw_value_text=value)
        for key, value in projection_pairs
    )
    projection_digest = _projection_sha256(
        contract_id=contract.contract_id,
        body_sha256=body_sha256,
        row_index=0,
        fields=projection,
    )
    if raw_security_code != request.security_code:
        return _blocked(raw_body, body_sha256, body_size_bytes, "security_code_mismatch")
    if report_date != request.report_date:
        return _blocked(raw_body, body_sha256, body_size_bytes, "report_date_mismatch")
    try:
        raw_row_context = _freeze_json_mapping(row)
    except (TypeError, ValueError):
        return _blocked(raw_body, body_sha256, body_size_bytes, "row_context_invalid")

    identity = BalanceCandidateSourceRowIdentity(
        contract_id=contract.contract_id,
        report_name=contract.report_name,
        symbol=request.symbol,
        security_code=raw_security_code,
        report_date=report_date,
        notice_date=notice_date,
        row_index=0,
        row_projection_sha256=projection_digest,
    )
    return BalanceCandidateParseResult(
        outcome="candidate_parsed",
        raw_body=raw_body,
        body_sha256=body_sha256,
        body_size_bytes=body_size_bytes,
        row_index=0,
        raw_row_projection=projection,
        raw_row_context=raw_row_context,
        row_projection_sha256=projection_digest,
        source_row_identity=identity,
        values=tuple(projected_values),
        blocked_reason=None,
    )


def _blocked(
    raw_body: bytes,
    body_sha256: str,
    body_size_bytes: int,
    reason: str,
) -> BalanceCandidateParseResult:
    """Retain exact bytes while withholding any incomplete row projection."""

    return BalanceCandidateParseResult(
        outcome="blocked",
        raw_body=raw_body,
        body_sha256=body_sha256,
        body_size_bytes=body_size_bytes,
        row_index=None,
        raw_row_projection=(),
        raw_row_context=MappingProxyType({}),
        row_projection_sha256=None,
        source_row_identity=None,
        values=(),
        blocked_reason=reason,
    )


def _mapping(value: object) -> Mapping[str, object] | None:
    """Narrow JSON objects without exposing untyped values to callers."""

    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def _freeze_json_mapping(value: Mapping[str, object]) -> Mapping[str, BalanceRawJsonValue]:
    """Preserve the complete decoded source row as an immutable typed JSON value."""

    frozen: dict[str, BalanceRawJsonValue] = {}
    for key, item in value.items():
        if type(key) is not str:
            raise ValueError("raw row context keys must remain exact JSON strings")
        frozen[key] = _freeze_json_value(item)
    return MappingProxyType(frozen)


def _freeze_json_value(value: object) -> BalanceRawJsonValue:
    """Narrow decoded JSON values without converting source numerics or text."""

    if type(value) is str or type(value) is int or type(value) is bool or value is None:
        return cast(str | int | bool | None, value)
    if type(value) is Decimal:
        if not value.is_finite():
            raise ValueError("raw row JSON decimals must remain finite")
        return value
    if type(value) is list:
        raw_items = cast(list[object], value)
        return tuple(_freeze_json_value(item) for item in raw_items)
    if isinstance(value, Mapping):
        return _freeze_json_mapping(cast(Mapping[str, object], value))
    raise TypeError("raw row context contains a value outside the strict JSON boundary")


def _strict_date(value: object) -> date | None:
    """Accept date precision or the provider's zero-time date string only."""

    if not isinstance(value, str) or value != value.strip():
        return None
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is not None:
        date_text = value
    elif re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} 00:00:00", value) is not None:
        date_text = value[:10]
    else:
        return None
    try:
        return date.fromisoformat(date_text)
    except ValueError:
        return None


def _strict_decimal(value: object) -> Decimal | None:
    """Accept finite JSON decimal or integer values without scale guessing."""

    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    else:
        return None
    return decimal_value if decimal_value.is_finite() else None


def _same_json_scalar(actual: object, expected: JsonStatusValue) -> bool:
    """Compare response markers without Python's bool/integer equality alias."""

    return type(actual) is type(expected) and actual == expected


def _projection_sha256(
    *,
    contract_id: str,
    body_sha256: str,
    row_index: int,
    fields: tuple[BalanceRawProjectionField, ...],
) -> str:
    """Hash a deterministic selected-field projection bound to its exact body."""

    payload = {
        "contract_id": contract_id,
        "body_sha256": body_sha256,
        "row_index": row_index,
        "fields": [[field.raw_key, field.raw_value_text] for field in fields],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_text(value: object, field_name: str) -> str:
    """Validate exact contract text without trimming or rewriting it."""

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"{field_name} must be non-empty unpadded text")
    return value


__all__ = [
    "BalanceCandidateContract",
    "BalanceCandidateNativeValue",
    "BalanceCandidateParseResult",
    "BalanceCandidateQuery",
    "BalanceCandidateRequest",
    "BalanceCandidateSourceRowIdentity",
    "BalanceRawJsonValue",
    "BalanceRawProjectionField",
    "BalanceValueBinding",
    "build_balance_candidate_query",
    "parse_balance_candidate_body",
]
