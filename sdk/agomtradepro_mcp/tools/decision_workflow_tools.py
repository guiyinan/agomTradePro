"""AgomTradePro MCP Tools - Decision Workflow 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def _derive_step3_status(response: dict[str, Any]) -> dict[str, Any]:
    """Attach MCP-friendly Step 3 summary fields without mutating API semantics."""
    payload = dict(response)
    step3 = ((payload.get("data") or {}).get("step3_sectors") or {})

    data_source = step3.get("rotation_data_source")
    is_stale = bool(step3.get("rotation_is_stale", False))
    warning_message = step3.get("rotation_warning_message")
    signal_date = step3.get("rotation_signal_date")

    if not step3:
        status = "unknown"
    elif is_stale:
        status = "fallback"
    elif data_source in {"fresh_generation", "stored_signal"}:
        status = "current"
    else:
        status = "unknown"

    payload["step3_status"] = status
    payload["step3_data_source"] = data_source
    payload["step3_signal_date"] = signal_date
    payload["step3_warning_message"] = warning_message
    return payload


def register_decision_workflow_tools(server: FastMCP) -> None:
    @server.tool()
    def decision_workflow_precheck(candidate_id: str) -> dict[str, Any]:
        """执行决策预检查。

        检查候选是否可以提交决策，包括 Beta Gate、配额、冷却期和候选状态。

        Args:
            candidate_id: Alpha 候选 ID

        Returns:
            预检查结果，包含各项检查状态和警告/错误信息
        """
        client = AgomTradeProClient()
        try:
            return client.decision_workflow.precheck(candidate_id)
        except Exception as exc:
            return {
                "success": False,
                "candidate_id": candidate_id,
                "error": str(exc),
            }

    @server.tool()
    def decision_workflow_list_recommendations(
        account_id: str,
        status: str = "",
        user_action: str = "",
        security_code: str = "",
        recommendation_id: str = "",
        include_ignored: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """获取决策工作台统一推荐列表。"""
        client = AgomTradeProClient()
        try:
            return client.decision_workflow.list_recommendations(
                account_id=account_id,
                status=status or None,
                user_action=user_action or None,
                security_code=security_code or None,
                recommendation_id=recommendation_id or None,
                include_ignored=include_ignored,
                page=page,
                page_size=page_size,
            )
        except Exception as exc:
            return {
                "success": False,
                "account_id": account_id,
                "error": str(exc),
            }

    @server.tool()
    def decision_workflow_refresh_recommendations(
        account_id: str = "",
        security_codes: list[str] | None = None,
        force: bool = False,
        async_mode: bool = True,
    ) -> dict[str, Any]:
        """刷新决策工作台推荐结果。"""
        client = AgomTradeProClient()
        try:
            return client.decision_workflow.refresh_recommendations(
                account_id=account_id or None,
                security_codes=security_codes,
                force=force,
                async_mode=async_mode,
            )
        except Exception as exc:
            return {
                "success": False,
                "account_id": account_id or None,
                "security_codes": security_codes or [],
                "error": str(exc),
            }

    @server.tool()
    def decision_workflow_apply_recommendation_action(
        recommendation_id: str,
        action: str,
        account_id: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        """记录用户对推荐的动作。action 支持 watch、adopt、ignore、pending。"""
        client = AgomTradeProClient()
        try:
            return client.decision_workflow.apply_recommendation_action(
                recommendation_id=recommendation_id,
                action=action,
                account_id=account_id or None,
                note=note or None,
            )
        except Exception as exc:
            return {
                "success": False,
                "recommendation_id": recommendation_id,
                "action": action,
                "error": str(exc),
            }

    @server.tool()
    def decision_workflow_get_funnel_context(
        trade_id: str = "unknown",
        backtest_id: int | None = None,
    ) -> dict[str, Any]:
        """获取全链路漏斗上下文。

        查询新版决策引擎的漏斗前3步环境判定(环境/方向/板块)，以及第6步(归因复盘)。
        这有助于 Agent 给出一笔端到端的分析背景。

        返回结构遵循 `/api/decision/funnel/context/` 的 JSON 响应；
        在输出 Step 3 轮动结论前，应优先检查：
        `data.step3_sectors.rotation_data_source`
        `data.step3_sectors.rotation_is_stale`
        `data.step3_sectors.rotation_warning_message`
        `data.step3_sectors.rotation_signal_date`
        """
        client = AgomTradeProClient()
        try:
            response = client.decision_workflow.get_funnel_context(
                trade_id=trade_id,
                backtest_id=backtest_id,
            )
            if isinstance(response, dict):
                return _derive_step3_status(response)
            return response
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
            }
