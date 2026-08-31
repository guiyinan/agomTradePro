from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_audit_event")

import django

django.setup()

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.audit.application.data_decision_read_audit import (
    DataDecisionReadAuditObservation,
    build_data_decision_read_audit_event,
)
from apps.audit.application.data_fetch_audit import (
    DataFetchAuditObservation,
    build_data_fetch_audit_event,
)
from apps.audit.application.data_publication_audit import (
    DataPublicationAuditObservation,
    build_data_publication_audit_event,
)
from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef, SystemAuditEvent
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_repository import (
    DjangoSystemAuditEventRepository,
    SystemAuditConflict,
    SystemAuditCorruption,
    SystemAuditUnavailable,
)
from tests.support.isolated_schema import isolated_schema
from tests.unit.audit.test_system_audit_event import make_event

NOW = datetime(2026, 8, 14, 12, 0, 0, 123456, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)
SCOPE = AuditScopeRef("tenant:research", "owner:alice")
OTHER_SCOPE = AuditScopeRef("tenant:other", "owner:alice")
RUN_ID = "run-1"
INGESTED_RUN_ID = "ingested-1"
PUBLICATION_ID = "publication-1"
PUBLICATION_HASH = "b" * 64


class FixedClock:
    """Deterministic aware clock for SQLite component evidence."""

    def now(self) -> datetime:
        return NOW + timedelta(days=1)


@pytest.fixture(scope="module", autouse=True)
def _audit_event_table(django_db_blocker: object) -> Iterator[None]:
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema((SystemAuditEventModel,)):
            yield


@pytest.fixture(autouse=True)
def _clear_audit_events(django_db_blocker: object) -> Iterator[None]:
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM audit_system_event")
        yield


def _repository() -> DjangoSystemAuditEventRepository:
    return DjangoSystemAuditEventRepository(clock=FixedClock())


def _successor(
    root: SystemAuditEvent, *, detail: dict[str, object] | None = None
) -> SystemAuditEvent:
    return SystemAuditEvent.create(
        event_id=root.event_id,
        event_version="2",
        schema_version=root.schema_version,
        category=root.category,
        event_type=root.event_type,
        owner=root.owner,
        write_policy=root.write_policy,
        outcome=root.outcome,
        severity=root.severity,
        reason_codes=root.reason_codes,
        occurred_at=root.occurred_at,
        recorded_at=LATER,
        observed_at=root.observed_at,
        actor=root.actor,
        source_app=root.source_app,
        source_component=root.source_component,
        source_surface=root.source_surface,
        correlations=root.correlations,
        resource=root.resource,
        dataset_key=root.dataset_key,
        provider_key=root.provider_key,
        capability=root.capability,
        publication_id=root.publication_id,
        evidence_refs=root.evidence_refs,
        scope=root.scope,
        detail_schema=root.detail_schema,
        detail=detail if detail is not None else dict(root.detail),
        stream_id=root.stream_id,
        sequence_no=2,
        predecessor_hash=root.content_hash,
        idempotency_key="fetch:run-1:successor",
    )


def _different_identity_payload(root: SystemAuditEvent) -> SystemAuditEvent:
    return SystemAuditEvent.create(
        event_id=root.event_id,
        event_version=root.event_version,
        schema_version=root.schema_version,
        category=root.category,
        event_type=root.event_type,
        owner=root.owner,
        write_policy=root.write_policy,
        outcome=root.outcome,
        severity=root.severity,
        reason_codes=root.reason_codes,
        occurred_at=root.occurred_at,
        recorded_at=root.recorded_at,
        observed_at=root.observed_at,
        actor=root.actor,
        source_app=root.source_app,
        source_component=root.source_component,
        source_surface=root.source_surface,
        correlations=root.correlations,
        resource=root.resource,
        dataset_key=root.dataset_key,
        provider_key=root.provider_key,
        capability=root.capability,
        publication_id=root.publication_id,
        evidence_refs=root.evidence_refs,
        scope=root.scope,
        detail_schema=root.detail_schema,
        detail={"rows": 3, "source_status": "valid", "nested": {"ok": True}},
        stream_id=root.stream_id,
        sequence_no=root.sequence_no,
        predecessor_hash=root.predecessor_hash,
        idempotency_key=root.idempotency_key,
    )


