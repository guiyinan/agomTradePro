"""Read-only original-body boundaries do not recapture or rewrite events."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.data_center import security_disclosure_body_composition as composition
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
)
from apps.data_center.infrastructure.official_szse_pdf_capture import (
    CapturedOfficialSzsePdf,
    OfficialDisclosureCaptureError,
    OfficialSzsePdfBodyStore,
)

_BODY = b"%PDF-1.4\nsynthetic original bytes\n%%EOF"


def _retained_event(root: Path) -> SecurityDisclosureEvent:
    """Persist only temporary bytes, without creating any database facts."""
    event = SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="300176.SZ",
        source_security_code="300176",
        source_event_id="cb0747e3-9f77-42a0-b221-ed1e5d3316ba",
        source_revision_id="sha256:" + hashlib.sha256(_BODY).hexdigest(),
        raw_event_type="配股发行结果公告",
        event_type=SecurityDisclosureEventType.RIGHTS_ISSUE,
        source_url="https://disc.static.szse.cn/download/disc/disk03/finalpage/2026-08-21/cb0747e3-9f77-42a0-b221-ed1e5d3316ba.PDF",
        source_document_body=_BODY,
        first_seen_at=datetime(2026, 11, 13, tzinfo=UTC),
    )
    OfficialSzsePdfBodyStore(root).retain(
        CapturedOfficialSzsePdf(
            event.source_url,
            event.source_event_id,
            event.first_seen_at,
            event.source_body_sha256,
            _BODY,
        )
    )
    return event


def test_original_body_reader_keeps_event_clock_and_exact_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reopening an original never uses the current clock or network."""
    event = _retained_event(tmp_path)
    seen: list[CapturedOfficialSzsePdf] = []

    def verify(capture: CapturedOfficialSzsePdf, expected_security_code: str) -> str:
        seen.append(capture)
        assert expected_security_code == "300176"
        return expected_security_code

    monkeypatch.setattr(composition, "verify_szse_pdf_security_code", verify)
    assert composition.verify_security_disclosure_original_body(event, body_store_root=tmp_path)
    assert seen[0].body == _BODY and seen[0].first_seen_at == event.first_seen_at


@pytest.mark.parametrize("failure", ["missing", "corrupt", "wrong_security", "wrong_revision"])
def test_original_body_reader_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str,
) -> None:
    """A retained hash, native revision and strict security check are all required."""
    event = _retained_event(tmp_path)
    body_path = tmp_path / (event.source_body_sha256 + ".pdf")
    if failure == "missing":
        body_path.unlink()
    elif failure == "corrupt":
        body_path.write_bytes(_BODY + b"changed")
    elif failure == "wrong_revision":
        event = replace(event, source_revision_id="sha256:" + "f" * 64)

    def verify(capture: CapturedOfficialSzsePdf, expected_security_code: str) -> str:
        if failure == "wrong_security":
            raise OfficialDisclosureCaptureError("wrong security")
        return expected_security_code

    monkeypatch.setattr(composition, "verify_szse_pdf_security_code", verify)
    assert not composition.verify_security_disclosure_original_body(event, body_store_root=tmp_path)


def test_original_body_reader_does_not_create_an_absent_store(tmp_path: Path) -> None:
    """An inspection has no directory-creation side effect."""
    event = _retained_event(tmp_path)
    absent = tmp_path / "absent"
    assert not composition.verify_security_disclosure_original_body(event, body_store_root=absent)
    assert not absent.exists()
