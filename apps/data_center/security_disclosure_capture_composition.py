"""Capture and normalize official SZSE disclosure source evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from apps.data_center.application.security_disclosure_event import (
    AppendSecurityDisclosureEventUseCase,
    AppendSecurityDisclosureListingCoverageUseCase,
    QuerySecurityDisclosureEventsUseCase,
    QuerySecurityDisclosureListingCoverageUseCase,
)
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SecurityDisclosureEventAppendResult,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureListingCoverageProof,
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
    DjangoSecurityDisclosureListingCoverageRepository,
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


def make_security_disclosure_listing_coverage_reader(
    *, using: str = "default"
) -> QuerySecurityDisclosureListingCoverageUseCase:
    """Compose the non-current exact-window proof reader with Data Center repositories."""

    return QuerySecurityDisclosureListingCoverageUseCase(
        coverage_repository=DjangoSecurityDisclosureListingCoverageRepository(using=using),
        event_repository=DjangoSecurityDisclosureEventRepository(using=using),
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
class SecurityDisclosureEventAppendUseCases:
    """Data Center-owned append use cases bound to one database alias."""

    database_alias: str
    events: AppendSecurityDisclosureEventUseCase
    coverage: AppendSecurityDisclosureListingCoverageUseCase


def make_security_disclosure_event_append_use_cases(
    *, using: str, recorded_at: datetime
) -> SecurityDisclosureEventAppendUseCases:
    """Bind both append repositories to the caller's exact batch persistence instant."""

    if type(using) is not str or not using:
        raise ValueError("using must be a non-empty database alias")
    if (
        type(recorded_at) is not datetime
        or recorded_at.tzinfo is None
        or recorded_at.utcoffset() is None
    ):
        raise ValueError("recorded_at must be an aware batch timestamp")
    clock = _FixedSecurityDisclosureEventClock(recorded_at)
    return SecurityDisclosureEventAppendUseCases(
        database_alias=using,
        events=AppendSecurityDisclosureEventUseCase(
            DjangoSecurityDisclosureEventRepository(using=using, clock=clock)
        ),
        coverage=AppendSecurityDisclosureListingCoverageUseCase(
            DjangoSecurityDisclosureListingCoverageRepository(using=using, clock=clock)
        ),
    )


@dataclass(frozen=True, slots=True)
class _FixedSecurityDisclosureEventClock:
    """Return one trusted server timestamp for both batch append repositories."""

    instant: datetime

    def now(self) -> datetime:
        """Return the caller-supplied, timezone-aware batch instant."""

        return self.instant


@dataclass(frozen=True, slots=True)
class CapturedSzseDistributionCandidate:
    """Fully captured source documents and exact listing proof, not yet persisted."""

    listing: CapturedOfficialSzseListingWindow
    events: tuple[tuple[SecurityDisclosureEvent, bytes], ...]
    proof: SecurityDisclosureListingCoverageProof


def _distribution_title_key(title: str) -> str:
    """Normalize one source title only for a bounded correction-lineage match."""

    body = title.split("：", 1)[-1]
    return re.sub(r"\s+", "", body).removesuffix("（更正后）")


def capture_szse_distribution_window(
    *,
    asset_code: str,
    start_on: date,
    end_on: date,
    body_store_root: Path,
) -> CapturedSzseDistributionCandidate:
    """Capture every listed official PDF, recheck both lists, and return typed evidence."""

    if type(asset_code) is not str or re.fullmatch(r"[0-9]{6}\.SZ", asset_code) is None:
        raise ValueError("asset_code must be a canonical SZSE security code")
    listing = capture_official_szse_announcement_window(
        asset_code=asset_code,
        start_on=start_on,
        end_on=end_on,
        body_store_root=body_store_root / "listing",
    )
    body_store = OfficialSzsePdfBodyStore(body_store_root / "pdf")
    latest_by_title: dict[str, SecurityDisclosureEvent] = {}
    captured_events: list[tuple[SecurityDisclosureEvent, bytes]] = []
    listed_entries = sorted(
        listing.entries, key=lambda item: (item.published_on, item.announcement_id)
    )
    for item in listed_entries:
        issuer_name, separator, _ = item.title.partition("：")
        if not separator or not issuer_name:
            raise OfficialSzseListingError("listed PDF row does not identify its issuer")
        captured = capture_official_szse_pdf(item.source_url)
        if (
            captured.source_document_id != item.source_document_id
            or captured.source_url != item.source_url
            or captured.first_seen_at < listing.observed_at
        ):
            raise OfficialSzseListingError("listed PDF identity or capture clock is invalid")
        raw_event_type, event_type = classify_szse_pdf_disclosure(
            captured,
            asset_code[:6],
            expected_issuer_name=issuer_name,
            expected_listing_title=item.title,
        )
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
        captured_events.append((event, captured.body))
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
    if (
        final_listing.manifest_sha256 != listing.manifest_sha256
        or final_listing.coverage_manifest_sha256 != listing.coverage_manifest_sha256
    ):
        raise OfficialSzseListingError("SZSE listing changed during PDF capture")
    if any(event.first_seen_at > final_listing.observed_at for event, _ in captured_events):
        raise OfficialSzseListingError("SZSE PDF knowledge follows final listing verification")
    proof = SecurityDisclosureListingCoverageProof(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code=final_listing.asset_code,
        start_on=final_listing.start_on,
        end_on=final_listing.end_on,
        first_observed_at=listing.observed_at,
        verified_at=final_listing.observed_at,
        announcement_count=final_listing.announcement_count,
        entries=final_listing.entries,
        first_pass_page_body_sha256=final_listing.first_pass_page_body_sha256,
        second_pass_page_body_sha256=final_listing.page_body_sha256,
    )
    return CapturedSzseDistributionCandidate(
        listing=final_listing,
        events=tuple(captured_events),
        proof=proof,
    )
