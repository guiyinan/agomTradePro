"""Capture-only SZSE distribution candidates retain final listing provenance."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import apps.data_center.security_disclosure_capture_composition as composition
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureListingCoverageProof,
    SecurityDisclosureListingEntry,
    SecurityDisclosureSource,
)
from apps.data_center.infrastructure.official_szse_announcement_listing import (
    CapturedOfficialSzseListingWindow,
    OfficialSzseListingError,
)
from apps.data_center.infrastructure.official_szse_pdf_capture import CapturedOfficialSzsePdf

_FIRST_OBSERVED_AT = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)
_VERIFIED_AT = datetime(2026, 10, 1, 2, 5, tzinfo=UTC)


def _captured_window(
    observed_at: datetime,
    *,
    first_page_hash: str = "a" * 64,
    second_page_hash: str = "b" * 64,
) -> CapturedOfficialSzseListingWindow:
    """Build one exact retained zero-row listing window for composition tests."""

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
        first_pass_page_body_sha256=(first_page_hash,),
        second_pass_page_body_sha256=(second_page_hash,),
    )
    return CapturedOfficialSzseListingWindow(
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        observed_at=observed_at,
        announcement_count=0,
        entries=(),
        first_pass_page_body_sha256=(first_page_hash,),
        page_body_sha256=(second_page_hash,),
        manifest_sha256=proof.source_manifest_sha256,
        coverage_manifest_sha256=proof.coverage_manifest_sha256,
    )


def test_distribution_window_persists_proof_only_after_final_recheck(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The capture-only candidate retains both observation clocks without writing."""

    first = _captured_window(_FIRST_OBSERVED_AT)
    final = _captured_window(_VERIFIED_AT)
    captures = iter((first, final))
    append_factory_called = False

    def forbidden_append_factory(
        *, using: str
    ) -> composition.SecurityDisclosureEventAppendUseCases:
        nonlocal append_factory_called
        append_factory_called = True
        pytest.fail(f"capture-only composition must not create appenders for {using}")

    monkeypatch.setattr(
        composition,
        "capture_official_szse_announcement_window",
        lambda **kwargs: next(captures),
    )
    monkeypatch.setattr(
        composition,
        "make_security_disclosure_event_append_use_cases",
        forbidden_append_factory,
    )

    result = composition.capture_szse_distribution_window(
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        body_store_root=tmp_path,
    )

    assert result.listing is final
    assert result.proof.first_observed_at == _FIRST_OBSERVED_AT
    assert result.proof.verified_at == _VERIFIED_AT
    assert result.events == ()
    assert append_factory_called is False


