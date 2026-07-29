"""Execution, response, and observability contracts for capability routing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.ai_capability.application import facade as facade_module
from apps.ai_capability.application.facade import CapabilityRoutingFacade
from apps.ai_capability.domain.entities import (
    CapabilityDecision,
    CapabilityDefinition,
    RoutingContext,
    RoutingDecision,
    SourceType,
)


def _context(**overrides: object) -> RoutingContext:
    values: dict[str, object] = {
        "entrypoint": "terminal",
        "session_id": "session-1",
        "user_id": 7,
        "user_is_admin": False,
        "mcp_enabled": True,
        "provider_name": "provider",
        "model": "model",
        "context": {},
        "answer_chain_enabled": True,
    }
    values.update(overrides)
    return RoutingContext(**values)  # type: ignore[arg-type]


def _capability(
    source_type: SourceType = SourceType.BUILTIN,
    *,
    handler: str = "system_status",
) -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_key="system.status",
        source_type=source_type,
        source_ref="status",
        name="System status",
        summary="Show readiness",
        execution_target={"handler": handler},
    )


def _facade() -> CapabilityRoutingFacade:
    return CapabilityRoutingFacade(
        capability_repo=MagicMock(),
        routing_log_repo=MagicMock(),
    )


def test_decision_builders_cover_capability_suggestion_and_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facade = _facade()
    context = _context(user_is_admin=True)
    capability = _capability()
    candidates = [{"capability_key": capability.capability_key}]
    monkeypatch.setattr(facade, "_execute_capability", lambda *_args: {"reply": "ready"})

    selected = facade._build_capability_decision(capability, candidates, 0.9, "status", context)
    assert selected.decision == CapabilityDecision.CAPABILITY
    assert selected.reply == "ready"
    assert selected.answer_chain["visibility"] == "technical"

    suggestion = facade._build_suggestion_decision(capability, candidates, 0.7, "status", context)
    assert suggestion.decision == CapabilityDecision.ASK_CONFIRMATION
    assert suggestion.requires_confirmation is True

    monkeypatch.setattr(facade, "_execute_chat", lambda *_args: "chat reply")
    chat = facade._build_chat_decision(candidates, "hello", context)
    assert chat.decision == CapabilityDecision.CHAT
    assert chat.reply == "chat reply"


@pytest.mark.parametrize(
    ("source_type", "expected"),
    [
        (SourceType.TERMINAL_COMMAND, "Terminal command execution"),
        (SourceType.MCP_TOOL, "MCP tool execution"),
        (SourceType.API, "API execution"),
    ],
)
def test_execute_capability_dispatches_non_builtin_sources(
    source_type: SourceType,
    expected: str,
) -> None:
    result = _facade()._execute_capability(_capability(source_type), "run", _context())
    assert expected in result["reply"]


def test_execute_capability_dispatches_builtin_and_unknown_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facade = _facade()
    monkeypatch.setattr(facade, "_execute_system_status", lambda: {"reply": "ok"})
    monkeypatch.setattr(facade, "_execute_market_regime", lambda: {"reply": "regime"})
    assert facade._execute_builtin(_capability()) == {"reply": "ok"}
    assert facade._execute_builtin(_capability(handler="market_regime")) == {"reply": "regime"}
    assert "Unknown builtin" in facade._execute_builtin(_capability(handler="missing"))["reply"]
    unknown = SimpleNamespace(source_type="other")
    assert "Unknown capability" in facade._execute_capability(unknown, "run", _context())["reply"]


def test_system_status_formats_health_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = {
        "database": {"status": "ok"},
        "redis": {"status": "error", "error": "down"},
        "celery": {"status": "ok", "workers": 2},
        "critical_data": {"status": "warning", "empty_tables": ["prices"]},
    }
    monkeypatch.setattr(facade_module, "run_readiness_checks", lambda: checks)
    monkeypatch.setattr(facade_module, "is_healthy", lambda _checks: False)
    reply = _facade()._execute_system_status()["reply"]
    assert "System Readiness: `error`" in reply
    assert "2 workers" in reply
    assert "empty: prices" in reply


def test_market_regime_formats_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        facade_module,
        "resolve_current_regime",
        lambda: SimpleNamespace(
            dominant_regime="Recovery",
            confidence=0.85,
            source="test",
            observed_at="2026-07-24",
        ),
    )
    monkeypatch.setattr(
        facade_module,
        "get_current_policy_repository",
        lambda: SimpleNamespace(get_current_policy_level=lambda: SimpleNamespace(value="neutral")),
    )
    reply = _facade()._execute_market_regime()["reply"]
    assert "Recovery" in reply
    assert "85.0%" in reply
    assert "neutral" in reply


def test_chat_execution_handles_success_provider_error_and_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facade = _facade()
    client = MagicMock()
    factory = SimpleNamespace(get_client=lambda *_args, **_kwargs: client)
    monkeypatch.setattr(facade_module, "get_ai_client_factory", lambda: factory)
    context = _context(context={"history": [{"role": "system", "content": "x"}]})

    client.chat_completion.return_value = {"status": "success", "content": "answer"}
    assert facade._execute_chat("question", context) == "answer"
    client.chat_completion.return_value = {
        "status": "failed",
        "error_message": "quota",
    }
    assert facade._execute_chat("question", context) == "AI 调用失败: quota"
    client.chat_completion.side_effect = RuntimeError("offline")
    assert "offline" in facade._execute_chat("question", context)


def test_logging_and_response_contracts_handle_failures_and_suggestions() -> None:
    facade = _facade()
    context = _context()
    decision = RoutingDecision(
        decision=CapabilityDecision.ASK_CONFIRMATION,
        selected_capability_key="account.refresh",
        confidence=0.7,
        candidate_capabilities=[{"capability_key": "account.refresh"}],
        requires_confirmation=True,
        reply="confirm",
        metadata={"route": "intent_suggestion"},
        answer_chain={"steps": []},
    )
    response = facade._build_response(decision, "session-1", context)
    assert response["suggested_command"] == "/refresh"
    assert response["suggested_intent"] == "account"
    assert response["answer_chain"] == {"steps": []}

    facade.routing_log_repo.save.side_effect = RuntimeError("audit unavailable")
    facade._log_routing(context, "refresh", [], decision)
    facade.routing_log_repo.save.assert_called_once()

    chat_response = facade._build_response(
        RoutingDecision(decision=CapabilityDecision.CHAT, reply="hello"),
        "session-2",
        _context(answer_chain_enabled=False),
    )
    assert chat_response["suggested_command"] is None
    assert chat_response["answer_chain"] == {}


def test_no_candidate_handler_delegates_logging_and_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facade = _facade()
    context = _context()
    decision = RoutingDecision(decision=CapabilityDecision.CHAT, reply="fallback")
    monkeypatch.setattr(facade, "_build_chat_decision", lambda *_args: decision)
    log = MagicMock()
    monkeypatch.setattr(facade, "_log_routing", log)
    monkeypatch.setattr(facade, "_build_response", lambda *_args: {"decision": "chat"})
    assert facade._handle_no_candidates("hello", "session-1", context) == {"decision": "chat"}
    log.assert_called_once()
