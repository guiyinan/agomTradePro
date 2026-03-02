"""AgomSAAF SDK - Decision Workflow 模块。

决策工作流模块，提供预检查功能。

注意：check_beta_gate、check_quota、check_cooldown 方法已移除，
这些功能已整合到 precheck 方法中。
"""

from typing import Any

from .base import BaseModule


class DecisionWorkflowModule(BaseModule):
    """决策工作流模块。

    提供决策预检查功能，整合 Beta Gate、配额、冷却期和候选状态检查。
    """

    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/decision-workflow")

    def precheck(self, candidate_id: str) -> dict[str, Any]:
        """执行决策预检查。

        检查候选是否可以提交决策，包括：
        - Beta Gate 是否通过
        - 配额是否足够
        - 冷却期是否通过
        - 候选状态是否有效

        Args:
            candidate_id: Alpha 候选 ID

        Returns:
            预检查结果，包含各项检查状态和警告/错误信息

        Example:
            >>> result = client.decision_workflow.precheck("cand_xxx")
            >>> if result["result"]["beta_gate_passed"]:
            ...     print("Beta Gate 通过")
        """
        return self._post("precheck/", json={"candidate_id": candidate_id})

    # 注意：以下方法已移除，因为后端没有对应的 API 端点
    # 这些功能已整合到 precheck 方法中
    #
    # 如需单独检查，请使用以下替代方案：
    # - Beta Gate: 使用 beta_gate 模块的相关方法
    # - 配额: 使用 decision_rhythm.get_quotas() 方法
    # - 冷却期: 使用 decision_rhythm.get_cooldowns() 方法
