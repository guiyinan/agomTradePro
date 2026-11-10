"""Compose official PDF capture with Data Center disclosure fact persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from apps.data_center.application.security_disclosure_event import (
    AppendSecurityDisclosureEventUseCase,
    QuerySecurityDisclosureEventsUseCase,
)
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SecurityDisclosureEventAppendResult,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
    SzseDistributionTerms,
)
from apps.data_center.infrastructure.official_szse_announcement_listing import (
    CapturedOfficialSzseListingWindow,
    OfficialSzseListingError,
    capture_official_szse_announcement_window,
)
from apps.data_center.infrastructure.official_szse_pdf_capture import (
    CapturedOfficialSzsePdf,
    OfficialSzsePdfBodyStore,
    capture_official_szse_pdf,
    classify_szse_pdf_disclosure,
    extract_szse_distribution_dates,
    extract_szse_distribution_terms,
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


def make_security_disclosure_event_reader(
    *, using: str = "default"
) -> QuerySecurityDisclosureEventsUseCase:
    """Compose the public PIT reader with its owning Data Center repository."""

    return QuerySecurityDisclosureEventsUseCase(
        DjangoSecurityDisclosureEventRepository(using=using)
    )


def read_verified_szse_distribution(
    event: SecurityDisclosureEvent, *, body_store_root: Path
) -> SzseDistributionTerms | None:
    """Reopen the retained body and parse exact distribution terms in Data Center."""

    body = OfficialSzsePdfBodyStore(body_store_root).read(event.source_body_sha256)
    capture = CapturedOfficialSzsePdf(
        source_url=event.source_url,
        source_document_id=event.source_event_id,
        first_seen_at=event.first_seen_at,
        body_sha256=event.source_body_sha256,
        body=body,
    )
    return extract_szse_distribution_terms(capture, event.source_security_code)


@dataclass(frozen=True, slots=True)
class SzseDistributionWindowIngestion:
    """Retained complete list and only its explicitly selected distribution notices."""

    listing: CapturedOfficialSzseListingWindow
    events: tuple[SecurityDisclosureEventAppendResult, ...]


def _distribution_title_key(title: str) -> str:
    """Normalize one source title only for a bounded correction-lineage match."""

    body = title.split("：", 1)[-1]
    return re.sub(r"\s+", "", body).removesuffix("（更正后）")


def capture_and_append_szse_distribution_window(
    *,
    asset_code: str,
    start_on: date,
    end_on: date,
    body_store_root: Path,
    using: str = "default",
) -> SzseDistributionWindowIngestion:
    """Append distribution PDFs from a twice-stable official list with correction links."""

    listing = capture_official_szse_announcement_window(
        asset_code=asset_code,
        start_on=start_on,
        end_on=end_on,
        body_store_root=body_store_root / "listing",
    )
    repository = DjangoSecurityDisclosureEventRepository(using=using)
    use_case = AppendSecurityDisclosureEventUseCase(repository)
    body_store = OfficialSzsePdfBodyStore(body_store_root / "pdf")
    latest_by_title: dict[str, SecurityDisclosureEvent] = {}
    results: list[SecurityDisclosureEventAppendResult] = []
    selected = sorted(
        (item for item in listing.entries if "权益分派" in item.title),
        key=lambda item: (item.published_on, item.announcement_id),
    )
    for item in selected:
        captured = capture_official_szse_pdf(item.source_url)
        if (
            captured.source_document_id != item.source_document_id
            or captured.source_url != item.source_url
            or captured.first_seen_at < listing.observed_at
        ):
            raise OfficialSzseListingError("listed PDF identity or capture clock is invalid")
        raw_event_type, event_type = classify_szse_pdf_disclosure(captured, asset_code[:6])
        corrected = item.title.endswith("（更正后）")
        title_key = _distribution_title_key(item.title)
        prior = latest_by_title.get(title_key)
        if corrected and prior is None:
            raise OfficialSzseListingError("corrected distribution has no prior source PDF")
        if (
            not corrected
            and event_type
            in (
                SecurityDisclosureEventType.CASH_DIVIDEND,
                SecurityDisclosureEventType.STOCK_DIVIDEND,
            )
            and prior is not None
        ):
            raise OfficialSzseListingError("distribution title identity is ambiguous")
        if corrected and event_type not in (
            SecurityDisclosureEventType.CASH_DIVIDEND,
            SecurityDisclosureEventType.STOCK_DIVIDEND,
        ):
            raise OfficialSzseListingError("corrected distribution PDF is not classified")
        effective_on = None
        if event_type in (
            SecurityDisclosureEventType.CASH_DIVIDEND,
            SecurityDisclosureEventType.STOCK_DIVIDEND,
        ):
            _, effective_on = extract_szse_distribution_dates(captured, asset_code[:6])
        body_store.retain(captured)
        event = SecurityDisclosureEvent.from_source_document(
            source=SecurityDisclosureSource.SZSE_OFFICIAL,
            exchange=SecurityDisclosureExchange.SZSE,
            asset_code=asset_code,
            source_security_code=asset_code[:6],
            source_event_id=captured.source_document_id,
            source_revision_id=f"sha256:{captured.body_sha256}",
            raw_event_type=raw_event_type,
            event_type=event_type,
            source_url=captured.source_url,
            source_document_body=captured.body,
            first_seen_at=captured.first_seen_at,
            announced_at=item.published_on,
            source_available_at=item.published_on,
            effective_at=effective_on,
            supersedes_source_event_id=prior.source_event_id if corrected and prior else None,
            supersedes_source_revision_id=(
                prior.source_revision_id if corrected and prior else None
            ),
        )
        results.append(use_case.execute(event, captured.body))
        if event_type in (
            SecurityDisclosureEventType.CASH_DIVIDEND,
            SecurityDisclosureEventType.STOCK_DIVIDEND,
        ):
            latest_by_title[title_key] = event
    final_listing = capture_official_szse_announcement_window(
        asset_code=asset_code,
        start_on=start_on,
        end_on=end_on,
        body_store_root=body_store_root / "listing",
    )
    if final_listing.manifest_sha256 != listing.manifest_sha256:
        raise OfficialSzseListingError("SZSE listing changed during PDF capture")
    return SzseDistributionWindowIngestion(listing=final_listing, events=tuple(results))
