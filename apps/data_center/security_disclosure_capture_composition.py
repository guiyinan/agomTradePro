"""Compose official PDF capture with Data Center disclosure fact persistence."""

from __future__ import annotations

import re
from pathlib import Path

from apps.data_center.application.security_disclosure_event import (
    AppendSecurityDisclosureEventUseCase,
)
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SecurityDisclosureEventAppendResult,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
)
from apps.data_center.infrastructure.official_szse_pdf_capture import (
    OfficialSzsePdfBodyStore,
    capture_official_szse_pdf,
    classify_szse_pdf_disclosure,
    extract_szse_distribution_dates,
)
from apps.data_center.infrastructure.security_disclosure_event_repository import (
    DjangoSecurityDisclosureEventRepository,
)


def capture_and_append_szse_disclosure(
    *, source_url: str, asset_code: str, body_store_root: Path, using: str = "default"
) -> SecurityDisclosureEventAppendResult:
    """Retain one verified official PDF and append its conservative PIT fact."""

    if type(asset_code) is not str or re.fullmatch(r"[0-9]{6}\.SZ", asset_code) is None:
        raise ValueError("asset_code must be a canonical SZSE security code")
    source_security_code = asset_code[:6]
    captured = capture_official_szse_pdf(source_url)
    raw_event_type, event_type = classify_szse_pdf_disclosure(captured, source_security_code)
    effective_on = None
    if event_type in (
        SecurityDisclosureEventType.CASH_DIVIDEND,
        SecurityDisclosureEventType.STOCK_DIVIDEND,
    ):
        _, effective_on = extract_szse_distribution_dates(captured, source_security_code)
    body_store = OfficialSzsePdfBodyStore(body_store_root)
    body_store.retain(captured)
    event = SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code=asset_code,
        source_security_code=source_security_code,
        source_event_id=captured.source_document_id,
        source_revision_id=f"sha256:{captured.body_sha256}",
        raw_event_type=raw_event_type,
        event_type=event_type,
        source_url=captured.source_url,
        source_document_body=captured.body,
        first_seen_at=captured.first_seen_at,
        effective_at=effective_on,
    )
    repository = DjangoSecurityDisclosureEventRepository(using=using)
    return AppendSecurityDisclosureEventUseCase(repository).execute(event, captured.body)
