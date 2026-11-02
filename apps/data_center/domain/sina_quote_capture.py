"""Exact, source-clocked captures of Sina's public A-share quote response."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import TypedDict, cast
from zoneinfo import ZoneInfo

SINA_QUOTE_REQUEST_PREFIX = "https://hq.sinajs.cn/list="
SINA_QUOTE_SOURCE_ID = "sina_public_quote"
SINA_VENDOR_STATUS_MAPPING_SHA256 = (
    "f41849458131169afb92f0ea1b266841052419867f9ea3b363e0fafaa4ebc3ee"
)
MAX_SINA_QUOTE_RESPONSE_BYTES = 65_536
_ASSET_CODE_RE = re.compile(r"(?P<digits>[0-9]{6})\.(?P<market>SH|SZ)\Z")
_SINA_LINE_RE = re.compile(
    r'\s*var\s+hq_str_(?P<market>sh|sz)(?P<digits>[0-9]{6})="(?P<value>[^"]*)";?\s*\Z'
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SINA_TIMEZONE = ZoneInfo("Asia/Shanghai")
_SOURCE_STATUS_LABELS: dict[str, str] = {
    "00": "",
    "01": "临停1H",
    "02": "停牌",
    "03": "停牌",
    "04": "临停",
    "05": "停1/2",
    "07": "暂停",
    "-1": "无记录",
    "-2": "未上市",
    "-3": "退市",
}
_SOURCE_STATUS_STATES: dict[str, SinaReportedTradingState] = {}


class SinaQuoteCaptureValidationError(ValueError):
    """Raised when a Sina request or retained capture violates its exact contract."""


class SinaQuoteClockStatus(StrEnum):
    """Parse and chronology status of the vendor's own date/time fields."""

    VALID = "valid"
    MISSING = "missing"
    INVALID = "invalid"
    FUTURE = "future"


class SinaReportedTradingState(StrEnum):
    """State reported by Sina's captured page parser, not by an exchange."""

    TRADING = "trading"
    SUSPENDED = "suspended"
    DELISTED = "delisted"
    NOT_LISTED = "not_listed"
    NO_RECORD = "no_record"
    UNKNOWN = "unknown"


class SinaQuoteCaptureIssue(StrEnum):
    """Stable parse blockers for one retained source response."""

    HTTP_STATUS_NOT_SUCCESS = "http_status_not_success"
    UNEXPECTED_URL = "unexpected_url"
    UNEXPECTED_CONTENT_TYPE = "unexpected_content_type"
    UNSUPPORTED_CHARSET = "unsupported_charset"
    UNSUPPORTED_CONTENT_ENCODING = "unsupported_content_encoding"
    INVALID_TEXT_ENCODING = "invalid_text_encoding"
    MALFORMED_RESPONSE = "malformed_response"
    QUOTE_NOT_FOUND = "quote_not_found"
    DUPLICATE_QUOTE = "duplicate_quote"


_SOURCE_STATUS_STATES.update(
    {
        "00": SinaReportedTradingState.TRADING,
        "01": SinaReportedTradingState.SUSPENDED,
        "02": SinaReportedTradingState.SUSPENDED,
        "03": SinaReportedTradingState.SUSPENDED,
        "04": SinaReportedTradingState.SUSPENDED,
        "05": SinaReportedTradingState.SUSPENDED,
        "07": SinaReportedTradingState.SUSPENDED,
        "-1": SinaReportedTradingState.NO_RECORD,
        "-2": SinaReportedTradingState.NOT_LISTED,
        "-3": SinaReportedTradingState.DELISTED,
    }
)


class SinaQuoteCapturePayload(TypedDict):
    """Exact JSON fields that can reconstruct one retained Sina response."""

    schema: str
    asset_code: str
    requested_url: str
    final_url: str
    request_started_at: str
    response_completed_at: str
    http_status: int
    http_date: str | None
    content_type: str | None
    charset: str | None
    content_encoding: str | None
    body_base64: str
    body_size_bytes: int
    body_sha256: str
    parse_issue: str | None


