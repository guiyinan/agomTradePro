"""Read retained official disclosure bodies through the owning Data Center boundary."""

from __future__ import annotations

from pathlib import Path

from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
)
from apps.data_center.domain.szse_rights_terms import SzseRightsCompletionTerms
from apps.data_center.infrastructure.official_szse_pdf_capture import (
    CapturedOfficialSzsePdf,
    OfficialDisclosureCaptureError,
    OfficialSzsePdfBodyStore,
    extract_szse_rights_completion,
    verify_szse_pdf_security_code,
)


def security_disclosure_window_pdf_store_root(body_store_root: Path) -> Path:
    """Resolve the Data Center-owned PDF subdirectory of an official window capture."""
    if not isinstance(body_store_root, Path):
        raise OfficialDisclosureCaptureError("window store root must be an explicit Path")
    return body_store_root / "pdf"


def _read_original_capture(
    event: SecurityDisclosureEvent,
    *,
    body_store_root: Path,
) -> CapturedOfficialSzsePdf:
    """Read and verify exact existing bytes without network, recapture or new clocks."""
    if type(event) is not SecurityDisclosureEvent:
        raise OfficialDisclosureCaptureError("disclosure event is not typed")
    event.__post_init__()
    if (
        event.source is not SecurityDisclosureSource.SZSE_OFFICIAL
        or event.exchange is not SecurityDisclosureExchange.SZSE
        or event.source_revision_id != f"sha256:{event.source_body_sha256}"
        or not isinstance(body_store_root, Path)
        or not body_store_root.is_dir()
    ):
        raise OfficialDisclosureCaptureError("original disclosure identity or store is unavailable")
    body = OfficialSzsePdfBodyStore(body_store_root).read(event.source_body_sha256)
    capture = CapturedOfficialSzsePdf(
        source_url=event.source_url,
        source_document_id=event.source_event_id,
        first_seen_at=event.first_seen_at,
        body_sha256=event.source_body_sha256,
        body=body,
    )
    verify_szse_pdf_security_code(capture, event.source_security_code)
    return capture


def verify_security_disclosure_original_body(
    event: SecurityDisclosureEvent,
    *,
    body_store_root: Path,
) -> bool:
    """Verify the exact retained original hash and security without changing facts."""
    try:
        _read_original_capture(event, body_store_root=body_store_root)
    except (OfficialDisclosureCaptureError, OSError, TypeError, ValueError):
        return False
    return True


def read_verified_szse_rights_completion(
    event: SecurityDisclosureEvent,
    *,
    body_store_root: Path,
) -> SzseRightsCompletionTerms | None:
    """Read confirmed rights-result facts from one verified original document only."""
    if (
        type(event) is not SecurityDisclosureEvent
        or event.event_type is not SecurityDisclosureEventType.RIGHTS_ISSUE
    ):
        return None
    try:
        capture = _read_original_capture(event, body_store_root=body_store_root)
        return extract_szse_rights_completion(capture, event.source_security_code)
    except (OfficialDisclosureCaptureError, OSError, TypeError, ValueError):
        return None
