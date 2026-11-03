"""Proof contracts for separately captured ETF publication-page metadata."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.risk_center.application.portfolio_risk_disclosed_etf_report_clock import (
    PortfolioRiskETFReportPublicationCapture,
)
from apps.risk_center.application.portfolio_risk_source_admission import (
    PortfolioRiskSourceAdmissionError,
    PortfolioRiskSourceAdmissionRequest,
    parse_portfolio_risk_source_admission_request,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import (
    PortfolioRiskCaptureReceipt,
)
from apps.risk_center.infrastructure.portfolio_risk_etf_publication_capture_manifest import (
    decode_etf_publication_capture_manifest,
    encode_etf_publication_capture_manifest,
)
from apps.risk_center.infrastructure.portfolio_risk_source_admission_codec import (
    RetainedPortfolioRiskAdmissionManifestCodec,
)

_REPORT_URL = "https://source.example.test/reports/510050-q3.pdf"
_PUBLICATION_URL = "https://source.example.test/reports/510050-q3.html"
_REPORT_RECORD_ID = "report-record-q3"
_REPORT_DATE = date(2026, 9, 30)
_PUBLICATION_DATE = date(2026, 10, 27)
_REPORT_BODY = b"%PDF-1.7\x00retained report body"
_PUBLICATION_BODY = (
    b'<div class="p">\xe6\x97\xb6\xe9\x97\xb4\xef\xbc\x9a2026-10-27</div>'
    b'<a href="/reports/510050-q3.pdf">Download</a>'
)


def _receipt(
    *,
    capture_id: str,
    source_record_id: str,
    body: bytes,
    completed_at: datetime,
    source_id: str = "official_etf_publisher",
    body_complete: bool = True,
) -> PortfolioRiskCaptureReceipt:
    """Build one local capture receipt bound to exactly the supplied bytes."""

    return PortfolioRiskCaptureReceipt(
        capture_id=capture_id,
        source_id=source_id,
        source_record_id=source_record_id,
        original_body_sha256=hashlib.sha256(body).hexdigest(),
        response_completed_at=completed_at,
        http_status=200,
        body_size_bytes=len(body),
        body_complete=body_complete,
    )


def _capture() -> PortfolioRiskETFReportPublicationCapture:
    """Return a page capture with an independent response identity and clock."""

    return PortfolioRiskETFReportPublicationCapture(
        publication_on=_PUBLICATION_DATE,
        original_body=_PUBLICATION_BODY,
        original_url=_PUBLICATION_URL,
        receipt=_receipt(
            capture_id="publication-capture-q3",
            source_record_id="publication-record-q3",
            body=_PUBLICATION_BODY,
            completed_at=datetime(2026, 11, 3, 1, 44, 22, tzinfo=UTC),
            source_id="official_release_page_capture",
        ),
    )


def _manifest(
    capture: PortfolioRiskETFReportPublicationCapture | None = None,
) -> dict[str, object]:
    """Return the exact nested v2 page-capture shape used in retained manifests."""

    selected = capture or _capture()
    receipt = selected.receipt
    return {
        "publication_on": selected.publication_on.isoformat(),
        "url": selected.original_url,
        "body_base64": base64.b64encode(selected.original_body).decode("ascii"),
        "receipt": {
            "capture_id": receipt.capture_id,
            "source_id": receipt.source_id,
            "source_record_id": receipt.source_record_id,
            "original_body_sha256": receipt.original_body_sha256,
            "response_completed_at": receipt.response_completed_at.isoformat(),
            "http_status": receipt.http_status,
            "body_size_bytes": receipt.body_size_bytes,
            "body_complete": receipt.body_complete,
        },
    }


def _decode(value: object) -> PortfolioRiskETFReportPublicationCapture:
    """Decode one manifest using the report's exact effective and observed dates."""

    return decode_etf_publication_capture_manifest(
        value,
        report_original_url=_REPORT_URL,
        report_date=_REPORT_DATE,
        source_effective_on=_REPORT_DATE,
        source_observation_date=_PUBLICATION_DATE,
    )


