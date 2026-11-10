"""Capture a bounded, complete SZSE company-announcement listing window."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import requests
from django.utils import timezone

from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureExchange,
    SecurityDisclosureListingCoverageProof,
    SecurityDisclosureListingEntry,
    SecurityDisclosureSource,
)
from core.exceptions import DataFetchError

_LISTING_URL = "https://www.szse.cn/api/disc/announcement/annList"
_PAGE_URL = "https://www.szse.cn/disclosure/listed/notice/"
_PDF_HOST = "https://disc.static.szse.cn"
_PDF_PATH = re.compile(
    r"^/(?:download/)?disc/disk[0-9]+/finalpage/[0-9]{4}-[0-9]{2}-[0-9]{2}/"
    r"(?P<document_id>[0-9a-fA-F-]{36})\.PDF$"
)
_PUBLISH_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2}$")
_MAX_PAGE_BYTES = 2 * 1024 * 1024
_MAX_ANNOUNCEMENTS = 10_000


class OfficialSzseListingError(DataFetchError):
    """A listing page, identity, or bounded coverage claim is not verifiable."""

    default_message = "深交所公告列表无法完整核验。"
    default_code = "OFFICIAL_SZSE_LISTING_INVALID"


@dataclass(frozen=True, slots=True)
class CapturedOfficialSzseListingWindow:
    """Two matching complete page passes for one security and date window."""

    asset_code: str
    start_on: date
    end_on: date
    observed_at: datetime
    announcement_count: int
    entries: tuple[SecurityDisclosureListingEntry, ...]
    first_pass_page_body_sha256: tuple[str, ...]
    page_body_sha256: tuple[str, ...]
    manifest_sha256: str
    coverage_manifest_sha256: str


def _required_uuid(value: object, *, field_name: str) -> str:
    """Narrow one source-native UUID without accepting ambiguous identifiers."""

    if type(value) is not str:
        raise OfficialSzseListingError(f"{field_name} is missing")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise OfficialSzseListingError(f"{field_name} is invalid") from error
    if str(parsed) != value.lower():
        raise OfficialSzseListingError(f"{field_name} is not canonical")
    return str(parsed)


def _entry_from_json(
    raw: object, *, security_code: str, start_on: date, end_on: date
) -> SecurityDisclosureListingEntry:
    """Validate one listing row before it enters a coverage snapshot."""

    if not isinstance(raw, dict):
        raise OfficialSzseListingError("announcement row is not an object")
    listing_id = _required_uuid(raw.get("id"), field_name="listing id")
    announcement_id = raw.get("annId")
    title = raw.get("title")
    raw_publish_time = raw.get("publishTime")
    attach_path = raw.get("attachPath")
    if type(announcement_id) is not int or announcement_id <= 0:
        raise OfficialSzseListingError("announcement id is invalid")
    if type(title) is not str or not title.strip() or len(title) > 320:
        raise OfficialSzseListingError("announcement title is invalid")
    if type(raw_publish_time) is not str:
        raise OfficialSzseListingError("announcement publication date is missing")
    match = _PUBLISH_TIME.fullmatch(raw_publish_time)
    if match is None:
        raise OfficialSzseListingError("announcement publication precision is invalid")
    try:
        published_on = datetime.fromisoformat(raw_publish_time).date()
    except ValueError as error:
        raise OfficialSzseListingError("announcement publication date is invalid") from error
    if not start_on <= published_on <= end_on:
        raise OfficialSzseListingError("announcement is outside the requested window")
    if raw.get("secCode") != [security_code]:
        raise OfficialSzseListingError("announcement security identity is ambiguous")
    if raw.get("attachFormat") != "PDF" or type(attach_path) is not str:
        raise OfficialSzseListingError("announcement has no qualified PDF attachment")
    pdf_match = _PDF_PATH.fullmatch(attach_path)
    if pdf_match is None:
        raise OfficialSzseListingError("announcement PDF path is not source-native")
    document_id = _required_uuid(pdf_match.group("document_id"), field_name="PDF document id")
    return SecurityDisclosureListingEntry(
        listing_id=listing_id,
        announcement_id=announcement_id,
        title=title.strip(),
        published_on=published_on,
        raw_publish_time=raw_publish_time,
        source_document_id=document_id,
        source_url=_PDF_HOST + attach_path,
    )


def _response_body(response: requests.Response) -> bytes:
    """Reject redirects, non-JSON responses, and unbounded page bodies."""

    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    body = response.content
    if (
        response.status_code != 200
        or content_type != "application/json"
        or not body
        or len(body) > _MAX_PAGE_BYTES
    ):
        raise OfficialSzseListingError("SZSE announcement page response is invalid")
    return body


def _read_page(
    session: requests.Session,
    *,
    security_code: str,
    start_on: date,
    end_on: date,
    page_number: int,
    page_size: int,
) -> tuple[int, tuple[SecurityDisclosureListingEntry, ...], bytes]:
    """Read and narrow one exact POST JSON page from the official listing API."""

    payload = {
        "pageSize": page_size,
        "pageNum": page_number,
        "stock": [security_code],
        "channelCode": ["listedNotice_disc"],
        "seDate": [start_on.isoformat(), end_on.isoformat()],
    }
    try:
        response = session.post(
            _LISTING_URL,
            json=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://www.szse.cn",
                "Referer": f"{_PAGE_URL}?stock={security_code}",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=(5, 20),
            allow_redirects=False,
        )
        body = _response_body(response)
        decoded = json.loads(body.decode("utf-8"))
    except (requests.RequestException, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OfficialSzseListingError("SZSE announcement page could not be read") from error
    if not isinstance(decoded, dict):
        raise OfficialSzseListingError("SZSE announcement page is not an object")
    total = decoded.get("announceCount")
    raw_entries = decoded.get("data")
    if type(total) is not int or not 0 <= total <= _MAX_ANNOUNCEMENTS:
        raise OfficialSzseListingError("SZSE announcement total is invalid")
    if not isinstance(raw_entries, list):
        raise OfficialSzseListingError("SZSE announcement page rows are invalid")
    expected_count = min(page_size, max(0, total - (page_number - 1) * page_size))
    if len(raw_entries) != expected_count:
        raise OfficialSzseListingError("SZSE announcement page is incomplete")
    entries = tuple(
        _entry_from_json(row, security_code=security_code, start_on=start_on, end_on=end_on)
        for row in raw_entries
    )
    return total, entries, body


def _read_complete_pass(
    session: requests.Session,
    *,
    security_code: str,
    start_on: date,
    end_on: date,
    page_size: int,
) -> tuple[int, tuple[SecurityDisclosureListingEntry, ...], tuple[bytes, ...]]:
    """Collect every page and reject count changes or duplicate source identities."""

    total, first_entries, first_body = _read_page(
        session,
        security_code=security_code,
        start_on=start_on,
        end_on=end_on,
        page_number=1,
        page_size=page_size,
    )
    pages = (total + page_size - 1) // page_size
    entries = list(first_entries)
    bodies = [first_body]
    for page_number in range(2, pages + 1):
        next_total, next_entries, body = _read_page(
            session,
            security_code=security_code,
            start_on=start_on,
            end_on=end_on,
            page_number=page_number,
            page_size=page_size,
        )
        if next_total != total:
            raise OfficialSzseListingError("SZSE announcement count changed during paging")
        entries.extend(next_entries)
        bodies.append(body)
    if len(entries) != total or len({row.listing_id for row in entries}) != total:
        raise OfficialSzseListingError("SZSE announcement identities are incomplete")
    if len({row.source_document_id for row in entries}) != total:
        raise OfficialSzseListingError("SZSE announcement PDFs are not unique")
    return total, tuple(entries), tuple(bodies)


def _retain_page(root: Path, body: bytes) -> str:
    """Retain one exact public JSON response with atomic first-writer behavior."""

    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(body).hexdigest()
    target = root / f"{digest}.json"
    temporary = root / f".{uuid4().hex}.partial"
    try:
        with temporary.open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
    except OSError as error:
        raise OfficialSzseListingError("SZSE listing page retention failed") from error
    finally:
        temporary.unlink(missing_ok=True)
    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise OfficialSzseListingError("retained SZSE listing page hash mismatched")
    return digest


def capture_official_szse_announcement_window(
    *,
    asset_code: str,
    start_on: date,
    end_on: date,
    body_store_root: Path,
    session: requests.Session | None = None,
    page_size: int = 50,
) -> CapturedOfficialSzseListingWindow:
    """Capture two stable complete official pagesets before claiming coverage."""

    if type(asset_code) is not str or re.fullmatch(r"[0-9]{6}\.SZ", asset_code) is None:
        raise OfficialSzseListingError("listing asset identity is invalid")
    if type(start_on) is not date or type(end_on) is not date or start_on > end_on:
        raise OfficialSzseListingError("listing date window is invalid")
    if type(page_size) is not int or not 1 <= page_size <= 50:
        raise OfficialSzseListingError("listing page size is invalid")
    if not isinstance(body_store_root, Path):
        raise OfficialSzseListingError("listing body store root is invalid")
    owns_session = session is None
    http = session or requests.Session()
    try:
        landing = http.get(_PAGE_URL, timeout=(5, 20), allow_redirects=False)
        if landing.status_code != 200:
            raise OfficialSzseListingError("official SZSE listing page is unavailable")
        first = _read_complete_pass(
            http,
            security_code=asset_code[:6],
            start_on=start_on,
            end_on=end_on,
            page_size=page_size,
        )
        second = _read_complete_pass(
            http,
            security_code=asset_code[:6],
            start_on=start_on,
            end_on=end_on,
            page_size=page_size,
        )
    except requests.RequestException as error:
        raise OfficialSzseListingError("official SZSE listing request failed") from error
    finally:
        if owns_session:
            http.close()
    if first[0] != second[0] or first[1] != second[1]:
        raise OfficialSzseListingError("SZSE listing changed between complete passes")
    first_page_hashes = tuple(_retain_page(body_store_root, body) for body in first[2])
    second_page_hashes = tuple(_retain_page(body_store_root, body) for body in second[2])
    observed_at = timezone.now()
    proof = SecurityDisclosureListingCoverageProof(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code=asset_code,
        start_on=start_on,
        end_on=end_on,
        first_observed_at=observed_at,
        verified_at=observed_at,
        announcement_count=second[0],
        entries=second[1],
        first_pass_page_body_sha256=first_page_hashes,
        second_pass_page_body_sha256=second_page_hashes,
    )
    return CapturedOfficialSzseListingWindow(
        asset_code=asset_code,
        start_on=start_on,
        end_on=end_on,
        observed_at=observed_at,
        announcement_count=second[0],
        entries=second[1],
        first_pass_page_body_sha256=first_page_hashes,
        page_body_sha256=second_page_hashes,
        manifest_sha256=proof.source_manifest_sha256,
        coverage_manifest_sha256=proof.coverage_manifest_sha256,
    )
