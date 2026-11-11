"""A stable official list links original and corrected distribution PDF facts."""

from __future__ import annotations

import hashlib
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.audit import security_disclosure_capture_composition as composition
from apps.audit.application.security_disclosure_audit import (
    AppendSecurityDisclosureAuditObservationUseCase,
    SecurityDisclosureAuditConflict,
    SecurityDisclosureAuditDisposition,
    SecurityDisclosureAuditUnavailable,
)
from apps.audit.application.system_audit_authority_renewal_guard import (
    SystemAuditAuthorityLease,
)
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCommit
from apps.audit.domain.system_audit_event import AuditScopeRef, SystemAuditEvent
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_repository import DjangoSystemAuditEventRepository
from apps.data_center import security_disclosure_capture_composition as source_composition
from apps.data_center.application.security_disclosure_event import (
    AppendSecurityDisclosureEventUseCase,
    AppendSecurityDisclosureListingCoverageUseCase,
    QuerySecurityDisclosureEventsUseCase,
    QuerySecurityDisclosureListingCoverageUseCase,
)
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SecurityDisclosureEventReadScope,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureListingCoverageProof,
    SecurityDisclosureListingCoverageReadScope,
    SecurityDisclosureListingCoverageStatus,
    SecurityDisclosureListingEntry,
    SecurityDisclosureSource,
)
from apps.data_center.infrastructure.official_szse_announcement_listing import (
    CapturedOfficialSzseListingWindow,
)
from apps.data_center.infrastructure.official_szse_pdf_capture import CapturedOfficialSzsePdf
from apps.data_center.infrastructure.security_disclosure_event_models import (
    SecurityDisclosureEventModel,
    SecurityDisclosureListingCoverageModel,
)
from apps.data_center.infrastructure.security_disclosure_event_repository import (
    DjangoSecurityDisclosureEventRepository,
    DjangoSecurityDisclosureListingCoverageRepository,
)


