"""AgomSAAF SDK - Decision Rhythm 模块。"""

from typing import Any

from .base import BaseModule


class DecisionRhythmModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/decision-rhythm")

    def list_quotas(self) -> list[dict[str, Any]]:
        response = self._get("quotas/")
        return response.get("results", response) if isinstance(response, dict) else response

    def list_cooldowns(self) -> list[dict[str, Any]]:
        response = self._get("cooldowns/")
        return response.get("results", response) if isinstance(response, dict) else response

    def list_requests(self) -> list[dict[str, Any]]:
        response = self._get("requests/")
        return response.get("results", response) if isinstance(response, dict) else response

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("submit/", json=payload)

    def submit_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("submit-batch/", json=payload)

    def summary(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._get("summary/", params=payload)

    def reset_quota(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("reset-quota/", json=payload)

    def trend_data(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if payload:
            return self._post("trend-data/", json=payload)
        return self._get("trend-data/")

    def update_quota(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("quota/update/", json=payload)

    def execute_request(self, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """执行决策请求。

        将已批准的决策请求执行到指定目标（模拟盘或账户持仓）。

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
            执行结果，包含：
            - request_id: 请求 ID
            - execution_status: 执行状态（EXECUTED/FAILED）
            - executed_at: 执行时间
            - execution_ref: 执行引用（trade_id 或 position_id）
            - candidate_status: 候选状态

        Example:
            >>> # 模拟盘执行
            >>> result = client.decision_rhythm.execute_request(
            ...     "req_xxx",
            ...     {
            ...         "target": "SIMULATED",
            ...         "sim_account_id": 1,
            ...         "asset_code": "000001.SH",
            ...         "action": "buy",
            ...         "quantity": 1000,
            ...         "price": 12.35,
            ...         "reason": "按决策请求执行"
            ...     }
            ... )
            >>> # 账户记录
            >>> result = client.decision_rhythm.execute_request(
            ...     "req_xxx",
            ...     {
            ...         "target": "ACCOUNT",
            ...         "portfolio_id": 9,
            ...         "asset_code": "000001.SH",
            ...         "shares": 1000,
            ...         "avg_cost": 12.35,
            ...         "current_price": 12.35,
            ...         "reason": "按决策请求落地持仓"
            ...     }
            ... )
        """
        return self._post(f"requests/{request_id}/execute/", json=payload)

    def cancel_request(self, request_id: str, reason: str | None = None) -> dict[str, Any]:
        """取消决策请求。

        将待执行的决策请求标记为取消。

        Args:
            request_id: 决策请求 ID
            reason: 取消原因（可选）

        Returns:
            取消结果
        """
        payload: dict[str, Any] = {}
        if reason:
            payload["reason"] = reason
        return self._post(f"requests/{request_id}/cancel/", json=payload)

    def get_request(self, request_id: str) -> dict[str, Any]:
        """获取决策请求详情。

        Args:
            request_id: 决策请求 ID

        Returns:
            决策请求详情，包含执行状态和执行引用
        """
        return self._get(f"requests/{request_id}/")