@dataclass(frozen=True, slots=True)
class SinaQuoteObservation:
    """One Sina vendor row with independent source time and reported status."""

    asset_code: str
    source_symbol: str
    name: str
    source_date_text: str
    source_time_text: str
    source_observed_at: datetime | None
    source_clock_status: SinaQuoteClockStatus
    vendor_status_code: str | None
    vendor_status_label: str | None
    reported_trading_state: SinaReportedTradingState
    open_price: Decimal | None
    previous_close: Decimal | None
    last_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    bid_price: Decimal | None
    ask_price: Decimal | None
    volume: Decimal | None
    amount: Decimal | None

    def __post_init__(self) -> None:
        """Require source-native values and consistent clock/status shapes."""

        _require_asset_code(self.asset_code)
        expected_symbol = _source_symbol(self.asset_code)
        if type(self.source_symbol) is not str or self.source_symbol != expected_symbol:
            raise SinaQuoteCaptureValidationError("quote source symbol does not match asset")
        if type(self.name) is not str or len(self.name) > 256:
            raise SinaQuoteCaptureValidationError("quote name is invalid")
        for field_name, value in (
            ("source_date_text", self.source_date_text),
            ("source_time_text", self.source_time_text),
        ):
            if type(value) is not str or len(value) > 32:
                raise SinaQuoteCaptureValidationError(f"{field_name} is invalid")
        if type(self.source_clock_status) is not SinaQuoteClockStatus:
            raise SinaQuoteCaptureValidationError("quote source clock status is invalid")
        if self.source_clock_status in (SinaQuoteClockStatus.VALID, SinaQuoteClockStatus.FUTURE):
            _require_shanghai_datetime(self.source_observed_at)
        elif self.source_observed_at is not None:
            raise SinaQuoteCaptureValidationError("invalid source clock must not carry an instant")
        if self.source_clock_status is SinaQuoteClockStatus.MISSING and (
            self.source_date_text or self.source_time_text
        ):
            raise SinaQuoteCaptureValidationError("missing source clock has source text")
        if self.source_clock_status is SinaQuoteClockStatus.INVALID and not (
            self.source_date_text or self.source_time_text
        ):
            raise SinaQuoteCaptureValidationError("invalid source clock has no source text")
        if self.vendor_status_code is None:
            if self.vendor_status_label is not None:
                raise SinaQuoteCaptureValidationError("missing status cannot carry a label")
            if self.reported_trading_state is not SinaReportedTradingState.UNKNOWN:
                raise SinaQuoteCaptureValidationError("missing status must remain unknown")
        else:
            if type(self.vendor_status_code) is not str or len(self.vendor_status_code) > 8:
                raise SinaQuoteCaptureValidationError("vendor status code is invalid")
            if self.vendor_status_label != _SOURCE_STATUS_LABELS.get(self.vendor_status_code):
                raise SinaQuoteCaptureValidationError("vendor status label differs from mapping")
            expected_state = _SOURCE_STATUS_STATES.get(
                self.vendor_status_code, SinaReportedTradingState.UNKNOWN
            )
            if self.reported_trading_state is not expected_state:
                raise SinaQuoteCaptureValidationError("vendor status state differs from mapping")
        if type(self.reported_trading_state) is not SinaReportedTradingState:
            raise SinaQuoteCaptureValidationError("vendor trading state is invalid")
        for field_name in (
            "open_price",
            "previous_close",
            "last_price",
            "high_price",
            "low_price",
            "bid_price",
            "ask_price",
        ):
            _require_optional_decimal(getattr(self, field_name), field_name, positive=True)
        _require_optional_decimal(self.volume, "volume", positive=False)
        _require_optional_decimal(self.amount, "amount", positive=False)


