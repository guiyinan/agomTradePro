"""Bounded retention of strict, successful Tushare table responses for rehearsal replay."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from core.exceptions import DataFetchError

RESPONSE_REF_SCHEMA: Literal["release.provider-response-artifact-ref.v1"] = (
    "release.provider-response-artifact-ref.v1"
)
PROVIDER_FORMAT: Literal["tushare_pro_table.v1"] = "tushare_pro_table.v1"

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_CANDIDATE_RE = re.compile(r"[0-9a-f]{40}")
_CODE_RE = re.compile(r"[0-9]{6}\.(?:SZ|SH|BJ)")
_DATE_RE = re.compile(r"[0-9]{8}")
_IDENTIFIER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}")
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,128}")

_QUOTE_FIELDS = frozenset(
    {
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    }
)
_VALUATION_FIELDS = frozenset(
    {
        "ts_code",
        "trade_date",
        "close",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "total_share",
        "float_share",
        "free_share",
        "total_mv",
        "circ_mv",
    }
)

SafeResponseValue = str | int | float | None
TushareResponseRow = dict[str, SafeResponseValue]


@dataclass(frozen=True)
class RehearsalResponseContext:
    """Bind one provider response to its candidate, universe and exact provider identity."""

    candidate_sha: str
    target_trade_date: str
    universe_sha256: str
    provider_identities_sha256: str
    provider_id: int
    provider_source: str
    endpoint_id: str
    dataset: Literal["equity.quote.snapshot", "equity.valuation.fact"]
    sample_codes: tuple[str, ...]
    provider_format: Literal["tushare_pro_table.v1"] = PROVIDER_FORMAT

    def __post_init__(self) -> None:
        """Reject malformed, secret-like or mismatched context before any response is stored."""
        if (
            not isinstance(self.candidate_sha, str)
            or _CANDIDATE_RE.fullmatch(self.candidate_sha) is None
        ):
            raise ValueError("REHEARSAL_RESPONSE_CONTEXT_INVALID")
        if not isinstance(self.target_trade_date, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", self.target_trade_date
        ):
            raise ValueError("REHEARSAL_RESPONSE_CONTEXT_INVALID")
        try:
            target_date = date.fromisoformat(self.target_trade_date)
        except ValueError as exc:
            raise ValueError("REHEARSAL_RESPONSE_CONTEXT_INVALID") from exc
        if target_date.isoformat() != self.target_trade_date:
            raise ValueError("REHEARSAL_RESPONSE_CONTEXT_INVALID")
        if (
            not isinstance(self.universe_sha256, str)
            or _SHA256_RE.fullmatch(self.universe_sha256) is None
            or not isinstance(self.provider_identities_sha256, str)
            or _SHA256_RE.fullmatch(self.provider_identities_sha256) is None
        ):
            raise ValueError("REHEARSAL_RESPONSE_CONTEXT_INVALID")
        if isinstance(self.provider_id, bool) or not isinstance(self.provider_id, int):
            raise ValueError("REHEARSAL_RESPONSE_CONTEXT_INVALID")
        if self.provider_id <= 0 or self.provider_source != "tushare":
            raise ValueError("REHEARSAL_RESPONSE_CONTEXT_INVALID")
        if (
            not isinstance(self.endpoint_id, str)
            or _IDENTIFIER_RE.fullmatch(self.endpoint_id) is None
        ):
            raise ValueError("REHEARSAL_RESPONSE_CONTEXT_INVALID")
        if self.provider_format != PROVIDER_FORMAT:
            raise ValueError("REHEARSAL_RESPONSE_FORMAT_UNSUPPORTED")
        if self.dataset not in ("equity.quote.snapshot", "equity.valuation.fact"):
            raise ValueError("REHEARSAL_RESPONSE_CONTEXT_INVALID")
        if (
            not isinstance(self.sample_codes, tuple)
            or not self.sample_codes
            or any(
                not isinstance(code, str) or _CODE_RE.fullmatch(code) is None
                for code in self.sample_codes
            )
            or tuple(sorted(set(self.sample_codes))) != self.sample_codes
        ):
            raise ValueError("REHEARSAL_RESPONSE_CONTEXT_INVALID")


@dataclass(frozen=True)
class RehearsalResponseArtifactRef:
    """Safe, relative receipt metadata for an exact retained provider response body."""

    schema: Literal["release.provider-response-artifact-ref.v1"]
    path: str
    body_sha256: str
    body_bytes: int
    receipt_index: int
    status_code: int
    method: str
    host: str
    path_sha256: str
    started_at: str
    finished_at: str
    candidate_sha: str
    target_trade_date: str
    universe_sha256: str
    provider_identities_sha256: str
    provider_id: int
    provider_source: str
    endpoint_id: str
    provider_format: Literal["tushare_pro_table.v1"]
    dataset: Literal["equity.quote.snapshot", "equity.valuation.fact"]
    sample_codes: tuple[str, ...]


def parse_validate_tushare_response(
    response_body: bytes, context: RehearsalResponseContext
) -> tuple[TushareResponseRow, ...]:
    """Parse a strict successful Tushare daily/daily_basic envelope without changing its bytes."""
    if not isinstance(response_body, bytes) or not response_body:
        raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID")
    allowed_fields = (
        _QUOTE_FIELDS if context.dataset == "equity.quote.snapshot" else _VALUATION_FIELDS
    )
    try:
        decoded = response_body.decode("utf-8", errors="strict")
        root: object = json.loads(decoded, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID") from exc
    envelope = _as_object(root)
    if set(envelope) - {"request_id", "code", "msg", "data"}:
        raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID")
    code = envelope.get("code")
    if type(code) is not int or code != 0:
        raise ValueError("REHEARSAL_RESPONSE_NOT_SUCCESS")
    message = envelope.get("msg", "")
    if message is not None and (not isinstance(message, str) or message != ""):
        raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID")
    request_id = envelope.get("request_id")
    if request_id is not None and (
        not isinstance(request_id, str) or _REQUEST_ID_RE.fullmatch(request_id) is None
    ):
        raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID")
    data = _as_object(envelope.get("data"))
    if set(data) - {"fields", "items", "has_more"}:
        raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID")
    if "fields" not in data or "items" not in data:
        raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID")
    has_more = data.get("has_more", False)
    if type(has_more) is not bool or has_more:
        raise ValueError("REHEARSAL_RESPONSE_INCOMPLETE")
    raw_fields = data["fields"]
    raw_items = data["items"]
    if not isinstance(raw_fields, list) or not raw_fields or not isinstance(raw_items, list):
        raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID")
    fields: list[str] = []
    for raw_field in raw_fields:
        if not isinstance(raw_field, str) or raw_field not in allowed_fields:
            raise ValueError("REHEARSAL_RESPONSE_FIELD_UNSUPPORTED")
        fields.append(raw_field)
    if len(set(fields)) != len(fields) or "ts_code" not in fields or "trade_date" not in fields:
        raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID")
    target_date = date.fromisoformat(context.target_trade_date)
    rows: list[TushareResponseRow] = []
    for raw_row in raw_items:
        if not isinstance(raw_row, list) or len(raw_row) != len(fields):
            raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID")
        row: TushareResponseRow = {}
        for field, value in zip(fields, raw_row, strict=True):
            if field == "ts_code":
                if not isinstance(value, str) or _CODE_RE.fullmatch(value) is None:
                    raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID")
                row[field] = value
            elif field == "trade_date":
                if not isinstance(value, str) or _DATE_RE.fullmatch(value) is None:
                    raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID")
                try:
                    row_date = datetime.strptime(value, "%Y%m%d").date()
                except ValueError as exc:
                    raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID") from exc
                if row_date > target_date:
                    raise ValueError("REHEARSAL_RESPONSE_FUTURE_DATE")
                row[field] = value
            elif value is None:
                row[field] = None
            elif type(value) is int or type(value) is float:
                try:
                    if not math.isfinite(float(value)):
                        raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID")
                except OverflowError as exc:
                    raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID") from exc
                row[field] = value
            else:
                raise ValueError("REHEARSAL_RESPONSE_VALUE_UNSUPPORTED")
        rows.append(row)
    return tuple(rows)


class RehearsalResponseStore:
    """Write explicit, validated provider bodies under strict exclusive file and byte budgets."""

    def __init__(
        self,
        root: Path,
        *,
        max_responses: int,
        max_response_bytes: int,
        max_total_bytes: int,
    ) -> None:
        """Bind retention to an existing, caller-owned evidence directory and bounded budgets."""
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (max_responses, max_response_bytes, max_total_bytes)
        ):
            raise ValueError("REHEARSAL_RESPONSE_BUDGET_INVALID")
        if not root.exists() or not root.is_dir():
            raise ValueError("REHEARSAL_RESPONSE_ROOT_UNAVAILABLE")
        self.root = root.resolve(strict=True)
        self.max_responses = max_responses
        self.max_response_bytes = max_response_bytes
        self.max_total_bytes = max_total_bytes
        self._response_count = 0
        self._total_bytes = 0
        self._lock = threading.Lock()

    def persist_response(
        self,
        context: RehearsalResponseContext,
        *,
        receipt_index: int,
        host: str,
        path_sha256: str,
        method: str,
        started_at: str,
        finished_at: str,
        status_code: int,
        response_body: bytes,
    ) -> RehearsalResponseArtifactRef:
        """Retain one validated HTTP 200 body and return its safe relative artifact reference."""
        if (
            isinstance(receipt_index, bool)
            or not isinstance(receipt_index, int)
            or receipt_index < 0
            or status_code != 200
            or isinstance(status_code, bool)
            or method not in ("GET", "POST")
            or not host
            or len(host) > 253
            or re.fullmatch(r"[A-Za-z0-9.:-]+", host) is None
            or not isinstance(path_sha256, str)
            or _SHA256_RE.fullmatch(path_sha256) is None
            or not _is_aware_iso8601(started_at)
            or not _is_aware_iso8601(finished_at)
        ):
            raise DataFetchError(
                "Rehearsal response receipt is invalid", code="REHEARSAL_RESPONSE_RECEIPT_INVALID"
            )
        if not isinstance(response_body, bytes) or not response_body:
            raise DataFetchError(
                "Rehearsal response body is unavailable", code="REHEARSAL_RESPONSE_BODY_INVALID"
            )
        if len(response_body) > self.max_response_bytes:
            raise DataFetchError(
                "Rehearsal response exceeds its byte budget",
                code="REHEARSAL_RESPONSE_BODY_LIMIT",
            )
        try:
            parse_validate_tushare_response(response_body, context)
        except ValueError as exc:
            raise DataFetchError(
                "Rehearsal response is not a supported successful table",
                code="REHEARSAL_RESPONSE_NOT_RETAINABLE",
            ) from exc
        body_sha256 = hashlib.sha256(response_body).hexdigest()
        relative_path = f"provider-responses/{receipt_index:04d}-{body_sha256}.body"
        responses_dir = self.root / "provider-responses"
        with self._lock:
            if self._response_count >= self.max_responses:
                raise DataFetchError(
                    "Rehearsal response count budget exhausted",
                    code="REHEARSAL_RESPONSE_COUNT_LIMIT",
                )
            if self._total_bytes + len(response_body) > self.max_total_bytes:
                raise DataFetchError(
                    "Rehearsal total response byte budget exhausted",
                    code="REHEARSAL_RESPONSE_TOTAL_LIMIT",
                )
            if responses_dir.exists():
                if responses_dir.is_symlink() or not responses_dir.is_dir():
                    raise DataFetchError(
                        "Rehearsal response directory is unsafe",
                        code="REHEARSAL_RESPONSE_DIRECTORY_INVALID",
                    )
            else:
                try:
                    responses_dir.mkdir(mode=0o700)
                except FileExistsError:
                    if responses_dir.is_symlink() or not responses_dir.is_dir():
                        raise DataFetchError(
                            "Rehearsal response directory is unsafe",
                            code="REHEARSAL_RESPONSE_DIRECTORY_INVALID",
                        ) from None
                except OSError as exc:
                    raise DataFetchError(
                        "Rehearsal response directory could not be created",
                        code="REHEARSAL_RESPONSE_WRITE_FAILED",
                    ) from exc
            try:
                if responses_dir.resolve(strict=True).parent != self.root:
                    raise DataFetchError(
                        "Rehearsal response directory escapes its root",
                        code="REHEARSAL_RESPONSE_DIRECTORY_INVALID",
                    )
            except OSError as exc:
                raise DataFetchError(
                    "Rehearsal response directory is unavailable",
                    code="REHEARSAL_RESPONSE_DIRECTORY_INVALID",
                ) from exc
            path = self.root / relative_path
            created = False
            descriptor: int | None = None
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            try:
                descriptor = os.open(path, flags, 0o600)
                created = True
                with os.fdopen(descriptor, "wb") as stream:
                    descriptor = None
                    written = stream.write(response_body)
                    if written != len(response_body):
                        raise OSError("short response write")
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError as exc:
                raise DataFetchError(
                    "Rehearsal response artifact already exists",
                    code="REHEARSAL_RESPONSE_ARTIFACT_EXISTS",
                ) from exc
            except OSError as exc:
                if descriptor is not None:
                    os.close(descriptor)
                if created:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise DataFetchError(
                    "Rehearsal response artifact write failed",
                    code="REHEARSAL_RESPONSE_WRITE_FAILED",
                ) from exc
            self._response_count += 1
            self._total_bytes += len(response_body)
        return RehearsalResponseArtifactRef(
            schema=RESPONSE_REF_SCHEMA,
            path=relative_path,
            body_sha256=body_sha256,
            body_bytes=len(response_body),
            receipt_index=receipt_index,
            status_code=status_code,
            method=method,
            host=host,
            path_sha256=path_sha256,
            started_at=started_at,
            finished_at=finished_at,
            candidate_sha=context.candidate_sha,
            target_trade_date=context.target_trade_date,
            universe_sha256=context.universe_sha256,
            provider_identities_sha256=context.provider_identities_sha256,
            provider_id=context.provider_id,
            provider_source=context.provider_source,
            endpoint_id=context.endpoint_id,
            provider_format=context.provider_format,
            dataset=context.dataset,
            sample_codes=context.sample_codes,
        )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build a JSON object while rejecting duplicate keys at every nesting level."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _as_object(value: object) -> dict[str, object]:
    """Narrow a parsed JSON value to a string-keyed object."""
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("REHEARSAL_RESPONSE_SCHEMA_INVALID")
    return value


def _is_aware_iso8601(value: str) -> bool:
    """Return whether a timestamp is bounded ISO 8601 with an explicit UTC offset."""
    if not isinstance(value, str) or len(value) > 64:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None