def _correlated_events(
    *, scope: AuditScopeRef = SCOPE
) -> tuple[SystemAuditEvent, SystemAuditEvent, SystemAuditEvent]:
    """Build a three-stream fetch/publication/read chain for repository tests."""

    raw_hash = "a" * 64
    fetch = build_data_fetch_audit_event(
        DataFetchAuditObservation(
            provider_key="provider-main",
            capability="macro",
            dataset_key="macro.series.cpi",
            run_id=RUN_ID,
            ingested_run_id=INGESTED_RUN_ID,
            raw_audit_id="raw-1",
            raw_audit_version="1",
            raw_audit_content_hash=raw_hash,
            outcome=AuditOutcome.SUCCESS,
            row_count=1,
            occurred_at=NOW,
            recorded_at=NOW,
            scope=scope,
        ),
        sequence_no=1,
        predecessor_hash=None,
    )
    publication = build_data_publication_audit_event(
        DataPublicationAuditObservation(
            dataset_key="macro.series.cpi",
            publication_key="CPI",
            publication_id=PUBLICATION_ID,
            publication_version="policy-v1",
            publication_hash=PUBLICATION_HASH,
            provider_key="provider-main",
            run_id=RUN_ID,
            ingested_run_id=INGESTED_RUN_ID,
            member_count=1,
            coverage_requested_count=1,
            coverage_eligible_count=1,
            coverage_selected_count=1,
            outcome=AuditOutcome.PUBLISHED,
            raw_audit_id="raw-1",
            raw_audit_version="1",
            raw_audit_content_hash=raw_hash,
            occurred_at=NOW + timedelta(seconds=1),
            recorded_at=NOW + timedelta(seconds=1),
            scope=scope,
        ),
        sequence_no=1,
        predecessor_hash=None,
    )
    decision_read = build_data_decision_read_audit_event(
        DataDecisionReadAuditObservation(
            dataset_key="macro.series.cpi",
            publication_key="CPI",
            publication_id=PUBLICATION_ID,
            publication_version="policy-v1",
            publication_hash=PUBLICATION_HASH,
            provider_key="provider-main",
            run_id=RUN_ID,
            ingested_run_id=INGESTED_RUN_ID,
            decision_key="portfolio-readiness",
            freshness_status="fresh",
            outcome=AuditOutcome.RECOVERED,
            occurred_at=NOW + timedelta(seconds=2),
            recorded_at=NOW + timedelta(seconds=2),
            scope=scope,
        ),
        sequence_no=1,
        predecessor_hash=None,
    )
    return fetch, publication, decision_read


def test_root_append_exact_replay_and_pit_reads() -> None:
    repository = _repository()
    root = make_event()
    with repository.atomic():
        assert (
            repository.append(
                root,
                expected_predecessor_hash=None,
                recorded_at=NOW,
            )
            == root
        )
    with repository.atomic():
        assert (
            repository.append(
                root,
                expected_predecessor_hash=None,
                recorded_at=NOW,
            )
            == root
        )
    assert SystemAuditEventModel._default_manager.count() == 1
    assert (
        repository.get_exact_by_hash(
            event_id=root.event_id,
            event_version=root.event_version,
            expected_content_hash=root.content_hash,
            as_of=NOW,
        )
        == root
    )
    assert repository.get_current_head(stream_id=root.stream_id, as_of=NOW) == root


def test_successor_cas_and_pit_head_never_fallback_from_future_state() -> None:
    repository = _repository()
    root = make_event()
    successor = _successor(root)
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        with pytest.raises(SystemAuditConflict, match="predecessor CAS"):
            repository.append(
                successor,
                expected_predecessor_hash="b" * 64,
                recorded_at=LATER,
            )
    assert (
        repository.get_current_head(stream_id=root.stream_id, as_of=NOW + timedelta(seconds=30))
        == root
    )
    with repository.atomic():
        repository.append(
            successor,
            expected_predecessor_hash=root.content_hash,
            recorded_at=LATER,
        )
    assert repository.get_current_head(stream_id=root.stream_id, as_of=NOW) == root
    assert repository.get_current_head(stream_id=root.stream_id, as_of=LATER) == successor
    assert repository.list_events(stream_id=root.stream_id, as_of=LATER) == (root, successor)


def test_same_identity_different_content_is_conflict_and_append_requires_uow() -> None:
    repository = _repository()
    root = make_event()
    different = _different_identity_payload(root)
    with pytest.raises(SystemAuditConflict, match="repository.atomic"):
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        with pytest.raises(SystemAuditConflict, match="another winner"):
            repository.append(different, expected_predecessor_hash=None, recorded_at=NOW)
    with pytest.raises(ValidationError, match="may not be nested"):
        with repository.atomic():
            with repository.atomic():
                pass


def test_unrelated_scalar_tamper_is_hidden_by_no_selector_and_fails_closed() -> None:
    repository = _repository()
    root = make_event()
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE audit_system_event SET owner = %s WHERE event_id = %s",
            ["tampered", root.event_id],
        )
    with pytest.raises(SystemAuditCorruption, match="headers"):
        repository.get_current_head(stream_id=root.stream_id, as_of=NOW)


