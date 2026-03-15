"""AgomSAAF MCP Tools - Decision Rhythm 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_decision_rhythm_tools(server: FastMCP) -> None:
    @server.tool()
    def list_decision_quotas() -> list[dict[str, Any]]:
        client = AgomSAAFClient()
        return client.decision_rhythm.list_quotas()

    @server.tool()
    def list_decision_requests() -> list[dict[str, Any]]:
        client = AgomSAAFClient()
        return client.decision_rhythm.list_requests()

    @server.tool()
    def submit_decision_request(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        try:
            return client.decision_rhythm.submit(payload)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "payload": payload,
            }

    @server.tool()
    def submit_batch_decision_request(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        try:
            return client.decision_rhythm.submit_batch(payload)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "payload": payload,
            }

    @server.tool()
    def get_decision_rhythm_summary(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.decision_rhythm.summary(payload)

    @server.tool()
    def reset_decision_quota(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        normalized = dict(payload)
        period = normalized.get("period")
        if isinstance(period, str):
            normalized["period"] = period.strip().lower()
        return client.decision_rhythm.reset_quota(normalized)

    @server.tool()
    def decision_execute_request(request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """执行决策请求。

        将已批准的决策请求执行到指定目标（模拟盘或账户持仓）。
        仅 admin、owner、investment_manager 角色可执行。

        Args:
            request_id: 决策请求 ID
            payload: 执行参数，包含：
                - target: 执行目标（SIMULATED/ACCOUNT）
                - asset_code: 资产代码
                - 对于模拟盘执行：
                    - sim_account_id: 模拟账户 ID
                    - action: 交易动作（buy/sell）
                    - quantity: 数量
                    - price: 价格（可选）
                    - reason: 执行原因
                - 对于账户记录：
                    - portfolio_id: 投资组合 ID
                    - shares: 持仓数量
                    - avg_cost: 平均成本
                    - current_price: 当前价格
                    - reason: 执行原因

        Returns:
            执行结果，包含执行状态、执行时间和执行引用
        """
        client = AgomSAAFClient()
        try:
            return client.decision_rhythm.execute_request(request_id, payload)
        except Exception as exc:
            return {
                "success": False,
                "request_id": request_id,
                "error": str(exc),
                "payload": payload,
            }

    @server.tool()
    def decision_cancel_request(request_id: str, reason: str | None = None) -> dict[str, Any]:
        """取消决策请求。

        将待执行的决策请求标记为取消。

        Args:
            request_id: 决策请求 ID
            reason: 取消原因（可选）

        Returns:
            取消结果
        """
        client = AgomSAAFClient()
        try:
            return client.decision_rhythm.cancel_request(request_id, reason)
        except Exception as exc:
            return {
                "success": False,
                "request_id": request_id,
                "reason": reason,
                "error": str(exc),
            }

    @server.tool()
    def get_decision_request(request_id: str) -> dict[str, Any]:
        """获取决策请求详情。

        Args:
            request_id: 决策请求 ID

        Returns:
            决策请求详情，包含执行状态和执行引用
        """
        client = AgomSAAFClient()
        try:
            return client.decision_rhythm.get_request(request_id)
        except Exception as exc:
            return {
                "success": False,
                "request_id": request_id,
                "error": str(exc),
            }
