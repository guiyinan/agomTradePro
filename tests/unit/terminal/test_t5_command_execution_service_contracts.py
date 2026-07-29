"""Command execution and formatting contracts for Terminal services."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.http import HttpResponse
from django.urls import Resolver404

from apps.terminal.application import services as service_module
from apps.terminal.application.repository_provider import TerminalApiRequestError
from apps.terminal.application.services import (
    AnswerChainSettingsService,
    ChatScopeSettingsService,
    CommandExecutionService,
)
from apps.terminal.domain.entities import CommandType, TerminalCommand
from apps.terminal.domain.exceptions import TerminalCommandExecutionError


def _command(
    *,
    name: str = "test",
    endpoint: str | None = "https://example.test/api/{code}",
    jq_filter: str | None = None,
    command_type: CommandType = CommandType.API,
) -> TerminalCommand:
    return TerminalCommand(
        id="cmd-1",
        name=name,
        description="test",
        command_type=command_type,
        api_endpoint=endpoint,
        response_jq_filter=jq_filter,
        user_prompt_template="Analyse {asset}",
        system_prompt="system",
    )


def test_lazy_ai_factory_and_runtime_are_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = object()
    runtime = object()
    get_factory = MagicMock(return_value=factory)
    build_runtime = MagicMock(return_value=runtime)
    monkeypatch.setattr(service_module, "get_ai_client_factory", get_factory)
    monkeypatch.setattr(service_module, "build_terminal_agent_runtime", build_runtime)
    service = CommandExecutionService()

    assert service.ai_client_factory is factory
    assert service.ai_client_factory is factory
    assert service._get_agent_runtime() is runtime
    assert service._get_agent_runtime() is runtime
    get_factory.assert_called_once()
    build_runtime.assert_called_once_with(factory)


def test_prompt_command_formats_request_response_and_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        execute=lambda request: SimpleNamespace(
            success=True,
            final_answer="answer",
            error_message=None,
            tool_calls=[SimpleNamespace(tool_name="get_regime_status")],
            used_context=["regime"],
            turn_count=2,
            provider_used="provider",
            model_used="model",
            total_tokens=42,
            execution_id="exec-1",
        )
    )
    service = CommandExecutionService()
    monkeypatch.setattr(service, "_get_agent_runtime", lambda: runtime)

    result = service.execute_prompt_command(
        _command(command_type=CommandType.PROMPT),
        {"asset": "600000.SH"},
        session_id="session-1",
    )

    assert result["output"] == "answer"
    assert result["metadata"]["trace"] == {
        "tools_used": ["get_regime_status"],
        "context_domains": ["regime"],
        "turn_count": 2,
    }
    assert result["metadata"]["provider"] == "provider"


def test_external_api_command_replaces_path_and_keeps_query_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.request_json.return_value = (200, {"data": {"value": 3}})
    monkeypatch.setattr(service_module, "get_terminal_command_http_client", lambda: client)
    service = CommandExecutionService()
    command = _command(jq_filter=".data.value")

    result = service.execute_api_command(command, {"code": "600000", "limit": 5})

    client.request_json.assert_called_once_with(
        method="GET",
        url="https://example.test/api/600000",
        params={"limit": 5},
        timeout=60,
    )
    assert result["output"] == "3"
    assert result["metadata"]["structured_output"] == {"data": {"value": 3}}


def test_external_api_command_maps_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.request_json.side_effect = TerminalApiRequestError("offline")
    monkeypatch.setattr(service_module, "get_terminal_command_http_client", lambda: client)

    with pytest.raises(
        TerminalCommandExecutionError,
        match="terminal_external_api_failed",
    ):
        CommandExecutionService().execute_api_command(_command(), {"code": "x"})


def test_internal_api_command_maps_missing_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service_module,
        "resolve",
        lambda _url: (_ for _ in ()).throw(Resolver404()),
    )
    monkeypatch.setattr(
        service_module,
        "get_terminal_auth_user",
        lambda _id: SimpleNamespace(id=7),
    )
    with pytest.raises(
        TerminalCommandExecutionError,
        match="terminal_internal_api_not_found",
    ):
        CommandExecutionService().execute_api_command(
            _command(endpoint="/api/missing"),
            {},
            user_id=7,
        )


def test_internal_api_command_dispatches_authenticated_drf_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = SimpleNamespace(
        data={"ok": True},
        status_code=201,
        render=MagicMock(),
    )
    match = SimpleNamespace(
        func=lambda request, **kwargs: response,
        kwargs={"item_id": "1"},
    )
    monkeypatch.setattr(service_module, "resolve", lambda _url: match)
    monkeypatch.setattr(
        service_module,
        "get_terminal_auth_user",
        lambda _id: SimpleNamespace(id=7),
    )
    authenticate = MagicMock()
    monkeypatch.setattr(service_module, "force_authenticate", authenticate)

    result = CommandExecutionService().execute_api_command(
        _command(endpoint="/api/items/1"),
        {"verbose": True},
        user_id=7,
    )
    assert result["metadata"]["internal_dispatch"] is True
    assert result["metadata"]["status_code"] == 201
    assert '"ok": true' in result["output"]
    authenticate.assert_called_once()
    response.render.assert_called_once()


def test_internal_api_command_decodes_plain_http_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = HttpResponse("plain", status=202)
    monkeypatch.setattr(
        service_module,
        "resolve",
        lambda _url: SimpleNamespace(func=lambda request: response, kwargs={}),
    )
    monkeypatch.setattr(
        service_module,
        "get_terminal_auth_user",
        lambda _id: SimpleNamespace(id=7),
    )
    result = CommandExecutionService().execute_api_command(
        _command(endpoint="/api/plain"),
        {},
        user_id=7,
    )
    assert result["output"] == "plain"
    assert result["metadata"]["status_code"] == 202


def test_output_filter_formats_special_commands_and_raw_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CommandExecutionService()
    market = service._filter_and_format_api_output(
        command=_command(name="market_temperature"),
        data={
            "score": 80,
            "effective_band": "hot",
            "threshold_source": "user_override",
            "trigger_reasons": ["volume", "momentum"],
            "must_not_use_for_decision": True,
            "blocked_reason": "stale",
        },
    )
    assert "市场温度分数: 80.0" in market
    assert "个人阈值" in market
    assert "避免追高: 是" in market
    assert "数据完整性提示" in market

    monkeypatch.setattr(
        service,
        "_apply_jq_filter",
        lambda _data, _filter: (_ for _ in ()).throw(ValueError("bad filter")),
    )
    with pytest.raises(
        TerminalCommandExecutionError,
        match="terminal_output_filter_failed",
    ):
        service._filter_and_format_api_output(
            command=_command(jq_filter=".bad"),
            data={"x": 1},
            params={"verbose": True},
        )
    assert service._filter_and_format_api_output(command=_command(), data="text") == "text"


def test_advisor_today_formatter_covers_orders_blockers_and_actions() -> None:
    payload = {
        "success": True,
        "data": {
            "account": {
                "account_name": "模拟账户",
                "account_type_label": "模拟",
                "total_asset": 100,
                "available_cash": 20,
                "holding_count": 1,
            },
            "baseline": "v1",
            "today_conclusion": "hold",
            "risk_policy": {"version": "r1"},
            "data_health": {"status": "healthy"},
            "execution_plan": {
                "execution_mode": "manual",
                "confirmation_status": "required",
                "broker_execution_enabled": False,
            },
            "order_summary": {"total": 1, "buy": 1},
            "order_intents": [
                {
                    "side": "BUY",
                    "asset_code": "600000.SH",
                    "asset_name": "浦发银行",
                    "delta_quantity": 100,
                    "estimated_amount": 1000,
                    "price_band": {"label": "10-11"},
                    "blocking_status": "clear",
                    "risk_gate_status": "passed",
                    "data_asof": {"quote_freshness_status": "fresh"},
                    "confirmation": {"status": "required"},
                }
            ],
            "blockers": [{"asset_code": "X", "type": "risk", "message": "blocked"}],
            "next_actions": [{"label": "确认", "hint": "/confirm"}],
        },
    }
    output = CommandExecutionService._format_advisor_today_output(payload)
    assert "前 5 条订单意图:" in output
    assert "BUY 600000.SH" in output
    assert "阻断项:" in output
    assert "下一步命令:" in output
    assert (
        CommandExecutionService._format_advisor_today_output({"success": True, "data": "bad"})
        == '{\n  "success": true,\n  "data": "bad"\n}'
    )


def test_advisor_query_formatter_covers_dict_text_and_evidence() -> None:
    payload = {
        "success": True,
        "data": {
            "account": {"account_id": 1},
            "query": {"question": "why", "intent": "explain"},
            "answer": "because",
            "highlights": [
                {"asset_code": "600000.SH", "message": "signal"},
                "plain evidence",
            ],
            "evidence": {"regime": "Recovery", "policy": "P1"},
        },
    }
    output = CommandExecutionService._format_advisor_query_output(payload)
    assert "回答: because" in output
    assert "600000.SH: signal" in output
    assert "plain evidence" in output
    assert "证据字段:" in output
    assert '"data": []' in CommandExecutionService._format_advisor_query_output(
        {"success": True, "data": []}
    )


def test_jq_filter_supports_keys_indexes_and_invalid_paths() -> None:
    service = CommandExecutionService()
    data = {"items": [{"value": 3}], "nested": {"values": [1, 2]}}
    with pytest.raises(ValueError, match="invalid terminal output filter"):
        service._apply_jq_filter(data, "items")
    assert service._apply_jq_filter(data, ".items[0].value") == 3
    assert service._apply_jq_filter(data["nested"]["values"], ".1") == 2
    with pytest.raises(ValueError, match="invalid terminal output filter path"):
        service._apply_jq_filter(data, ".missing.value")


def test_runtime_settings_services_apply_visibility_and_prompt_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SimpleNamespace(
        get_settings=lambda: {
            "answer_chain_enabled": True,
            "fallback_chat_system_prompt": " custom prompt ",
        }
    )
    monkeypatch.setattr(
        service_module,
        "get_terminal_runtime_settings_repository",
        lambda: repository,
    )
    assert AnswerChainSettingsService.get_config(
        SimpleNamespace(is_staff=True, is_superuser=False)
    ) == {"enabled": True, "visibility": "technical", "is_admin": True}
    assert AnswerChainSettingsService.get_config(None)["visibility"] == "masked"
    assert ChatScopeSettingsService.get_fallback_chat_system_prompt() == "custom prompt"

    repository.get_settings = lambda: {
        "answer_chain_enabled": False,
        "fallback_chat_system_prompt": " ",
    }
    assert (
        ChatScopeSettingsService.get_fallback_chat_system_prompt()
        == ChatScopeSettingsService.DEFAULT_FALLBACK_CHAT_SYSTEM_PROMPT
    )