class _StaticDisclosureAuditScope:
    """Provide a fixed authority scope for isolated transactional components."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        assert as_of.tzinfo is not None
        return AuditScopeRef("test-tenant", "test-owner")


class _TestDisclosureAuditWriter:
    """Add complete stream reads to the canonical coordinator for component tests."""

    def __init__(self) -> None:
        self._coordinator = DjangoSystemAuditEventOutboxCoordinator(using="default")
        self._event_repository = DjangoSystemAuditEventRepository(using="default")

    @property
    def database_alias(self) -> str:
        return self._coordinator.database_alias

    def atomic(self) -> AbstractContextManager[None]:
        return self._coordinator.atomic()

    def append_and_enqueue(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> SystemAuditEventOutboxCommit:
        return self._coordinator.append_and_enqueue(
            event,
            expected_predecessor_hash=expected_predecessor_hash,
            recorded_at=recorded_at,
        )

    def get_winner(
        self,
        *,
        event_id: str,
        event_version: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        return self._coordinator.get_winner(
            event_id=event_id,
            event_version=event_version,
            as_of=as_of,
        )

    def get_current_head(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> SystemAuditEvent | None:
        return self._coordinator.get_current_head(
            stream_id=stream_id,
            as_of=as_of,
            scope=scope,
        )

    def list_events(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> tuple[SystemAuditEvent, ...]:
        return self._event_repository.list_events(
            stream_id=stream_id,
            as_of=as_of,
            scope=scope,
        )


def _configure_test_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> AppendSecurityDisclosureAuditObservationUseCase:
    """Use the real same-alias Audit coordinator with a controlled authority scope."""

    writer = AppendSecurityDisclosureAuditObservationUseCase(
        _TestDisclosureAuditWriter(),
        _StaticDisclosureAuditScope(),
    )
    monkeypatch.setattr(
        composition,
        "get_system_audit_authority_lease",
        lambda **kwargs: SystemAuditAuthorityLease(
            mode="required",
            outbox_enabled=True,
            valid_until=timezone.now() + timedelta(hours=1),
        ),
    )
    monkeypatch.setattr(
        composition,
        "build_security_disclosure_audit_writer",
        lambda **kwargs: writer,
    )
    return writer


@pytest.mark.django_db
def test_window_ingestion_links_corrected_pdf_and_replays_without_duplicate_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_test_audit(monkeypatch)
    original_id = "37e23922-f64d-4203-9d27-9ed981a8f799"
    notice_id = "ab610720-03a5-49f0-9986-d66826f56985"
    corrected_id = "78dc6344-f740-4c50-b4a0-7e9d5159f02e"
    documents = (
        (original_id, 1225568073, date(2026, 9, 17), "权益分派实施公告"),
        (notice_id, 1225572157, date(2026, 9, 19), "权益分派实施的更正公告"),
        (corrected_id, 1225572158, date(2026, 9, 19), "权益分派实施公告（更正后）"),
    )
    entries = tuple(
        SecurityDisclosureListingEntry(
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
    listing_observed_at = timezone.now() - timedelta(seconds=30)
    verified_at = listing_observed_at + timedelta(seconds=5)
    retained_entries = tuple(reversed(entries))
    proof = SecurityDisclosureListingCoverageProof(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        first_observed_at=listing_observed_at,
        verified_at=verified_at,
        announcement_count=len(retained_entries),
        entries=retained_entries,
        first_pass_page_body_sha256=("a" * 64,),
        second_pass_page_body_sha256=("a" * 64,),
    )

    def make_listing(observed_at: datetime) -> CapturedOfficialSzseListingWindow:
        return CapturedOfficialSzseListingWindow(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            observed_at=observed_at,
            announcement_count=len(retained_entries),
            entries=retained_entries,
            first_pass_page_body_sha256=("a" * 64,),
            page_body_sha256=("a" * 64,),
            manifest_sha256=proof.source_manifest_sha256,
            coverage_manifest_sha256=proof.coverage_manifest_sha256,
        )

    listing = make_listing(listing_observed_at)
    final_listing = make_listing(verified_at)
    later_listing = make_listing(listing_observed_at + timedelta(seconds=10))
    later_final_listing = make_listing(listing_observed_at + timedelta(seconds=15))
    batch_first_seen_at = (
        listing_observed_at + timedelta(seconds=1),
        listing_observed_at + timedelta(seconds=1),
        listing_observed_at + timedelta(seconds=11),
    )
    bodies = {
        document_id: f"%PDF-1.4\n{document_id}\n%%EOF".encode() for document_id, *_ in documents
    }
    by_url = {entry.source_url: entry for entry in entries}
    capture_count = 0

    def fake_capture(url: str) -> CapturedOfficialSzsePdf:
        nonlocal capture_count
        batch_number = capture_count // len(entries)
        capture_count += 1
        entry = by_url[url]
        body = bodies[entry.source_document_id]
        return CapturedOfficialSzsePdf(
            source_url=url,
            source_document_id=entry.source_document_id,
            first_seen_at=batch_first_seen_at[batch_number],
            body_sha256=hashlib.sha256(body).hexdigest(),
            body=body,
        )

    def fake_classify(
        capture: CapturedOfficialSzsePdf, security_code: str, **kwargs: object
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

    listings = iter(
        (
            listing,
            final_listing,
            listing,
            final_listing,
            later_listing,
            later_final_listing,
        )
    )
    monkeypatch.setattr(
        source_composition,
        "capture_official_szse_announcement_window",
        lambda **kwargs: next(listings),
    )
    monkeypatch.setattr(source_composition, "capture_official_szse_pdf", fake_capture)
    monkeypatch.setattr(source_composition, "classify_szse_pdf_disclosure", fake_classify)
    monkeypatch.setattr(
        source_composition,
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
    later = composition.capture_and_append_szse_distribution_window(
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

    assert len(first.events) == len(second.events) == len(later.events) == len(facts) == 3
    assert first.audit.disposition is SecurityDisclosureAuditDisposition.STORED
    assert second.audit.disposition is SecurityDisclosureAuditDisposition.DUPLICATE
    assert later.audit.disposition is SecurityDisclosureAuditDisposition.STORED
    assert later.coverage.disposition.value == "stored"
    assert (
        SystemAuditEventModel.objects.filter(event_type="data.disclosure_fact.appended").count()
        == 2
    )
    assert SystemAuditOutboxModel.objects.count() == 2
    assert SecurityDisclosureListingCoverageModel.objects.count() == 2
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


@pytest.mark.django_db
def test_final_listing_change_leaves_no_disclosure_facts_or_coverage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_test_audit(monkeypatch)
    document_id = "37e23922-f64d-4203-9d27-9ed981a8f799"
    entry = SecurityDisclosureListingEntry(
        listing_id="00000000-0000-4000-8000-000000000001",
        announcement_id=1225568073,
        title="一心堂：2026年中期权益分派实施公告",
        published_on=date(2026, 9, 17),
        raw_publish_time="2026-09-17 00:00:00",
        source_document_id=document_id,
        source_url=(
            "https://disc.static.szse.cn/disc/disk03/finalpage/" f"2026-09-17/{document_id}.PDF"
        ),
    )
    observed_at = timezone.now() - timedelta(seconds=30)

    def make_listing(*, observed: datetime, page_digest: str) -> CapturedOfficialSzseListingWindow:
        proof = SecurityDisclosureListingCoverageProof(
            source=SecurityDisclosureSource.SZSE_OFFICIAL,
            exchange=SecurityDisclosureExchange.SZSE,
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            first_observed_at=observed,
            verified_at=observed,
            announcement_count=1,
            entries=(entry,),
            first_pass_page_body_sha256=(page_digest,),
            second_pass_page_body_sha256=(page_digest,),
        )
        return CapturedOfficialSzseListingWindow(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            observed_at=observed,
            announcement_count=1,
            entries=(entry,),
            first_pass_page_body_sha256=(page_digest,),
            page_body_sha256=(page_digest,),
            manifest_sha256=proof.source_manifest_sha256,
            coverage_manifest_sha256=proof.coverage_manifest_sha256,
        )

    first_listing = make_listing(observed=observed_at, page_digest="a" * 64)
    changed_listing = make_listing(
        observed=observed_at + timedelta(seconds=5), page_digest="b" * 64
    )
    body = b"%PDF-1.4\nfinal-listing-rollback\n%%EOF"
    captured = CapturedOfficialSzsePdf(
        source_url=entry.source_url,
        source_document_id=document_id,
        first_seen_at=observed_at + timedelta(seconds=1),
        body_sha256=hashlib.sha256(body).hexdigest(),
        body=body,
    )
    listings = iter((first_listing, changed_listing))
    monkeypatch.setattr(
        source_composition,
        "capture_official_szse_announcement_window",
        lambda **kwargs: next(listings),
    )
    monkeypatch.setattr(source_composition, "capture_official_szse_pdf", lambda url: captured)
    monkeypatch.setattr(
        source_composition,
        "classify_szse_pdf_disclosure",
        lambda capture, security_code, **kwargs: (
            "cash_dividend",
            SecurityDisclosureEventType.CASH_DIVIDEND,
        ),
    )
    monkeypatch.setattr(
        source_composition,
        "extract_szse_distribution_dates",
        lambda capture, security_code: (date(2026, 9, 23), date(2026, 9, 24)),
    )

    with pytest.raises(source_composition.OfficialSzseListingError, match="listing changed"):
        composition.capture_and_append_szse_distribution_window(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            body_store_root=tmp_path,
        )

    assert SecurityDisclosureEventModel.objects.count() == 0
    assert SecurityDisclosureListingCoverageModel.objects.count() == 0


@pytest.mark.django_db
def test_audit_append_failure_rolls_back_facts_coverage_event_and_outbox(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_test_audit(monkeypatch)
    document_id = "37e23922-f64d-4203-9d27-9ed981a8f799"
    entry = SecurityDisclosureListingEntry(
        listing_id="00000000-0000-4000-8000-000000000002",
        announcement_id=1225568073,
        title="一心堂：2026年中期权益分派实施公告",
        published_on=date(2026, 9, 17),
        raw_publish_time="2026-09-17 00:00:00",
        source_document_id=document_id,
        source_url=(
            "https://disc.static.szse.cn/disc/disk03/finalpage/" f"2026-09-17/{document_id}.PDF"
        ),
    )
    observed_at = timezone.now() - timedelta(seconds=30)
    first_proof = SecurityDisclosureListingCoverageProof(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        first_observed_at=observed_at,
        verified_at=observed_at,
        announcement_count=1,
        entries=(entry,),
        first_pass_page_body_sha256=("a" * 64,),
        second_pass_page_body_sha256=("a" * 64,),
    )
    final_proof = SecurityDisclosureListingCoverageProof(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        first_observed_at=observed_at,
        verified_at=observed_at + timedelta(seconds=5),
        announcement_count=1,
        entries=(entry,),
        first_pass_page_body_sha256=("a" * 64,),
        second_pass_page_body_sha256=("a" * 64,),
    )

    def make_listing(
        *, proof: SecurityDisclosureListingCoverageProof
    ) -> CapturedOfficialSzseListingWindow:
        return CapturedOfficialSzseListingWindow(
            asset_code=proof.asset_code,
            start_on=proof.start_on,
            end_on=proof.end_on,
            observed_at=proof.verified_at,
            announcement_count=proof.announcement_count,
            entries=proof.entries,
            first_pass_page_body_sha256=proof.first_pass_page_body_sha256,
            page_body_sha256=proof.second_pass_page_body_sha256,
            manifest_sha256=proof.source_manifest_sha256,
            coverage_manifest_sha256=proof.coverage_manifest_sha256,
        )

    listings = iter((make_listing(proof=first_proof), make_listing(proof=final_proof)))
    body = b"%PDF-1.4\naudit-rollback\n%%EOF"
    captured = CapturedOfficialSzsePdf(
        source_url=entry.source_url,
        source_document_id=document_id,
        first_seen_at=observed_at + timedelta(seconds=1),
        body_sha256=hashlib.sha256(body).hexdigest(),
        body=body,
    )
    monkeypatch.setattr(
        source_composition,
        "capture_official_szse_announcement_window",
        lambda **kwargs: next(listings),
    )
    monkeypatch.setattr(source_composition, "capture_official_szse_pdf", lambda url: captured)
    monkeypatch.setattr(
        source_composition,
        "classify_szse_pdf_disclosure",
        lambda capture, security_code, **kwargs: (
            "cash_dividend",
            SecurityDisclosureEventType.CASH_DIVIDEND,
        ),
    )
    monkeypatch.setattr(
        source_composition,
        "extract_szse_distribution_dates",
        lambda capture, security_code: (date(2026, 9, 23), date(2026, 9, 24)),
    )
    original_append = DjangoSystemAuditEventOutboxCoordinator.append_and_enqueue

    def append_then_fail(
        coordinator: DjangoSystemAuditEventOutboxCoordinator,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> SystemAuditEventOutboxCommit:
        original_append(
            coordinator,
            event,
            expected_predecessor_hash=expected_predecessor_hash,
            recorded_at=recorded_at,
        )
        raise RuntimeError("injected failure after the Audit and Outbox inserts")

    monkeypatch.setattr(
        DjangoSystemAuditEventOutboxCoordinator,
        "append_and_enqueue",
        append_then_fail,
    )

    with pytest.raises(RuntimeError, match="after the Audit and Outbox inserts"):
        composition.capture_and_append_szse_distribution_window(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            body_store_root=tmp_path,
        )

    assert SecurityDisclosureEventModel.objects.count() == 0
    assert SecurityDisclosureListingCoverageModel.objects.count() == 0
    assert (
        SystemAuditEventModel.objects.filter(event_type="data.disclosure_fact.appended").count()
        == 0
    )
    assert SystemAuditOutboxModel.objects.count() == 0


@pytest.mark.django_db
def test_legacy_duplicate_fact_without_audit_is_blocked_and_not_backfilled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_test_audit(monkeypatch)
    document_id = "37e23922-f64d-4203-9d27-9ed981a8f799"
    entry = SecurityDisclosureListingEntry(
        listing_id="00000000-0000-4000-8000-000000000003",
        announcement_id=1225568073,
        title="一心堂：2026年中期权益分派实施公告",
        published_on=date(2026, 9, 17),
        raw_publish_time="2026-09-17 00:00:00",
        source_document_id=document_id,
        source_url=(
            "https://disc.static.szse.cn/disc/disk03/finalpage/" f"2026-09-17/{document_id}.PDF"
        ),
    )
    observed_at = timezone.now() - timedelta(seconds=60)
    verified_at = observed_at + timedelta(seconds=5)
    proof = SecurityDisclosureListingCoverageProof(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        first_observed_at=observed_at,
        verified_at=verified_at,
        announcement_count=1,
        entries=(entry,),
        first_pass_page_body_sha256=("a" * 64,),
        second_pass_page_body_sha256=("a" * 64,),
    )

    def make_listing(observed: datetime) -> CapturedOfficialSzseListingWindow:
        return CapturedOfficialSzseListingWindow(
            asset_code=proof.asset_code,
            start_on=proof.start_on,
            end_on=proof.end_on,
            observed_at=observed,
            announcement_count=proof.announcement_count,
            entries=proof.entries,
            first_pass_page_body_sha256=proof.first_pass_page_body_sha256,
            page_body_sha256=proof.second_pass_page_body_sha256,
            manifest_sha256=proof.source_manifest_sha256,
            coverage_manifest_sha256=proof.coverage_manifest_sha256,
        )

    body = b"%PDF-1.4\nlegacy-unaudited-fact\n%%EOF"
    captured = CapturedOfficialSzsePdf(
        source_url=entry.source_url,
        source_document_id=document_id,
        first_seen_at=observed_at + timedelta(seconds=1),
        body_sha256=hashlib.sha256(body).hexdigest(),
        body=body,
    )
    legacy_event = SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="002727.SZ",
        source_security_code="002727",
        source_event_id=document_id,
        source_revision_id=f"sha256:{captured.body_sha256}",
        raw_event_type="cash_dividend",
        event_type=SecurityDisclosureEventType.CASH_DIVIDEND,
        source_url=entry.source_url,
        source_document_body=body,
        first_seen_at=captured.first_seen_at,
        announced_at=entry.published_on,
        source_available_at=entry.published_on,
        effective_at=date(2026, 9, 24),
    )
    AppendSecurityDisclosureEventUseCase(
        DjangoSecurityDisclosureEventRepository(using="default")
    ).execute(legacy_event, body)
    AppendSecurityDisclosureListingCoverageUseCase(
        DjangoSecurityDisclosureListingCoverageRepository(using="default")
    ).execute(proof)
    listings = iter((make_listing(observed_at), make_listing(verified_at)))
    monkeypatch.setattr(
        source_composition,
        "capture_official_szse_announcement_window",
        lambda **kwargs: next(listings),
    )
    monkeypatch.setattr(source_composition, "capture_official_szse_pdf", lambda url: captured)
    monkeypatch.setattr(
        source_composition,
        "classify_szse_pdf_disclosure",
        lambda capture, security_code, **kwargs: (
            "cash_dividend",
            SecurityDisclosureEventType.CASH_DIVIDEND,
        ),
    )
    monkeypatch.setattr(
        source_composition,
        "extract_szse_distribution_dates",
        lambda capture, security_code: (date(2026, 9, 23), date(2026, 9, 24)),
    )

    with pytest.raises(SecurityDisclosureAuditConflict, match="no exact prior Audit evidence"):
        composition.capture_and_append_szse_distribution_window(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            body_store_root=tmp_path,
        )

    assert SecurityDisclosureEventModel.objects.count() == 1
    assert SecurityDisclosureListingCoverageModel.objects.count() == 1
    assert (
        SystemAuditEventModel.objects.filter(event_type="data.disclosure_fact.appended").count()
        == 0
    )
    assert SystemAuditOutboxModel.objects.count() == 0


def test_expired_audit_authority_blocks_before_external_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture_called = False

    def forbidden_capture(**kwargs: object) -> CapturedOfficialSzseListingWindow:
        nonlocal capture_called
        capture_called = True
        pytest.fail("network capture must not run without a live Audit lease")

    monkeypatch.setattr(
        composition,
        "get_system_audit_authority_lease",
        lambda **kwargs: SystemAuditAuthorityLease(
            mode="required",
            outbox_enabled=True,
            valid_until=timezone.now() - timedelta(seconds=1),
        ),
    )
    monkeypatch.setattr(
        source_composition, "capture_official_szse_announcement_window", forbidden_capture
    )

    with pytest.raises(SecurityDisclosureAuditUnavailable):
        composition.capture_and_append_szse_distribution_window(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            body_store_root=tmp_path,
        )

    assert capture_called is False


@pytest.mark.django_db
def test_second_pdf_capture_failure_leaves_database_empty_and_retains_first_pdf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_test_audit(monkeypatch)
    documents = (
        ("37e23922-f64d-4203-9d27-9ed981a8f799", 1225568073, date(2026, 9, 17)),
        ("ab610720-03a5-49f0-9986-d66826f56985", 1225572157, date(2026, 9, 19)),
    )
    entries = tuple(
        SecurityDisclosureListingEntry(
            listing_id=f"00000000-0000-4000-8000-{index:012d}",
            announcement_id=announcement_id,
            title=f"一心堂：2026年中期权益分派实施公告{index}",
            published_on=published_on,
            raw_publish_time=f"{published_on.isoformat()} 00:00:00",
            source_document_id=document_id,
            source_url=(
                "https://disc.static.szse.cn/disc/disk03/finalpage/"
                f"{published_on.isoformat()}/{document_id}.PDF"
            ),
        )
        for index, (document_id, announcement_id, published_on) in enumerate(documents, start=1)
    )
    observed_at = timezone.now() - timedelta(seconds=30)
    proof = SecurityDisclosureListingCoverageProof(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        first_observed_at=observed_at,
        verified_at=observed_at,
        announcement_count=len(entries),
        entries=entries,
        first_pass_page_body_sha256=("a" * 64,),
        second_pass_page_body_sha256=("a" * 64,),
    )
    listing = CapturedOfficialSzseListingWindow(
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        observed_at=observed_at,
        announcement_count=len(entries),
        entries=entries,
        first_pass_page_body_sha256=("a" * 64,),
        page_body_sha256=("a" * 64,),
        manifest_sha256=proof.source_manifest_sha256,
        coverage_manifest_sha256=proof.coverage_manifest_sha256,
    )
    first_body = b"%PDF-1.4\nfirst-retained-pdf\n%%EOF"
    first_capture = CapturedOfficialSzsePdf(
        source_url=entries[0].source_url,
        source_document_id=entries[0].source_document_id,
        first_seen_at=observed_at + timedelta(seconds=1),
        body_sha256=hashlib.sha256(first_body).hexdigest(),
        body=first_body,
    )
    capture_count = 0

    def capture_pdf(url: str) -> CapturedOfficialSzsePdf:
        nonlocal capture_count
        capture_count += 1
        if capture_count == 2:
            raise source_composition.OfficialSzseListingError("injected second PDF capture failure")
        return first_capture

    monkeypatch.setattr(
        source_composition,
        "capture_official_szse_announcement_window",
        lambda **kwargs: listing,
    )
    monkeypatch.setattr(source_composition, "capture_official_szse_pdf", capture_pdf)
    monkeypatch.setattr(
        source_composition,
        "classify_szse_pdf_disclosure",
        lambda capture, security_code, **kwargs: (
            "cash_dividend",
            SecurityDisclosureEventType.CASH_DIVIDEND,
        ),
    )
    monkeypatch.setattr(
        source_composition,
        "extract_szse_distribution_dates",
        lambda capture, security_code: (date(2026, 9, 23), date(2026, 9, 24)),
    )

    with pytest.raises(source_composition.OfficialSzseListingError, match="second PDF"):
        composition.capture_and_append_szse_distribution_window(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            body_store_root=tmp_path,
        )

    assert capture_count == 2
    assert (tmp_path / "pdf" / f"{first_capture.body_sha256}.pdf").is_file()
    assert SecurityDisclosureEventModel.objects.count() == 0
    assert SecurityDisclosureListingCoverageModel.objects.count() == 0
    assert (
        SystemAuditEventModel.objects.filter(event_type="data.disclosure_fact.appended").count()
        == 0
    )
    assert SystemAuditOutboxModel.objects.count() == 0


def test_audit_alias_mismatch_blocks_before_external_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _WrongAliasWriter:
        database_alias = "other"

        def preflight(self, *, as_of: datetime) -> AuditScopeRef:
            pytest.fail("scope lookup must not run for a mismatched alias")

    capture_called = False

    def forbidden_capture(**kwargs: object) -> CapturedOfficialSzseListingWindow:
        nonlocal capture_called
        capture_called = True
        pytest.fail("network capture must not run for a mismatched alias")

    monkeypatch.setattr(
        composition,
        "get_system_audit_authority_lease",
        lambda **kwargs: SystemAuditAuthorityLease(
            mode="required",
            outbox_enabled=True,
            valid_until=timezone.now() + timedelta(hours=1),
        ),
    )
    monkeypatch.setattr(
        composition,
        "build_security_disclosure_audit_writer",
        lambda **kwargs: _WrongAliasWriter(),
    )
    monkeypatch.setattr(
        source_composition, "capture_official_szse_announcement_window", forbidden_capture
    )

    with pytest.raises(SecurityDisclosureAuditUnavailable, match="database alias"):
        composition.capture_and_append_szse_distribution_window(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            body_store_root=tmp_path,
        )

    assert capture_called is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("classified_type", "expected_coverage_status"),
    [
        (
            SecurityDisclosureEventType.CASH_DIVIDEND,
            SecurityDisclosureListingCoverageStatus.COMPLETE,
        ),
        (
            SecurityDisclosureEventType.UNKNOWN,
            SecurityDisclosureListingCoverageStatus.UNKNOWN,
        ),
    ],
)
def test_batch_timestamp_is_shared_by_facts_coverage_and_audit_at_exact_cutoff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    classified_type: SecurityDisclosureEventType,
    expected_coverage_status: SecurityDisclosureListingCoverageStatus,
) -> None:
    """One frozen post-capture clock makes all three append-only records PIT-visible."""

    _configure_test_audit(monkeypatch)
    actual_now = timezone.now()
    first_observed_at = actual_now - timedelta(seconds=60)
    verified_at = actual_now - timedelta(seconds=45)
    fact_first_seen_at = actual_now - timedelta(seconds=55)
    preflight_started_at = actual_now - timedelta(seconds=5)
    preflight_finished_at = actual_now - timedelta(seconds=3)
    batch_recorded_at = actual_now - timedelta(seconds=1)
    tick_times = iter((preflight_started_at, preflight_finished_at, batch_recorded_at))
    body = b"%PDF-1.4\nshared-batch-clock\n%%EOF"
    document_id = "37e23922-f64d-4203-9d27-9ed981a8f799"
    entry = SecurityDisclosureListingEntry(
        listing_id="00000000-0000-4000-8000-000000000088",
        announcement_id=1225568073,
        title="一心堂：2026年中期权益分派实施公告",
        published_on=date(2026, 9, 17),
        raw_publish_time="2026-09-17 00:00:00",
        source_document_id=document_id,
        source_url=(
            "https://disc.static.szse.cn/disc/disk03/finalpage/" f"2026-09-17/{document_id}.PDF"
        ),
    )

    def make_listing(observed_at: datetime) -> CapturedOfficialSzseListingWindow:
        proof = SecurityDisclosureListingCoverageProof(
            source=SecurityDisclosureSource.SZSE_OFFICIAL,
            exchange=SecurityDisclosureExchange.SZSE,
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            first_observed_at=observed_at,
            verified_at=observed_at,
            announcement_count=1,
            entries=(entry,),
            first_pass_page_body_sha256=("a" * 64,),
            second_pass_page_body_sha256=("a" * 64,),
        )
        return CapturedOfficialSzseListingWindow(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            observed_at=observed_at,
            announcement_count=1,
            entries=(entry,),
            first_pass_page_body_sha256=("a" * 64,),
            page_body_sha256=("a" * 64,),
            manifest_sha256=proof.source_manifest_sha256,
            coverage_manifest_sha256=proof.coverage_manifest_sha256,
        )

    captured = CapturedOfficialSzsePdf(
        source_url=entry.source_url,
        source_document_id=document_id,
        first_seen_at=fact_first_seen_at,
        body_sha256=hashlib.sha256(body).hexdigest(),
        body=body,
    )
    listings = iter((make_listing(first_observed_at), make_listing(verified_at)))
    monkeypatch.setattr(
        source_composition,
        "capture_official_szse_announcement_window",
        lambda **kwargs: next(listings),
    )
    monkeypatch.setattr(source_composition, "capture_official_szse_pdf", lambda url: captured)
    monkeypatch.setattr(
        source_composition,
        "classify_szse_pdf_disclosure",
        lambda capture, security_code, **kwargs: (
            classified_type.value,
            classified_type,
        ),
    )
    monkeypatch.setattr(
        source_composition,
        "extract_szse_distribution_dates",
        lambda capture, security_code: (date(2026, 9, 23), date(2026, 9, 24)),
    )

    with monkeypatch.context() as time_patch:
        time_patch.setattr(
            composition.timezone,
            "now",
            lambda: next(tick_times, actual_now),
        )
        time_patch.setattr(
            composition,
            "get_system_audit_authority_lease",
            lambda **kwargs: SystemAuditAuthorityLease(
                mode="required",
                outbox_enabled=True,
                valid_until=batch_recorded_at + timedelta(hours=1),
            ),
        )
        result = composition.capture_and_append_szse_distribution_window(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            body_store_root=tmp_path,
        )

    audit_event = result.audit.commit.event
    assert audit_event.recorded_at == batch_recorded_at
    assert result.coverage.record.recorded_at == audit_event.recorded_at
    assert result.events[0].record.recorded_at == audit_event.recorded_at

    event_records = DjangoSecurityDisclosureEventRepository().list_known_at(
        SecurityDisclosureEventReadScope(
            as_of=audit_event.recorded_at,
            exchange=SecurityDisclosureExchange.SZSE,
            asset_code="002727.SZ",
        )
    )
    assert len(event_records) == 1
    assert event_records[0].recorded_at == audit_event.recorded_at

    coverage_snapshot = QuerySecurityDisclosureListingCoverageUseCase(
        coverage_repository=DjangoSecurityDisclosureListingCoverageRepository(),
        event_repository=DjangoSecurityDisclosureEventRepository(),
    ).execute(
        SecurityDisclosureListingCoverageReadScope(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            as_of=audit_event.recorded_at,
        )
    )
    assert coverage_snapshot.coverage_status is expected_coverage_status
    if classified_type is SecurityDisclosureEventType.UNKNOWN:
        assert coverage_snapshot.reason_code == "LISTED_EVENT_CLASSIFICATION_UNKNOWN"
    assert coverage_snapshot.proof is not None
    assert coverage_snapshot.proof.recorded_at == audit_event.recorded_at

    audit_events = DjangoSystemAuditEventRepository().list_events(
        stream_id=audit_event.stream_id,
        as_of=audit_event.recorded_at,
        scope=AuditScopeRef("test-tenant", "test-owner"),
    )
    assert audit_events == (audit_event,)


@pytest.mark.django_db
def test_batch_timestamp_at_authority_lease_expiry_blocks_all_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The frozen persistence instant must be strictly earlier than lease expiry."""

    _configure_test_audit(monkeypatch)
    actual_now = timezone.now()
    first_observed_at = actual_now - timedelta(seconds=60)
    verified_at = actual_now - timedelta(seconds=45)
    preflight_started_at = actual_now - timedelta(seconds=5)
    preflight_finished_at = actual_now - timedelta(seconds=3)
    batch_recorded_at = actual_now - timedelta(seconds=1)
    tick_times = iter((preflight_started_at, preflight_finished_at, batch_recorded_at))

    def make_listing(observed_at: datetime) -> CapturedOfficialSzseListingWindow:
        proof = SecurityDisclosureListingCoverageProof(
            source=SecurityDisclosureSource.SZSE_OFFICIAL,
            exchange=SecurityDisclosureExchange.SZSE,
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            first_observed_at=observed_at,
            verified_at=observed_at,
            announcement_count=0,
            entries=(),
            first_pass_page_body_sha256=("d" * 64,),
            second_pass_page_body_sha256=("d" * 64,),
        )
        return CapturedOfficialSzseListingWindow(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            observed_at=observed_at,
            announcement_count=0,
            entries=(),
            first_pass_page_body_sha256=("d" * 64,),
            page_body_sha256=("d" * 64,),
            manifest_sha256=proof.source_manifest_sha256,
            coverage_manifest_sha256=proof.coverage_manifest_sha256,
        )

    listings = iter((make_listing(first_observed_at), make_listing(verified_at)))
    monkeypatch.setattr(
        source_composition,
        "capture_official_szse_announcement_window",
        lambda **kwargs: next(listings),
    )
    with monkeypatch.context() as time_patch:
        time_patch.setattr(
            composition.timezone,
            "now",
            lambda: next(tick_times, actual_now),
        )
        time_patch.setattr(
            composition,
            "get_system_audit_authority_lease",
            lambda **kwargs: SystemAuditAuthorityLease(
                mode="required",
                outbox_enabled=True,
                valid_until=batch_recorded_at,
            ),
        )
        with pytest.raises(SecurityDisclosureAuditUnavailable, match="outside the active"):
            composition.capture_and_append_szse_distribution_window(
                asset_code="002727.SZ",
                start_on=date(2026, 9, 1),
                end_on=date(2026, 9, 30),
                body_store_root=tmp_path,
            )

    assert SecurityDisclosureEventModel.objects.count() == 0
    assert SecurityDisclosureListingCoverageModel.objects.count() == 0
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


