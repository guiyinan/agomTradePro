"""Financial research routing must use evidence-backed capabilities or fail closed."""

import pytest

from apps.ai_capability.application.dtos import RouteRequestDTO
from apps.ai_capability.application.use_cases import RouteMessageUseCase
from apps.ai_capability.infrastructure.models import CapabilityCatalogModel


@pytest.mark.django_db
def test_chinese_all_information_query_routes_directly_to_research_snapshot(mocker) -> None:
    CapabilityCatalogModel._default_manager.create(
        capability_key="mcp_tool.equity.read.research_snapshot",
        source_type="mcp_tool",
        source_ref="equity.read.research_snapshot",
        name="个股完整研究快照",
        summary="查询股票的身份、行情、历史、估值、财务、新闻与资金流。",
        description="使用持久化证据查询一只证券的全部可靠信息。",
        route_group="tool",
        category="equity",
        tags=["股票", "个股", "所有信息", "完整研究"],
        input_schema={
            "type": "object",
            "properties": {"stock_code": {"type": "string"}},
            "required": ["stock_code"],
            "additionalProperties": False,
        },
        execution_target={
            "type": "mcp_tool",
            "tool_name": "agom_capability_call",
            "capability_key": "equity.read.research_snapshot",
        },
        risk_level="low",
        requires_mcp=True,
        requires_confirmation=False,
        enabled_for_routing=True,
        enabled_for_terminal=True,
        enabled_for_chat=True,
        enabled_for_agent=True,
        visibility="public",
        auto_collected=True,
        review_status="approved",
    )
    use_case = RouteMessageUseCase()
    dispatch = mocker.patch.object(
        use_case.dispatcher,
        "dispatch",
        return_value={"reply": "证据快照", "result": {"stock_code": "002156.SZ"}},
    )

    response = use_case.execute(
        RouteRequestDTO(
            message="使用这个金融分析 MCP，查询关于通富微电的所有信息",
            entrypoint="agent",
            context={"mcp_enabled": True},
        )
    )

    assert response.decision == "capability"
    assert response.selected_capability_key == "mcp_tool.equity.read.research_snapshot"
    routed_context = dispatch.call_args.args[2]
    assert routed_context.context["params"]["stock_code"] == "通富微电"
    assert response.requires_confirmation is False


@pytest.mark.django_db
def test_financial_fact_query_without_evidence_capability_never_calls_chat_model(mocker) -> None:
    use_case = RouteMessageUseCase()
    chat = mocker.patch.object(
        use_case,
        "_execute_chat",
        side_effect=AssertionError("financial facts must not use free-form chat fallback"),
    )

    response = use_case.execute(
        RouteRequestDTO(
            message="查询关于通富微电的所有信息",
            entrypoint="agent",
            context={"mcp_enabled": True},
        )
    )

    assert response.decision == "chat"
    assert response.metadata["route"] == "financial_evidence_blocked"
    assert response.result["must_not_use_for_decision"] is True
    assert response.result["block_reason_code"] == "financial_evidence_capability_unavailable"
    chat.assert_not_called()
