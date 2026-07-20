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
