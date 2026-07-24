"""Audit and sensitive-payload contracts for Prompt agent trace logging."""

from unittest.mock import Mock

from apps.prompt.application.trace_logging import AgentExecutionLogger, _truncate
from apps.prompt.domain.agent_entities import (
    AgentExecutionRequest,
    AgentExecutionResponse,
    ToolCallRecord,
)


def test_success_trace_is_bounded_structured_and_persisted() -> None:
    repository = Mock()
    request = AgentExecutionRequest(
        task_type="analysis",
        user_input="x" * 6000,
        context_scope=["macro"],
        context_params={"asset": "000001.SZ"},
        tool_names=["market.lookup"],
        session_id="session-1",
    )
    response = AgentExecutionResponse(
        success=True,
        final_answer="y" * 6000,
        structured_output={"signal": "BUY"},
        used_context=["macro"],
        tool_calls=[
            ToolCallRecord(
                tool_name="market.lookup",
                arguments={"asset": "000001.SZ"},
                success=True,
                result={"price": 10},
                duration_ms=12,
            ),
            {
                "tool_name": "policy.current",
                "arguments": {},
                "success": False,
            },
            object(),
        ],
        turn_count=2,
        provider_used="provider",
        model_used="model",
        total_tokens=15,
        prompt_tokens=9,
        completion_tokens=6,
        estimated_cost=0.2,
        response_time_ms=25,
        execution_id="execution-1",
    )

    AgentExecutionLogger(repository).log_agent_execution(request, response)

    log = repository.create_log.call_args.args[0]
    assert log["execution_id"] == "execution-1"
    assert len(log["rendered_prompt"]) == 5003
    assert log["rendered_prompt"].endswith("...")
    assert len(log["ai_response"]) == 5003
    assert log["status"] == "success"
    assert log["placeholder_values"] == {
        "context_scope": ["macro"],
        "tool_names": ["market.lookup"],
        "context_params": {"asset": "000001.SZ"},
    }
    assert log["parsed_output"]["tool_calls"] == [
        {
            "tool_name": "market.lookup",
            "arguments": {"asset": "000001.SZ"},
            "success": True,
            "duration_ms": 12,
            "error": None,
        },
        {
            "tool_name": "policy.current",
            "arguments": {},
            "success": False,
        },
    ]


def test_failed_trace_tolerates_empty_values_and_repository_failure() -> None:
    repository = Mock()
    repository.create_log.side_effect = RuntimeError("audit database unavailable")
    request = AgentExecutionRequest(task_type="chat", user_input="")
    response = AgentExecutionResponse(
        success=False,
        final_answer=None,
        error_message="provider unavailable",
        execution_id="execution-2",
    )

    AgentExecutionLogger(repository).log_agent_execution(request, response)

    repository.create_log.assert_called_once()
    log = repository.create_log.call_args.args[0]
    assert log["rendered_prompt"] == ""
    assert log["ai_response"] == ""
    assert log["parsed_output"]["tool_calls"] == []
    assert log["status"] == "error"
    assert log["error_message"] == "provider unavailable"


def test_logger_without_repository_and_truncation_boundaries_are_safe() -> None:
    AgentExecutionLogger().log_agent_execution(
        AgentExecutionRequest(task_type="chat", user_input="hello"),
        AgentExecutionResponse(success=True, final_answer="world"),
    )

    assert _truncate(None, 5) is None
    assert _truncate("", 5) == ""
    assert _truncate("short", 5) == "short"
    assert _truncate("longer", 4) == "long..."