@pytest.mark.django_db
def test_late_recorded_fact_does_not_complete_older_exact_coverage_snapshot() -> None:
    """A later-inserted fact with earlier source time cannot rewrite an old PIT result."""

    actual_now = timezone.now()
    proof_recorded_at = actual_now - timedelta(minutes=2)
    fact_recorded_at = actual_now - timedelta(minutes=1)
    first_seen_at = actual_now - timedelta(minutes=5)
    document_id = "37e23922-f64d-4203-9d27-9ed981a8f799"
    entry = SecurityDisclosureListingEntry(
        listing_id="00000000-0000-4000-8000-000000000099",
        announcement_id=1225568073,
        title="一心堂：2026年中期权益分派实施公告",
        published_on=date(2026, 9, 17),
        raw_publish_time="2026-09-17 00:00:00",
        source_document_id=document_id,
        source_url=(
            "https://disc.static.szse.cn/disc/disk03/finalpage/" f"2026-09-17/{document_id}.PDF"
        ),
    )
    proof = SecurityDisclosureListingCoverageProof(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        first_observed_at=first_seen_at,
        verified_at=proof_recorded_at - timedelta(seconds=1),
        announcement_count=1,
        entries=(entry,),
        first_pass_page_body_sha256=("c" * 64,),
        second_pass_page_body_sha256=("c" * 64,),
    )
    body = b"%PDF-1.4\nlate-recorded-fact\n%%EOF"
    event = SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="002727.SZ",
        source_security_code="002727",
        source_event_id=document_id,
        source_revision_id=f"sha256:{hashlib.sha256(body).hexdigest()}",
        raw_event_type="cash_dividend",
        event_type=SecurityDisclosureEventType.CASH_DIVIDEND,
        source_url=entry.source_url,
        source_document_body=body,
        first_seen_at=first_seen_at,
        announced_at=entry.published_on,
        source_available_at=entry.published_on,
        effective_at=date(2026, 9, 24),
    )

    class _FixedClock:
        """Give one repository a deterministic persistence timestamp."""

        def __init__(self, instant: datetime) -> None:
            self._instant = instant

        def now(self) -> datetime:
            """Return the fixed aware timestamp for this append."""

            return self._instant

    AppendSecurityDisclosureListingCoverageUseCase(
        DjangoSecurityDisclosureListingCoverageRepository(clock=_FixedClock(proof_recorded_at))
    ).execute(proof)
    AppendSecurityDisclosureEventUseCase(
        DjangoSecurityDisclosureEventRepository(clock=_FixedClock(fact_recorded_at))
    ).execute(event, body)

    snapshot = QuerySecurityDisclosureListingCoverageUseCase(
        coverage_repository=DjangoSecurityDisclosureListingCoverageRepository(),
        event_repository=DjangoSecurityDisclosureEventRepository(),
    ).execute(
        SecurityDisclosureListingCoverageReadScope(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            as_of=proof_recorded_at,
        )
    )

    assert snapshot.proof is not None
    assert snapshot.proof.recorded_at == proof_recorded_at
    assert snapshot.events == ()
    assert snapshot.coverage_status is SecurityDisclosureListingCoverageStatus.PARTIAL
    assert snapshot.reason_code == "LISTED_EVENT_NOT_REPRESENTED"


