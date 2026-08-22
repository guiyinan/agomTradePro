"""SDK contract tests for durable queued Terminal Agent runs."""

from __future__ import annotations

from typing import Any

from agomtradepro import AgomTradeProClient
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
