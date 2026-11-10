"""Domain and Application contracts for official security disclosures."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, date, datetime

import pytest

from apps.data_center.application.security_disclosure_event import (
    AppendSecurityDisclosureEventUseCase,
    QuerySecurityDisclosureEventsUseCase,
)
from apps.data_center.domain.security_disclosure_event import (
    PersistedSecurityDisclosureEvent,
    SecurityDisclosureEvent,
    SecurityDisclosureEventAppendDisposition,
    SecurityDisclosureEventAppendResult,
    SecurityDisclosureEventReadScope,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
)
from core.exceptions import DataValidationError

FIRST_SEEN = datetime(2026, 11, 9, 3, 15, tzinfo=UTC)
RECORDED_AT = datetime(2026, 11, 9, 3, 16, tzinfo=UTC)
BODY = b"official exchange disclosure body"


def _event(
    *,
    source_event_id: str = "disclose-001",
    source_revision_id: str = "r1",
    body: bytes = BODY,
    first_seen_at: datetime = FIRST_SEEN,
    event_type: SecurityDisclosureEventType = SecurityDisclosureEventType.CASH_DIVIDEND,
    effective_at: date | datetime | None = date(2028, 6, 30),
    supersedes_source_event_id: str | None = None,
    supersedes_source_revision_id: str | None = None,
) -> SecurityDisclosureEvent:
    return SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="301237.SZ",
        source_security_code="301237",
        source_event_id=source_event_id,
        source_revision_id=source_revision_id,
        raw_event_type="利润分配方案",
        event_type=event_type,
        source_url="https://www.szse.cn/disclosure/listed/bulletinDetail/index.html",
        source_document_body=body,
        first_seen_at=first_seen_at,
        announced_at=date(2026, 11, 8),
        source_available_at=None,
        effective_at=effective_at,
        supersedes_source_event_id=supersedes_source_event_id,
        supersedes_source_revision_id=supersedes_source_revision_id,
    )


class _Repository:
    """Small typed fake to verify Application behavior without infrastructure."""

    def __init__(self) -> None:
        self.append_calls: list[tuple[SecurityDisclosureEvent, bytes]] = []
        self.read_calls: list[SecurityDisclosureEventReadScope] = []

    def append(
        self,
        event: SecurityDisclosureEvent,
        source_document_body: bytes,
    ) -> SecurityDisclosureEventAppendResult:
        self.append_calls.append((event, source_document_body))
        return SecurityDisclosureEventAppendResult(
            disposition=SecurityDisclosureEventAppendDisposition.STORED,
            record=PersistedSecurityDisclosureEvent(event, RECORDED_AT),
        )

    def list_known_at(
        self,
        scope: SecurityDisclosureEventReadScope,
    ) -> tuple[PersistedSecurityDisclosureEvent, ...]:
        self.read_calls.append(scope)
        return ()


def test_source_document_hash_and_original_date_precision_are_retained() -> None:
    event = _event()

    assert event.source_body_sha256 == hashlib.sha256(BODY).hexdigest()
    assert event.announced_at == date(2026, 11, 8)
    assert event.source_available_at is None
    assert event.available_at == FIRST_SEEN
    assert event.effective_at == date(2028, 6, 30)
    assert event.verifies_source_document(BODY)
    assert not event.verifies_source_document(BODY + b" changed")


def test_same_native_revision_content_hash_ignores_repeated_capture_time() -> None:
    first = _event()
    second = _event(first_seen_at=datetime(2026, 11, 10, 4, 0, tzinfo=UTC))

    assert first.identity_key == second.identity_key
    assert first.content_hash == second.content_hash


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("asset_code", "301237.SH"),
        ("source_security_code", "301238"),
        ("source_url", "https://szse.cn.evil.example/disclosure.pdf"),
        ("source_body_sha256", None),
        ("first_seen_at", datetime(2026, 11, 9, 3, 15)),
        ("announced_at", datetime(2026, 11, 9, 4, 0, tzinfo=UTC)),
    ],
)
def test_domain_rejects_mismatched_identity_or_malformed_evidence(
    field: str,
    value: object,
) -> None:
    values: dict[str, object] = {
        "source": SecurityDisclosureSource.SZSE_OFFICIAL,
        "exchange": SecurityDisclosureExchange.SZSE,
        "asset_code": "301237.SZ",
        "source_security_code": "301237",
        "source_event_id": "disclose-001",
        "source_revision_id": "r1",
        "raw_event_type": "利润分配方案",
        "event_type": SecurityDisclosureEventType.CASH_DIVIDEND,
        "source_url": "https://www.szse.cn/disclosure/listed/bulletinDetail/index.html",
        "source_body_sha256": hashlib.sha256(BODY).hexdigest(),
        "announced_at": date(2026, 11, 8),
        "source_available_at": None,
        "first_seen_at": FIRST_SEEN,
        "effective_at": date(2028, 6, 30),
    }
    values[field] = value

    with pytest.raises(ValueError):
        SecurityDisclosureEvent(**values)  # type: ignore[arg-type]


def test_domain_rejects_self_supersession() -> None:
    with pytest.raises(ValueError, match="cannot supersede itself"):
        _event(
            supersedes_source_event_id="disclose-001",
            supersedes_source_revision_id="r1",
        )


def test_unknown_event_type_is_logged_and_preserved(caplog: pytest.LogCaptureFixture) -> None:
    repository = _Repository()
    event = _event(event_type=SecurityDisclosureEventType.UNKNOWN)

    with caplog.at_level(
        logging.WARNING, logger="apps.data_center.application.security_disclosure_event"
    ):
        result = AppendSecurityDisclosureEventUseCase(repository).execute(event, BODY)

    assert result.disposition is SecurityDisclosureEventAppendDisposition.STORED
    assert repository.append_calls == [(event, BODY)]
    assert "Unknown official disclosure type retained as UNKNOWN" in caplog.text


def test_append_use_case_rejects_body_mismatch_before_repository_write() -> None:
    repository = _Repository()

    with pytest.raises(DataValidationError) as error:
        AppendSecurityDisclosureEventUseCase(repository).execute(_event(), BODY + b"changed")

    assert error.value.code == "SECURITY_DISCLOSURE_EVENT_SOURCE_BODY_MISMATCH"
    assert repository.append_calls == []


def test_query_use_case_passes_scope_without_effective_time_reinterpretation() -> None:
    repository = _Repository()
    scope = SecurityDisclosureEventReadScope(
        as_of=FIRST_SEEN,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="301237.SZ",
    )

    result = QuerySecurityDisclosureEventsUseCase(repository).execute(scope)

    assert result == ()
    assert repository.read_calls == [scope]