@dataclass(frozen=True, slots=True)
class SinaQuoteCapture:
    """One bounded HTTP body and its same-response parse, clocks, and digest.

    ``body`` is the exact application response byte sequence delivered by the
    transport. ``response_completed_at`` is a local receipt clock and never
    substitutes for the Sina row's ``source_observed_at``.
    """

    asset_code: str
    requested_url: str
    final_url: str
    request_started_at: datetime
    response_completed_at: datetime
    http_status: int
    http_date: str | None
    content_type: str | None
    charset: str | None
    content_encoding: str | None
    body: bytes = field(repr=False)
    body_sha256: str
    body_size_bytes: int
    quote: SinaQuoteObservation | None
    parse_issue: SinaQuoteCaptureIssue | None

    def __post_init__(self) -> None:
        """Validate body identity, request scope, clocks, and parse outcome."""

        _require_asset_code(self.asset_code)
        expected_url = build_sina_quote_request_url(self.asset_code)
        for field_name, url_value in (
            ("requested_url", self.requested_url),
            ("final_url", self.final_url),
        ):
            if type(url_value) is not str or not url_value or len(url_value) > 2048:
                raise SinaQuoteCaptureValidationError(f"{field_name} is invalid")
        if expected_url != self.requested_url and self.parse_issue is None:
            raise SinaQuoteCaptureValidationError(
                "unexpected request URL cannot have a parsed quote"
            )
        for field_name, clock_value in (
            ("request_started_at", self.request_started_at),
            ("response_completed_at", self.response_completed_at),
        ):
            _require_utc_datetime(clock_value, field_name)
        if self.response_completed_at < self.request_started_at:
            raise SinaQuoteCaptureValidationError("response completion precedes request start")
        if type(self.http_status) is not int or not 100 <= self.http_status <= 599:
            raise SinaQuoteCaptureValidationError("HTTP status is invalid")
        for field_name, header_value in (
            ("http_date", self.http_date),
            ("content_type", self.content_type),
            ("charset", self.charset),
            ("content_encoding", self.content_encoding),
        ):
            _require_optional_header_text(header_value, field_name)
        if type(self.body) is not bytes:
            raise SinaQuoteCaptureValidationError("response body must be bytes")
        if len(self.body) > MAX_SINA_QUOTE_RESPONSE_BYTES:
            raise SinaQuoteCaptureValidationError("response body exceeds the capture bound")
        if type(self.body_sha256) is not str or _SHA256_RE.fullmatch(self.body_sha256) is None:
            raise SinaQuoteCaptureValidationError("response SHA-256 is invalid")
        if hashlib.sha256(self.body).hexdigest() != self.body_sha256:
            raise SinaQuoteCaptureValidationError("response body SHA-256 does not match")
        if type(self.body_size_bytes) is not int or self.body_size_bytes != len(self.body):
            raise SinaQuoteCaptureValidationError("response body size does not match")
        if (self.quote is None) != (self.parse_issue is not None):
            raise SinaQuoteCaptureValidationError("parse issue and quote presence are inconsistent")
        if self.quote is not None:
            if (
                type(self.quote) is not SinaQuoteObservation
                or self.quote.asset_code != self.asset_code
            ):
                raise SinaQuoteCaptureValidationError("parsed quote is not bound to request asset")
            self.quote.__post_init__()
            if (
                self.requested_url != expected_url
                or self.final_url != expected_url
                or not 200 <= self.http_status < 300
                or _content_type_mime(self.content_type)
                not in {"application/javascript", "text/javascript"}
                or _normalize_charset(self.charset) is None
                or (self.content_encoding or "").strip().lower() not in {"", "identity"}
            ):
                raise SinaQuoteCaptureValidationError("parsed quote response metadata is unusable")
            expected_observed_at, expected_clock_status = _source_observation_time(
                self.quote.source_date_text,
                self.quote.source_time_text,
                response_completed_at=self.response_completed_at,
            )
            if (
                self.quote.source_observed_at != expected_observed_at
                or self.quote.source_clock_status is not expected_clock_status
            ):
                raise SinaQuoteCaptureValidationError(
                    "source clock does not match retained row fields"
                )
            observed_at = self.quote.source_observed_at
            if observed_at is not None:
                is_future = observed_at.astimezone(UTC) > self.response_completed_at
                expected_clock_status = (
                    SinaQuoteClockStatus.FUTURE if is_future else SinaQuoteClockStatus.VALID
                )
                if self.quote.source_clock_status is not expected_clock_status:
                    raise SinaQuoteCaptureValidationError("source clock chronology is inconsistent")
        elif type(self.parse_issue) is not SinaQuoteCaptureIssue:
            raise SinaQuoteCaptureValidationError("capture parse issue is unrecognized")

    @property
    def usable_parse(self) -> bool:
        """Return whether one successful HTTP response produced a quote row."""

        return 200 <= self.http_status < 300 and self.quote is not None and self.parse_issue is None

    @property
    def body_base64(self) -> str:
        """Return the retained response bytes in a JSON-safe representation."""

        return base64.b64encode(self.body).decode("ascii")

    def to_payload(self) -> SinaQuoteCapturePayload:
        """Return exact response evidence suitable for a server-signed preview."""

        self.__post_init__()
        return {
            "schema": "sina-quote-capture.v1",
            "asset_code": self.asset_code,
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "request_started_at": _utc_text(self.request_started_at),
            "response_completed_at": _utc_text(self.response_completed_at),
            "http_status": self.http_status,
            "http_date": self.http_date,
            "content_type": self.content_type,
            "charset": self.charset,
            "content_encoding": self.content_encoding,
            "body_base64": self.body_base64,
            "body_size_bytes": self.body_size_bytes,
            "body_sha256": self.body_sha256,
            "parse_issue": self.parse_issue.value if self.parse_issue is not None else None,
        }

    @classmethod
    def from_payload(cls, payload: object) -> SinaQuoteCapture:
        """Rebuild from signed-preview fields and reparse the retained exact body."""

        values = _capture_payload_object(payload)
        body_text = values["body_base64"]
        maximum_encoded_size = ((MAX_SINA_QUOTE_RESPONSE_BYTES + 2) // 3) * 4
        if len(body_text) > maximum_encoded_size:
            raise SinaQuoteCaptureValidationError("response body exceeds the capture bound")
        try:
            body = base64.b64decode(body_text, validate=True)
        except (binascii.Error, ValueError) as error:
            raise SinaQuoteCaptureValidationError("response body base64 is invalid") from error
        if len(body) > MAX_SINA_QUOTE_RESPONSE_BYTES:
            raise SinaQuoteCaptureValidationError("response body exceeds the capture bound")
        if len(body) != values["body_size_bytes"]:
            raise SinaQuoteCaptureValidationError("response body size does not match")
        if hashlib.sha256(body).hexdigest() != values["body_sha256"]:
            raise SinaQuoteCaptureValidationError("response body SHA-256 does not match")
        rebuilt = parse_sina_quote_capture(
            asset_code=values["asset_code"],
            requested_url=values["requested_url"],
            final_url=values["final_url"],
            request_started_at=_parse_utc_text(values["request_started_at"]),
            response_completed_at=_parse_utc_text(values["response_completed_at"]),
            http_status=values["http_status"],
            http_date=values["http_date"],
            content_type=values["content_type"],
            charset=values["charset"],
            content_encoding=values["content_encoding"],
            body=body,
        )
        if rebuilt.to_payload() != values:
            raise SinaQuoteCaptureValidationError("capture payload differs from parsed source body")
        return rebuilt


def build_sina_quote_request_url(asset_code: str) -> str:
    """Build the exact public Sina URL for one canonical SH or SZ asset."""

    digits, market = _require_asset_code(asset_code)
    return f"{SINA_QUOTE_REQUEST_PREFIX}{market.lower()}{digits}"


def parse_sina_quote_capture(
    *,
    asset_code: str,
    requested_url: str,
    final_url: str,
    request_started_at: datetime,
    response_completed_at: datetime,
    http_status: int,
    http_date: str | None,
    content_type: str | None,
    charset: str | None,
    content_encoding: str | None,
    body: bytes,
) -> SinaQuoteCapture:
    """Bind one transport response to its exact request, raw body, and Sina row."""

    _require_asset_code(asset_code)
    issue: SinaQuoteCaptureIssue | None = None
    quote: SinaQuoteObservation | None = None
    expected_url = build_sina_quote_request_url(asset_code)
    if not 200 <= http_status < 300:
        issue = SinaQuoteCaptureIssue.HTTP_STATUS_NOT_SUCCESS
    elif requested_url != expected_url or final_url != expected_url:
        issue = SinaQuoteCaptureIssue.UNEXPECTED_URL
    elif _content_type_mime(content_type) not in {"application/javascript", "text/javascript"}:
        issue = SinaQuoteCaptureIssue.UNEXPECTED_CONTENT_TYPE
    elif content_encoding and content_encoding.strip().lower() not in {"", "identity"}:
        issue = SinaQuoteCaptureIssue.UNSUPPORTED_CONTENT_ENCODING
    elif _normalize_charset(charset) is None:
        issue = SinaQuoteCaptureIssue.UNSUPPORTED_CHARSET
    else:
        normalized_charset = _normalize_charset(charset)
        if normalized_charset is None:
            issue = SinaQuoteCaptureIssue.UNSUPPORTED_CHARSET
        else:
            try:
                text = body.decode(normalized_charset)
            except UnicodeError:
                issue = SinaQuoteCaptureIssue.INVALID_TEXT_ENCODING
            else:
                parsed, issue = _parse_quote_text(
                    text,
                    asset_code=asset_code,
                    response_completed_at=response_completed_at,
                )
                quote = parsed
    return SinaQuoteCapture(
        asset_code=asset_code,
        requested_url=requested_url,
        final_url=final_url,
        request_started_at=request_started_at,
        response_completed_at=response_completed_at,
        http_status=http_status,
        http_date=http_date,
        content_type=content_type,
        charset=charset,
        content_encoding=content_encoding,
        body=body,
        body_sha256=hashlib.sha256(body).hexdigest(),
        body_size_bytes=len(body),
        quote=quote,
        parse_issue=issue,
    )


def _parse_quote_text(
    text: str,
    *,
    asset_code: str,
    response_completed_at: datetime,
) -> tuple[SinaQuoteObservation | None, SinaQuoteCaptureIssue | None]:
    """Parse exactly one requested assignment without inferring extra fields."""

    expected_symbol = _source_symbol(asset_code)
    matched_rows: list[tuple[str, str]] = []
    nonempty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not nonempty_lines:
        return None, SinaQuoteCaptureIssue.MALFORMED_RESPONSE
    for line in nonempty_lines:
        matched = _SINA_LINE_RE.fullmatch(line)
        if matched is None:
            return None, SinaQuoteCaptureIssue.MALFORMED_RESPONSE
        symbol = matched.group("market") + matched.group("digits")
        matched_rows.append((symbol, matched.group("value")))
    requested_rows = [row for row in matched_rows if row[0] == expected_symbol]
    if not requested_rows:
        return None, SinaQuoteCaptureIssue.QUOTE_NOT_FOUND
    if len(requested_rows) != 1 or len(matched_rows) != 1:
        return None, SinaQuoteCaptureIssue.DUPLICATE_QUOTE
    try:
        return (
            _parse_quote_fields(
                asset_code=asset_code,
                source_symbol=requested_rows[0][0],
                value=requested_rows[0][1],
                response_completed_at=response_completed_at,
            ),
            None,
        )
    except (InvalidOperation, SinaQuoteCaptureValidationError, ValueError):
        return None, SinaQuoteCaptureIssue.MALFORMED_RESPONSE


def _parse_quote_fields(
    *,
    asset_code: str,
    source_symbol: str,
    value: str,
    response_completed_at: datetime,
) -> SinaQuoteObservation:
    """Normalize only Sina fields whose meanings are retained by its page parser."""

    fields = value.split(",")
    if len(fields) < 33 or len(fields) > 128:
        raise SinaQuoteCaptureValidationError(
            "quote row field count is outside the supported bound"
        )
    name = fields[0]
    date_text = fields[30]
    time_text = fields[31]
    observed_at, clock_status = _source_observation_time(
        date_text,
        time_text,
        response_completed_at=response_completed_at,
    )
    status_code = fields[32].strip() or None
    status_label = _SOURCE_STATUS_LABELS.get(status_code) if status_code is not None else None
    reported_state = (
        _SOURCE_STATUS_STATES.get(status_code, SinaReportedTradingState.UNKNOWN)
        if status_code is not None
        else SinaReportedTradingState.UNKNOWN
    )
    return SinaQuoteObservation(
        asset_code=asset_code,
        source_symbol=source_symbol,
        name=name,
        source_date_text=date_text,
        source_time_text=time_text,
        source_observed_at=observed_at,
        source_clock_status=clock_status,
        vendor_status_code=status_code,
        vendor_status_label=status_label,
        reported_trading_state=reported_state,
        open_price=_parse_price(fields[1], "open_price"),
        previous_close=_parse_price(fields[2], "previous_close"),
        last_price=_parse_price(fields[3], "last_price"),
        high_price=_parse_price(fields[4], "high_price"),
        low_price=_parse_price(fields[5], "low_price"),
        bid_price=_parse_price(fields[6], "bid_price"),
        ask_price=_parse_price(fields[7], "ask_price"),
        volume=_parse_nonnegative(fields[8], "volume"),
        amount=_parse_nonnegative(fields[9], "amount"),
    )


def _source_observation_time(
    source_date_text: str,
    source_time_text: str,
    *,
    response_completed_at: datetime,
) -> tuple[datetime | None, SinaQuoteClockStatus]:
    """Parse only Sina's date/time pair, keeping missing and malformed explicit."""

    if not source_date_text and not source_time_text:
        return None, SinaQuoteClockStatus.MISSING
    try:
        parsed_date = date.fromisoformat(source_date_text)
        parsed_time = datetime.strptime(source_time_text, "%H:%M:%S").time()
        if (
            parsed_date.isoformat() != source_date_text
            or parsed_time.strftime("%H:%M:%S") != source_time_text
        ):
            return None, SinaQuoteClockStatus.INVALID
    except (TypeError, ValueError):
        return None, SinaQuoteClockStatus.INVALID
    observed_at = datetime.combine(parsed_date, parsed_time, tzinfo=_SINA_TIMEZONE)
    if observed_at.astimezone(UTC) > response_completed_at:
        return observed_at, SinaQuoteClockStatus.FUTURE
    return observed_at, SinaQuoteClockStatus.VALID


def _parse_price(value: str, field_name: str) -> Decimal | None:
    """Parse one positive quote; zero and explicit blanks remain unknown values."""

    parsed = _parse_nonnegative(value, field_name)
    return parsed if parsed is not None and parsed > 0 else None


def _parse_nonnegative(value: str, field_name: str) -> Decimal | None:
    """Parse one finite nonnegative vendor number without float conversion."""

    text = value.strip()
    if not text or text in {"--", "-"}:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation as error:
        raise SinaQuoteCaptureValidationError(f"{field_name} is not decimal") from error
    if not parsed.is_finite() or parsed < 0:
        raise SinaQuoteCaptureValidationError(f"{field_name} is not a finite nonnegative decimal")
    parts = parsed.as_tuple()
    if len(parts.digits) > 64 or type(parts.exponent) is not int or abs(parts.exponent) > 64:
        raise SinaQuoteCaptureValidationError(f"{field_name} exceeds the decimal bound")
    return parsed


def _require_optional_decimal(value: Decimal | None, field_name: str, *, positive: bool) -> None:
    """Validate one optional exact finite numeric source field."""

    if value is None:
        return
    if type(value) is not Decimal or not value.is_finite():
        raise SinaQuoteCaptureValidationError(f"{field_name} must be a finite Decimal")
    if (positive and value <= 0) or (not positive and value < 0):
        raise SinaQuoteCaptureValidationError(f"{field_name} is outside its supported range")
    parts = value.as_tuple()
    if len(parts.digits) > 64 or type(parts.exponent) is not int or abs(parts.exponent) > 64:
        raise SinaQuoteCaptureValidationError(f"{field_name} exceeds the decimal bound")


def _require_asset_code(value: object) -> tuple[str, str]:
    """Return digits and market for one canonical Sina-supported A-share code."""

    if type(value) is not str:
        raise SinaQuoteCaptureValidationError("asset_code must be canonical SH/SZ text")
    matched = _ASSET_CODE_RE.fullmatch(value)
    if matched is None:
        raise SinaQuoteCaptureValidationError("asset_code must be canonical SH/SZ text")
    return matched.group("digits"), matched.group("market")


def _source_symbol(asset_code: str) -> str:
    """Map one canonical market code to Sina's lower-case source symbol."""

    digits, market = _require_asset_code(asset_code)
    return f"{market.lower()}{digits}"


def _require_utc_datetime(value: object, field_name: str) -> None:
    """Require an aware clock whose UTC offset is exactly zero."""

    if type(value) is not datetime or value.tzinfo is None:
        raise SinaQuoteCaptureValidationError(f"{field_name} must be timezone-aware")
    offset = value.utcoffset()
    if offset is None:
        raise SinaQuoteCaptureValidationError(f"{field_name} must be timezone-aware")
    if offset.total_seconds() != 0:
        raise SinaQuoteCaptureValidationError(f"{field_name} must be UTC")


def _require_shanghai_datetime(value: object) -> None:
    """Require the original Sina observation with its named Shanghai zone."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise SinaQuoteCaptureValidationError("source observation must be timezone-aware")
    if getattr(value.tzinfo, "key", None) != "Asia/Shanghai":
        raise SinaQuoteCaptureValidationError("source observation must retain Asia/Shanghai")


def _require_optional_header_text(value: object, field_name: str) -> None:
    """Bound untrusted HTTP metadata while retaining the original header value."""

    if value is None:
        return
    if (
        type(value) is not str
        or len(value) > 2048
        or any(ord(character) < 32 and character not in "\t" for character in value)
    ):
        raise SinaQuoteCaptureValidationError(f"{field_name} is invalid")


def _content_type_mime(value: str | None) -> str | None:
    """Return the source media type without interpreting its charset parameter."""

    if value is None:
        return None
    return value.split(";", 1)[0].strip().lower()


def _normalize_charset(value: str | None) -> str | None:
    """Allow only explicitly supported charsets observed from Sina responses."""

    if value is None:
        return None
    normalized = value.strip().lower().replace("_", "-")
    if normalized in {"gb18030", "gbk", "gb2312", "utf-8", "utf-8-sig"}:
        return normalized
    return None


def _utc_text(value: datetime) -> str:
    """Serialize one validated UTC clock using canonical Z notation."""

    _require_utc_datetime(value, "clock")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc_text(value: str) -> datetime:
    """Parse only canonical UTC payload clocks."""

    if not value.endswith("Z"):
        raise SinaQuoteCaptureValidationError("capture clock must use canonical UTC text")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise SinaQuoteCaptureValidationError("capture clock is invalid") from error
    _require_utc_datetime(parsed, "capture clock")
    if _utc_text(parsed) != value:
        raise SinaQuoteCaptureValidationError("capture clock is not canonical")
    return parsed


def _capture_payload_object(payload: object) -> SinaQuoteCapturePayload:
    """Type-check a signed JSON boundary and reject unknown capture fields."""

    expected = frozenset(
        {
            "schema",
            "asset_code",
            "requested_url",
            "final_url",
            "request_started_at",
            "response_completed_at",
            "http_status",
            "http_date",
            "content_type",
            "charset",
            "content_encoding",
            "body_base64",
            "body_size_bytes",
            "body_sha256",
            "parse_issue",
        }
    )
    if type(payload) is not dict or frozenset(payload) != expected:
        raise SinaQuoteCaptureValidationError("capture payload fields are incomplete or unknown")
    values = cast(dict[str, object], payload)
    if values["schema"] != "sina-quote-capture.v1":
        raise SinaQuoteCaptureValidationError("capture schema is unsupported")
    text_fields = (
        "asset_code",
        "requested_url",
        "final_url",
        "request_started_at",
        "response_completed_at",
        "body_base64",
        "body_sha256",
    )
    if any(type(values[name]) is not str for name in text_fields):
        raise SinaQuoteCaptureValidationError("capture payload text field is invalid")
    optional_text_fields = (
        "http_date",
        "content_type",
        "charset",
        "content_encoding",
        "parse_issue",
    )
    if any(
        values[name] is not None and type(values[name]) is not str for name in optional_text_fields
    ):
        raise SinaQuoteCaptureValidationError("capture payload header field is invalid")
    if type(values["http_status"]) is not int or type(values["body_size_bytes"]) is not int:
        raise SinaQuoteCaptureValidationError("capture payload integer field is invalid")
    if values["parse_issue"] is not None:
        try:
            SinaQuoteCaptureIssue(cast(str, values["parse_issue"]))
        except ValueError as error:
            raise SinaQuoteCaptureValidationError("capture parse issue is unknown") from error
    return cast(SinaQuoteCapturePayload, values)


__all__ = (
    "MAX_SINA_QUOTE_RESPONSE_BYTES",
    "SINA_QUOTE_REQUEST_PREFIX",
    "SINA_QUOTE_SOURCE_ID",
    "SINA_VENDOR_STATUS_MAPPING_SHA256",
    "SinaQuoteCapture",
    "SinaQuoteCaptureIssue",
    "SinaQuoteCapturePayload",
    "SinaQuoteCaptureValidationError",
    "SinaQuoteClockStatus",
    "SinaQuoteObservation",
    "SinaReportedTradingState",
    "build_sina_quote_request_url",
    "parse_sina_quote_capture",
)
