"""Capture-only SZSE distribution candidates retain final listing provenance."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import apps.data_center.security_disclosure_capture_composition as composition
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureExchange,
    SecurityDisclosureListingCoverageProof,
    SecurityDisclosureSource,
)
from apps.data_center.infrastructure.official_szse_announcement_listing import (
    CapturedOfficialSzseListingWindow,
    OfficialSzseListingError,
)

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
