"""No-database contract tests for exact Sina quote source capture."""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest

from apps.data_center.application.sina_quote_capture import (
    CaptureSinaQuoteUseCase,
)
from apps.data_center.domain.sina_quote_capture import (
    MAX_SINA_QUOTE_RESPONSE_BYTES,
    SinaQuoteCapture,
    SinaQuoteCaptureIssue,
    SinaQuoteClockStatus,
    SinaReportedTradingState,
    build_sina_quote_request_url,
    parse_sina_quote_capture,
)


def _sina_body(
    *,
    symbol: str = "sh600000",
    status: str = "00",
    source_date: str = "2026-11-02",
    source_time: str = "13:59:00",
    bid: str = "9.94",
    ask: str = "9.95",
    numeric_overrides: dict[int, str] | None = None,
) -> bytes:
    fields = [
        "浦发银行",
        "10.04",
        "9.98",
        "9.95",
        "10.05",
        "9.90",
        bid,
        ask,
        "123456",
        "1234567.00",
        *("" for _ in range(20)),
        source_date,
        source_time,
        status,
        "D|11800|118236.00",
    ]
    if numeric_overrides is not None:
        for index, value in numeric_overrides.items():
            fields[index] = value
    line = f'var hq_str_{symbol}="{",".join(fields)}";\n'
    return line.encode("gb18030")


def _response(
    *,
    body: bytes | None = None,
    status_code: int = 200,
    asset_code: str = "600000.SH",
    source_date: str = "2026-11-02",
    source_time: str = "13:59:00",
    response_completed_at: datetime = datetime(2026, 11, 2, 6, 0, tzinfo=UTC),
    requested_url: str | None = None,
    final_url: str | None = None,
    content_type: str | None = "application/javascript; charset=GB18030",
    charset: str | None = "GB18030",
    content_encoding: str | None = "identity",
    http_date: str | None = "Mon, 02 Nov 2026 06:00:00 GMT",
    request_started_at: datetime | None = None,
) -> SinaQuoteCapture:
    expected_url = build_sina_quote_request_url(asset_code)
    return parse_sina_quote_capture(
        asset_code=asset_code,
        requested_url=requested_url if requested_url is not None else expected_url,
        final_url=final_url if final_url is not None else expected_url,
        request_started_at=(
            request_started_at
            if request_started_at is not None
            else response_completed_at - timedelta(seconds=1)
        ),
        response_completed_at=response_completed_at,
        http_status=status_code,
        http_date=http_date,
        content_type=content_type,
        charset=charset,
        content_encoding=content_encoding,
        body=(
            body
            if body is not None
            else _sina_body(source_date=source_date, source_time=source_time)
        ),
    )


class _FakeTransport:
    def __init__(self, response: SinaQuoteCapture) -> None:
        self.response = response
        self.requested_assets: list[str] = []

    def fetch_quote_capture(self, asset_code: str) -> SinaQuoteCapture:
        self.requested_assets.append(asset_code)
        return self.response


