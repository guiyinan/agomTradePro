"""Official SZSE listing coverage requires complete stable source pages."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import requests

from apps.data_center.infrastructure.official_szse_announcement_listing import (
    OfficialSzseListingError,
    capture_official_szse_announcement_window,
)


def _response(payload: dict[str, Any] | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "application/json" if payload is not None else "text/html"
    response._content = json.dumps(payload).encode("utf-8") if payload is not None else b"ok"
    return response


def _row(
    *,
    listing_id: str,
    document_id: str,
    title: str,
    published: str,
    announcement_id: int = 1225572157,
) -> dict[str, Any]:
    return {
        "id": listing_id,
        "annId": announcement_id,
        "title": title,
        "publishTime": published,
        "attachPath": f"/disc/disk03/finalpage/{published[:10]}/{document_id}.PDF",
        "attachFormat": "PDF",
        "secCode": ["002727"],
    }


class _ListingSession(requests.Session):
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        super().__init__()
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        assert url == "https://www.szse.cn/disclosure/listed/notice/"
        assert kwargs["allow_redirects"] is False
        return _response()

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        assert url == "https://www.szse.cn/api/disc/announcement/annList"
        assert kwargs["allow_redirects"] is False
        assert kwargs["headers"]["Content-Type"] == "application/json"
        self.calls.append(kwargs["json"])
        return _response(self.pages[len(self.calls) - 1])


def _official_rows() -> list[dict[str, Any]]:
    return [
        _row(
            listing_id="9c43da56-f888-4402-9870-a23a4f23bfd6",
            document_id="37e23922-f64d-4203-9d27-9ed981a8f799",
            title="一心堂：2026年中期权益分派实施公告",
            published="2026-09-17 00:00:00",
            announcement_id=1225572157,
        ),
        _row(
            listing_id="290e0f62-0344-42a4-96ef-1414340c764a",
            document_id="78dc6344-f740-4c50-b4a0-7e9d5159f02e",
            title="一心堂：2026年中期权益分派实施公告（更正后）",
            published="2026-09-19 00:00:00",
            announcement_id=1225572158,
        ),
    ]


def test_complete_listing_keeps_original_and_correction_with_exact_page_bodies(
    tmp_path: Path,
) -> None:
    original, corrected = _official_rows()
    session = _ListingSession(
        [
            {"announceCount": 2, "data": [original]},
            {"announceCount": 2, "data": [corrected]},
            {"announceCount": 2, "data": [original]},
            {"announceCount": 2, "data": [corrected]},
        ]
    )

    result = capture_official_szse_announcement_window(
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        body_store_root=tmp_path,
        session=session,
        page_size=1,
    )

    assert result.announcement_count == 2
    assert len(result.entries) == 2
    assert result.entries[1].source_document_id == "78dc6344-f740-4c50-b4a0-7e9d5159f02e"
    assert result.entries[1].published_on == date(2026, 9, 19)
    assert len(result.page_body_sha256) == 2
    assert len(result.first_pass_page_body_sha256) == len(result.page_body_sha256)
    assert result.first_pass_page_body_sha256 == result.page_body_sha256
    assert all((tmp_path / f"{digest}.json").is_file() for digest in result.page_body_sha256)
    assert all(
        (tmp_path / f"{digest}.json").is_file() for digest in result.first_pass_page_body_sha256
    )
    assert [call["pageNum"] for call in session.calls] == [1, 2, 1, 2]
    assert all(call["stock"] == ["002727"] for call in session.calls)


def test_listing_manifest_replay_is_deterministic_and_versions_both_passes(
    tmp_path: Path,
) -> None:
    row = _official_rows()[0]
    pages = [
        {"announceCount": 1, "data": [row]},
        {"announceCount": 1, "data": [row]},
        {"announceCount": 1, "data": [row]},
        {"announceCount": 1, "data": [row]},
    ]
    first = capture_official_szse_announcement_window(
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        body_store_root=tmp_path,
        session=_ListingSession(pages.copy()),
    )
    replay = capture_official_szse_announcement_window(
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        body_store_root=tmp_path,
        session=_ListingSession(pages.copy()),
    )

    assert first.manifest_sha256 == replay.manifest_sha256
    assert first.coverage_manifest_sha256 == replay.coverage_manifest_sha256
    assert first.manifest_sha256 != first.coverage_manifest_sha256
    assert first.first_pass_page_body_sha256 == replay.first_pass_page_body_sha256
    assert first.page_body_sha256 == replay.page_body_sha256
    legacy_manifest = {
        "schema": "szse.announcement-window.v1",
        "asset_code": first.asset_code,
        "start_on": first.start_on.isoformat(),
        "end_on": first.end_on.isoformat(),
        "announcement_count": first.announcement_count,
        "entries": [item.to_manifest_payload() for item in first.entries],
        "page_body_sha256": first.page_body_sha256,
    }
    expected_v1 = hashlib.sha256(
        json.dumps(
            legacy_manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert first.manifest_sha256 == expected_v1


@pytest.mark.parametrize(
    "pages",
    [
        lambda a, b: [
            {"announceCount": 2, "data": [a]},
            {"announceCount": 2, "data": [a]},
        ],
        lambda a, b: [
            {"announceCount": 2, "data": [a]},
            {"announceCount": 1, "data": [b]},
        ],
        lambda a, b: [
            {"announceCount": 1, "data": [a]},
            {"announceCount": 1, "data": [b]},
        ],
    ],
)
def test_listing_rejects_duplicate_changed_count_or_changed_second_pass(
    tmp_path: Path, pages: Any
) -> None:
    original, corrected = _official_rows()
    session = _ListingSession(pages(original, corrected))

    with pytest.raises(OfficialSzseListingError):
        capture_official_szse_announcement_window(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            body_store_root=tmp_path,
            session=session,
            page_size=1,
        )


def test_listing_rejects_wrong_security_or_out_of_window_row(tmp_path: Path) -> None:
    for replacement in (
        "301237",
        "2026-10-01 00:00:00",
        "2026-09-17 99:99:99",
    ):
        row = _official_rows()[0]
        if replacement == "301237":
            row["secCode"] = [replacement]
        else:
            row["publishTime"] = replacement
        session = _ListingSession([{"announceCount": 1, "data": [row]}])
        with pytest.raises(OfficialSzseListingError):
            capture_official_szse_announcement_window(
                asset_code="002727.SZ",
                start_on=date(2026, 9, 1),
                end_on=date(2026, 9, 30),
                body_store_root=tmp_path,
                session=session,
            )


@pytest.mark.parametrize("failed_method", ["GET", "POST"])
@pytest.mark.parametrize("failures", [2, 4])
def test_owned_official_transport_retries_resets_but_never_certifies_exhaustion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failed_method: str, failures: int
) -> None:
    """Run the actual HTTP retry path over synthetic transport resets and source bytes."""
    import io

    from urllib3.connectionpool import HTTPSConnectionPool
    from urllib3.exceptions import ProtocolError
    from urllib3.response import HTTPResponse
    from urllib3.util.retry import Retry

    import apps.data_center.infrastructure.official_szse_announcement_listing as listing

    attempts: list[str] = []
    failed = 0
    original_factory = listing._official_session

    def session_factory() -> requests.Session:
        session = original_factory()
        session.trust_env = False
        return session

    def make_request(
        pool: object, conn: object, method: str, url: str, **kwargs: Any
    ) -> HTTPResponse:
        nonlocal failed
        attempts.append(method)
        if method == failed_method and failed < failures:
            failed += 1
            raise ProtocolError("synthetic official connection reset")
        body = b"synthetic landing" if method == "GET" else b'{"announceCount":0,"data":[]}'
        return HTTPResponse(
            body=io.BytesIO(body),
            status=200,
            headers={"Content-Type": "text/html" if method == "GET" else "application/json"},
            preload_content=False,
        )

    monkeypatch.setattr(listing, "_official_session", session_factory)
    monkeypatch.setattr(HTTPSConnectionPool, "_make_request", make_request)
    monkeypatch.setattr(Retry, "sleep", lambda self, response=None: None)
    arguments = {
        "asset_code": "001211.SZ",
        "start_on": date(2026, 11, 6),
        "end_on": date(2026, 11, 15),
        "body_store_root": tmp_path,
    }
    if failures == 4:
        with pytest.raises(OfficialSzseListingError):
            listing.capture_official_szse_announcement_window(**arguments)
        assert attempts.count(failed_method) == 4
        assert not tuple(tmp_path.iterdir())
    else:
        result = listing.capture_official_szse_announcement_window(**arguments)
        assert result.announcement_count == 0
        assert result.first_pass_page_body_sha256 == result.page_body_sha256
        assert len(attempts) == 5