def _admission_request(
    *,
    publication_capture: PortfolioRiskETFReportPublicationCapture | None = None,
    observed_on: date = _PUBLICATION_DATE,
) -> PortfolioRiskSourceAdmissionRequest:
    """Build an explicit PDF request and keep page capture separately typed."""

    pdf_completed_at = datetime(2026, 11, 3, 1, 44, 23, tzinfo=UTC)
    document: dict[str, object] = {
        "schema_version": "ash07.source_admission_request.v1",
        "kind": "etf_report",
        "asset_code": "510050.SH",
        "security_id": "etf:SH:510050",
        "source_record_id": _REPORT_RECORD_ID,
        "original_url": _REPORT_URL,
        "captured_at": pdf_completed_at.isoformat(),
        "source_evidence": {
            "source_id": "official_etf_publisher",
            "source_record_id": _REPORT_RECORD_ID,
            "original_payload_sha256": hashlib.sha256(_REPORT_BODY).hexdigest(),
            "observation_precision": "date",
            "observed_at": None,
            "observed_on": observed_on.isoformat(),
            "available_at": None,
            "known_at": (pdf_completed_at + timedelta(seconds=1)).isoformat(),
            "valid_until": None,
            "source_purpose": "ash07_portfolio_exposure",
            "allowed_purposes": ["ash07_portfolio_exposure"],
            "restrictions": [],
            "must_not_use_for_decision": False,
            "coverage": {
                "status": "complete",
                "precision_basis": "portfolio_weight",
                "reported_weight_fraction": "1",
                "expected_item_count": None,
                "observed_item_count": None,
            },
            "effective_on": _REPORT_DATE.isoformat(),
            "effective_until": None,
        },
        "facts": {
            "report_date": _REPORT_DATE.isoformat(),
            "constituents": [{"asset_code": "cash:cn", "weight_fraction": "1", "kind": "cash"}],
        },
    }
    pdf_receipt = _receipt(
        capture_id="report-capture-q3",
        source_record_id=_REPORT_RECORD_ID,
        body=_REPORT_BODY,
        completed_at=pdf_completed_at,
    )
    return parse_portfolio_risk_source_admission_request(
        document,
        original_body=_REPORT_BODY,
        capture_receipt=pdf_receipt,
        etf_publication_capture=publication_capture or _capture(),
    )


def test_publication_page_round_trip_binds_separate_receipt_and_report_url() -> None:
    """The nested page receipt and body remain independent from the PDF response."""

    encoded = encode_etf_publication_capture_manifest(
        _capture(),
        report_original_url=_REPORT_URL,
        report_date=_REPORT_DATE,
        source_effective_on=_REPORT_DATE,
        source_observation_date=_PUBLICATION_DATE,
    )

    decoded = _decode(encoded)
    report_receipt = _receipt(
        capture_id="report-capture-q3",
        source_record_id=_REPORT_RECORD_ID,
        body=_REPORT_BODY,
        completed_at=datetime(2026, 11, 3, 1, 44, 22, tzinfo=UTC),
    )

    assert decoded == _capture()
    assert decoded.original_body == _PUBLICATION_BODY
    assert decoded.receipt.original_body_sha256 == hashlib.sha256(_PUBLICATION_BODY).hexdigest()
    assert decoded.receipt.source_record_id == "publication-record-q3"
    assert decoded.receipt.source_record_id != report_receipt.source_record_id
    assert decoded.receipt.source_id == "official_release_page_capture"
    assert decoded.receipt.capture_id != report_receipt.capture_id
    assert decoded.receipt.original_body_sha256 != report_receipt.original_body_sha256


def test_manifest_date_is_not_allowed_to_override_the_captured_page_text() -> None:
    """A caller-supplied date cannot replace the one actually printed on the page."""

    manifest = _manifest()
    manifest["publication_on"] = "2026-10-28"

    with pytest.raises(ValueError, match="original page text"):
        decode_etf_publication_capture_manifest(
            manifest,
            report_original_url=_REPORT_URL,
            report_date=_REPORT_DATE,
            source_effective_on=_REPORT_DATE,
            source_observation_date=date(2026, 10, 28),
        )


def test_publication_page_must_link_the_exact_pdf_on_the_same_https_origin() -> None:
    """A same-origin page that links another PDF cannot qualify this report."""

    other_body = _PUBLICATION_BODY.replace(b"510050-q3.pdf", b"other-report.pdf")
    other_capture = PortfolioRiskETFReportPublicationCapture(
        publication_on=_PUBLICATION_DATE,
        original_body=other_body,
        original_url=_PUBLICATION_URL,
        receipt=_receipt(
            capture_id="publication-capture-other",
            source_record_id="publication-record-other",
            body=other_body,
            completed_at=datetime(2026, 11, 3, 1, 44, 22, tzinfo=UTC),
        ),
    )

    with pytest.raises(ValueError, match="does not link"):
        encode_etf_publication_capture_manifest(
            other_capture,
            report_original_url=_REPORT_URL,
            report_date=_REPORT_DATE,
            source_effective_on=_REPORT_DATE,
            source_observation_date=_PUBLICATION_DATE,
        )