def test_future_recorded_at_append_is_rejected() -> None:
    repository = _repository()
    root = make_event()
    future = _successor(root)
    future = replace(future, recorded_at=NOW + timedelta(days=2))
    with repository.atomic():
        with pytest.raises(SystemAuditUnavailable, match="future"):
            repository.append(
                future,
                expected_predecessor_hash=None,
                recorded_at=future.recorded_at,
            )


def test_correlated_read_resolves_publication_to_the_complete_run() -> None:
    repository = _repository()
    events = _correlated_events()
    with repository.atomic():
        for event in events:
            repository.append(
                event,
                expected_predecessor_hash=None,
                recorded_at=event.recorded_at,
            )

    assert repository.list_correlated_events(None, PUBLICATION_ID, LATER, SCOPE) == events
    assert repository.list_correlated_events(RUN_ID, None, LATER, SCOPE) == events


def test_correlated_read_is_scope_and_pit_bounded() -> None:
    repository = _repository()
    scoped_events = _correlated_events()
    with repository.atomic():
        for event in scoped_events:
            repository.append(
                event,
                expected_predecessor_hash=None,
                recorded_at=event.recorded_at,
            )

    assert (
        repository.list_correlated_events(
            None,
            PUBLICATION_ID,
            LATER,
            OTHER_SCOPE,
        )
        == ()
    )
    assert (
        repository.list_correlated_events(
            None,
            PUBLICATION_ID,
            NOW + timedelta(seconds=1),
            SCOPE,
        )
        == scoped_events[:2]
    )


def _foreign_root(root: SystemAuditEvent) -> SystemAuditEvent:
    """Rebuild one root under a distinct identity, stream and scope."""

    return SystemAuditEvent.create(
        event_id=f"{root.event_id}:foreign",
        event_version=root.event_version,
        schema_version=root.schema_version,
        category=root.category,
        event_type=root.event_type,
        owner=root.owner,
        write_policy=root.write_policy,
        outcome=root.outcome,
        severity=root.severity,
        reason_codes=root.reason_codes,
        occurred_at=root.occurred_at,
        recorded_at=root.recorded_at,
        observed_at=root.observed_at,
        actor=root.actor,
        source_app=root.source_app,
        source_component=root.source_component,
        source_surface=root.source_surface,
        correlations=root.correlations,
        resource=root.resource,
        dataset_key=root.dataset_key,
        provider_key=root.provider_key,
        capability=root.capability,
        publication_id=root.publication_id,
        evidence_refs=root.evidence_refs,
        scope=OTHER_SCOPE,
        detail_schema=root.detail_schema,
        detail=root.detail,
        stream_id=f"{root.stream_id}:foreign",
        sequence_no=1,
        predecessor_hash=None,
        idempotency_key=f"{root.idempotency_key}:foreign",
    )


def test_archive_window_read_is_scoped_bounded_and_globally_ordered() -> None:
    repository = _repository()
    scoped_events = _correlated_events()
    foreign = _foreign_root(scoped_events[0])
    with repository.atomic():
        for event in (*scoped_events, foreign):
            repository.append(
                event,
                expected_predecessor_hash=None,
                recorded_at=event.recorded_at,
            )

    assert (
        repository.list_archive_window(
            window_started_at=NOW,
            window_ended_at=NOW + timedelta(seconds=1),
            as_of=LATER,
            scope=SCOPE,
            limit=3,
        )
        == scoped_events[:1]
    )
    assert (
        repository.list_archive_window(
            window_started_at=NOW,
            window_ended_at=NOW + timedelta(seconds=3),
            as_of=LATER,
            scope=SCOPE,
            limit=2,
        )
        == scoped_events[:2]
    )


@pytest.mark.parametrize(
    ("started_at", "ended_at", "as_of", "limit", "reason"),
    [
        (LATER, NOW, LATER, 1, "window order"),
        (NOW, NOW, LATER, 1, "window order"),
        (NOW, LATER + timedelta(seconds=1), LATER, 1, "after the PIT"),
        (NOW, LATER, LATER, 0, "limit"),
        (NOW.replace(tzinfo=None), LATER, LATER, 1, "timezone-aware"),
    ],
)
def test_archive_window_read_rejects_unbounded_or_invalid_selectors(
    started_at: datetime,
    ended_at: datetime,
    as_of: datetime,
    limit: int,
    reason: str,
) -> None:
    with pytest.raises(SystemAuditUnavailable, match=reason):
        _repository().list_archive_window(
            window_started_at=started_at,
            window_ended_at=ended_at,
            as_of=as_of,
            scope=SCOPE,
            limit=limit,
        )
