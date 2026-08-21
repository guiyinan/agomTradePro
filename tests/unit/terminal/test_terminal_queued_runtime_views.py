"""Enabled-path contract tests for the durable queued Terminal Agent API."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from django.test import override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.agent_runtime.application.terminal_agent_run_ports import TerminalRunQueueSummary
from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalAgentRunContract,
    TerminalRunStatus,
)
from apps.terminal.interface import queued_runtime_views


class _FakeRepository:
    """In-memory adapter for HTTP admission and owner-scoped status tests."""

    def __init__(self) -> None:
        self.submitted: TerminalAgentRunContract | None = None

    def queue_summary(self, *, actor_user_id: int) -> TerminalRunQueueSummary:
        """Return an empty bounded queue snapshot."""

        return TerminalRunQueueSummary(
            actor_user_id=actor_user_id,
            user_active=0,
            user_queued=0,
            global_active=0,
            global_queued=0,
            worker_ready=True,
        )

    def submit(self, request: object) -> TerminalAgentRunContract:
        """Preserve the durable submission identity."""

        submission = request.submission
        self.submitted = TerminalAgentRunContract(
            submission=submission,
            dispatch_status=TerminalRunStatus.QUEUED,
        )
        return self.submitted


def test_enabled_create_admits_and_dispatches_only_identifiers(monkeypatch):
    """Authorized admission returns 202 and sends the run/task IDs to Celery."""

    repository = _FakeRepository()
    dispatched: list[dict[str, object]] = []
    monkeypatch.setattr(queued_runtime_views.transaction, "atomic", nullcontext)
    monkeypatch.setattr(queued_runtime_views.transaction, "on_commit", lambda callback: callback())
    monkeypatch.setattr(
        queued_runtime_views, "get_terminal_agent_run_repository", lambda: repository
    )
    monkeypatch.setattr(
        queued_runtime_views.execute_terminal_agent_run,
        "apply_async",
        lambda **kwargs: dispatched.append(kwargs),
    )
    factory = APIRequestFactory()
    request = factory.post(
        "/api/terminal/runs/",
        {
            "task_id": 17,
            "client_request_id": "request-view-contract-0001",
            "message": "health check",
            "run_id": "run-view-contract-0001",
        },
        format="json",
    )
    force_authenticate(request, user=SimpleNamespace(pk=7, is_authenticated=True))

    with override_settings(
        TERMINAL_QUEUED_INTAKE_ENABLED=True,
        TERMINAL_QUEUED_WORKER_ENABLED=True,
        TERMINAL_RUNTIME_AUTHORIZED=True,
        TERMINAL_EMERGENCY_STOP=False,
    ):
        response = queued_runtime_views.TerminalQueuedRunView.as_view()(request)

    assert response.status_code == 202
    assert response.data["run_id"] == "run-view-contract-0001"
    assert dispatched == [
        {
            "args": ["run-view-contract-0001", 17],
            "queue": "terminal_agent",
        }
    ]


def test_enabled_create_stays_fail_closed_when_emergency_stop_is_on(monkeypatch):
    """The emergency stop wins over both explicit queue flags."""

    monkeypatch.setattr(
        queued_runtime_views,
        "get_terminal_agent_run_repository",
        lambda: (_ for _ in ()).throw(AssertionError("repository must not be built")),
    )
    request = APIRequestFactory().post(
        "/api/terminal/runs/",
        {"task_id": 17, "client_request_id": "request-view-contract-0002", "message": "x"},
        format="json",
    )
    force_authenticate(request, user=SimpleNamespace(pk=7, is_authenticated=True))

    with override_settings(
        TERMINAL_QUEUED_INTAKE_ENABLED=True,
        TERMINAL_QUEUED_WORKER_ENABLED=True,
        TERMINAL_RUNTIME_AUTHORIZED=True,
        TERMINAL_EMERGENCY_STOP=True,
    ):
        response = queued_runtime_views.TerminalQueuedRunView.as_view()(request)

    assert response.status_code == 503
    assert response.data["reason_code"] == "queued_runtime_not_wired"


def test_committed_admission_survives_transient_broker_dispatch_failure(monkeypatch):
    """Broker outage does not turn a committed durable queue row into HTTP 500."""

    monkeypatch.setattr(
        queued_runtime_views.execute_terminal_agent_run,
        "apply_async",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("broker unavailable")),
    )

    queued_runtime_views._dispatch_queued_run("run-dispatch-failure", 17)
