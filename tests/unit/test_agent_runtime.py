"""
Agent Runtime 单元测试。

覆盖：
- Runtime 无工具调用时直接返回答案
- Runtime 单工具调用闭环
- Runtime 多工具调用闭环
- 工具异常时的错误记录和继续策略
- Context provider summary/raw_data 构建
- AI provider tool call 提取
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.prompt.application.agent_runtime import AgentRuntime
from apps.prompt.application.context_builders import (
    AssetPoolContextProvider,
    ContextBundleBuilder,
    MacroContextProvider,
    PortfolioContextProvider,
    RegimeContextProvider,
    SignalContextProvider,
)
from apps.prompt.application.tool_execution import create_agent_tool_registry
from apps.prompt.application.use_cases import ExecuteChainUseCase
from apps.prompt.domain.agent_entities import (
    AgentExecutionRequest,
    AgentExecutionResponse,
    ToolCallRecord,
)
from apps.prompt.domain.context_entities import ContextBundle, ContextSection
from apps.prompt.infrastructure.adapters.function_registry import (
    FunctionRegistry,
    ToolDefinition,
)

# ========== Fixtures ==========


def _mock_ai_client(responses):
    """Create a mock AI client that returns a sequence of responses."""
    client = MagicMock()
    client.chat_completion = MagicMock(side_effect=responses)
    return client


def _mock_ai_factory(client):
    factory = MagicMock()
    factory.get_client.return_value = client
    return factory


def _success_response(content="Hello", tool_calls=None, finish_reason="stop"):
    result = {
        "status": "success",
        "content": content,
        "model": "test-model",
        "provider_used": "test-provider",
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "total_tokens": 30,
        "finish_reason": finish_reason,
        "tool_calls": tool_calls,
    }
    return result


def _tool_call_response(tool_name, arguments, call_id="call_1"):
    return _success_response(
        content="",
        tool_calls=[{
            "id": call_id,
            "tool_name": tool_name,
            "arguments": json.dumps(arguments),
        }],
        finish_reason="tool_calls",
    )


def _error_response(error_msg="Provider error"):
    return {
        "status": "error",
        "content": None,
        "model": "test-model",
        "provider_used": "test-provider",
        "prompt_tokens": 5,
        "completion_tokens": 0,
        "total_tokens": 5,
        "finish_reason": None,
        "error_message": error_msg,
        "tool_calls": None,
    }


def _build_registry_with_tools():
    """Build a registry with test tools."""
    registry = FunctionRegistry()
    registry.register(ToolDefinition(
        name="get_test_data",
        description="Get test data",
        parameters={
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
        function=lambda key="default": {"value": f"data_for_{key}"},
    ))
    registry.register(ToolDefinition(
        name="get_failing_data",
        description="A tool that always fails",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        function=lambda: (_ for _ in ()).throw(RuntimeError("tool error")),
    ))
    return registry


# ========== Tests: No tool calls ==========


class TestAgentRuntimeNoTools:
    """Runtime 无工具调用时直接返回答案。"""

    def test_direct_answer(self):
        """模型直接返回文本答案。"""
        client = _mock_ai_client([_success_response("宏观环境稳定")])
        factory = _mock_ai_factory(client)

        runtime = AgentRuntime(ai_client_factory=factory)
        request = AgentExecutionRequest(
            task_type="chat",
            user_input="当前宏观环境如何？",
        )

        response = runtime.execute(request)

        assert response.success is True
        assert response.final_answer == "宏观环境稳定"
        assert response.turn_count == 1
        assert response.total_tokens == 30
        assert response.tool_calls is None
        assert response.execution_id is not None

    def test_with_system_prompt(self):
        """带 system prompt 时正确构建 messages。"""
        client = _mock_ai_client([_success_response("OK")])
        factory = _mock_ai_factory(client)

        runtime = AgentRuntime(ai_client_factory=factory)
        request = AgentExecutionRequest(
            task_type="chat",
            user_input="hello",
            system_prompt="你是投资顾问",
        )

        response = runtime.execute(request)
        assert response.success is True

        # 验证 messages 包含 system prompt
        call_kwargs = client.chat_completion.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages") or call_kwargs[0][0]
        assert any(m.get("role") == "system" for m in messages)

    def test_provider_error(self):
        """AI provider 错误时返回失败。"""
        client = _mock_ai_client([_error_response()])
        factory = _mock_ai_factory(client)

        runtime = AgentRuntime(ai_client_factory=factory)
        request = AgentExecutionRequest(
            task_type="chat",
            user_input="test",
        )

        response = runtime.execute(request)
        assert response.success is False
        assert "Provider error" in response.error_message


# ========== Tests: Single tool call ==========


class TestAgentRuntimeSingleToolCall:
    """Runtime 单工具调用闭环。"""

    def test_single_tool_call_and_final_answer(self):
        """一次工具调用 + 一次最终回答。"""
        responses = [
            _tool_call_response("get_test_data", {"key": "macro"}),
            _success_response("基于查询结果：宏观数据正常"),
        ]
        client = _mock_ai_client(responses)
        factory = _mock_ai_factory(client)
        registry = _build_registry_with_tools()

        runtime = AgentRuntime(
            ai_client_factory=factory,
            tool_registry=registry,
        )
        request = AgentExecutionRequest(
            task_type="chat",
            user_input="查询宏观数据",
            tool_names=["get_test_data"],
        )

        response = runtime.execute(request)

        assert response.success is True
        assert response.final_answer == "基于查询结果：宏观数据正常"
        assert response.turn_count == 2
        assert response.tool_calls is not None
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].tool_name == "get_test_data"
        assert response.tool_calls[0].success is True
        assert response.tool_calls[0].result == {"value": "data_for_macro"}

    def test_tool_not_found(self):
        """调用不存在的工具时记录错误。"""
        responses = [
            _tool_call_response("nonexistent_tool", {}),
            _success_response("无法获取数据"),
        ]
        client = _mock_ai_client(responses)
        factory = _mock_ai_factory(client)
        registry = FunctionRegistry()

        runtime = AgentRuntime(
            ai_client_factory=factory,
            tool_registry=registry,
        )
        request = AgentExecutionRequest(
            task_type="chat",
            user_input="test",
            tool_names=["nonexistent_tool"],
        )

        response = runtime.execute(request)
        assert response.success is True
        assert response.tool_calls is not None
        assert response.tool_calls[0].success is False
        assert "not found" in response.tool_calls[0].error_message


# ========== Tests: Multiple tool calls ==========


class TestAgentRuntimeMultipleToolCalls:
    """Runtime 多工具调用闭环。"""

    def test_two_tool_calls_then_answer(self):
        """两轮工具调用 + 最终回答。"""
        responses = [
            _tool_call_response("get_test_data", {"key": "macro"}, "call_1"),
            _tool_call_response("get_test_data", {"key": "regime"}, "call_2"),
            _success_response("综合分析：环境良好"),
        ]
        client = _mock_ai_client(responses)
        factory = _mock_ai_factory(client)
        registry = _build_registry_with_tools()

        runtime = AgentRuntime(
            ai_client_factory=factory,
            tool_registry=registry,
        )
        request = AgentExecutionRequest(
            task_type="analysis",
            user_input="综合分析",
            tool_names=["get_test_data"],
            max_rounds=5,
        )

        response = runtime.execute(request)

        assert response.success is True
        assert response.turn_count == 3
        assert len(response.tool_calls) == 2

    def test_max_rounds_reached(self):
        """达到最大轮次时终止。"""
        # 所有轮都返回工具调用
        responses = [
            _tool_call_response("get_test_data", {"key": f"round_{i}"}, f"call_{i}")
            for i in range(5)
        ]
        client = _mock_ai_client(responses)
        factory = _mock_ai_factory(client)
        registry = _build_registry_with_tools()

        runtime = AgentRuntime(
            ai_client_factory=factory,
            tool_registry=registry,
        )
        request = AgentExecutionRequest(
            task_type="chat",
            user_input="test",
            tool_names=["get_test_data"],
            max_rounds=3,
        )

        response = runtime.execute(request)
        assert response.turn_count == 3  # 最多执行 3 轮
        assert response.success is False  # 应标记为失败
        assert "Max rounds" in (response.error_message or "")
        assert response.final_answer is None


# ========== Tests: Tool error handling ==========


class TestAgentRuntimeToolErrors:
    """工具异常时的错误记录和继续策略。"""

    def test_tool_execution_error_recorded(self):
        """工具执行异常时记录错误但继续推理。"""
        responses = [
            _tool_call_response("get_failing_data", {}),
            _success_response("数据暂不可用"),
        ]
        client = _mock_ai_client(responses)
        factory = _mock_ai_factory(client)
        registry = _build_registry_with_tools()

        runtime = AgentRuntime(
            ai_client_factory=factory,
            tool_registry=registry,
        )
        request = AgentExecutionRequest(
            task_type="chat",
            user_input="test",
            tool_names=["get_failing_data"],
        )

        response = runtime.execute(request)

        assert response.success is True  # 最终仍然成功
        assert response.tool_calls is not None
        assert response.tool_calls[0].success is False
        assert "tool error" in response.tool_calls[0].error_message

    def test_invalid_json_arguments(self):
        """工具参数 JSON 无效时记录错误。"""
        responses = [
            _success_response(
                content="",
                tool_calls=[{
                    "id": "call_1",
                    "tool_name": "get_test_data",
                    "arguments": "not valid json{{{",
                }],
                finish_reason="tool_calls",
            ),
            _success_response("fallback answer"),
        ]
        client = _mock_ai_client(responses)
        factory = _mock_ai_factory(client)
        registry = _build_registry_with_tools()

        runtime = AgentRuntime(
            ai_client_factory=factory,
            tool_registry=registry,
        )
        request = AgentExecutionRequest(
            task_type="chat",
            user_input="test",
            tool_names=["get_test_data"],
        )

        response = runtime.execute(request)
        assert response.tool_calls[0].success is False
        assert "Invalid JSON" in response.tool_calls[0].error_message


# ========== Tests: Context Providers ==========


class TestContextProviders:
    """Context provider summary/raw_data 构建。"""

    def test_macro_context_provider(self):
        """MacroContextProvider 构建摘要和原始数据。"""
        mock_adapter = MagicMock()
        mock_adapter.get_macro_summary.return_value = {"PMI": 51.2, "CPI": 2.1}
        mock_adapter.get_all_indicators.return_value = {"PMI": {"value": 51.2}}

        provider = MacroContextProvider(mock_adapter)
        section = provider.build_section({})

        assert section.name == "macro"
        assert section.summary == {"PMI": 51.2, "CPI": 2.1}
        assert section.raw_data == {"PMI": {"value": 51.2}}

    def test_regime_context_provider(self):
        """RegimeContextProvider 构建摘要和原始数据。"""
        mock_adapter = MagicMock()
        mock_adapter.get_current_regime.return_value = {"quadrant": "MD", "confidence": 0.8}
        mock_adapter.get_regime_distribution.return_value = {"MD": 0.6, "MU": 0.2}

        provider = RegimeContextProvider(mock_adapter)
        section = provider.build_section({})

        assert section.name == "regime"
        assert section.summary["quadrant"] == "MD"

    def test_portfolio_context_provider(self):
        """PortfolioContextProvider 构建摘要。"""
        mock_provider = MagicMock()
        mock_provider.get_positions.return_value = [{"code": "000001", "weight": 0.1}]
        mock_provider.get_cash.return_value = 50000

        provider = PortfolioContextProvider(mock_provider)
        section = provider.build_section({"portfolio_id": 1})

        assert section.name == "portfolio"
        assert section.summary["position_count"] == 1
        assert section.summary["cash"] == 50000

    def test_context_bundle_builder(self):
        """ContextBundleBuilder 按 scope 构建。"""
        mock_macro = MagicMock()
        mock_macro.get_macro_summary.return_value = "PMI: 51"
        mock_macro.get_all_indicators.return_value = {}

        builder = ContextBundleBuilder()
        builder.register_provider(MacroContextProvider(mock_macro))

        bundle = builder.build(scope=["macro"])

        assert "macro" in bundle.sections
        assert bundle.sections["macro"].summary == "PMI: 51"

    def test_context_bundle_missing_provider(self):
        """scope 中的域无对应 provider 时记录降级信息。"""
        builder = ContextBundleBuilder()
        bundle = builder.build(scope=["macro", "nonexistent"])

        assert "nonexistent" in bundle.sections
        assert "不可用" in bundle.sections["nonexistent"].summary

    def test_context_bundle_summary_text(self):
        """ContextBundle 构建摘要文本。"""
        bundle = ContextBundle()
        bundle.add_section(ContextSection(
            name="macro",
            summary="PMI: 51.2, CPI: 2.1",
            raw_data={},
        ))
        bundle.add_section(ContextSection(
            name="regime",
            summary={"quadrant": "MD"},
            raw_data={},
        ))

        text = bundle.build_summary_text()
        assert "MACRO" in text
        assert "PMI: 51.2" in text
        assert "REGIME" in text
        assert "MD" in text


# ========== Tests: Structured output parsing ==========


class TestStructuredOutput:
    """结构化输出解析测试。"""

    def test_parse_json_output(self):
        """直接 JSON 输出。"""
        content = '{"signals": [{"asset_code": "000001", "direction": "buy"}]}'
        client = _mock_ai_client([_success_response(content)])
        factory = _mock_ai_factory(client)

        runtime = AgentRuntime(ai_client_factory=factory)
        request = AgentExecutionRequest(
            task_type="signal",
            user_input="生成信号",
            response_schema={"type": "json_object"},
        )

        response = runtime.execute(request)
        assert response.success is True
        assert response.structured_output is not None
        assert response.structured_output["signals"][0]["asset_code"] == "000001"

    def test_parse_json_code_block(self):
        """从 ```json``` 代码块中提取。"""
        content = '分析结果如下：\n\n```json\n{"result": "ok"}\n```'
        client = _mock_ai_client([_success_response(content)])
        factory = _mock_ai_factory(client)

        runtime = AgentRuntime(ai_client_factory=factory)
        request = AgentExecutionRequest(
            task_type="analysis",
            user_input="test",
            response_schema={"type": "json_object"},
        )

        response = runtime.execute(request)
        assert response.structured_output == {"result": "ok"}


# ========== Tests: AI Provider tool call extraction ==========


class TestAIProviderToolCallExtraction:
    """AI provider tool call 提取测试。"""

    def test_responses_api_tool_call_extraction(self):
        """Responses API 格式的 tool call 提取。"""
        from apps.ai_provider.infrastructure.adapters import OpenAICompatibleAdapter

        # 模拟 Responses API output
        mock_item = MagicMock()
        mock_item.type = "function_call"
        mock_item.call_id = "call_123"
        mock_item.name = "get_macro_summary"
        mock_item.arguments = '{"indicators": ["PMI"]}'

        mock_response = MagicMock()
        mock_response.output = [mock_item]

        result = OpenAICompatibleAdapter._extract_tool_calls_from_responses(mock_response)
        assert result is not None
        assert len(result) == 1
        assert result[0]["tool_name"] == "get_macro_summary"
        assert result[0]["id"] == "call_123"

    def test_responses_api_no_tool_calls(self):
        """Responses API 无 tool calls 时返回 None。"""
        from apps.ai_provider.infrastructure.adapters import OpenAICompatibleAdapter

        mock_item = MagicMock()
        mock_item.type = "message"

        mock_response = MagicMock()
        mock_response.output = [mock_item]

        result = OpenAICompatibleAdapter._extract_tool_calls_from_responses(mock_response)
        assert result is None


# ========== Tests: Function Registry ==========


class TestFunctionRegistry:
    """工具注册表测试。"""

    def test_register_and_execute(self):
        registry = FunctionRegistry()
        registry.register(ToolDefinition(
            name="add",
            description="Add two numbers",
            parameters={"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
            function=lambda a=0, b=0: a + b,
        ))

        assert "add" in registry.get_tool_names()
        result = registry.execute("add", {"a": 1, "b": 2})
        assert result == 3

    def test_openai_format(self):
        registry = FunctionRegistry()
        registry.register(ToolDefinition(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}},
            function=lambda: None,
        ))

        tools = registry.to_openai_format()
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "test_tool"

    def test_whitelist_filtering(self):
        """AgentRuntime 按白名单过滤工具。"""
        registry = FunctionRegistry()
        registry.register(ToolDefinition(
            name="allowed_tool", description="", parameters={}, function=lambda: None,
        ))
        registry.register(ToolDefinition(
            name="blocked_tool", description="", parameters={}, function=lambda: None,
        ))

        client = _mock_ai_client([_success_response()])
        factory = _mock_ai_factory(client)

        runtime = AgentRuntime(
            ai_client_factory=factory,
            tool_registry=registry,
        )

        # 只允许 allowed_tool
        schema = runtime._get_tools_schema(["allowed_tool"])
        assert schema is not None
        assert len(schema) == 1
        assert schema[0]["function"]["name"] == "allowed_tool"


class TestChainFinalOutputResolution:
    """并行链路最终输出必须按步骤顺序稳定解析。"""

    def test_parallel_final_output_uses_step_order_not_completion_order(self):
        chain = SimpleNamespace(steps=[
            SimpleNamespace(step_id="step_a", order=1),
            SimpleNamespace(step_id="step_b", order=2),
            SimpleNamespace(step_id="step_c", order=3),
        ])

        accumulated_output = {
            # Simulate completion order being different from execution order.
            "step_c": {"content": "final"},
            "step_a": {"content": "first"},
            "step_b": {"content": "middle"},
        }

        final_output = ExecuteChainUseCase._resolve_final_output(chain, accumulated_output)

        assert final_output == "final"


class TestMCPToolNaming:
    """Agent Runtime MCP 工具不能覆盖旧 prompt_* 工具。"""

    def test_agent_runtime_tool_names_are_distinct(self):
        import sys

        if "D:/githv/agomTradePro/sdk" not in sys.path:
            sys.path.insert(0, "D:/githv/agomTradePro/sdk")

        import agomtradepro_mcp.server as server_module

        tools = server_module.server._tool_manager._tools

        assert "prompt_chat" in tools
        assert "generate_prompt_report" in tools
        assert "generate_prompt_signal" in tools
        assert "agent_chat" in tools
        assert "agent_generate_report" in tools
        assert "agent_generate_signal" in tools