def test_capture_keeps_source_and_http_clocks_separate_and_roundtrips_exact_body() -> None:
    response = _response()
    transport = _FakeTransport(response)

    capture = CaptureSinaQuoteUseCase(transport=transport).execute("600000.SH")

    assert transport.requested_assets == ["600000.SH"]
    assert capture.request_started_at == response.request_started_at
    assert capture.response_completed_at == response.response_completed_at
    quote = capture.quote
    assert quote is not None
    assert quote.source_observed_at == datetime(
        2026, 11, 2, 13, 59, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    assert quote.source_observed_at != capture.response_completed_at
    assert quote.source_clock_status is SinaQuoteClockStatus.VALID
    assert quote.last_price == Decimal("9.95")
    assert quote.previous_close == Decimal("9.98")
    assert quote.bid_price == Decimal("9.94")
    assert quote.ask_price == Decimal("9.95")
    assert capture.body_sha256 == sha256(response.body).hexdigest()
    assert capture.body_size_bytes == len(response.body)

    restored = SinaQuoteCapture.from_payload(capture.to_payload())
    assert restored == capture
    assert restored.body == response.body


@pytest.mark.parametrize(
    ("status", "reported_state", "status_label"),
    [
        ("00", SinaReportedTradingState.TRADING, ""),
        ("02", SinaReportedTradingState.SUSPENDED, "停牌"),
        ("-3", SinaReportedTradingState.DELISTED, "退市"),
        ("98", SinaReportedTradingState.UNKNOWN, None),
    ],
)
def test_status_is_mapped_only_by_the_captured_sina_vendor_mapping(
    status: str,
    reported_state: SinaReportedTradingState,
    status_label: str | None,
) -> None:
    capture = CaptureSinaQuoteUseCase(
        transport=_FakeTransport(_response(body=_sina_body(status=status)))
    ).execute("600000.SH")

    assert capture.quote is not None
    assert capture.quote.vendor_status_code == status
    assert capture.quote.vendor_status_label == status_label
    assert capture.quote.reported_trading_state is reported_state


def test_missing_source_clock_and_zero_bbo_remain_unknown_without_fetch_time_fallback() -> None:
    capture = CaptureSinaQuoteUseCase(
        transport=_FakeTransport(
            _response(body=_sina_body(source_date="", source_time="", bid="0.00", ask="0.00"))
        )
    ).execute("600000.SH")

    assert capture.quote is not None
    assert capture.quote.source_observed_at is None
    assert capture.quote.source_clock_status is SinaQuoteClockStatus.MISSING
    assert capture.quote.bid_price is None
    assert capture.quote.ask_price is None
    assert capture.response_completed_at is not None


def test_future_source_clock_is_retained_and_marked_without_retiming() -> None:
    capture = CaptureSinaQuoteUseCase(
        transport=_FakeTransport(
            _response(
                source_date="2026-11-02",
                response_completed_at=datetime(2026, 11, 2, 5, 0, tzinfo=UTC),
            )
        )
    ).execute("600000.SH")

    assert capture.quote is not None
    assert capture.quote.source_clock_status is SinaQuoteClockStatus.FUTURE
    assert capture.quote.source_observed_at is not None
    assert capture.quote.source_observed_at > capture.response_completed_at


def test_non_success_response_is_retained_but_has_no_parsed_quote() -> None:
    body = b"upstream error"
    capture = CaptureSinaQuoteUseCase(
        transport=_FakeTransport(_response(body=body, status_code=503))
    ).execute("600000.SH")

    assert capture.body == body
    assert capture.body_sha256 == sha256(body).hexdigest()
    assert capture.quote is None
    assert capture.parse_issue is SinaQuoteCaptureIssue.HTTP_STATUS_NOT_SUCCESS


def test_capture_payload_rejects_raw_body_change_that_breaks_its_hash() -> None:
    capture = CaptureSinaQuoteUseCase(transport=_FakeTransport(_response())).execute("600000.SH")
    payload = capture.to_payload()
    payload["body_base64"] = "dGFtcGVyZWQ="
    payload["body_size_bytes"] = len(b"tampered")

    with pytest.raises(ValueError, match="SHA-256"):
        SinaQuoteCapture.from_payload(payload)


def test_market_symbol_mismatch_is_retained_as_unusable_source_evidence() -> None:
    capture = CaptureSinaQuoteUseCase(
        transport=_FakeTransport(_response(body=_sina_body(symbol="sz000001")))
    ).execute("600000.SH")

    assert capture.quote is None
    assert capture.parse_issue is SinaQuoteCaptureIssue.QUOTE_NOT_FOUND


@pytest.mark.parametrize(
    "numeric_overrides",
    [
        {3: "not-a-number"},
        {3: "NaN"},
        {2: "-0.01"},
        {8: "-1"},
        {9: "1e65"},
    ],
)
def test_malformed_vendor_numeric_fields_never_become_quote_values(
    numeric_overrides: dict[int, str],
) -> None:
    capture = _response(body=_sina_body(numeric_overrides=numeric_overrides))

    assert capture.quote is None
    assert capture.parse_issue is SinaQuoteCaptureIssue.MALFORMED_RESPONSE


@pytest.mark.parametrize(
    ("response_changes", "expected_issue"),
    [
        (
            {"requested_url": "https://hq.sinajs.cn/list=sh600000?redirect=1"},
            SinaQuoteCaptureIssue.UNEXPECTED_URL,
        ),
        ({"final_url": "https://example.invalid/quote"}, SinaQuoteCaptureIssue.UNEXPECTED_URL),
        (
            {"content_type": "text/html; charset=GB18030"},
            SinaQuoteCaptureIssue.UNEXPECTED_CONTENT_TYPE,
        ),
        ({"content_type": None}, SinaQuoteCaptureIssue.UNEXPECTED_CONTENT_TYPE),
        ({"content_encoding": "gzip"}, SinaQuoteCaptureIssue.UNSUPPORTED_CONTENT_ENCODING),
        ({"charset": "latin-1"}, SinaQuoteCaptureIssue.UNSUPPORTED_CHARSET),
        ({"charset": None}, SinaQuoteCaptureIssue.UNSUPPORTED_CHARSET),
        ({"body": b"\xff", "charset": "UTF-8"}, SinaQuoteCaptureIssue.INVALID_TEXT_ENCODING),
    ],
)
def test_response_metadata_or_encoding_failure_is_retained_without_quote(
    response_changes: dict[str, object],
    expected_issue: SinaQuoteCaptureIssue,
) -> None:
    capture = _response(**response_changes)

    assert capture.quote is None
    assert capture.parse_issue is expected_issue


@pytest.mark.parametrize(
    ("source_date", "source_time"),
    [
        ("2026-11-2", "13:59:00"),
        ("2026-11-02", "13:59"),
        ("not-a-date", "13:59:00"),
        ("", "13:59:00"),
        ("2026-11-02", ""),
    ],
)
def test_partial_or_noncanonical_source_clock_remains_invalid(
    source_date: str,
    source_time: str,
) -> None:
    capture = CaptureSinaQuoteUseCase(
        transport=_FakeTransport(_response(source_date=source_date, source_time=source_time))
    ).execute("600000.SH")

    assert capture.quote is not None
    assert capture.quote.source_clock_status is SinaQuoteClockStatus.INVALID
    assert capture.quote.source_observed_at is None


def test_quote_observation_constructor_rejects_misbinding_and_inconsistent_states() -> None:
    capture = _response()
    quote = capture.quote
    assert quote is not None

    with pytest.raises(ValueError, match="symbol"):
        replace(quote, source_symbol="sz000001")
    with pytest.raises(ValueError, match="invalid source clock"):
        replace(quote, source_clock_status=SinaQuoteClockStatus.MISSING)
    with pytest.raises(ValueError, match="state differs"):
        replace(
            quote,
            vendor_status_code="98",
            vendor_status_label=None,
            reported_trading_state=SinaReportedTradingState.TRADING,
        )
    with pytest.raises(ValueError, match="finite Decimal"):
        replace(quote, last_price=Decimal("NaN"))


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_field",
        "unknown_field",
        "schema",
        "bad_base64",
        "noncanonical_clock",
        "noncanonical_clock_precision",
        "unknown_parse_issue",
        "invalid_http_status_type",
        "invalid_text_field_type",
        "unexpected_url",
    ],
)
def test_signed_capture_payload_rejects_malformed_shape_and_metadata(mutation: str) -> None:
    payload: dict[str, object] = dict(_response().to_payload())
    if mutation == "missing_field":
        payload.pop("final_url")
    elif mutation == "unknown_field":
        payload["unrecognized"] = "must not be ignored"
    elif mutation == "schema":
        payload["schema"] = "sina-quote-capture.v2"
    elif mutation == "bad_base64":
        payload["body_base64"] = "%%%"
    elif mutation == "noncanonical_clock":
        payload["request_started_at"] = "2026-11-02T05:59:59+00:00"
    elif mutation == "noncanonical_clock_precision":
        payload["request_started_at"] = "2026-11-02T05:59:59Z"
    elif mutation == "unknown_parse_issue":
        payload["parse_issue"] = "invented_issue"
    elif mutation == "invalid_http_status_type":
        payload["http_status"] = True
    elif mutation == "invalid_text_field_type":
        payload["asset_code"] = 600000
    elif mutation == "unexpected_url":
        payload["requested_url"] = "https://example.invalid/quote"

    with pytest.raises(ValueError):
        SinaQuoteCapture.from_payload(payload)


