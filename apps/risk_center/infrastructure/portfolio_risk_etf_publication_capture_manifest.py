"""Validate a retained ETF publication page and its independent capture receipt."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from datetime import date
from html.parser import HTMLParser
from typing import TypedDict
from urllib.parse import unquote, urljoin, urlsplit

from apps.risk_center.application.portfolio_risk_disclosed_etf_report_clock import (
    PortfolioRiskETFReportPublicationCapture,
)
from apps.risk_center.infrastructure.portfolio_risk_assets_manifest import (
    _capture_receipt_from_manifest,
    _require_exact_keys,
    _require_mapping,
    _required_string,
)

_PUBLICATION_CAPTURE_KEYS = frozenset({"publication_on", "url", "body_base64", "receipt"})
_PUBLICATION_DATE_PATTERN = re.compile(r"(?:时间|发布日期)\s*[：:]\s*(\d{4}-\d{2}-\d{2})")
_NON_VISIBLE_CONTENT_TAGS = frozenset({"noscript", "script", "style", "template"})


class PortfolioRiskETFPublicationReceiptManifest(TypedDict):
    """Exact receipt shape serialized for the separate publication-page response."""

    capture_id: str
    source_id: str
    source_record_id: str
    original_body_sha256: str
    response_completed_at: str
    http_status: int
    body_size_bytes: int
    body_complete: bool


class PortfolioRiskETFPublicationCaptureManifest(TypedDict):
    """Versioned publication-page evidence nested beside the PDF capture."""

    publication_on: str
    url: str
    body_base64: str
    receipt: PortfolioRiskETFPublicationReceiptManifest


class _PublicationPageParser(HTMLParser):
    """Collect visible publication labels and links without executing page code."""

    def __init__(self) -> None:
        """Initialize the parser's bounded text and link collections."""

        super().__init__(convert_charrefs=True)
        self.publication_blocks: list[str] = []
        self.links: list[str] = []
        self._capture_publication_block = False
        self._current_publication_text: list[str] = []
        self._non_visible_content_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Retain only visible publication blocks and anchor targets."""

        if tag in _NON_VISIBLE_CONTENT_TAGS:
            self._non_visible_content_depth += 1
        if self._non_visible_content_depth:
            return
        attributes = dict(attrs)
        if tag == "div" and "p" in (attributes.get("class") or "").split():
            self._capture_publication_block = True
            self._current_publication_text = []
        if tag == "a":
            href = attributes.get("href")
            if href is not None:
                self.links.append(href)

    def handle_data(self, data: str) -> None:
        """Accumulate text only while inside a visible publication block."""

        if self._capture_publication_block and not self._non_visible_content_depth:
            self._current_publication_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        """Finish a publication block when its containing div closes."""

        if tag in _NON_VISIBLE_CONTENT_TAGS:
            self._non_visible_content_depth = max(0, self._non_visible_content_depth - 1)
            return
        if self._non_visible_content_depth:
            return
        if tag == "div" and self._capture_publication_block:
            self.publication_blocks.append("".join(self._current_publication_text))
            self._current_publication_text = []
            self._capture_publication_block = False


def decode_etf_publication_capture_manifest(
    value: object,
    *,
    report_original_url: str | None,
    report_date: date,
    source_effective_on: date | None,
    source_observation_date: date | None,
) -> PortfolioRiskETFReportPublicationCapture:
    """Decode and verify the release page against the exact retained ETF PDF."""

    mapping = _require_mapping(value, "etf_publication_capture")
    _require_exact_keys(mapping, _PUBLICATION_CAPTURE_KEYS, "etf_publication_capture")
    publication_on = _parse_manifest_date(mapping["publication_on"])
    url = _required_string(mapping["url"], "etf_publication_capture.url")
    body_text = _required_string(mapping["body_base64"], "etf_publication_capture.body_base64")
    try:
        original_body = base64.b64decode(body_text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("ETF publication body must be strict base64") from exc
    if not original_body or base64.b64encode(original_body).decode("ascii") != body_text:
        raise ValueError("ETF publication body must be nonempty canonical base64")
    receipt = _capture_receipt_from_manifest(mapping["receipt"])
    capture = PortfolioRiskETFReportPublicationCapture(
        publication_on=publication_on,
        original_body=original_body,
        original_url=url,
        receipt=receipt,
    )
    return validate_etf_publication_capture(
        capture,
        report_original_url=report_original_url,
        report_date=report_date,
        source_effective_on=source_effective_on,
        source_observation_date=source_observation_date,
    )


def encode_etf_publication_capture_manifest(
    capture: PortfolioRiskETFReportPublicationCapture,
    *,
    report_original_url: str | None,
    report_date: date,
    source_effective_on: date | None,
    source_observation_date: date | None,
) -> PortfolioRiskETFPublicationCaptureManifest:
    """Validate and serialize a typed capture without trusting its date claim."""

    validated = validate_etf_publication_capture(
        capture,
        report_original_url=report_original_url,
        report_date=report_date,
        source_effective_on=source_effective_on,
        source_observation_date=source_observation_date,
    )
    receipt = validated.receipt
    return {
        "publication_on": validated.publication_on.isoformat(),
        "url": validated.original_url,
        "body_base64": base64.b64encode(validated.original_body).decode("ascii"),
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


def validate_etf_publication_capture(
    capture: PortfolioRiskETFReportPublicationCapture,
    *,
    report_original_url: str | None,
    report_date: date,
    source_effective_on: date | None,
    source_observation_date: date | None,
) -> PortfolioRiskETFReportPublicationCapture:
    """Re-derive publication date from the page and bind it to the report PDF."""

    if type(capture) is not PortfolioRiskETFReportPublicationCapture:
        raise TypeError("ETF publication capture must use the typed application DTO")
    capture.__post_init__()
    if (
        type(report_date) is not date
        or source_effective_on != report_date
        or report_original_url is None
    ):
        raise ValueError("ETF publication proof requires an exact report date and URL")
    if type(source_observation_date) is not date:
        raise ValueError("ETF publication proof requires the original DATE observation")
    receipt = capture.receipt
    body = capture.original_body
    if type(body) is not bytes or not body:
        raise ValueError("ETF publication page body must be nonempty original bytes")
    if (
        receipt.original_body_sha256 != hashlib.sha256(body).hexdigest()
        or receipt.body_size_bytes != len(body)
        or not receipt.body_complete
        or not 200 <= receipt.http_status < 300
    ):
        raise ValueError("ETF publication receipt does not match its complete response body")
    if capture.publication_on != source_observation_date:
        raise ValueError("ETF publication DATE differs from source observed_on")
    if capture.publication_on < report_date:
        raise ValueError("ETF publication DATE precedes the report period end")
    _require_same_https_origin(capture.original_url, report_original_url)
    published_on_in_body = _publication_date_from_body(body)
    if published_on_in_body != capture.publication_on:
        raise ValueError("ETF publication DATE differs from the original page text")
    if not _page_links_exact_report(
        body,
        publication_url=capture.original_url,
        report_url=report_original_url,
    ):
        raise ValueError("ETF publication page does not link the exact retained report PDF")
    return capture


def _parse_manifest_date(value: object) -> date:
    """Parse one canonical DATE without allowing timestamps or coercion."""

    if type(value) is not str:
        raise TypeError("ETF publication_on must be an ISO date string")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("ETF publication_on must use YYYY-MM-DD form")
    return parsed


def _publication_date_from_body(original_body: bytes) -> date:
    """Extract the one visible publication DATE from a strict UTF-8 HTML page."""

    try:
        page = original_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("ETF publication page must be valid UTF-8") from exc
    parser = _PublicationPageParser()
    parser.feed(page)
    parser.close()
    candidates = tuple(
        match
        for text in parser.publication_blocks
        for match in _PUBLICATION_DATE_PATTERN.findall(text)
    )
    if len(candidates) != 1:
        raise ValueError("ETF publication page must contain exactly one visible publication DATE")
    return _parse_manifest_date(candidates[0])


def _page_links_exact_report(
    original_body: bytes,
    *,
    publication_url: str,
    report_url: str,
) -> bool:
    """Require an anchor in the captured page to resolve to the exact report URL."""

    try:
        page = original_body.decode("utf-8")
        parser = _PublicationPageParser()
        parser.feed(page)
        parser.close()
        expected = _canonical_https_url(report_url)
        for link in parser.links:
            try:
                candidate = _canonical_https_url(urljoin(publication_url, link))
            except ValueError:
                continue
            if candidate == expected:
                return True
        return False
    except (UnicodeDecodeError, ValueError):
        return False


def _require_same_https_origin(first_url: str, second_url: str) -> None:
    """Reject non-HTTPS or cross-origin publication/report URL pairs."""

    first = _canonical_https_url(first_url)
    second = _canonical_https_url(second_url)
    if first[:3] != second[:3]:
        raise ValueError("ETF publication page and report PDF must share one HTTPS origin")


def _canonical_https_url(url: str) -> tuple[str, str, int, str, str]:
    """Return a strict comparison key for a canonical HTTPS URL."""

    if type(url) is not str or not url or url.strip() != url:
        raise ValueError("ETF source URL must be canonical text")
    parsed = urlsplit(url)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("ETF source URL must be an absolute HTTPS URL without credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("ETF source URL port is invalid") from exc
    path = parsed.path
    if re.search(r"%(?![0-9a-fA-F]{2})", path):
        raise ValueError("ETF source URL path contains an invalid escape")
    for escape in re.finditer(r"%([0-9a-fA-F]{2})", path):
        escaped_byte = int(escape.group(1), 16)
        if escaped_byte < 128 and chr(escaped_byte) not in (
            "-",
            ".",
            "_",
            "~",
            *"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        ):
            raise ValueError("ETF source URL path escapes a reserved character")
    try:
        canonical_path = unquote(path, errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("ETF source URL path must use valid UTF-8 escapes") from exc
    return (
        "https",
        parsed.hostname.lower(),
        443 if port is None else port,
        canonical_path,
        parsed.query,
    )


__all__ = (
    "PortfolioRiskETFPublicationCaptureManifest",
    "PortfolioRiskETFPublicationReceiptManifest",
    "decode_etf_publication_capture_manifest",
    "encode_etf_publication_capture_manifest",
    "validate_etf_publication_capture",
)