def test_unrelated_javascript_navigation_before_pdf_link_is_skipped() -> None:
    """An unrelated non-HTTP anchor cannot hide a later exact report link."""

    body = _PUBLICATION_BODY.replace(
        b'<a href="/reports/510050-q3.pdf">Download</a>',
        b'<a href="javascript:void(0)">Menu</a>' b'<a href="/reports/510050-q3.pdf">Download</a>',
    )
    capture = PortfolioRiskETFReportPublicationCapture(
        publication_on=_PUBLICATION_DATE,
        original_body=body,
        original_url=_PUBLICATION_URL,
        receipt=_receipt(
            capture_id="publication-capture-navigation",
            source_record_id="publication-record-navigation",
            body=body,
            completed_at=datetime(2026, 11, 3, 1, 44, 22, tzinfo=UTC),
            source_id="official_release_page_capture",
        ),
    )

    encoded = encode_etf_publication_capture_manifest(
        capture,
        report_original_url=_REPORT_URL,
        report_date=_REPORT_DATE,
        source_effective_on=_REPORT_DATE,
        source_observation_date=_PUBLICATION_DATE,
    )

    assert encoded["publication_on"] == _PUBLICATION_DATE.isoformat()


def test_date_inside_script_is_not_treated_as_visible_publication_evidence() -> None:
    """Inert script text inside a publication block cannot supply its date."""

    body = (
        b'<div class="p"><script>\xe6\x97\xb6\xe9\x97\xb4\xef\xbc\x9a2026-10-27</script>'
        b'</div><a href="/reports/510050-q3.pdf">Download</a>'
    )
    capture = PortfolioRiskETFReportPublicationCapture(
        publication_on=_PUBLICATION_DATE,
        original_body=body,
        original_url=_PUBLICATION_URL,
        receipt=_receipt(
            capture_id="publication-capture-script-only-date",
            source_record_id="publication-record-script-only-date",
            body=body,
            completed_at=datetime(2026, 11, 3, 1, 44, 22, tzinfo=UTC),
            source_id="official_release_page_capture",
        ),
    )

    with pytest.raises(ValueError, match="exactly one visible publication DATE"):
        encode_etf_publication_capture_manifest(
            capture,
            report_original_url=_REPORT_URL,
            report_date=_REPORT_DATE,
            source_effective_on=_REPORT_DATE,
            source_observation_date=_PUBLICATION_DATE,
        )


def test_publication_page_from_a_different_origin_is_rejected() -> None:
    """A matching link string on another origin is not a publisher capture."""

    capture = _capture()
    cross_origin = PortfolioRiskETFReportPublicationCapture(
        publication_on=capture.publication_on,
        original_body=capture.original_body,
        original_url="https://unrelated.example.test/notice.html",
        receipt=capture.receipt,
    )

    with pytest.raises(ValueError, match="share one HTTPS origin"):
        encode_etf_publication_capture_manifest(
            cross_origin,
            report_original_url=_REPORT_URL,
            report_date=_REPORT_DATE,
            source_effective_on=_REPORT_DATE,
            source_observation_date=_PUBLICATION_DATE,
        )


