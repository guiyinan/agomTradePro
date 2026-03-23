"""AgomTradePro SDK - Decision Workflow 模块。"""

from typing import Any

from .base import BaseModule


class DecisionWorkflowModule(BaseModule):
    """决策工作流模块。

    提供决策预检查、统一推荐列表、推荐刷新和用户决策动作能力。
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

    def list_recommendations(
        self,
        account_id: str,
        *,
        status: str | None = None,
        user_action: str | None = None,
        security_code: str | None = None,
        recommendation_id: str | None = None,
        include_ignored: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """获取决策工作台统一推荐列表。"""
        params: dict[str, Any] = {
            "account_id": account_id,
            "include_ignored": include_ignored,
            "page": page,
            "page_size": page_size,
        }
        if status:
            params["status"] = status
        if user_action:
            params["user_action"] = user_action
        if security_code:
            params["security_code"] = security_code
        if recommendation_id:
            params["recommendation_id"] = recommendation_id
        return self._client.get("/api/decision/workspace/recommendations/", params=params)

    def refresh_recommendations(
        self,
        *,
        account_id: str | None = None,
        security_codes: list[str] | None = None,
        force: bool = False,
        async_mode: bool = True,
    ) -> dict[str, Any]:
        """手动刷新统一推荐。"""
        payload: dict[str, Any] = {
            "force": force,
            "async_mode": async_mode,
        }
        if account_id is not None:
            payload["account_id"] = account_id
        if security_codes is not None:
            payload["security_codes"] = security_codes
        return self._client.post("/api/decision/workspace/recommendations/refresh/", json=payload)

    def apply_recommendation_action(
        self,
        recommendation_id: str,
        action: str,
        *,
        account_id: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """记录用户对推荐的动作。

        `action` 支持 `watch`、`adopt`、`ignore`、`pending`。
        """
        payload: dict[str, Any] = {
            "recommendation_id": recommendation_id,
            "action": action,
        }
        if account_id is not None:
            payload["account_id"] = account_id
        if note is not None:
            payload["note"] = note
        return self._client.post("/api/decision/workspace/recommendations/action/", json=payload)
