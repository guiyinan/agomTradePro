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
    asset_code: str = "002727.SZ",
    entries: tuple[SecurityDisclosureListingEntry, ...] = (),
    first_page_hash: str = "a" * 64,
    second_page_hash: str = "b" * 64,
) -> CapturedOfficialSzseListingWindow:
    """Build one exact retained zero-row listing window for composition tests."""

    proof = SecurityDisclosureListingCoverageProof(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code=asset_code,
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        first_observed_at=observed_at,
        verified_at=observed_at,
        announcement_count=len(entries),
        entries=entries,
        first_pass_page_body_sha256=(first_page_hash,),
        second_pass_page_body_sha256=(second_page_hash,),
    )
    return CapturedOfficialSzseListingWindow(
        asset_code=asset_code,
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        observed_at=observed_at,
        announcement_count=len(entries),
        entries=entries,
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


@pytest.mark.parametrize(
    "action_type",
    [SecurityDisclosureEventType.CASH_DIVIDEND, SecurityDisclosureEventType.RIGHTS_ISSUE],
)
def test_distribution_capture_visits_every_listed_pdf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    action_type: SecurityDisclosureEventType,
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
                else action_type
            ),
        ),
    )
    monkeypatch.setattr(
        composition,
        "extract_szse_distribution_dates",
        lambda captured, security_code: (date(2026, 9, 23), date(2026, 9, 24)),
    )
    from decimal import Decimal

    from apps.data_center.domain.szse_rights_terms import SzseRightsCompletionTerms

    monkeypatch.setattr(
        composition,
        "extract_szse_rights_completion",
        lambda captured, security_code: SzseRightsCompletionTerms(
            source_security_code=security_code,
            record_date=date(2026, 9, 23),
            subscription_end_date=date(2026, 9, 24),
            offered_rights_per_ten=Decimal("4"),
            subscription_price_cny_per_share=Decimal("3.36"),
            actual_aggregate_rights_per_ten=Decimal("3.722702"),
            actual_ex_rights_date=date(2026, 9, 25),
        ),
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
        action_type,
    )
    assert candidate.events[1][0].effective_at == (
        date(2026, 9, 25)
        if action_type is SecurityDisclosureEventType.RIGHTS_ISSUE
        else date(2026, 9, 24)
    )


def test_distribution_cohort_collects_all_pdfs_before_final_rechecks_and_shares_clock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """All members are gathered before final listings and receive one verification clock."""

    start_on = date(2026, 9, 1)
    end_on = date(2026, 9, 30)
    asset_codes = ("002727.SZ", "301237.SZ")
    entries = {
        asset_code: SecurityDisclosureListingEntry(
            listing_id=f"00000000-0000-4000-8000-0000000000{index + 1:02d}",
            announcement_id=1225568073 + index,
            title=f"Issuer {asset_code}：公告",
            published_on=date(2026, 9, 17),
            raw_publish_time="2026-09-17 00:00:00",
            source_document_id=(
                "37e23922-f64d-4203-9d27-9ed981a8f799"
                if index == 0
                else "68f7d189-bc81-497b-a1e5-2c81b414123c"
            ),
            source_url=(
                "https://disc.static.szse.cn/disc/disk03/finalpage/2026-09-17/"
                + (
                    "37e23922-f64d-4203-9d27-9ed981a8f799"
                    if index == 0
                    else "68f7d189-bc81-497b-a1e5-2c81b414123c"
                )
                + ".PDF"
            ),
        )
        for index, asset_code in enumerate(asset_codes)
    }
    listings: dict[str, list[CapturedOfficialSzseListingWindow]] = {}
    pdfs: dict[str, CapturedOfficialSzsePdf] = {}
    final_clock_by_asset = {
        asset_codes[0]: _VERIFIED_AT,
        asset_codes[1]: _VERIFIED_AT.replace(second=_VERIFIED_AT.second + 1),
    }
    for asset_code in asset_codes:
        entry = entries[asset_code]
        body = f"%PDF-1.4\n{asset_code}\n%%EOF".encode()
        captured = CapturedOfficialSzsePdf(
            source_url=entry.source_url,
            source_document_id=entry.source_document_id,
            first_seen_at=_FIRST_OBSERVED_AT.replace(second=1),
            body_sha256=hashlib.sha256(body).hexdigest(),
            body=body,
        )
        pdfs[entry.source_url] = captured
        listings[asset_code] = [
            _captured_window(
                _FIRST_OBSERVED_AT,
                asset_code=asset_code,
                entries=(entry,),
                first_page_hash="c" * 64,
                second_page_hash="c" * 64,
            ),
            _captured_window(
                final_clock_by_asset[asset_code],
                asset_code=asset_code,
                entries=(entry,),
                first_page_hash="c" * 64,
                second_page_hash="c" * 64,
            ),
        ]
    calls: list[tuple[str, str]] = []

    def capture_listing(**kwargs: object) -> CapturedOfficialSzseListingWindow:
        asset_code = str(kwargs["asset_code"])
        calls.append(("listing", asset_code))
        return listings[asset_code].pop(0)

    def capture_pdf(source_url: str) -> CapturedOfficialSzsePdf:
        calls.append(("pdf", source_url))
        return pdfs[source_url]

    monkeypatch.setattr(composition, "capture_official_szse_announcement_window", capture_listing)
    monkeypatch.setattr(composition, "capture_official_szse_pdf", capture_pdf)
    monkeypatch.setattr(
        composition,
        "classify_szse_pdf_disclosure",
        lambda captured, security_code, **kwargs: ("notice", SecurityDisclosureEventType.OTHER),
    )

    requests = tuple(
        composition.SzseDistributionWindowRequest(
            asset_code=asset_code,
            start_on=start_on,
            end_on=end_on,
            body_store_root=tmp_path / asset_code,
        )
        for asset_code in asset_codes
    )
    candidates = composition.capture_szse_distribution_cohort(requests)

    assert calls == [
        ("listing", asset_codes[0]),
        ("pdf", entries[asset_codes[0]].source_url),
        ("listing", asset_codes[1]),
        ("pdf", entries[asset_codes[1]].source_url),
        ("listing", asset_codes[0]),
        ("listing", asset_codes[1]),
    ]
    assert tuple(candidate.proof.asset_code for candidate in candidates) == asset_codes
    assert {candidate.proof.verified_at for candidate in candidates} == {
        final_clock_by_asset[asset_codes[1]]
    }
