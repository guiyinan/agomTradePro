"""AgomSAAF MCP Tools - Decision Workflow 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


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
        client = AgomSAAFClient()
        return client.decision_workflow.precheck(candidate_id)

    @server.tool()
    def decision_workflow_check_beta_gate(asset_code: str) -> dict[str, Any]:
        """检查资产是否通过 Beta Gate。

        Args:
            asset_code: 资产代码

        Returns:
            Beta Gate 检查结果
        """
        client = AgomSAAFClient()
        return client.decision_workflow.check_beta_gate(asset_code)

    @server.tool()
    def decision_workflow_check_quota(quota_period: str = "WEEKLY") -> dict[str, Any]:
        """检查配额状态。

        Args:
            quota_period: 配额周期（DAILY/WEEKLY/MONTHLY）

        Returns:
            配额检查结果
        """
        client = AgomSAAFClient()
        return client.decision_workflow.check_quota(quota_period)

    @server.tool()
    def decision_workflow_check_cooldown(
        asset_code: str, direction: str | None = None
    ) -> dict[str, Any]:
        """检查冷却期状态。

        Args:
            asset_code: 资产代码
            direction: 交易方向（BUY/SELL），可选

        Returns:
            冷却期检查结果
        """
        client = AgomSAAFClient()
        return client.decision_workflow.check_cooldown(asset_code, direction)
