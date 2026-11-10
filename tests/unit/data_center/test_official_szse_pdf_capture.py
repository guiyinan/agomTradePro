"""Official PDF transport and immutable body retention boundaries."""

from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from apps.data_center.domain.security_disclosure_event import SecurityDisclosureEventType
from apps.data_center.infrastructure import official_szse_pdf_capture as capture_module
from apps.data_center.infrastructure.official_szse_pdf_capture import (
    OfficialDisclosureCaptureError,
    OfficialSzsePdfBodyStore,
    capture_official_szse_pdf,
    classify_szse_pdf_disclosure,
    extract_szse_distribution_dates,
    verify_szse_pdf_security_code,
)

_URL = (
    "https://disc.static.szse.cn/disc/disk03/finalpage/2026-09-17/"
    "37e23922-f64d-4203-9d27-9ed981a8f799.PDF"
)
_BODY = b"%PDF-1.4\nsource bytes\n%%EOF\n"


def _response(body: bytes, *, content_type: str = "application/pdf") -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = content_type
    response.raw = BytesIO(body)
    return response


def test_official_pdf_is_captured_with_native_document_id_and_exact_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))

    capture = capture_official_szse_pdf(_URL)
    store = OfficialSzsePdfBodyStore(tmp_path)
    first_path = store.retain(capture)

    assert capture.source_document_id == "37e23922-f64d-4203-9d27-9ed981a8f799"
    assert capture.first_seen_at.tzinfo is not None
    assert store.retain(capture) == first_path
    assert store.read(capture.body_sha256) == _BODY


@pytest.mark.parametrize(
    "url",
    [
        "http://disc.static.szse.cn/disc/disk03/finalpage/2026-09-17/"
        "37e23922-f64d-4203-9d27-9ed981a8f799.PDF",
        "https://evil.example/disc/disk03/finalpage/2026-09-17/"
        "37e23922-f64d-4203-9d27-9ed981a8f799.PDF",
        "https://disc.static.szse.cn/disc/disk03/finalpage/2026-09-17/file.PDF",
    ],
)
def test_unapproved_url_rejected_before_network(url: str) -> None:
    with pytest.raises(OfficialDisclosureCaptureError):
        capture_official_szse_pdf(url)


def test_html_response_does_not_become_source_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: _response(b"<html>blocked</html>", content_type="text/html"),
    )

    with pytest.raises(OfficialDisclosureCaptureError, match="complete PDF"):
        capture_official_szse_pdf(_URL)


def test_corrupt_retained_pdf_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    store = OfficialSzsePdfBodyStore(tmp_path)
    path = store.retain(capture)
    path.write_bytes(b"corrupt")

    with pytest.raises(OfficialDisclosureCaptureError, match="hash mismatch"):
        store.read(capture.body_sha256)
    with pytest.raises(OfficialDisclosureCaptureError, match="integrity check"):
        store.retain(capture)


def test_pdf_header_must_match_exact_security(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(SimpleNamespace(extract_text=lambda: "股票代码：002727 股票简称：一心堂"),)
        ),
    )

    assert verify_szse_pdf_security_code(capture, "002727") == "002727"
    with pytest.raises(OfficialDisclosureCaptureError, match="does not match"):
        verify_szse_pdf_security_code(capture, "301237")


@pytest.mark.parametrize(
    ("terms", "expected"),
    [
        ("每10股派发现金红利2元，不以公积金转增股本", SecurityDisclosureEventType.CASH_DIVIDEND),
        ("每10股转增4股，不派发现金红利", SecurityDisclosureEventType.STOCK_DIVIDEND),
        ("每10股派发现金红利2元，每10股转增4股", SecurityDisclosureEventType.UNKNOWN),
    ],
)
def test_ambiguous_corporate_action_stays_unknown(
    monkeypatch: pytest.MonkeyPatch, terms: str, expected: SecurityDisclosureEventType
) -> None:
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    monkeypatch.setattr(
        capture_module,
        "verify_szse_pdf_security_code",
        lambda value, security_code: security_code,
    )
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(SimpleNamespace(extract_text=lambda: f"2026 年中期权益分派实施公告\n{terms}"),)
        ),
    )

    title, event_type = classify_szse_pdf_disclosure(capture, "002727")

    assert title == "2026 年中期权益分派实施公告"
    assert event_type is expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("2026 年中期权益分派实施公告（更正后）", SecurityDisclosureEventType.CASH_DIVIDEND),
        (
            "2026 年中期权益分派实施的更正公告",
            SecurityDisclosureEventType.CORRECTION_NOTICE,
        ),
    ],
)
def test_corrected_distribution_and_correction_notice_have_distinct_types(
    monkeypatch: pytest.MonkeyPatch, title: str, expected: SecurityDisclosureEventType
) -> None:
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    monkeypatch.setattr(
        capture_module,
        "verify_szse_pdf_security_code",
        lambda value, security_code: security_code,
    )
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(SimpleNamespace(extract_text=lambda: f"{title}\n每10股派发现金红利2元"),)
        ),
    )

    observed_title, event_type = classify_szse_pdf_disclosure(capture, "002727")

    assert observed_title == title
    assert event_type is expected


def test_distribution_dates_preserve_source_date_precision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    monkeypatch.setattr(
        capture_module,
        "verify_szse_pdf_security_code",
        lambda value, security_code: security_code,
    )
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(
                SimpleNamespace(
                    extract_text=lambda: (
                        "股权登记日为：2026 年09 月23 日，"
                        "除权日（除息日）为：2026 年09 月24 日。"
                    )
                ),
            )
        ),
    )

    assert extract_szse_distribution_dates(capture, "002727") == (
        date(2026, 9, 23),
        date(2026, 9, 24),
    )