def test_distribution_window_returns_no_candidate_after_changed_final_listing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Changed exact window content yields no typed candidate or appender access."""

    first = _captured_window(_FIRST_OBSERVED_AT)
    changed_final = _captured_window(
        _VERIFIED_AT,
        first_page_hash="c" * 64,
        second_page_hash="d" * 64,
    )
    captures = iter((first, changed_final))
    append_factory_called = False

    def forbidden_append_factory(
        *, using: str
    ) -> composition.SecurityDisclosureEventAppendUseCases:
        nonlocal append_factory_called
        append_factory_called = True
        pytest.fail(f"changed listing must not create appenders for {using}")

    monkeypatch.setattr(
        composition,
        "capture_official_szse_announcement_window",
        lambda **kwargs: next(captures),
    )
    monkeypatch.setattr(
        composition,
        "make_security_disclosure_event_append_use_cases",
        forbidden_append_factory,
    )

    with pytest.raises(OfficialSzseListingError, match="listing changed"):
        composition.capture_szse_distribution_window(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            body_store_root=tmp_path,
        )

    assert append_factory_called is False


def test_distribution_capture_visits_every_listed_pdf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A complete window candidate captures non-distribution listed documents too."""

    entries = (
        SecurityDisclosureListingEntry(
            listing_id="00000000-0000-4000-8000-000000000011",
            announcement_id=1225551150,
            title="一心堂：关于使用暂时闲置自有资金进行现金管理的进展公告",
            published_on=date(2026, 9, 8),
            raw_publish_time="2026-09-08 00:00:00",
            source_document_id="68f7d189-bc81-497b-a1e5-2c81b414123c",
            source_url=(
                "https://disc.static.szse.cn/disc/disk03/finalpage/2026-09-08/"
                "68f7d189-bc81-497b-a1e5-2c81b414123c.PDF"
            ),
        ),
        SecurityDisclosureListingEntry(
            listing_id="00000000-0000-4000-8000-000000000012",
            announcement_id=1225568073,
            title="一心堂：2026年中期权益分派实施公告",
            published_on=date(2026, 9, 17),
            raw_publish_time="2026-09-17 00:00:00",
            source_document_id="37e23922-f64d-4203-9d27-9ed981a8f799",
            source_url=(
                "https://disc.static.szse.cn/disc/disk03/finalpage/2026-09-17/"
                "37e23922-f64d-4203-9d27-9ed981a8f799.PDF"
            ),
        ),
    )

    def make_listing(observed_at: datetime) -> CapturedOfficialSzseListingWindow:
        proof = SecurityDisclosureListingCoverageProof(
            source=SecurityDisclosureSource.SZSE_OFFICIAL,
            exchange=SecurityDisclosureExchange.SZSE,
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            first_observed_at=_FIRST_OBSERVED_AT,
            verified_at=observed_at,
            announcement_count=len(entries),
            entries=entries,
            first_pass_page_body_sha256=("c" * 64,),
            second_pass_page_body_sha256=("c" * 64,),
        )
        return CapturedOfficialSzseListingWindow(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            observed_at=observed_at,
            announcement_count=len(entries),
            entries=entries,
            first_pass_page_body_sha256=("c" * 64,),
            page_body_sha256=("c" * 64,),
            manifest_sha256=proof.source_manifest_sha256,
            coverage_manifest_sha256=proof.coverage_manifest_sha256,
        )

    captures = {}
    for index, entry in enumerate(entries):
        body = f"%PDF-1.4\nlisted-{index}\n%%EOF".encode()
        captures[entry.source_url] = CapturedOfficialSzsePdf(
            source_url=entry.source_url,
            source_document_id=entry.source_document_id,
            first_seen_at=_FIRST_OBSERVED_AT.replace(second=1 + index),
            body_sha256=hashlib.sha256(body).hexdigest(),
            body=body,
        )
    listing_windows = iter((make_listing(_FIRST_OBSERVED_AT), make_listing(_VERIFIED_AT)))
    capture_calls: list[str] = []

    def capture_pdf(source_url: str) -> CapturedOfficialSzsePdf:
        capture_calls.append(source_url)
        return captures[source_url]

    monkeypatch.setattr(
        composition,
        "capture_official_szse_announcement_window",
        lambda **kwargs: next(listing_windows),
    )
    monkeypatch.setattr(composition, "capture_official_szse_pdf", capture_pdf)
    monkeypatch.setattr(
        composition,
        "classify_szse_pdf_disclosure",
        lambda captured, security_code, **kwargs: (
            (
                "现金管理公告"
                if captured.source_document_id == entries[0].source_document_id
                else "权益分派实施公告"
            ),
            (
                SecurityDisclosureEventType.OTHER
                if captured.source_document_id == entries[0].source_document_id
                else SecurityDisclosureEventType.CASH_DIVIDEND
            ),
        ),
    )
    monkeypatch.setattr(
        composition,
        "extract_szse_distribution_dates",
        lambda captured, security_code: (date(2026, 9, 23), date(2026, 9, 24)),
    )

    candidate = composition.capture_szse_distribution_window(
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        body_store_root=tmp_path,
    )

    assert capture_calls == [entry.source_url for entry in entries]
    assert len(candidate.events) == len(entries)
    assert tuple(event.event_type for event, _ in candidate.events) == (
        SecurityDisclosureEventType.OTHER,
        SecurityDisclosureEventType.CASH_DIVIDEND,
    )
