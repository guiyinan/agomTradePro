"""Official SZSE listing coverage requires complete stable source pages."""

from __future__ import annotations

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


def _row(*, listing_id: str, document_id: str, title: str, published: str) -> dict[str, Any]:
    return {
        "id": listing_id,
        "annId": 1225572157,
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
        ),
        _row(
            listing_id="290e0f62-0344-42a4-96ef-1414340c764a",
            document_id="78dc6344-f740-4c50-b4a0-7e9d5159f02e",
            title="一心堂：2026年中期权益分派实施公告（更正后）",
            published="2026-09-19 00:00:00",
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
    assert all((tmp_path / f"{digest}.json").is_file() for digest in result.page_body_sha256)
    assert [call["pageNum"] for call in session.calls] == [1, 2, 1, 2]
    assert all(call["stock"] == ["002727"] for call in session.calls)


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
