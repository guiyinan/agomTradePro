"""Unit coverage for source-qualified disclosure Audit/Outbox observations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from apps.audit.application.security_disclosure_audit import (
    AppendSecurityDisclosureAuditObservationUseCase,
    SecurityDisclosureAuditConflict,
    SecurityDisclosureAuditDisposition,
    SecurityDisclosureAuditObservation,
    SecurityDisclosureFactEvidence,
    build_security_disclosure_fact_audit_event,
)
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCommit
from apps.audit.domain.system_audit_event import AuditScopeRef, SystemAuditEvent

_NOW = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)
_SCOPE = AuditScopeRef("test-tenant", "test-owner")


def _observation(
    *,
    first_observed_at: datetime = _NOW - timedelta(minutes=2),
    verified_at: datetime = _NOW - timedelta(minutes=1),
    recorded_at: datetime = _NOW,
) -> SecurityDisclosureAuditObservation:
    """Return one complete, source-qualified official listing batch."""

    body_hash = "a" * 64
    return SecurityDisclosureAuditObservation(
        source="szse_official",
        exchange="SZSE",
        asset_code="002727.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        first_observed_at=first_observed_at,
        verified_at=verified_at,
        announcement_count=1,
        coverage_manifest_sha256="b" * 64,
        source_manifest_sha256="c" * 64,
        first_pass_page_body_sha256=("d" * 64,),
        second_pass_page_body_sha256=("e" * 64,),
        facts=(
            SecurityDisclosureFactEvidence(
                source_event_id="37e23922-f64d-4203-9d27-9ed981a8f799",
                source_revision_id=f"sha256:{body_hash}",
                content_hash="f" * 64,
                source_body_sha256=body_hash,
            ),
        ),
        recorded_at=recorded_at,
    )


class _StaticScopeProvider:
    """Supply one stable server-issued audit scope for the unit contract."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        assert as_of.tzinfo is not None
        return _SCOPE


