"""
AgomTradePro MCP Tools - Agent Runtime Execution Tools

Task-oriented MCP tools that call the unified Agent Runtime.
These tools provide AI-powered analysis capabilities via MCP,
reusing the same Runtime kernel that Django internal modules use.

Tools:
- agent_chat: Quick AI chat with context injection and tool calling
- agent_generate_report: Generate AI analysis report via Agent Runtime
- agent_generate_signal: Generate AI-powered investment signals via Agent Runtime
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_agent_runtime_tools(server: FastMCP) -> None:
    """Register Agent Runtime MCP tools."""

    @server.tool()
    def agent_chat(
        message: str,
        context_scope: list[str] | None = None,
        tool_names: list[str] | None = None,
        provider_ref: str | None = None,
        model: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """
        AI chat with system data access via the Agent Runtime.

        Unlike basic prompt_chat, this tool can access real-time system data
        through context injection and tool calling. The AI can query
        macro indicators, regime status, portfolio positions, etc.

        Args:
            message: User message or question
            context_scope: Context domains to include in the conversation.
                          Options: macro, regime, portfolio, signals, asset_pool
            tool_names: Tools the AI can use to query data.
                       Options: get_macro_summary, get_macro_indicator,
                       get_regime_status, get_regime_distribution,
                       get_portfolio_snapshot, get_portfolio_positions,
                       get_valid_signals, get_asset_pool
            provider_ref: AI provider name or ID (optional)
            model: Model name override (optional)
            session_id: Session ID for conversation continuity

        Returns:
            Dict with final_answer, tool_calls, turn_count, tokens

        Example:
            >>> result = agent_chat(
            ...     message="当前宏观环境如何？Regime是什么状态？",
            ...     context_scope=["macro", "regime"],
            ...     tool_names=["get_macro_summary", "get_regime_status"]
            ... )
        """
        client = AgomTradeProClient()
        return client.prompt.agent_execute(
            task_type="chat",
            user_input=message,
            context_scope=context_scope,
            tool_names=tool_names,
            provider_ref=provider_ref,
            model=model,
            session_id=session_id,
        )

    @server.tool()
    def agent_generate_report(
        topic: str,
        context_scope: list[str] | None = None,
        tool_names: list[str] | None = None,
        system_prompt: str | None = None,
        provider_ref: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """
        Generate an AI analysis report using the Agent Runtime.

        The AI will use system context and tools to produce a structured
        analysis report on the given topic.

        Args:
            topic: Report topic or analysis question
            context_scope: Context domains (default: macro, regime, portfolio)
            tool_names: Available data tools
            system_prompt: Custom system prompt for the report
            provider_ref: AI provider name or ID
            model: Model name override

        Returns:
            Dict with final_answer (report text), tool_calls, tokens

        Example:
            >>> result = agent_generate_report(
            ...     topic="分析当前宏观环境对投资组合的影响",
            ...     context_scope=["macro", "regime", "portfolio"],
            ... )
        """
        client = AgomTradeProClient()
        scope = context_scope or ["macro", "regime", "portfolio"]
        return client.prompt.agent_execute(
            task_type="report",
            user_input=topic,
            context_scope=scope,
            tool_names=tool_names,
            system_prompt=system_prompt,
            provider_ref=provider_ref,
            model=model,
        )

    @server.tool()
    def agent_generate_signal(
        analysis_request: str,
        context_scope: list[str] | None = None,
        tool_names: list[str] | None = None,
        response_schema: dict[str, Any] | None = None,
        provider_ref: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """
        Generate AI-powered investment signals using the Agent Runtime.

        The AI analyzes system data (macro, regime, signals, portfolio)
        and generates structured signal recommendations.

        Args:
            analysis_request: Description of the signal analysis needed
            context_scope: Context domains (default: all)
            tool_names: Available data tools
            response_schema: JSON Schema for structured output
            provider_ref: AI provider name or ID
            model: Model name override

        Returns:
            Dict with final_answer, structured_output (signal list), tokens

        Example:
            >>> result = agent_generate_signal(
            ...     analysis_request="基于当前Regime和宏观数据，推荐投资信号",
            ...     context_scope=["macro", "regime", "signals", "asset_pool"],
            ... )
        """
        client = AgomTradeProClient()
        scope = context_scope or ["macro", "regime", "signals", "asset_pool", "portfolio"]
        schema = response_schema or {
            "type": "json_schema",
            "json_schema": {
                "name": "signal_recommendations",
                "schema": {
                    "type": "object",
                    "properties": {
                        "signals": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "asset_code": {"type": "string"},
                                    "direction": {"type": "string"},
                                    "confidence": {"type": "number"},
                                    "reason": {"type": "string"},
                                    "risk_notes": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        }
        return client.prompt.agent_execute(
            task_type="signal",
            user_input=analysis_request,
            context_scope=scope,
            tool_names=tool_names,
            response_schema=schema,
            provider_ref=provider_ref,
            model=model,
        )
