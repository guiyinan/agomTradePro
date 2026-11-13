"""Exact Data Center identity checks for each current official-window member."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.data_center.application.security_disclosure_event import (
    QuerySecurityDisclosureEventsUseCase,
)
from apps.data_center.domain.security_disclosure_event import (
    PersistedSecurityDisclosureEvent,
    SecurityDisclosureEvent,
    SecurityDisclosureEventReadScope,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
)
from apps.portfolio.domain.transition_plan_event_review import TransitionPlanEventRevision
from apps.simulated_trading import corporate_action_original_body_composition as composition


def _facts() -> tuple[PersistedSecurityDisclosureEvent, TransitionPlanEventRevision]:
    """Build typed synthetic facts with all original and durable clocks distinct."""
    body = b"%PDF-1.4\nbody\n%%EOF"
    seen = datetime(2026, 11, 13, tzinfo=UTC)
    event = SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="300176.SZ",
        source_security_code="300176",
        source_event_id="cb0747e3-9f77-42a0-b221-ed1e5d3316ba",
        source_revision_id="sha256:" + hashlib.sha256(body).hexdigest(),
        raw_event_type="配股发行结果公告",
        event_type=SecurityDisclosureEventType.RIGHTS_ISSUE,
        source_url="https://disc.static.szse.cn/download/disc/disk03/finalpage/2026-08-21/cb0747e3-9f77-42a0-b221-ed1e5d3316ba.PDF",
        source_document_body=body,
        first_seen_at=seen,
    )
    record = PersistedSecurityDisclosureEvent(event, seen + timedelta(seconds=1))
    revision = TransitionPlanEventRevision(
        asset_code=event.asset_code,
        security_id=event.asset_code,
        source_id="szse_official",
        source_event_id=event.source_event_id,
        source_revision_id=event.source_revision_id,
        event_type=event.event_type.value,
        announced_at=event.announced_at,
        available_at=event.first_seen_at,
        known_at=record.recorded_at,
        effective_at=event.effective_at,
        body_sha256=event.source_body_sha256,
        manifest_sha256=event.content_hash,
    )
    return record, revision


class _Reader:
    def __init__(self, records: tuple[PersistedSecurityDisclosureEvent, ...]) -> None:
        self.records = records
        self.scopes: list[SecurityDisclosureEventReadScope] = []

    def execute(
        self, scope: SecurityDisclosureEventReadScope
    ) -> tuple[PersistedSecurityDisclosureEvent, ...]:
        self.scopes.append(scope)
        return self.records


@pytest.mark.parametrize(
    "failure", [None, "missing", "duplicate", "manifest", "clock", "category", "body"]
)
def test_member_checks_exact_record_before_reading_original(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str | None,
) -> None:
    """Hash-only matches never bypass the original record, clocks or security scope."""
    record, revision = _facts()
    records = (record,)
    if failure == "missing":
        records = ()
    elif failure == "duplicate":
        records = (record, record)
    elif failure == "manifest":
        revision = replace(revision, manifest_sha256="f" * 64)
    elif failure == "clock":
        revision = replace(revision, known_at=revision.known_at + timedelta(seconds=1))
    elif failure == "category":
        revision = replace(revision, event_type="other")
    reader = _Reader(records)

    def build(*, using: str) -> QuerySecurityDisclosureEventsUseCase:
        assert using == "qa"
        return cast(QuerySecurityDisclosureEventsUseCase, reader)

    bodies: list[SecurityDisclosureEvent] = []

    def verify(event: SecurityDisclosureEvent, *, body_store_root: Path) -> bool:
        bodies.append(event)
        assert event == record.event and body_store_root == tmp_path
        return failure != "body"

    monkeypatch.setattr(composition, "make_security_disclosure_event_reader", build)
    monkeypatch.setattr(composition, "verify_security_disclosure_original_body", verify)
    verifier = composition.DataCenterCorporateActionOriginalBodyVerifier(using="qa")
    assert verifier.verify_original_body(event=revision, body_store_root=tmp_path) is (
        failure is None
    )
    assert reader.scopes == [
        SecurityDisclosureEventReadScope(
            as_of=revision.known_at,
            exchange=SecurityDisclosureExchange.SZSE,
            asset_code="300176.SZ",
        )
    ]
    assert len(bodies) == (1 if failure in {None, "body"} else 0)
