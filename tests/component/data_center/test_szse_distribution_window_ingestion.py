"""A stable official list links original and corrected distribution PDF facts."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from apps.data_center import security_disclosure_capture_composition as composition
from apps.data_center.application.security_disclosure_event import (
    QuerySecurityDisclosureEventsUseCase,
)
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEventReadScope,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
)
from apps.data_center.infrastructure.official_szse_announcement_listing import (
    CapturedOfficialSzseListingWindow,
    OfficialSzseListingEntry,
)
from apps.data_center.infrastructure.official_szse_pdf_capture import CapturedOfficialSzsePdf
from apps.data_center.infrastructure.security_disclosure_event_repository import (
    DjangoSecurityDisclosureEventRepository,
)


@pytest.mark.django_db
def test_window_ingestion_links_corrected_pdf_and_replays_without_duplicate_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original_id = "37e23922-f64d-4203-9d27-9ed981a8f799"
    notice_id = "ab610720-03a5-49f0-9986-d66826f56985"
    corrected_id = "78dc6344-f740-4c50-b4a0-7e9d5159f02e"
    documents = (
        (original_id, 1225568073, date(2026, 9, 17), "权益分派实施公告"),
        (notice_id, 1225572157, date(2026, 9, 19), "权益分派实施的更正公告"),
        (corrected_id, 1225572158, date(2026, 9, 19), "权益分派实施公告（更正后）"),
    )
    entries = tuple(
        OfficialSzseListingEntry(
            listing_id=f"00000000-0000-4000-8000-{index:012d}",
            announcement_id=announcement_id,
            title=f"一心堂：2026年中期{title}",
            published_on=published_on,
            raw_publish_time=f"{published_on.isoformat()} 00:00:00",
            source_document_id=document_id,
            source_url=(
                f"https://disc.static.szse.cn/disc/disk03/finalpage/"
                f"{published_on.isoformat()}/{document_id}.PDF"
            ),
        )
        for index, (document_id, announcement_id, published_on, title) in enumerate(
            documents, start=1
        )
    )
    listing_observed_at = timezone.now() - timedelta(seconds=2)
    listing = CapturedOfficialSzseListingWindow(
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        observed_at=listing_observed_at,
        announcement_count=3,
        entries=tuple(reversed(entries)),
        page_body_sha256=("a" * 64,),
        manifest_sha256="b" * 64,
    )
    first_seen_at = listing_observed_at + timedelta(seconds=1)
    bodies = {
        document_id: f"%PDF-1.4\n{document_id}\n%%EOF".encode() for document_id, *_ in documents
    }
    by_url = {entry.source_url: entry for entry in entries}

    def fake_capture(url: str) -> CapturedOfficialSzsePdf:
        entry = by_url[url]
        body = bodies[entry.source_document_id]
        return CapturedOfficialSzsePdf(
            source_url=url,
            source_document_id=entry.source_document_id,
            first_seen_at=first_seen_at,
            body_sha256=hashlib.sha256(body).hexdigest(),
            body=body,
        )

    def fake_classify(
        capture: CapturedOfficialSzsePdf, security_code: str
    ) -> tuple[str, SecurityDisclosureEventType]:
        assert security_code == "002727"
        return (
            capture.source_document_id,
            (
                SecurityDisclosureEventType.CORRECTION_NOTICE
                if capture.source_document_id == notice_id
                else SecurityDisclosureEventType.CASH_DIVIDEND
            ),
        )

    monkeypatch.setattr(
        composition, "capture_official_szse_announcement_window", lambda **kwargs: listing
    )
    monkeypatch.setattr(composition, "capture_official_szse_pdf", fake_capture)
    monkeypatch.setattr(composition, "classify_szse_pdf_disclosure", fake_classify)
    monkeypatch.setattr(
        composition,
        "extract_szse_distribution_dates",
        lambda capture, code: (date(2026, 9, 23), date(2026, 9, 24)),
    )

    first = composition.capture_and_append_szse_distribution_window(
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        body_store_root=tmp_path,
    )
    second = composition.capture_and_append_szse_distribution_window(
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        body_store_root=tmp_path,
    )
    facts = QuerySecurityDisclosureEventsUseCase(DjangoSecurityDisclosureEventRepository()).execute(
        SecurityDisclosureEventReadScope(
            as_of=timezone.now(),
            exchange=SecurityDisclosureExchange.SZSE,
            asset_code="002727.SZ",
        )
    )

    assert len(first.events) == len(second.events) == len(facts) == 3
    corrected = next(item.event for item in facts if item.event.source_event_id == corrected_id)
    assert corrected.supersedes_source_event_id == original_id
    assert corrected.supersedes_source_revision_id == (
        f"sha256:{hashlib.sha256(bodies[original_id]).hexdigest()}"
    )
    assert corrected.announced_at == date(2026, 9, 19)
    assert (
        next(item.event for item in facts if item.event.source_event_id == notice_id).event_type
        is SecurityDisclosureEventType.CORRECTION_NOTICE
    )