def test_page_receipt_hash_and_completeness_are_checked_against_page_bytes() -> None:
    """A page receipt must authenticate the full page response, not just its date."""

    malformed = _manifest()
    receipt_value = malformed["receipt"]
    assert isinstance(receipt_value, dict)
    receipt_value["original_body_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="receipt"):
        _decode(malformed)

    wrong_size = _manifest()
    wrong_size_receipt = wrong_size["receipt"]
    assert isinstance(wrong_size_receipt, dict)
    wrong_size_receipt["body_size_bytes"] = len(_PUBLICATION_BODY) + 1

    with pytest.raises(ValueError, match="size differs"):
        _decode(wrong_size)

    incomplete = _capture()
    incomplete_receipt = PortfolioRiskCaptureReceipt(
        capture_id="publication-capture-incomplete",
        source_id=incomplete.receipt.source_id,
        source_record_id=incomplete.receipt.source_record_id,
        original_body_sha256=hashlib.sha256(incomplete.original_body).hexdigest(),
        response_completed_at=incomplete.receipt.response_completed_at,
        http_status=200,
        body_size_bytes=len(incomplete.original_body),
        body_complete=False,
    )
    incomplete_manifest = _manifest()
    incomplete_manifest_receipt = incomplete_manifest["receipt"]
    assert isinstance(incomplete_manifest_receipt, dict)
    incomplete_manifest_receipt["capture_id"] = incomplete_receipt.capture_id
    incomplete_manifest_receipt["body_complete"] = False

    with pytest.raises(ValueError, match="complete successful response"):
        _decode(incomplete_manifest)


def test_publication_date_must_match_the_pinned_date_observation_and_report_period() -> None:
    """The page date cannot stand in for the PDF report period or another source date."""

    with pytest.raises(ValueError, match="source observed_on"):
        decode_etf_publication_capture_manifest(
            _manifest(),
            report_original_url=_REPORT_URL,
            report_date=_REPORT_DATE,
            source_effective_on=_REPORT_DATE,
            source_observation_date=date(2026, 10, 28),
        )

    with pytest.raises(ValueError, match="exact report date"):
        decode_etf_publication_capture_manifest(
            _manifest(),
            report_original_url=_REPORT_URL,
            report_date=_REPORT_DATE,
            source_effective_on=date(2026, 9, 29),
            source_observation_date=_PUBLICATION_DATE,
        )


def test_admission_manifest_v2_binds_pdf_and_publication_response_separately() -> None:
    """The added publication metadata extends v2 without replacing PDF evidence."""

    request = _admission_request()
    payload = RetainedPortfolioRiskAdmissionManifestCodec().build_payload(request)
    page_capture = payload.payload["etf_publication_capture"]
    pdf_receipt = payload.payload["capture_receipt"]

    assert payload.parser_version == "ash07.retained_risk_input.v2"
    assert set(payload.payload) == {
        "schema_version",
        "kind",
        "asset_code",
        "security_id",
        "source_record_id",
        "original_body_base64",
        "original_url",
        "source_evidence",
        "facts",
        "capture_receipt",
        "sina_capture_metadata",
        "etf_publication_capture",
    }
    assert payload.payload["schema_version"] == "ash07.retained_risk_input.v2"
    assert isinstance(page_capture, dict)
    assert isinstance(pdf_receipt, dict)
    source_evidence = payload.payload["source_evidence"]
    assert isinstance(source_evidence, dict)
    page_receipt = page_capture["receipt"]
    assert isinstance(page_receipt, dict)
    assert pdf_receipt["capture_id"] != page_receipt["capture_id"]
    assert pdf_receipt["source_record_id"] != page_receipt["source_record_id"]
    assert pdf_receipt["original_body_sha256"] == hashlib.sha256(_REPORT_BODY).hexdigest()
    assert page_receipt["original_body_sha256"] == hashlib.sha256(_PUBLICATION_BODY).hexdigest()
    assert payload.fetched_at.isoformat() == pdf_receipt["response_completed_at"]
    assert source_evidence["observation_precision"] == "date"
    assert source_evidence["observed_at"] is None
    assert source_evidence["observed_on"] == _PUBLICATION_DATE.isoformat()
    assert source_evidence["available_at"] is None
    assert source_evidence["valid_until"] is None
    assert source_evidence["effective_on"] == _REPORT_DATE.isoformat()


def test_admission_refuses_publication_date_not_matching_the_pdf_evidence() -> None:
    """A typed page capture cannot contradict the ETF source DATE observation."""

    with pytest.raises(
        PortfolioRiskSourceAdmissionError,
        match="RISK_INPUT_ADMISSION_DOCUMENT_INVALID",
    ) as exc_info:
        _admission_request(observed_on=date(2026, 10, 28))
    assert exc_info.value.__cause__ is not None
    assert (
        str(exc_info.value.__cause__)
        == "etf_publication_date_must_match_the_original_DATE_observation"
    )


def test_admission_requires_independent_capture_ids_for_pdf_and_publication_page() -> None:
    """Two source bodies must not masquerade as one transport capture."""

    page = _capture()
    duplicate_receipt = _receipt(
        capture_id="report-capture-q3",
        source_record_id=page.receipt.source_record_id,
        body=page.original_body,
        completed_at=page.receipt.response_completed_at,
        source_id=page.receipt.source_id,
    )
    duplicate_capture = PortfolioRiskETFReportPublicationCapture(
        publication_on=page.publication_on,
        original_body=page.original_body,
        original_url=page.original_url,
        receipt=duplicate_receipt,
    )

    with pytest.raises(ValueError, match="RISK_INPUT_ADMISSION_DOCUMENT_INVALID") as exc_info:
        _admission_request(publication_capture=duplicate_capture)
    assert exc_info.value.__cause__ is not None
    assert str(exc_info.value.__cause__) == "ETF PDF and publication page need distinct capture IDs"
