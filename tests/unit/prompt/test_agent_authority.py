"""Server-side Agent authority gate tests."""

from __future__ import annotations

from typing import Any

from apps.prompt.application.agent_authority import (
    AGENT_AUTHORITY_NOT_WIRED,
    UnwiredAgentAuthorityGate,
)
from apps.prompt.application.agent_runtime import AgentRuntime
from apps.prompt.domain.agent_entities import AgentExecutionRequest


class _ClientFactory:
    def __init__(self) -> None:
        self.calls = 0

    def get_client(self, _provider_ref: object = None) -> Any:
        self.calls += 1
        raise AssertionError("model client must not be requested")


def test_unwired_gate_blocks_portfolio_scope_and_tools() -> None:
    """Caller-supplied portfolio selectors cannot become authority."""

    gate = UnwiredAgentAuthorityGate()

    assert (
        gate.check(
            context_scope=["portfolio"],
            context_params={"portfolio_id": 17},
            tool_names=None,
        )
        == AGENT_AUTHORITY_NOT_WIRED
    )
    assert (
        gate.check(
            context_scope=["macro"],
            context_params=None,
            tool_names=["get_portfolio_positions"],
        )
        == AGENT_AUTHORITY_NOT_WIRED
    )
    assert gate.check(context_scope=["macro"], context_params=None, tool_names=None) is None


def test_agent_runtime_blocks_before_model_for_unwired_portfolio_scope() -> None:
    """The server gate runs before context construction or model/provider access."""

    factory = _ClientFactory()
    runtime = AgentRuntime(
        ai_client_factory=factory,
        authority_gate=UnwiredAgentAuthorityGate(),
    )

    response = runtime.execute(
        AgentExecutionRequest(
            task_type="analysis",
            user_input="show my portfolio",
            context_scope=["portfolio"],
            context_params={"portfolio_id": 17},
        )
    )

    assert response.success is False
    assert response.error_message == AGENT_AUTHORITY_NOT_WIRED
    assert response.provider_used is None
    assert factory.calls == 0


def test_agent_runtime_defaults_to_fail_closed_authority() -> None:
    """Direct/internal construction cannot bypass the server authority gate."""

    factory = _ClientFactory()
    runtime = AgentRuntime(ai_client_factory=factory)

    response = runtime.execute(
        AgentExecutionRequest(
            task_type="strategy",
            user_input="show portfolio positions",
            context_scope=["portfolio"],
            context_params={"portfolio_id": 99},
            tool_names=["get_portfolio_positions"],
        )
    )

    assert response.success is False
    assert response.error_message == AGENT_AUTHORITY_NOT_WIRED
    assert factory.calls == 0
