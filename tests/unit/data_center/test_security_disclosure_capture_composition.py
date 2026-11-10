"""Coverage proof publication follows stable listing and downstream ingestion."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import apps.data_center.security_disclosure_capture_composition as composition
from apps.data_center.domain.security_disclosure_event import (
    PersistedSecurityDisclosureListingCoverage,
    SecurityDisclosureEventAppendDisposition,
    SecurityDisclosureExchange,
    SecurityDisclosureListingCoverageAppendResult,
    SecurityDisclosureListingCoverageProof,
    SecurityDisclosureSource,
)
from apps.data_center.infrastructure.official_szse_announcement_listing import (
    CapturedOfficialSzseListingWindow,
    OfficialSzseListingError,
)

_FIRST_OBSERVED_AT = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)
_VERIFIED_AT = datetime(2026, 10, 1, 2, 5, tzinfo=UTC)
_RECORDED_AT = datetime(2026, 10, 1, 2, 5, 1, tzinfo=UTC)


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
    """A persisted proof retains first observation and final verification clocks."""

    first = _captured_window(_FIRST_OBSERVED_AT)
    final = _captured_window(_VERIFIED_AT)
    captures = iter((first, final))
    persisted_proofs: list[SecurityDisclosureListingCoverageProof] = []

    class _CoverageUseCase:
        """Capture the proof submitted by the composition after final recheck."""

        def __init__(self, repository: object) -> None:
            del repository

        def execute(
            self, proof: SecurityDisclosureListingCoverageProof
        ) -> SecurityDisclosureListingCoverageAppendResult:
            persisted_proofs.append(proof)
            return SecurityDisclosureListingCoverageAppendResult(
                disposition=SecurityDisclosureEventAppendDisposition.STORED,
                record=PersistedSecurityDisclosureListingCoverage(
                    proof=proof,
                    recorded_at=_RECORDED_AT,
                ),
            )

    monkeypatch.setattr(
        composition,
        "capture_official_szse_announcement_window",
        lambda **kwargs: next(captures),
    )
    monkeypatch.setattr(
        composition, "AppendSecurityDisclosureListingCoverageUseCase", _CoverageUseCase
    )

    result = composition.capture_and_append_szse_distribution_window(
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        body_store_root=tmp_path,
    )

    assert result.listing is final
    assert len(persisted_proofs) == 1
    assert persisted_proofs[0].first_observed_at == _FIRST_OBSERVED_AT
    assert persisted_proofs[0].verified_at == _VERIFIED_AT
    assert result.coverage.record.proof == persisted_proofs[0]


def test_distribution_window_does_not_persist_proof_after_changed_final_listing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Changed exact window content leaves appended event facts without coverage proof."""

    first = _captured_window(_FIRST_OBSERVED_AT)
    changed_final = _captured_window(
        _VERIFIED_AT,
        first_page_hash="c" * 64,
        second_page_hash="d" * 64,
    )
    captures = iter((first, changed_final))
    append_called = False

    class _CoverageUseCase:
        """Fail if a changed list reaches the proof repository boundary."""

        def __init__(self, repository: object) -> None:
            del repository

        def execute(
            self, proof: SecurityDisclosureListingCoverageProof
        ) -> SecurityDisclosureListingCoverageAppendResult:
            del proof
            nonlocal append_called
            append_called = True
            raise AssertionError("changed listing cannot persist coverage")

    monkeypatch.setattr(
        composition,
        "capture_official_szse_announcement_window",
        lambda **kwargs: next(captures),
    )
    monkeypatch.setattr(
        composition, "AppendSecurityDisclosureListingCoverageUseCase", _CoverageUseCase
    )

    with pytest.raises(OfficialSzseListingError, match="listing changed"):
        composition.capture_and_append_szse_distribution_window(
            asset_code="002727.SZ",
            start_on=date(2026, 9, 1),
            end_on=date(2026, 9, 30),
            body_store_root=tmp_path,
        )

    assert append_called is False