def test_capture_constructor_rejects_non_utc_and_reversed_receipt_clocks() -> None:
    with pytest.raises(ValueError, match="must be UTC"):
        _response(
            response_completed_at=datetime(2026, 11, 2, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        )
    with pytest.raises(ValueError, match="precedes request start"):
        _response(
            request_started_at=datetime(2026, 11, 2, 6, 0, 1, tzinfo=UTC),
            response_completed_at=datetime(2026, 11, 2, 6, 0, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("asset_type", "asset_code must be canonical SH/SZ"),
        ("bad_asset", "canonical SH/SZ"),
        ("empty_url", "requested_url is invalid"),
        ("oversized_url", "final_url is invalid"),
        ("parsed_foreign_url", "unexpected request URL"),
        ("naive_clock", "timezone-aware"),
        ("invalid_http", "HTTP status is invalid"),
        ("control_header", "http_date is invalid"),
        ("oversized_header", "content_type is invalid"),
        ("body_type", "response body must be bytes"),
        ("body_bound", "response body exceeds the capture bound"),
        ("digest_shape", "response SHA-256 is invalid"),
        ("digest_mismatch", "response body SHA-256 does not match"),
        ("size_mismatch", "response body size does not match"),
        ("parse_quote_conflict", "parse issue and quote presence are inconsistent"),
        ("foreign_quote", "parsed quote is not bound to request asset"),
        ("unusable_metadata", "response metadata is unusable"),
        ("row_clock_mismatch", "source clock does not match retained row fields"),
        ("unknown_parse_issue", "capture parse issue is unrecognized"),
    ],
)
def test_capture_constructor_rejects_invalid_request_and_retained_evidence(
    mutation: str,
    message: str,
) -> None:
    capture = _response()
    quote = capture.quote
    assert quote is not None
    changes: dict[str, object] = {}
    if mutation == "asset_type":
        changes = {"asset_code": 600000}
    elif mutation == "bad_asset":
        changes = {"asset_code": "60000.SH"}
    elif mutation == "empty_url":
        changes = {"requested_url": ""}
    elif mutation == "oversized_url":
        changes = {"final_url": "x" * 2049}
    elif mutation == "parsed_foreign_url":
        changes = {"requested_url": "https://example.invalid/quote"}
    elif mutation == "naive_clock":
        changes = {"request_started_at": datetime(2026, 11, 2, 5, 59, 59)}
    elif mutation == "invalid_http":
        changes = {"http_status": True}
    elif mutation == "control_header":
        changes = {"http_date": "Mon\nInjected: yes"}
    elif mutation == "oversized_header":
        changes = {"content_type": "x" * 2049}
    elif mutation == "body_type":
        changes = {"body": bytearray(capture.body)}
    elif mutation == "body_bound":
        changes = {"body": b"x" * (MAX_SINA_QUOTE_RESPONSE_BYTES + 1)}
    elif mutation == "digest_shape":
        changes = {"body_sha256": "not-a-digest"}
    elif mutation == "digest_mismatch":
        changes = {"body_sha256": "0" * 64}
    elif mutation == "size_mismatch":
        changes = {"body_size_bytes": capture.body_size_bytes + 1}
    elif mutation == "parse_quote_conflict":
        changes = {"parse_issue": SinaQuoteCaptureIssue.MALFORMED_RESPONSE}
    elif mutation == "foreign_quote":
        foreign_capture = _response(
            asset_code="000001.SZ",
            body=_sina_body(symbol="sz000001"),
        )
        assert foreign_capture.quote is not None
        changes = {"quote": foreign_capture.quote}
    elif mutation == "unusable_metadata":
        changes = {"content_encoding": "gzip"}
    elif mutation == "row_clock_mismatch":
        changes = {"quote": replace(quote, source_time_text="13:58:00")}
    elif mutation == "unknown_parse_issue":
        changes = {"quote": None, "parse_issue": "unrecognized"}

    with pytest.raises(ValueError, match=message):
        replace(capture, **changes)


def test_missing_vendor_prices_stay_missing_instead_of_becoming_numeric_defaults() -> None:
    capture = _response(
        body=_sina_body(
            numeric_overrides={
                1: "",
                2: "",
                3: "",
                4: "",
                5: "",
                6: "",
                7: "",
                8: "",
                9: "",
            }
        )
    )

    assert capture.quote is not None
    assert capture.quote.open_price is None
    assert capture.quote.previous_close is None
    assert capture.quote.last_price is None
    assert capture.quote.high_price is None
    assert capture.quote.low_price is None
    assert capture.quote.bid_price is None
    assert capture.quote.ask_price is None
    assert capture.quote.volume is None
    assert capture.quote.amount is None


@pytest.mark.parametrize(
    "mutation",
    [
        "name_type",
        "name_bound",
        "date_text_type",
        "time_text_bound",
        "clock_status_type",
        "missing_clock_instant",
        "wrong_clock_zone",
        "missing_clock_text",
        "invalid_clock_without_text",
        "missing_status_label",
        "missing_status_state",
        "status_code_type",
        "status_code_bound",
        "status_label_mapping",
        "zero_price",
        "negative_price",
        "decimal_bound",
    ],
)
def test_observation_constructor_rejects_malformed_source_fields(mutation: str) -> None:
    capture = _response()
    quote = capture.quote
    assert quote is not None
    if mutation == "name_type":
        changes: dict[str, object] = {"name": 7}
    elif mutation == "name_bound":
        changes = {"name": "x" * 257}
    elif mutation == "date_text_type":
        changes = {"source_date_text": 20261102}
    elif mutation == "time_text_bound":
        changes = {"source_time_text": "1" * 33}
    elif mutation == "clock_status_type":
        changes = {"source_clock_status": "valid"}
    elif mutation == "missing_clock_instant":
        changes = {"source_observed_at": None}
    elif mutation == "wrong_clock_zone":
        changes = {"source_observed_at": datetime(2026, 11, 2, 5, 59, tzinfo=UTC)}
    elif mutation == "missing_clock_text":
        changes = {
            "source_clock_status": SinaQuoteClockStatus.MISSING,
            "source_observed_at": None,
        }
    elif mutation == "invalid_clock_without_text":
        changes = {
            "source_clock_status": SinaQuoteClockStatus.INVALID,
            "source_observed_at": None,
            "source_date_text": "",
            "source_time_text": "",
        }
    elif mutation == "missing_status_label":
        changes = {
            "vendor_status_code": None,
            "vendor_status_label": "Trading",
            "reported_trading_state": SinaReportedTradingState.UNKNOWN,
        }
    elif mutation == "missing_status_state":
        changes = {
            "vendor_status_code": None,
            "vendor_status_label": None,
            "reported_trading_state": SinaReportedTradingState.TRADING,
        }
    elif mutation == "status_code_type":
        changes = {"vendor_status_code": 0}
    elif mutation == "status_code_bound":
        changes = {"vendor_status_code": "0" * 9}
    elif mutation == "status_label_mapping":
        changes = {"vendor_status_label": "unknown label"}
    elif mutation == "zero_price":
        changes = {"last_price": Decimal("0")}
    elif mutation == "negative_price":
        changes = {"last_price": Decimal("-0.01")}
    else:
        changes = {"last_price": Decimal("1E+65")}

    with pytest.raises(ValueError):
        replace(quote, **changes)


@pytest.mark.parametrize(
    "mutation",
    [
        "header_type",
        "invalid_clock_text",
        "encoded_body_bound",
        "decoded_body_bound",
        "size_mismatch",
    ],
)
def test_payload_decoder_rejects_header_clock_and_raw_body_boundaries(mutation: str) -> None:
    payload: dict[str, object] = dict(_response().to_payload())
    if mutation == "header_type":
        payload["charset"] = 7
    elif mutation == "invalid_clock_text":
        payload["request_started_at"] = "not-a-timestampZ"
    elif mutation == "encoded_body_bound":
        payload["body_base64"] = "A" * (((MAX_SINA_QUOTE_RESPONSE_BYTES + 2) // 3) * 4 + 4)
    elif mutation == "decoded_body_bound":
        oversized_body = b"x" * (MAX_SINA_QUOTE_RESPONSE_BYTES + 1)
        payload["body_base64"] = base64.b64encode(oversized_body).decode("ascii")
        payload["body_size_bytes"] = len(oversized_body)
        payload["body_sha256"] = sha256(oversized_body).hexdigest()
    else:
        payload["body_size_bytes"] = int(payload["body_size_bytes"]) + 1

    with pytest.raises(ValueError):
        SinaQuoteCapture.from_payload(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "header_type",
        "invalid_clock_text",
        "encoded_body_bound",
        "decoded_body_bound",
        "size_mismatch",
    ],
)
def test_payload_decoder_rejects_typed_header_clock_and_body_boundaries(mutation: str) -> None:
    payload: dict[str, object] = dict(_response().to_payload())
    if mutation == "header_type":
        payload["charset"] = 7
    elif mutation == "invalid_clock_text":
        payload["request_started_at"] = "not-a-timestampZ"
    elif mutation == "encoded_body_bound":
        payload["body_base64"] = "A" * (((MAX_SINA_QUOTE_RESPONSE_BYTES + 2) // 3) * 4 + 4)
    elif mutation == "decoded_body_bound":
        oversized_body = b"x" * (MAX_SINA_QUOTE_RESPONSE_BYTES + 1)
        payload["body_base64"] = base64.b64encode(oversized_body).decode("ascii")
        payload["body_size_bytes"] = len(oversized_body)
        payload["body_sha256"] = sha256(oversized_body).hexdigest()
    elif mutation == "size_mismatch":
        payload["body_size_bytes"] = int(payload["body_size_bytes"]) + 1

    with pytest.raises(ValueError):
        SinaQuoteCapture.from_payload(payload)
