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

    def generate_transition_plan(
        self,
        account_id: str,
        *,
        recommendation_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """生成并保存账户调仓计划。

        返回的订单包含后端标准决策契约字段：
        `thesis`、`risk_summary`、`reward_risk`、`data_asof`。
        """
        payload: dict[str, Any] = {"account_id": account_id}
        if recommendation_ids is not None:
            payload["recommendation_ids"] = recommendation_ids
        return self._client.post("/api/decision/workspace/plans/generate/", json=payload)

    def get_transition_plan(self, plan_id: str) -> dict[str, Any]:
        """获取已保存的调仓计划详情。"""
        return self._client.get(f"/api/decision/workspace/plans/{plan_id}/")

    def update_transition_plan(
        self,
        plan_id: str,
        *,
        orders: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """更新调仓计划订单参数。

        常用字段包括 `execution_price`、`take_profit_price`、`stop_loss_price`、
        `invalidation_rule`、`invalidation_description`、`review_by`。后端会同步重算
        `reward_risk`。
        """
        return self._client.post(
            f"/api/decision/workspace/plans/{plan_id}/update/",
            json={"orders": orders},
        )

    def preview_execution(
        self,
        *,
        account_id: str,
        plan_id: str | None = None,
        recommendation_id: str | None = None,
        create_request: bool = False,
        market_price: str | float | int | None = None,
    ) -> dict[str, Any]:
        """预览执行计划，可选创建审批请求。"""
        payload: dict[str, Any] = {
            "account_id": account_id,
            "create_request": create_request,
        }
        if plan_id is not None:
            payload["plan_id"] = plan_id
        if recommendation_id is not None:
            payload["recommendation_id"] = recommendation_id
        if market_price is not None:
            payload["market_price"] = market_price
        return self._client.post("/api/decision/execute/preview/", json=payload)

    def get_funnel_context(
        self,
        trade_id: str = "unknown",
        *,
        backtest_id: int | None = None,
    ) -> dict[str, Any]:
        """获取决策工作台全链路漏斗上下文。

        获取环境评估(Step1)、方向选择(Step2)、板块偏好(Step3)以后的基础环境，
        以及针对指定交易的归因复盘(Step6)。

        Step 3 返回的 `step3_sectors` 额外包含轮动可靠性元数据：
        - `rotation_data_source`: `fresh_generation` / `stored_signal` / `stored_signal_fallback`
        - `rotation_is_stale`: 是否已回退到历史落库信号
        - `rotation_warning_message`: 回退时的人类可读提示
        - `rotation_signal_date`: 当前轮动信号日期

        Args:
            trade_id: 获取 Step 6 需要的归因交易 ID，默认为 'unknown'
            backtest_id: 直接指定归因回测 ID，用于 Step 6 精确定位审计报告
        """
        params: dict[str, Any] = {"trade_id": trade_id}
        if backtest_id is not None:
            params["backtest_id"] = backtest_id
        return self._client.get("/api/decision/funnel/context/", params=params)
