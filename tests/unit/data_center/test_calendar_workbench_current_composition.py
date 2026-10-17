"""Scope-bound current-calendar owner composition tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from apps.data_center import calendar_workbench_current_composition as composition
from apps.data_center.application.calendar_publication_operations import (
    CalendarPublicationOperationsError,
    ReadCurrentCalendarIntent,
)
from apps.data_center.application.calendar_workbench_scope import (
    CalendarWorkbenchScopeContext,
    CalendarWorkbenchScopeMetadataStatus,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CurrentPublishedExchangeCalendar,
)
from tests.unit.data_center.test_calendar_publication_api_views import _formal_commit
from tests.unit.data_center.test_calendar_publication_operations import NOW
from tests.unit.data_center.test_calendar_workbench_api_views import (
    _blocked_scope,
    _selected_scope,
)


def _current() -> CurrentPublishedExchangeCalendar:
    """Build a valid exact current result without a database read."""

    commit = _formal_commit()
    return CurrentPublishedExchangeCalendar(
        record=commit.record,
        pointer=commit.pointer,
        as_of=NOW + timedelta(seconds=2),
    )


def test_current_composition_uses_selected_dataset_and_same_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve one selected dataset before delegating exact current read."""

    scope = _selected_scope()
    current = _current()
    calls: list[object] = []

    def read_scope() -> CalendarWorkbenchScopeContext:
        calls.append("scope")
        return scope

    def read_current(intent: object) -> CurrentPublishedExchangeCalendar:
        calls.append(intent)
        assert type(intent) is ReadCurrentCalendarIntent
        assert intent.dataset_key == scope.metadata.dataset_key
        assert intent.exchange == "SSE"
        return current

    monkeypatch.setattr(composition, "read_calendar_workbench_scope_context", read_scope)
    monkeypatch.setattr(composition, "read_current_exchange_calendar", read_current)

    result = composition.read_calendar_workbench_current("SSE")

    assert calls[0] == "scope"
    assert result.scope is scope
    assert result.current is current
    assert len(calls) == 2


def test_blocked_configuration_reason_is_preserved_without_current_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blocked configuration remains typed and never falls back to old datasets."""

    scope = _blocked_scope()
    calls: list[bool] = []
    monkeypatch.setattr(composition, "read_calendar_workbench_scope_context", lambda: scope)
    monkeypatch.setattr(
        composition,
        "read_current_exchange_calendar",
        lambda intent: calls.append(True),
    )

    result = composition.read_calendar_workbench_current("SSE")

    assert result.scope.metadata_status is CalendarWorkbenchScopeMetadataStatus.BLOCKED
    assert result.scope.blocked_reason == scope.blocked_reason
    assert result.current is None
    assert calls == []


def test_invalid_exchange_is_rejected_before_scope_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The composition validates exchange even when no catalog scope is available."""

    calls: list[bool] = []
    monkeypatch.setattr(
        composition,
        "read_calendar_workbench_scope_context",
        lambda: calls.append(True),
    )

    with pytest.raises(CalendarPublicationOperationsError) as error:
        composition.read_calendar_workbench_current("SSE/SHENZHEN")

    assert error.value.code == "CALENDAR_CURRENT_READ_QUERY_INVALID"
    assert calls == []


def test_current_result_must_match_selected_dataset_and_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken owner adapter cannot make a different scope look current."""

    selected_scope = _selected_scope()
    assert selected_scope.metadata is not None
    scope = replace(
        selected_scope,
        metadata=replace(selected_scope.metadata, dataset_key="other"),
    )
    current = _current()
    monkeypatch.setattr(composition, "read_calendar_workbench_scope_context", lambda: scope)
    monkeypatch.setattr(
        composition,
        "read_current_exchange_calendar",
        lambda intent: current,
    )

    with pytest.raises(CalendarPublicationOperationsError) as error:
        composition.read_calendar_workbench_current("SSE")

    assert error.value.code == "CALENDAR_CURRENT_READ_SCOPE_MISMATCH"


def test_no_current_pointer_is_retained_as_an_explicit_empty_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A selected config without a pointer is not replaced by another dataset."""

    scope = _selected_scope()
    calls: list[object] = []
    monkeypatch.setattr(composition, "read_calendar_workbench_scope_context", lambda: scope)
    monkeypatch.setattr(
        composition,
        "read_current_exchange_calendar",
        lambda intent: calls.append(intent),
    )

    result = composition.read_calendar_workbench_current("SSE")

    assert result.scope is scope
    assert result.current is None
    assert len(calls) == 1
