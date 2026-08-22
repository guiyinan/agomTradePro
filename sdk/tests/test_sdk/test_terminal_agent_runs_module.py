"""SDK contract tests for durable queued Terminal Agent runs."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from agomtradepro import AgomTradeProClient
from agomtradepro.exceptions import TimeoutError as SDKTimeoutError
from agomtradepro.modules.terminal_agent_runs import TerminalAgentRunsModule


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def post(self, url: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("POST", url, kwargs.get("json")))
        return {"url": url, "body": kwargs.get("json")}

    def get(self, url: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("GET", url, kwargs.get("params")))
        return {"url": url, "params": kwargs.get("params")}


def test_terminal_agent_runs_facade_preserves_idempotency_and_routes() -> None:
    """Create, status, queue, events, and cancel use the durable API paths."""

    fake = _FakeClient()
    module = TerminalAgentRunsModule(fake)

    module.create_run(
        task_id=7,
        client_request_id="request-7",
        message="hello",
        request_digest="digest-7",
        run_id="run-7",
    )
    module.queue()
    module.get_run("run-7")
    module.get_events("run-7", after=3)
    module.cancel_run("run-7")

    assert fake.calls == [
        (
            "POST",
            "/api/terminal/runs/",
            {
                "task_id": 7,
                "client_request_id": "request-7",
                "message": "hello",
                "request_digest": "digest-7",
                "run_id": "run-7",
            },
        ),
        ("GET", "/api/terminal/runs/queue/", None),
        ("GET", "/api/terminal/runs/run-7/", None),
        ("GET", "/api/terminal/runs/run-7/events/", {"after": 3}),
        ("POST", "/api/terminal/runs/run-7/cancel/", None),
    ]


def test_client_exposes_singleton_terminal_agent_runs_module() -> None:
    """The public client exposes one stable queued-run module instance."""

    client = AgomTradeProClient(base_url="http://test.example.com", api_token="token")

    assert isinstance(client.agent_runtime.queued_runs, TerminalAgentRunsModule)
    assert client.agent_runtime.queued_runs is client.agent_runtime.queued_runs


def test_iter_events_replays_one_bounded_server_page() -> None:
    """Reconnects use the durable cursor without client-side mutation retry."""

    fake = _FakeClient()
    fake.get = lambda url, **kwargs: {
        "run_id": "run-7",
        "events": [{"event_id": "event-4", "sequence": 4, "event_type": "run.progress"}],
    }
    module = TerminalAgentRunsModule(fake)

    assert list(module.iter_events("run-7", after=3)) == [
        {"event_id": "event-4", "sequence": 4, "event_type": "run.progress"}
    ]


def test_wait_for_run_polls_until_terminal_without_executing_locally() -> None:
    """Waiting only reads server status and returns the durable terminal row."""

    class _PollingClient(_FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.statuses = iter(["queued", "running", "completed"])

        def get(self, url: str, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("GET", url, kwargs.get("params")))
            return {"run_id": "run-7", "status": next(self.statuses)}

    fake = _PollingClient()
    module = TerminalAgentRunsModule(fake)
    with (
        patch(
            "agomtradepro.modules.terminal_agent_runs.time.monotonic", side_effect=[0.0, 0.1, 0.2]
        ),
        patch("agomtradepro.modules.terminal_agent_runs.time.sleep") as sleep,
    ):
        result = module.wait_for_run("run-7", timeout_seconds=5.0, poll_interval_seconds=1.0)

    assert result["status"] == "completed"
    assert sleep.call_count == 2
    assert [call[1] for call in fake.calls] == [
        "/api/terminal/runs/run-7/",
        "/api/terminal/runs/run-7/",
        "/api/terminal/runs/run-7/",
    ]


def test_wait_for_run_times_out_explicitly() -> None:
    """A disconnected client receives a bounded timeout, not an infinite loop."""

    fake = _FakeClient()
    fake.get = lambda url, **kwargs: {"run_id": "run-7", "status": "running"}
    module = TerminalAgentRunsModule(fake)

    with (
        patch("agomtradepro.modules.terminal_agent_runs.time.monotonic", side_effect=[0.0, 2.0]),
        patch("agomtradepro.modules.terminal_agent_runs.time.sleep") as sleep,
        pytest.raises(SDKTimeoutError, match="Timed out waiting for run run-7"),
    ):
        module.wait_for_run("run-7", timeout_seconds=1.0, poll_interval_seconds=0.1)
    sleep.assert_not_called()


def test_cursor_and_poll_durations_reject_unsafe_values() -> None:
    """Cursor and wait controls reject bool, negative, zero, and non-finite values."""

    module = TerminalAgentRunsModule(_FakeClient())
    with pytest.raises(ValueError):
        module.get_events("run-7", after=-1)
    with pytest.raises(ValueError):
        module.get_events("run-7", after=True)
    with pytest.raises(ValueError):
        module.wait_for_run("run-7", timeout_seconds=0)
    with pytest.raises(ValueError):
        module.wait_for_run("run-7", poll_interval_seconds=float("inf"))
