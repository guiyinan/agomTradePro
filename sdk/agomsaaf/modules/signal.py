"""
AgomSAAF SDK - Investment Signal 投资信号模块

提供投资信号相关的 API 操作。
"""

from datetime import date, datetime
from typing import Any, Optional

from agomsaaf.modules.base import BaseModule
from agomsaaf.types import (
    CreateSignalParams,
    InvestmentSignal,
    RegimeType,
    SignalEligibilityResult,
    SignalStatus,
)


class SignalModule(BaseModule):
    """
    投资信号模块

    提供信号创建、查询、审批、准入检查等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Signal 模块

        Args:
            client: AgomSAAF 客户端实例
        """
        super().__init__(client, "/api/signal")

    def list(
        self,
        status: Optional[SignalStatus] = None,
        asset_code: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[InvestmentSignal]:
        """
        获取投资信号列表

        Args:
            status: 信号状态过滤（可选）
            asset_code: 资产代码过滤（可选）
            limit: 返回数量限制
            offset: 分页偏移量

        Returns:
            投资信号列表

        Example:
            >>> client = AgomSAAFClient()
            >>> signals = client.signal.list(status="approved", limit=10)
            >>> for signal in signals:
            ...     print(f"{signal.asset_code}: {signal.logic_desc}")
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if status is not None:
            params["status"] = status
        if asset_code is not None:
            params["asset_code"] = asset_code

        response = self._get("signals/", params=params)
        results = response.get("results", response)
        return [self._parse_signal(item) for item in results]

    def get(self, signal_id: int) -> InvestmentSignal:
        """
        获取单个投资信号详情

        Args:
            signal_id: 信号 ID

        Returns:
            投资信号详情

        Raises:
            NotFoundError: 当信号不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> signal = client.signal.get(123)
            >>> print(f"资产: {signal.asset_code}")
            >>> print(f"状态: {signal.status}")
        """
        response = self._get(f"signals/{signal_id}/")
        return self._parse_signal(response)

    def create(
        self,
        asset_code: str,
        logic_desc: str,
        invalidation_logic: str,
        invalidation_threshold: float,
        target_regime: Optional[RegimeType] = None,
    ) -> InvestmentSignal:
        """
        创建投资信号

        Args:
            asset_code: 资产代码
            logic_desc: 逻辑描述
            invalidation_logic: 证伪逻辑
            invalidation_threshold: 证伪阈值
            target_regime: 目标象限（可选）

        Returns:
            创建的投资信号

        Raises:
            ValidationError: 当参数验证失败时
            ConflictError: 当信号已存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> signal = client.signal.create(
            ...     asset_code="000001.SH",
            ...     logic_desc="PMI 回升，经济复苏",
            ...     invalidation_logic="PMI 跌破 50",
            ...     invalidation_threshold=49.5,
            ...     target_regime="Recovery"
            ... )
            >>> print(f"信号已创建: {signal.id}")
        """
        data: dict[str, Any] = {
            "asset_code": asset_code,
            "logic_desc": logic_desc,
            "invalidation_logic": invalidation_logic,
            "invalidation_threshold": invalidation_threshold,
        }

        if target_regime is not None:
            data["target_regime"] = target_regime

        response = self._post("signals/", json=data)
        return self._parse_signal(response)

    def approve(
        self,
        signal_id: int,
        approver: Optional[str] = None,
    ) -> InvestmentSignal:
        """
        审批投资信号

        Args:
            signal_id: 信号 ID
            approver: 审批人（可选）

        Returns:
            更新后的投资信号

        Raises:
            NotFoundError: 当信号不存在时
            ValidationError: 当信号状态不允许审批时

        Example:
            >>> client = AgomSAAFClient()
            >>> signal = client.signal.approve(123, approver="admin")
            >>> print(f"信号已审批: {signal.status}")
        """
        data: dict[str, Any] = {}
        if approver is not None:
            data["approver"] = approver

        response = self._post(f"signals/{signal_id}/approve/", json=data)
        return self._parse_signal(response)

    def reject(
        self,
        signal_id: int,
        reason: str,
    ) -> InvestmentSignal:
        """
        拒绝投资信号

        Args:
            signal_id: 信号 ID
            reason: 拒绝原因

        Returns:
            更新后的投资信号

        Raises:
            NotFoundError: 当信号不存在时
            ValidationError: 当信号状态不允许拒绝时

        Example:
            >>> client = AgomSAAFClient()
            >>> signal = client.signal.reject(123, reason="不符合当前象限")
            >>> print(f"信号已拒绝: {signal.status}")
        """
        response = self._post(f"signals/{signal_id}/reject/", json={"reason": reason})
        return self._parse_signal(response)

    def invalidate(
        self,
        signal_id: int,
        reason: str,
    ) -> InvestmentSignal:
        """
        使投资信号失效（证伪）

        Args:
            signal_id: 信号 ID
            reason: 失效原因

        Returns:
            更新后的投资信号

        Raises:
            NotFoundError: 当信号不存在时
            ValidationError: 当信号状态不允许失效时

        Example:
            >>> client = AgomSAAFClient()
            >>> signal = client.signal.invalidate(123, reason="PMI 跌破 50")
            >>> print(f"信号已失效: {signal.status}")
        """
        response = self._post(f"signals/{signal_id}/invalidate/", json={"reason": reason})
        return self._parse_signal(response)

    def check_eligibility(
        self,
        asset_code: str,
        logic_desc: str,
        target_regime: Optional[RegimeType] = None,
    ) -> SignalEligibilityResult:
        """
        检查信号准入条件

        检查信号是否符合当前宏观象限和政策档位的准入条件。

        Args:
            asset_code: 资产代码
            logic_desc: 逻辑描述
            target_regime: 目标象限（可选）

        Returns:
            准入检查结果

        Example:
            >>> client = AgomSAAFClient()
            >>> result = client.signal.check_eligibility(
            ...     asset_code="000001.SH",
            ...     logic_desc="PMI 回升，经济复苏",
            ...     target_regime="Recovery"
            ... )
            >>> if result.is_eligible:
            ...     print("信号准入")
            ... else:
            ...     print(f"信号不准入: {result.rejection_reason}")
        """
        data: dict[str, Any] = {
            "asset_code": asset_code,
            "logic_desc": logic_desc,
        }

        if target_regime is not None:
            data["target_regime"] = target_regime

        response = self._post("check-eligibility/", json=data)
        return self._parse_eligibility_result(response)

    def _parse_signal(self, data: dict[str, Any]) -> InvestmentSignal:
        """
        解析投资信号数据

        Args:
            data: API 返回的 JSON 数据

        Returns:
            InvestmentSignal 对象
        """
        def parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
            if dt_str is None:
                return None
            if isinstance(dt_str, datetime):
                return dt_str
            return datetime.fromisoformat(dt_str)

        return InvestmentSignal(
            id=data["id"],
            asset_code=data["asset_code"],
            logic_desc=data["logic_desc"],
            status=data["status"],
            created_at=parse_datetime(data["created_at"]),
            invalidation_logic=data.get("invalidation_logic"),
            invalidation_threshold=data.get("invalidation_threshold"),
            approved_at=parse_datetime(data.get("approved_at")),
            invalidated_at=parse_datetime(data.get("invalidated_at")),
            created_by=data.get("created_by"),
        )

    def _parse_eligibility_result(self, data: dict[str, Any]) -> SignalEligibilityResult:
        """
        解析准入检查结果

        Args:
            data: API 返回的 JSON 数据

        Returns:
            SignalEligibilityResult 对象
        """
        return SignalEligibilityResult(
            is_eligible=data["is_eligible"],
            regime_match=data.get("regime_match", False),
            policy_match=data.get("policy_match", False),
            current_regime=data.get("current_regime"),
            policy_status=data.get("policy_status"),
            rejection_reason=data.get("rejection_reason"),
        )
