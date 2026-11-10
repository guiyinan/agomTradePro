"""A verified official document reaches the append-only source fact store once."""

from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from apps.data_center import security_disclosure_capture_composition as composition
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEventAppendDisposition,
    SecurityDisclosureEventReadScope,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
)
from apps.data_center.infrastructure.official_szse_pdf_capture import CapturedOfficialSzsePdf
from apps.data_center.infrastructure.security_disclosure_event_repository import (
    DjangoSecurityDisclosureEventRepository,
)

_URL = (
    "https://disc.static.szse.cn/disc/disk03/finalpage/2026-09-17/"
    "37e23922-f64d-4203-9d27-9ed981a8f799.PDF"
)


@pytest.mark.django_db
def test_verified_szse_pdf_append_replays_without_duplicate_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hashlib

    body = b"%PDF-1.4\nverified source\n%%EOF"
    first_seen_at = timezone.now() - timedelta(seconds=1)
    capture = CapturedOfficialSzsePdf(
        source_url=_URL,
        source_document_id="37e23922-f64d-4203-9d27-9ed981a8f799",
        first_seen_at=first_seen_at,
        body_sha256=hashlib.sha256(body).hexdigest(),
        body=body,
    )
    monkeypatch.setattr(composition, "capture_official_szse_pdf", lambda url: capture)
    monkeypatch.setattr(
        composition,
        "classify_szse_pdf_disclosure",
        lambda value, security_code, **kwargs: (
            "2026 年中期权益分派实施公告",
            SecurityDisclosureEventType.CASH_DIVIDEND,
        ),
    )
    monkeypatch.setattr(
        composition,
        "extract_szse_distribution_dates",
        lambda value, security_code: (None, None),
    )

    first = composition.capture_and_append_szse_disclosure(
        source_url=_URL, asset_code="002727.SZ", body_store_root=tmp_path
    )
    replay = composition.capture_and_append_szse_disclosure(
        source_url=_URL, asset_code="002727.SZ", body_store_root=tmp_path
    )
    rows = DjangoSecurityDisclosureEventRepository().list_known_at(
        SecurityDisclosureEventReadScope(
            as_of=timezone.now(),
            exchange=SecurityDisclosureExchange.SZSE,
            asset_code="002727.SZ",
        )
    )

    assert first.disposition is SecurityDisclosureEventAppendDisposition.STORED
    assert replay.disposition is SecurityDisclosureEventAppendDisposition.DUPLICATE
    assert len(rows) == 1
    assert rows[0].event.source_revision_id == f"sha256:{capture.body_sha256}"
    assert rows[0].event.announced_at is None
    assert rows[0].event.first_seen_at == first_seen_at
