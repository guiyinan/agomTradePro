"""RED contracts for run/publication-correlated system-audit reads."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.audit.application.system_audit_query import (
    ListCorrelatedSystemAuditEventsCommand,
    ListCorrelatedSystemAuditEventsUseCase,
    SystemAuditQueryCorruption,
    SystemAuditQueryUnavailable,
    SystemAuditReaderContext,
)
from apps.audit.domain.system_audit_event import AuditCorrelations, AuditScopeRef, SystemAuditEvent
from tests.unit.audit.test_system_audit_event import make_event

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
SCOPE = AuditScopeRef("tenant:primary", "owner:research")
OTHER_SCOPE = AuditScopeRef("tenant:other", "owner:research")


def _reader(*, staff: bool = True) -> SystemAuditReaderContext:
    """Issue a valid test reader context through the private composition seam."""

    return SystemAuditReaderContext._from_authority(
        authority_source_id="authority:7",
        authority_source_version="v1",
        actor_id="django-user:7",
        user_id=7,
        tenant_id=SCOPE.tenant_id,
        owner_id=SCOPE.owner_id,
        authority_content_hash="a" * 64,
        is_authenticated=True,
        is_staff=staff,
        role="admin",
        authority_state="active",
        authority_recorded_at=NOW - timedelta(minutes=1),
        authority_valid_until=NOW + timedelta(hours=1),
    )


def _event(
    *,
    event_id: str,
    sequence_no: int,
    run_id: str | None = "run-1",
    publication_id: str | None = "publication-1",
    recorded_at: datetime = NOW,
    scope: AuditScopeRef | None = SCOPE,
) -> SystemAuditEvent:
    """Build one valid event carrying the requested correlation values."""

    base = make_event(scope=scope)
    return replace(
        base,
        event_id=event_id,
        idempotency_key=f"idempotency:{event_id}",
        sequence_no=sequence_no,
        predecessor_hash=(base.content_hash if sequence_no > 1 else None),
        recorded_at=recorded_at,
        correlations=AuditCorrelations(
            run_id=run_id,
            ingested_run_id="ingested-1" if run_id is not None else None,
            dataset_key="equity.price.bar",
            provider_key="provider-main",
            capability="historical_price",
            publication_id=publication_id,
        ),
        publication_id=publication_id,
    )


class _Repository:
    """Typed fake for the proposed correlated repository port."""

    def __init__(self, events: tuple[SystemAuditEvent, ...]) -> None:
        self.events = events
        self.calls: list[tuple[str | None, str | None, datetime, AuditScopeRef]] = []

    def list_correlated_events(
        self,
        run_id: str | None,
        publication_id: str | None,
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> tuple[SystemAuditEvent, ...]:
        self.calls.append((run_id, publication_id, as_of, scope))
        return self.events


def _execute(
    repository: _Repository,
    *,
    run_id: str | None = "run-1",
    publication_id: str | None = None,
    reader: SystemAuditReaderContext | None = None,
) -> object:
    """Execute the intended use case with one explicit selector."""

    return ListCorrelatedSystemAuditEventsUseCase(repository).execute(
        ListCorrelatedSystemAuditEventsCommand(
            run_id=run_id,
            publication_id=publication_id,
            as_of=NOW,
            reader=reader or _reader(),
        )
    )


def test_run_selector_returns_sorted_full_correlated_chain_and_forwards_scope() -> None:
    events = (_event(event_id="evt-1", sequence_no=1), _event(event_id="evt-2", sequence_no=2))
    repository = _Repository(events)

    result = _execute(repository, run_id="run-1")

    assert result.events == events
    assert result.resolved_run_id == "run-1"
    assert result.requested_publication_id is None
    assert repository.calls == [("run-1", None, NOW, SCOPE)]


def test_publication_selector_resolves_unique_run_and_returns_that_run() -> None:
    repository = _Repository(
        (
            _event(event_id="fetch", sequence_no=1, publication_id=None),
            _event(event_id="publish", sequence_no=2, publication_id="publication-1"),
        )
    )

    result = _execute(repository, run_id=None, publication_id="publication-1")

    assert result.resolved_run_id == "run-1"
    assert result.requested_publication_id == "publication-1"
    assert result.events[0].correlations.run_id == "run-1"


def test_staff_and_pit_authority_are_required_before_repository_call() -> None:
    repository = _Repository(())

    with pytest.raises(SystemAuditQueryUnavailable):
        _execute(repository, reader=_reader(staff=False))
    assert repository.calls == []

    expired = replace(
        _reader(),
        authority_recorded_at=NOW - timedelta(hours=2),
        authority_valid_until=NOW - timedelta(hours=1),
    )
    with pytest.raises(SystemAuditQueryUnavailable):
        _execute(repository, reader=expired)
    assert repository.calls == []


def test_empty_correlated_result_is_unavailable() -> None:
    with pytest.raises(SystemAuditQueryUnavailable):
        _execute(_Repository(()))


@pytest.mark.parametrize(
    "events,publication_id",
    [
        ((_event(event_id="fetch", sequence_no=1),), "missing-publication"),
        (
            (
                _event(event_id="one", sequence_no=1, publication_id="publication-1"),
                _event(
                    event_id="two", sequence_no=2, run_id="run-2", publication_id="publication-1"
                ),
            ),
            "publication-1",
        ),
    ],
)
def test_publication_selector_requires_one_nonempty_run(
    events: tuple[SystemAuditEvent, ...], publication_id: str
) -> None:
    with pytest.raises(SystemAuditQueryCorruption):
        _execute(_Repository(events), run_id=None, publication_id=publication_id)


@pytest.mark.parametrize(
    "events",
    [
        (_event(event_id="foreign", sequence_no=1, scope=OTHER_SCOPE),),
        (_event(event_id="mixed", sequence_no=1, run_id="run-2"),),
        (_event(event_id="missing-run", sequence_no=1, run_id=None),),
    ],
)
def test_correlated_result_rejects_scope_run_or_run_correlation_mixing(
    events: tuple[SystemAuditEvent, ...],
) -> None:
    with pytest.raises(SystemAuditQueryCorruption):
        _execute(_Repository(events))


def test_global_order_must_be_recorded_stream_sequence() -> None:
    first = _event(event_id="first", sequence_no=1, recorded_at=NOW)
    second = _event(
        event_id="second",
        sequence_no=2,
        recorded_at=NOW - timedelta(minutes=1),
    )

    with pytest.raises(SystemAuditQueryCorruption):
        _execute(_Repository((first, second)))


@pytest.mark.parametrize(
    "run_id,publication_id",
    [
        (None, None),
        ("", None),
        (" run-1", None),
        (None, ""),
        (None, " publication-1"),
        ("run-1", "publication-1"),
    ],
)
def test_command_requires_exactly_one_canonical_selector(
    run_id: str | None,
    publication_id: str | None,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        ListCorrelatedSystemAuditEventsCommand(
            run_id=run_id,
            publication_id=publication_id,
            as_of=NOW,
            reader=_reader(),
        )
