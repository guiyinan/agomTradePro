"""Prompt configuration and append-only evidence boundary regressions."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from django.core.exceptions import ValidationError

from apps.prompt.application.trace_logging import AgentExecutionLogger
from apps.prompt.domain.agent_entities import (
    AgentExecutionRequest,
    AgentExecutionResponse,
    ToolCallRecord,
)
from apps.prompt.infrastructure.models import (
    ChainConfigORM,
    ChatSessionORM,
    PromptExecutionLogORM,
    PromptTemplateORM,
)
from apps.prompt.infrastructure.repositories import DjangoExecutionLogRepository


def _template_values() -> dict[str, Any]:
    return {
        "name": "governed-template",
        "category": "analysis",
        "template_content": "Analyze {{ asset_code }} using governed facts.",
        "placeholders": [
            {
                "name": "asset_code",
                "type": "simple",
                "description": "Target asset",
                "required": True,
            }
        ],
        "temperature": 0.3,
        "max_tokens": 1_000,
    }


def _chain_step(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "step_id": "step-1",
        "template_id": "1",
        "step_name": "Analyze",
        "order": 1,
        "input_mapping": {"asset_code": "request.asset_code"},
        "enable_tool_calling": False,
        "available_tools": [],
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
@pytest.mark.parametrize(
    "override",
    [
        {"temperature": True},
        {"temperature": float("nan")},
        {"temperature": float("inf")},
        {"max_tokens": True},
        {"max_tokens": 200_001},
    ],
)
def test_template_orm_create_rejects_invalid_sampling_policy(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PromptTemplateORM._default_manager.create(**(_template_values() | override))

    assert not PromptTemplateORM._default_manager.exists()


@pytest.mark.django_db
def test_template_orm_rejects_duplicate_or_nonfinite_placeholders() -> None:
    values = _template_values()
    values["placeholders"] = [
        {"name": "asset_code", "type": "simple"},
        {"name": "asset_code", "type": "simple", "default_value": float("nan")},
    ]

    with pytest.raises(ValidationError, match="finite JSON|unique"):
        PromptTemplateORM._default_manager.create(**values)


@pytest.mark.django_db
def test_chain_orm_rejects_empty_active_chain_and_conflicting_orders() -> None:
    with pytest.raises(ValidationError, match="active chains require"):
        ChainConfigORM._default_manager.create(
            name="empty-chain",
            category="analysis",
            steps=[],
            execution_mode="serial",
            is_active=True,
        )

    with pytest.raises(ValidationError, match="shared parallel_group"):
        ChainConfigORM._default_manager.create(
            name="conflicting-chain",
            category="analysis",
            steps=[
                _chain_step(parallel_group="group-a"),
                _chain_step(step_id="step-2", parallel_group="group-b"),
            ],
            execution_mode="parallel",
            is_active=True,
        )


@pytest.mark.django_db
def test_execution_evidence_is_redacted_and_append_only() -> None:
    evidence = PromptExecutionLogORM._default_manager.create(
        execution_id="exec-1",
        placeholder_values={
            "api_key": "top-secret",
            "nested": {"password": "database-secret"},
        },
        rendered_prompt="connect postgresql://user:pass@db.internal/prompt token=abc",
        ai_response="authorization=Bearer-secret",
        parsed_output={"credential": "private-value"},
        response_time_ms=5,
        prompt_tokens=2,
        completion_tokens=3,
        total_tokens=5,
        estimated_cost="0.01",
        status="error",
        error_message="postgresql://user:pass@db.internal/root-cause",
    )

    assert evidence.placeholder_values == {
        "api_key": "***",
        "nested": {"password": "***"},
    }
    assert evidence.parsed_output == {"credential": "***"}
    assert "pass@db.internal" not in evidence.rendered_prompt
    assert "token=abc" not in evidence.rendered_prompt
    assert "Bearer-secret" not in evidence.ai_response
    assert evidence.error_message == "prompt_execution_failed"

    evidence.ai_response = "changed"
    with pytest.raises(ValidationError, match="immutable"):
        evidence.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        evidence.delete()


@pytest.mark.django_db
def test_chat_evidence_is_redacted_and_append_only() -> None:
    session = ChatSessionORM._default_manager.create(
        session_id="session-1",
        user_message="password=hunter2",
        ai_response="redis://user:secret@cache.internal/0",
        context={"authorization": "Bearer private"},
    )

    assert "hunter2" not in session.user_message
    assert "secret@cache.internal" not in session.ai_response
    assert session.context == {"authorization": "***"}
    with pytest.raises(ValidationError, match="immutable"):
        session.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        session.delete()


@pytest.mark.django_db
def test_execution_repository_converts_invalid_evidence_to_stable_failure() -> None:
    with pytest.raises(RuntimeError, match="prompt_execution_log_write_failed") as exc_info:
        DjangoExecutionLogRepository().create_log(
            {
                "execution_id": "exec-invalid",
                "placeholder_values": {},
                "rendered_prompt": "",
                "ai_response": "",
                "response_time_ms": 1,
                "prompt_tokens": 2,
                "completion_tokens": 3,
                "total_tokens": 999,
                "estimated_cost": 0,
                "status": "error",
            }
        )

    assert "999" not in str(exc_info.value)


class _CapturingWriter:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    def create_log(self, log_data: dict[str, Any]) -> object:
        self.payload = log_data
        return object()


def test_agent_trace_logger_publishes_stable_error_without_secret_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    writer = _CapturingWriter()
    request = AgentExecutionRequest(
        task_type="analysis",
        user_input="postgresql://user:pass@db.internal/request",
    )
    response = AgentExecutionResponse(
        success=False,
        final_answer=None,
        tool_calls=[
            ToolCallRecord(
                tool_name="lookup",
                arguments={"api_key": "private"},
                success=False,
                result=None,
                error_message="token=private",
            )
        ],
        prompt_tokens=2,
        completion_tokens=3,
        total_tokens=5,
        response_time_ms=4,
        error_message="postgresql://user:pass@db.internal/provider",
        execution_id="exec-agent",
    )

    with caplog.at_level(logging.WARNING):
        AgentExecutionLogger(writer).log_agent_execution(request, response)

    assert writer.payload is not None
    assert writer.payload["error_message"] == "prompt_agent_execution_failed"
    assert "pass@db.internal" not in str(writer.payload)
    assert "private" not in str(writer.payload)
    assert "pass@db.internal" not in caplog.text
    assert "token=private" not in caplog.text
