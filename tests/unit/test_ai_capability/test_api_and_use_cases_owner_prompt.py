# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_prompt."""

from .api_and_use_cases_support import *


@pytest.mark.django_db
def test_chat_fallback_uses_admin_configured_system_prompt(regular_user):
    use_case = RouteMessageUseCase()
    settings_obj = TerminalRuntimeSettingsORM.get_solo()
    settings_obj.fallback_chat_system_prompt = (
        "你是 AgomTradePro 平台助手。请优先回答系统状态、Regime、政策、RSS 新闻与热点相关问题。"
    )
    settings_obj.save(update_fields=["fallback_chat_system_prompt"])

    with patch("apps.ai_capability.application.use_cases.AIClientFactory") as mock_factory:
        mock_client = mock_factory.return_value.get_client.return_value
        mock_client.chat_completion.return_value = {
            "status": "success",
            "content": "建议先查看当前 Regime、系统状态或投资组合配置。",
        }

        response = use_case.execute(
            RouteRequestDTO(
                message="系统推荐什么",
                entrypoint="terminal",
                provider_name="openai-main",
                model="gpt-4.1",
                context={
                    "user_id": regular_user.id,
                    "user_is_admin": False,
                    "mcp_enabled": True,
                    "answer_chain_enabled": True,
                    "history": [{"role": "user", "content": "你好"}],
                },
            )
        )

    assert response.decision == "chat"
    sent_messages = mock_client.chat_completion.call_args.kwargs["messages"]
    assert sent_messages[0]["role"] == "system"
    assert sent_messages[0]["content"] == settings_obj.fallback_chat_system_prompt
    assert sent_messages[-1] == {"role": "user", "content": "系统推荐什么"}


def test_sync_mcp_tools_preserves_prompt_template_catalog_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="prompt.read.template_catalog",
        summary="Read the available prompt template catalog.",
        description="Return the active prompt template list exposed by the prompt service.",
        owner_app="prompt",
        tags=("prompt", "template", "catalog", "read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("list_prompt_templates",),
    )

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[governed_manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call", "agom_capability_search"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(name="agom_capability_call", description="core", inputSchema={}),
                SimpleNamespace(
                    name="list_prompt_templates",
                    description="prompt template catalog",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.prompt.read.template_catalog"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "prompt.read.template_catalog"
    assert governed.execution_target["replacement_for"] == ["list_prompt_templates"]
    assert governed.semantic_key == "prompt.read.template_catalog"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.list_prompt_templates"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "prompt.read.template_catalog"
    assert legacy.semantic_key == "prompt.read.template_catalog"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_prompt_chain_catalog_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="prompt.read.chain_catalog",
        summary="Read the available prompt chain catalog.",
        description="Return the active prompt chain list exposed by the prompt service.",
        owner_app="prompt",
        tags=("prompt", "chain", "catalog", "read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("list_prompt_chains",),
    )

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[governed_manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call", "agom_capability_search"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(name="agom_capability_call", description="core", inputSchema={}),
                SimpleNamespace(
                    name="list_prompt_chains",
                    description="prompt chain catalog",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.prompt.read.chain_catalog"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "prompt.read.chain_catalog"
    assert governed.execution_target["replacement_for"] == ["list_prompt_chains"]
    assert governed.semantic_key == "prompt.read.chain_catalog"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.list_prompt_chains"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "prompt.read.chain_catalog"
    assert legacy.semantic_key == "prompt.read.chain_catalog"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_prompt_create_template_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="prompt.create.template",
        summary="Preview first, then create a prompt template.",
        description="Governed staff-only prompt template creation capability.",
        owner_app="prompt",
        tags=("prompt", "template", "configuration", "create", "write"),
        audit_tags=("prompt:create_template", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "category": {"type": "string"},
                "template_content": {"type": "string"},
            },
            "required": ["name", "category", "template_content"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_prompt_template",),
    )

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[governed_manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call", "agom_capability_search"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(name="agom_capability_call", description="core", inputSchema={}),
                SimpleNamespace(
                    name="create_prompt_template",
                    description="create prompt template",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.prompt.create.template"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_prompt_template"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "prompt:create_template",
        "mcp:write",
    ]
    assert governed.semantic_key == "prompt.create.template"

    legacy = by_key["mcp_tool.create_prompt_template"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "prompt.create.template"
    assert legacy.semantic_key == "prompt.create.template"
    assert legacy.enabled_for_terminal is False
