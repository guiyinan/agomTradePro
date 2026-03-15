"""
AgomSAAF MCP Tools - Investment Signal 投资信号工具

提供投资信号相关的 MCP 工具。
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_signal_tools(server: FastMCP) -> None:
    """注册 Signal 相关的 MCP 工具"""

    @server.tool()
    def list_signals(
        status: str | None = None,
        asset_code: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        获取投资信号列表

        Args:
            status: 信号状态过滤（pending/approved/rejected/invalidated）
            asset_code: 资产代码过滤（如 000001.SH）
            limit: 返回数量限制

        Returns:
            投资信号列表

        Example:
            >>> signals = list_signals(status="approved", limit=10)
        """
        client = AgomSAAFClient()
        signals = client.signal.list(
            status=status,
            asset_code=asset_code,
            limit=limit,
        )

        return [
            {
                "id": s.id,
                "asset_code": s.asset_code,
                "logic_desc": s.logic_desc,
                "status": s.status,
                "created_at": s.created_at.isoformat(),
                "invalidation_logic": s.invalidation_logic,
                "invalidation_threshold": s.invalidation_threshold,
            }
            for s in signals
        ]

    @server.tool()
    def get_signal(signal_id: int) -> dict[str, Any]:
        """
        获取单个投资信号详情

        Args:
            signal_id: 信号 ID

        Returns:
            投资信号详情

        Example:
            >>> signal = get_signal(123)
        """
        client = AgomSAAFClient()
        signal = client.signal.get(signal_id)

        return {
            "id": signal.id,
            "asset_code": signal.asset_code,
            "logic_desc": signal.logic_desc,
            "status": signal.status,
            "created_at": signal.created_at.isoformat(),
            "invalidation_logic": signal.invalidation_logic,
            "invalidation_threshold": signal.invalidation_threshold,
            "approved_at": signal.approved_at.isoformat() if signal.approved_at else None,
            "invalidated_at": signal.invalidated_at.isoformat() if signal.invalidated_at else None,
            "created_by": signal.created_by,
        }

    @server.tool()
    def check_signal_eligibility(
        asset_code: str,
        logic_desc: str,
        target_regime: str | None = None,
    ) -> dict[str, Any]:
        """
        检查投资信号准入条件

        检查信号是否符合当前宏观象限和政策档位的准入条件。

        Args:
            asset_code: 资产代码（如 000001.SH）
            logic_desc: 投资逻辑描述
            target_regime: 目标象限（可选）

        Returns:
            准入检查结果

        Example:
            >>> result = check_signal_eligibility(
            ...     asset_code="000001.SH",
            ...     logic_desc="PMI 回升，经济复苏",
            ...     target_regime="Recovery"
            ... )
        """
        client = AgomSAAFClient()
        result = client.signal.check_eligibility(
            asset_code=asset_code,
            logic_desc=logic_desc,
            target_regime=target_regime,
        )

        return {
            "is_eligible": result.is_eligible,
            "regime_match": result.regime_match,
            "policy_match": result.policy_match,
            "current_regime": result.current_regime,
            "policy_status": result.policy_status,
            "rejection_reason": result.rejection_reason,
        }

    @server.tool()
    def create_signal(
        asset_code: str,
        logic_desc: str,
        invalidation_logic: str,
        invalidation_threshold: float,
        target_regime: str | None = None,
    ) -> dict[str, Any]:
        """
        创建投资信号

        Args:
            asset_code: 资产代码（如 000001.SH）
            logic_desc: 逻辑描述
            invalidation_logic: 证伪逻辑
            invalidation_threshold: 证伪阈值
            target_regime: 目标象限（可选）

        Returns:
            创建的投资信号

        Example:
            >>> signal = create_signal(
            ...     asset_code="000001.SH",
            ...     logic_desc="PMI 回升，经济复苏",
            ...     invalidation_logic="PMI 跌破 50",
            ...     invalidation_threshold=49.5,
            ...     target_regime="Recovery"
            ... )
        """
        client = AgomSAAFClient()
        try:
            signal = client.signal.create(
                asset_code=asset_code,
                logic_desc=logic_desc,
                invalidation_logic=invalidation_logic,
                invalidation_threshold=invalidation_threshold,
                target_regime=target_regime,
            )
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "payload": {
                    "asset_code": asset_code,
                    "logic_desc": logic_desc,
                    "invalidation_logic": invalidation_logic,
                    "invalidation_threshold": invalidation_threshold,
                    "target_regime": target_regime,
                },
            }

        return {
            "id": signal.id,
            "asset_code": signal.asset_code,
            "logic_desc": signal.logic_desc,
            "status": signal.status,
            "created_at": signal.created_at.isoformat(),
        }

    @server.tool()
    def approve_signal(signal_id: int, approver: str | None = None) -> dict[str, Any]:
        """
        审批投资信号

        Args:
            signal_id: 信号 ID
            approver: 审批人（可选）

        Returns:
            更新后的投资信号

        Example:
            >>> signal = approve_signal(123, approver="admin")
        """
        client = AgomSAAFClient()
        signal = client.signal.approve(signal_id, approver=approver)

        return {
            "id": signal.id,
            "status": signal.status,
            "approved_at": signal.approved_at.isoformat() if signal.approved_at else None,
        }

    @server.tool()
    def reject_signal(signal_id: int, reason: str) -> dict[str, Any]:
        """
        拒绝投资信号

        Args:
            signal_id: 信号 ID
            reason: 拒绝原因

        Returns:
            更新后的投资信号

        Example:
            >>> signal = reject_signal(123, reason="不符合当前象限")
        """
        client = AgomSAAFClient()
        signal = client.signal.reject(signal_id, reason=reason)

        return {
            "id": signal.id,
            "status": signal.status,
        }

    @server.tool()
    def invalidate_signal(signal_id: int, reason: str) -> dict[str, Any]:
        """
        使投资信号失效（证伪）

        Args:
            signal_id: 信号 ID
            reason: 失效原因

        Returns:
            更新后的投资信号

        Example:
            >>> signal = invalidate_signal(123, reason="PMI 跌破 50")
        """
        client = AgomSAAFClient()
        try:
            signal = client.signal.invalidate(signal_id, reason=reason)
        except Exception as exc:
            return {
                "success": False,
                "signal_id": signal_id,
                "reason": reason,
                "error": str(exc),
            }

        return {
            "id": signal.id,
            "status": signal.status,
            "invalidated_at": signal.invalidated_at.isoformat() if signal.invalidated_at else None,
        }

