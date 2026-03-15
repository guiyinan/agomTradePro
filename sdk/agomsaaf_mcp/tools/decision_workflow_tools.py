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
        try:
            return client.decision_workflow.precheck(candidate_id)
        except Exception as exc:
            return {
                "success": False,
                "candidate_id": candidate_id,
                "error": str(exc),
            }
