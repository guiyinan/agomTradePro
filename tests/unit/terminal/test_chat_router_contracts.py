"""Behavior contracts for the terminal natural-language router."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.terminal.application.chat_router import (
    TerminalChatRouterService,
    TerminalIntentDecision,
)


def _factory_for(*responses: dict[str, object]) -> tuple[Mock, Mock]:
    client = Mock()
    client.chat_completion.side_effect = list(responses)
    factory = Mock()
    factory.get_client.return_value = client
    return factory, client


def _classification(intent: str, confidence: float) -> dict[str, object]:
    return {
        "status": "success",
        "content": (
            '{"intent": "'
            + intent
            + '", "confidence": '
            + str(confidence)
            + ', "reason": "contract"}'
        ),
    }


def test_high_confidence_system_status_returns_builtin_readiness_without_chat() -> None:
    factory, client = _factory_for(_classification("system_status", 0.95))
    checks = {
        "database": {"status": "ok"},
        "redis": {"status": "error", "error": "unavailable"},
        "celery": {"status": "ok", "workers": 2},
        "critical_data": {"status": "warning", "empty_tables": ["macro_fact"]},
    }

    with (
        patch(
            "apps.terminal.application.chat_router.get_ai_client_factory",
            return_value=factory,
        ),
        patch(
            "apps.terminal.application.chat_router.run_readiness_checks",
            return_value=checks,
        ),
        patch("apps.terminal.application.chat_router.is_healthy", return_value=False),
    ):
        result = TerminalChatRouterService().route_message(
            message="系统现在健康吗",
            session_id=None,
            provider_ref="primary",
            model="router",
            answer_chain_enabled=True,
            user_is_admin=True,
            user=SimpleNamespace(id=7),
        )

    assert result["metadata"]["route"] == "system_status"
    assert result["metadata"]["answer_chain"]["visibility"] == "technical"
    assert "System Readiness: `error`" in result["reply"]
    assert "unavailable" in result["reply"]
    assert "2 workers" in result["reply"]
    assert "empty: macro_fact" in result["reply"]
    assert result["route_confirmation_required"] is False
    factory.get_client.assert_called_once()
    assert client.chat_completion.call_count == 1


def test_high_confidence_regime_route_masks_technical_chain_for_normal_user() -> None:
    factory, _client = _factory_for(_classification("market_regime", 0.92))
    regime = SimpleNamespace(
        dominant_regime="ME",
        confidence=0.78,
        source="unit",
        observed_at="2026-07-25T00:00:00+00:00",
    )
    policy = SimpleNamespace(value="TIGHT")
    repository = Mock()
    repository.get_current_policy_level.return_value = policy

    with (
        patch(
            "apps.terminal.application.chat_router.get_ai_client_factory",
            return_value=factory,
        ),
        patch(
            "apps.terminal.application.chat_router.resolve_current_regime",
            return_value=regime,
        ),
        patch(
            "apps.terminal.application.chat_router.get_current_policy_repository",
            return_value=repository,
        ),
    ):
        result = TerminalChatRouterService().route_message(
            message="当前市场环境",
            session_id="session-1",
            provider_ref=None,
            model=None,
            answer_chain_enabled=True,
        )

    assert result["session_id"] == "session-1"
    assert result["metadata"]["route"] == "market_regime"
    assert result["metadata"]["answer_chain"]["visibility"] == "masked"
    assert "ME" in result["reply"]
    assert "78.0%" in result["reply"]
    assert "TIGHT" in result["reply"]
    assert all(
        "technical_details" not in step for step in result["metadata"]["answer_chain"]["steps"]
    )


@pytest.mark.parametrize(
    ("intent", "expected_command", "expected_label"),
    [
        ("system_status", "/status", "系统状态"),
        ("market_regime", "/regime", "市场 regime"),
    ],
)
def test_medium_confidence_intent_requires_confirmation(
    intent: str,
    expected_command: str,
    expected_label: str,
) -> None:
    factory, client = _factory_for(_classification(intent, 0.70))

    with patch(
        "apps.terminal.application.chat_router.get_ai_client_factory",
        return_value=factory,
    ):
        result = TerminalChatRouterService().route_message(
            message="maybe",
            session_id="session",
            provider_ref=None,
            model=None,
            answer_chain_enabled=True,
        )

    assert result["route_confirmation_required"] is True
    assert result["suggested_command"] == expected_command
    assert expected_label in result["reply"]
    assert result["metadata"]["answer_chain"]["visibility"] == "masked"
    assert client.chat_completion.call_count == 1


def test_chat_route_preserves_history_and_exposes_admin_answer_chain() -> None:
    factory, client = _factory_for(
        {
            "status": "success",
            "content": ("```json\n" '{"intent":"chat","confidence":2.5,"reason":"normal"}' "\n```"),
        },
        {
            "status": "success",
            "content": "answer",
            "provider_used": "openai",
            "model": "gpt-test",
            "total_tokens": 9,
        },
    )
    history: list[dict[str, str]] = [{"role": "assistant", "content": "before"}]

    with patch(
        "apps.terminal.application.chat_router.get_ai_client_factory",
        return_value=factory,
    ):
        result = TerminalChatRouterService().route_message(
            message="hello",
            session_id="chat-session",
            provider_ref="openai",
            model="gpt-test",
            context={"history": history},
            answer_chain_enabled=True,
            user_is_admin=True,
        )

    assert result["reply"] == "answer"
    assert result["metadata"] == {
        "provider": "openai",
        "model": "gpt-test",
        "tokens": 9,
        "route": "chat",
        "intent": "chat",
        "intent_confidence": 1.0,
        "answer_chain": {
            "label": "Answer chain",
            "visibility": "technical",
            "steps": [
                {
                    "title": "Intent classification",
                    "summary": "Classified the input as general chat with confidence 1.00.",
                    "source": "AI intent router",
                },
                {
                    "title": "Model response",
                    "summary": (
                        "Sent the request to the selected AI provider and returned "
                        "the generated answer."
                    ),
                    "source": "openai",
                    "technical_details": [
                        "provider=openai",
                        "model=gpt-test",
                    ],
                },
            ],
        },
    }
    assert history[-1] == {"role": "user", "content": "hello"}
    assert client.chat_completion.call_count == 2


@pytest.mark.parametrize(
    "classifier_response",
    [
        {"status": "error", "error_message": "offline"},
        {"status": "success", "content": "not-json"},
        {"status": "success", "content": "[1, 2]"},
        {"status": "success", "content": '{"intent":"delete","confidence":1}'},
    ],
)
def test_invalid_classifier_output_falls_back_to_chat(
    classifier_response: dict[str, object],
) -> None:
    factory, _client = _factory_for(
        classifier_response,
        {
            "status": "success",
            "content": "fallback",
            "provider_used": "",
            "model": "",
        },
    )

    with patch(
        "apps.terminal.application.chat_router.get_ai_client_factory",
        return_value=factory,
    ):
        result = TerminalChatRouterService().route_message(
            message="ambiguous",
            session_id="session",
            provider_ref=None,
            model=None,
        )

    assert result["metadata"]["route"] == "chat"
    assert result["metadata"]["intent"] == "chat"
    assert "answer_chain" not in result["metadata"]


def test_classifier_exception_falls_back_but_chat_failure_is_not_hidden() -> None:
    client = Mock()
    client.chat_completion.side_effect = [
        RuntimeError("classifier unavailable"),
        {"status": "error", "error_message": "chat unavailable"},
    ]
    factory = Mock()
    factory.get_client.return_value = client

    with (
        patch(
            "apps.terminal.application.chat_router.get_ai_client_factory",
            return_value=factory,
        ),
        pytest.raises(RuntimeError, match="chat unavailable"),
    ):
        TerminalChatRouterService().route_message(
            message="hello",
            session_id=None,
            provider_ref=None,
            model=None,
        )


def test_extract_json_and_chain_helpers_cover_empty_and_missing_details() -> None:
    service = TerminalChatRouterService()

    assert service._extract_json_object("") == {}
    assert service._extract_json_object('prefix {"intent": "chat"} suffix') == {"intent": "chat"}
    assert service._metadata_answer_chain(True, None) == {}
    assert service._metadata_answer_chain(False, {"steps": []}) == {}

    regime_chain = service._build_regime_chain(
        TerminalIntentDecision("market_regime", 0.9),
        SimpleNamespace(),
        SimpleNamespace(),
        True,
    )
    assert regime_chain["visibility"] == "technical"
    assert "RegimeSnapshot.dominant_regime=Unknown" in regime_chain["steps"][1]["technical_details"]