class _MemoryOutboxWriter:
    """Small exact-winner writer for Application idempotency tests."""

    def __init__(self) -> None:
        self.events: dict[tuple[str, str], SystemAuditEvent] = {}
        self.outbox_ids: dict[tuple[str, str], UUID] = {}
        self.atomic_active = False
        self.append_calls = 0

    @property
    def database_alias(self) -> str:
        return "default"

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.atomic_active = True
        try:
            yield
        finally:
            self.atomic_active = False

    def get_winner(
        self,
        *,
        event_id: str,
        event_version: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        event = self.events.get((event_id, event_version))
        return event if event is not None and event.recorded_at <= as_of else None

    def get_current_head(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> SystemAuditEvent | None:
        candidates = tuple(
            event
            for event in self.events.values()
            if event.stream_id == stream_id and event.scope == scope and event.recorded_at <= as_of
        )
        return max(candidates, key=lambda event: event.sequence_no) if candidates else None

    def list_events(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> tuple[SystemAuditEvent, ...]:
        return tuple(
            sorted(
                (
                    event
                    for event in self.events.values()
                    if event.stream_id == stream_id
                    and event.scope == scope
                    and event.recorded_at <= as_of
                ),
                key=lambda event: event.sequence_no,
            )
        )

    def append_and_enqueue(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> SystemAuditEventOutboxCommit:
        assert self.atomic_active
        assert event.predecessor_hash == expected_predecessor_hash
        assert event.recorded_at == recorded_at
        identity = (event.event_id, event.event_version)
        winner = self.events.get(identity)
        if winner is not None:
            assert winner == event
            event = winner
        else:
            self.events[identity] = event
            self.outbox_ids[identity] = uuid4()
        self.append_calls += 1
        outbox_id = self.outbox_ids[identity]
        return SystemAuditEventOutboxCommit(
            event=event,
            outbox_id=outbox_id,
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
        )


def test_observation_identity_and_event_bind_complete_source_hashes() -> None:
    observation = _observation()
    scoped = SecurityDisclosureAuditObservation(
        source=observation.source,
        exchange=observation.exchange,
        asset_code=observation.asset_code,
        start_on=observation.start_on,
        end_on=observation.end_on,
        first_observed_at=observation.first_observed_at,
        verified_at=observation.verified_at,
        announcement_count=observation.announcement_count,
        coverage_manifest_sha256=observation.coverage_manifest_sha256,
        source_manifest_sha256=observation.source_manifest_sha256,
        first_pass_page_body_sha256=observation.first_pass_page_body_sha256,
        second_pass_page_body_sha256=observation.second_pass_page_body_sha256,
        facts=observation.facts,
        recorded_at=observation.recorded_at,
        scope=_SCOPE,
    )

    event = build_security_disclosure_fact_audit_event(
        scoped,
        sequence_no=1,
        predecessor_hash=None,
    )

    assert event.event_type == "data.disclosure_fact.appended"
    assert event.detail_schema == "data.disclosure_fact.appended.v1"
    assert event.scope == _SCOPE
    assert event.detail["coverage_manifest_sha256"] == "b" * 64
    assert len(event.evidence_refs) == 2
    assert event.evidence_refs[1].content_hash == "a" * 64


def test_audit_replay_reuses_first_event_and_outbox_without_clock_identity_drift() -> None:
    writer = _MemoryOutboxWriter()
    use_case = AppendSecurityDisclosureAuditObservationUseCase(
        writer,
        _StaticScopeProvider(),
    )
    first = _observation()
    replay = _observation()
    scope = use_case.preflight(as_of=first.recorded_at)

    with use_case.atomic():
        first_result = use_case.execute_in_atomic_transaction(first, scope=scope)
    with use_case.atomic():
        replay_result = use_case.execute_in_atomic_transaction(replay, scope=scope)

    assert first_result.disposition is SecurityDisclosureAuditDisposition.STORED
    assert replay_result.disposition is SecurityDisclosureAuditDisposition.DUPLICATE
    assert replay_result.commit == first_result.commit
    assert len(writer.events) == 1
    assert len(writer.outbox_ids) == 1
    assert writer.append_calls == 2


def test_later_proof_episode_gets_new_audit_after_prior_fact_evidence_is_proven() -> None:
    writer = _MemoryOutboxWriter()
    use_case = AppendSecurityDisclosureAuditObservationUseCase(
        writer,
        _StaticScopeProvider(),
    )
    first = _observation()
    later = _observation(
        first_observed_at=_NOW - timedelta(minutes=1),
        verified_at=_NOW - timedelta(seconds=30),
        recorded_at=_NOW + timedelta(seconds=5),
    )
    scope = use_case.preflight(as_of=first.recorded_at)
    with use_case.atomic():
        first_result = use_case.execute_in_atomic_transaction(first, scope=scope)

    assert first.batch_identity != later.batch_identity
    use_case.assert_previously_audited_facts(
        later,
        facts=later.facts,
        as_of=later.recorded_at,
        scope=scope,
    )
    with use_case.atomic():
        later_result = use_case.execute_in_atomic_transaction(later, scope=scope)

    assert first_result.disposition is SecurityDisclosureAuditDisposition.STORED
    assert later_result.disposition is SecurityDisclosureAuditDisposition.STORED
    assert first_result.commit.event_id != later_result.commit.event_id
    assert len(writer.events) == 2
    assert len(writer.outbox_ids) == 2


def test_duplicate_fact_without_prior_audit_evidence_is_blocked() -> None:
    writer = _MemoryOutboxWriter()
    use_case = AppendSecurityDisclosureAuditObservationUseCase(
        writer,
        _StaticScopeProvider(),
    )
    observation = _observation()
    scope = use_case.preflight(as_of=observation.recorded_at)

    with pytest.raises(SecurityDisclosureAuditConflict, match="no exact prior Audit evidence"):
        use_case.assert_previously_audited_facts(
            observation,
            facts=observation.facts,
            as_of=observation.recorded_at,
            scope=scope,
        )


def test_existing_batch_identity_under_other_scope_fails_closed() -> None:
    writer = _MemoryOutboxWriter()
    use_case = AppendSecurityDisclosureAuditObservationUseCase(
        writer,
        _StaticScopeProvider(),
    )
    observation = _observation()
    other_scope = AuditScopeRef("other-tenant", "other-owner")
    scoped = SecurityDisclosureAuditObservation(
        source=observation.source,
        exchange=observation.exchange,
        asset_code=observation.asset_code,
        start_on=observation.start_on,
        end_on=observation.end_on,
        first_observed_at=observation.first_observed_at,
        verified_at=observation.verified_at,
        announcement_count=observation.announcement_count,
        coverage_manifest_sha256=observation.coverage_manifest_sha256,
        source_manifest_sha256=observation.source_manifest_sha256,
        first_pass_page_body_sha256=observation.first_pass_page_body_sha256,
        second_pass_page_body_sha256=observation.second_pass_page_body_sha256,
        facts=observation.facts,
        recorded_at=observation.recorded_at,
        scope=other_scope,
    )
    event = build_security_disclosure_fact_audit_event(
        scoped,
        sequence_no=1,
        predecessor_hash=None,
    )
    writer.events[(event.event_id, event.event_version)] = event
    scope = use_case.preflight(as_of=observation.recorded_at)

    with pytest.raises(SecurityDisclosureAuditConflict):
        use_case.find_exact_winner(observation, as_of=observation.recorded_at, scope=scope)


def test_invalid_source_revision_binding_is_rejected() -> None:
    with pytest.raises(ValueError, match="bind the retained source body hash"):
        SecurityDisclosureFactEvidence(
            source_event_id="document-1",
            source_revision_id=f"sha256:{'b' * 64}",
            content_hash="c" * 64,
            source_body_sha256="a" * 64,
        )