def _empty_candidate_for_asset(
    asset_code: str, *, verified_at: datetime
) -> source_composition.CapturedSzseDistributionCandidate:
    """Build one exact empty-listing candidate for a cohort transaction test."""

    page_hash = hashlib.sha256(asset_code.encode("ascii")).hexdigest()
    proof = SecurityDisclosureListingCoverageProof(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code=asset_code,
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        first_observed_at=verified_at - timedelta(seconds=1),
        verified_at=verified_at,
        announcement_count=0,
        entries=(),
        first_pass_page_body_sha256=(page_hash,),
        second_pass_page_body_sha256=(page_hash,),
    )
    listing = CapturedOfficialSzseListingWindow(
        asset_code=asset_code,
        start_on=proof.start_on,
        end_on=proof.end_on,
        observed_at=verified_at,
        announcement_count=0,
        entries=(),
        first_pass_page_body_sha256=proof.first_pass_page_body_sha256,
        page_body_sha256=proof.second_pass_page_body_sha256,
        manifest_sha256=proof.source_manifest_sha256,
        coverage_manifest_sha256=proof.coverage_manifest_sha256,
    )
    return source_composition.CapturedSzseDistributionCandidate(
        listing=listing,
        events=(),
        proof=proof,
    )


@pytest.mark.django_db
def test_multi_asset_cohort_commits_all_proofs_and_audits_at_shared_clocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Two securities share one verification and persistence clock in one cohort."""

    _configure_test_audit(monkeypatch)
    verified_at = timezone.now() - timedelta(seconds=1)
    asset_codes = ("002727.SZ", "301237.SZ")
    candidates = tuple(
        _empty_candidate_for_asset(asset_code, verified_at=verified_at)
        for asset_code in asset_codes
    )
    requests = tuple(
        source_composition.SzseDistributionWindowRequest(
            asset_code=asset_code,
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            body_store_root=tmp_path / asset_code,
        )
        for asset_code in asset_codes
    )
    monkeypatch.setattr(
        composition,
        "capture_szse_distribution_cohort",
        lambda windows: candidates,
    )

    results = composition.capture_and_append_szse_distribution_cohort(
        requests,
        lease_ttl=timedelta(seconds=60),
        using="default",
        audit_environment="development",
    )

    assert tuple(result.coverage.record.proof.asset_code for result in results) == asset_codes
    assert {result.coverage.record.proof.verified_at for result in results} == {verified_at}
    assert len({result.coverage.record.recorded_at for result in results}) == 1
    assert len({result.audit.commit.event.recorded_at for result in results}) == 1
    assert {result.coverage.record.recorded_at for result in results} == {
        result.audit.commit.event.recorded_at for result in results
    }
    assert SecurityDisclosureEventModel.objects.count() == 0
    assert SecurityDisclosureListingCoverageModel.objects.count() == 2
    assert (
        SystemAuditEventModel.objects.filter(event_type="data.disclosure_fact.appended").count()
        == 2
    )
    assert SystemAuditOutboxModel.objects.count() == 2


@pytest.mark.django_db
def test_second_asset_audit_failure_rolls_back_entire_cohort(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failure after the second Audit/outbox append leaves no cohort DB writes."""

    _configure_test_audit(monkeypatch)
    verified_at = timezone.now() - timedelta(seconds=1)
    asset_codes = ("002727.SZ", "301237.SZ")
    candidates = tuple(
        _empty_candidate_for_asset(asset_code, verified_at=verified_at)
        for asset_code in asset_codes
    )
    requests = tuple(
        source_composition.SzseDistributionWindowRequest(
            asset_code=asset_code,
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            body_store_root=tmp_path / asset_code,
        )
        for asset_code in asset_codes
    )
    monkeypatch.setattr(
        composition,
        "capture_szse_distribution_cohort",
        lambda windows: candidates,
    )
    original_append = DjangoSystemAuditEventOutboxCoordinator.append_and_enqueue
    append_count = 0

    def append_second_then_fail(
        coordinator: DjangoSystemAuditEventOutboxCoordinator,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> SystemAuditEventOutboxCommit:
        nonlocal append_count
        result = original_append(
            coordinator,
            event,
            expected_predecessor_hash=expected_predecessor_hash,
            recorded_at=recorded_at,
        )
        append_count += 1
        if append_count == 2:
            raise RuntimeError("second cohort audit append failed")
        return result

    monkeypatch.setattr(
        DjangoSystemAuditEventOutboxCoordinator,
        "append_and_enqueue",
        append_second_then_fail,
    )

    with pytest.raises(RuntimeError, match="second cohort audit append failed"):
        composition.capture_and_append_szse_distribution_cohort(
            requests,
            lease_ttl=timedelta(seconds=60),
            using="default",
            audit_environment="development",
        )

    assert append_count == 2
    assert SecurityDisclosureEventModel.objects.count() == 0
    assert SecurityDisclosureListingCoverageModel.objects.count() == 0
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("expire_before_commit", [False, True])
def test_cohort_source_proof_at_lease_expiry_blocks_all_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    expire_before_commit: bool,
) -> None:
    """The half-open cohort lease rejects a proof exactly at its configured expiry."""

    _configure_test_audit(monkeypatch)
    verified_at = datetime(2026, 11, 11, 1, 0, tzinfo=UTC)
    batch_recorded_at = verified_at + timedelta(seconds=59 if expire_before_commit else 60)
    candidates = (_empty_candidate_for_asset("002727.SZ", verified_at=verified_at),)
    request = source_composition.SzseDistributionWindowRequest(
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        body_store_root=tmp_path,
    )
    monkeypatch.setattr(composition, "capture_szse_distribution_cohort", lambda windows: candidates)
    ticks = iter(
        (
            verified_at + timedelta(seconds=1),
            verified_at + timedelta(seconds=2),
            batch_recorded_at,
            verified_at + timedelta(seconds=60),
        )
    )
    monkeypatch.setattr(composition, "timezone", SimpleNamespace(now=lambda: next(ticks)))
    monkeypatch.setattr(
        composition,
        "get_system_audit_authority_lease",
        lambda **kwargs: SystemAuditAuthorityLease(
            mode="required",
            outbox_enabled=True,
            valid_until=verified_at + timedelta(minutes=5),
        ),
    )

    with pytest.raises(SecurityDisclosureAuditUnavailable):
        composition.capture_and_append_szse_distribution_cohort(
            (request,),
            lease_ttl=timedelta(seconds=60),
            using="default",
            audit_environment="development",
        )

    assert SecurityDisclosureEventModel.objects.count() == 0
    assert SecurityDisclosureListingCoverageModel.objects.count() == 0
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0
