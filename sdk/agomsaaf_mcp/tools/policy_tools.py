"""
AgomSAAF MCP Tools - Policy 政策事件工具

提供政策事件相关的 MCP 工具。
"""

from datetime import date
from typing import Any

from mcp.server import Server

from agomsaaf import AgomSAAFClient


def register_policy_tools(server: Server) -> None:
    """注册 Policy 相关的 MCP 工具"""

    @server.tool()
    def get_policy_status() -> dict[str, Any]:
        """
        获取当前政策状态

        Returns:
            当前政策状态，包括档位和最近事件

        Example:
            >>> status = get_policy_status()
        """
        client = AgomSAAFClient()
        status = client.policy.get_status()
        return {
            "current_gear": status.current_gear,
            "observed_at": status.observed_at.isoformat(),
            "recent_events_count": len(status.recent_events),
        }

    @server.tool()
    def get_policy_events(
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        获取政策事件列表

        Args:
            start_date: 开始日期（ISO 格式）
            end_date: 结束日期（ISO 格式）
            limit: 返回数量限制

        Returns:
            政策事件列表

        Example:
            >>> events = get_policy_events(start_date="2023-01-01")
        """
        client = AgomSAAFClient()
        parsed_start = date.fromisoformat(start_date) if start_date else None
        parsed_end = date.fromisoformat(end_date) if end_date else None
        events = client.policy.get_events(start_date=parsed_start, end_date=parsed_end, limit=limit)

        return [
            {
                "id": e.id,
                "event_date": e.event_date.isoformat(),
                "event_type": e.event_type,
                "description": e.description,
                "gear": e.gear,
            }
            for e in events
        ]

    @server.tool()
    def create_policy_event(
        event_date: str,
        event_type: str,
        description: str,
        gear: str,
    ) -> dict[str, Any]:
        """
        创建政策事件

        Args:
            event_date: 事件日期（ISO 格式）
            event_type: 事件类型
            description: 事件描述
            gear: 政策档位（stimulus/neutral/tightening）

        Returns:
            创建的政策事件

        Example:
            >>> event = create_policy_event(
            ...     event_date="2024-01-01",
            ...     event_type="interest_rate_cut",
            ...     description="央行下调基准利率 25bp",
            ...     gear="stimulus"
            ... )
        """
        client = AgomSAAFClient()
        parsed_date = date.fromisoformat(event_date)
        event = client.policy.create_event(parsed_date, event_type, description, gear)
        return {
            "id": event.id,
            "event_date": event.event_date.isoformat(),
            "event_type": event.event_type,
            "description": event.description,
            "gear": event.gear,
        }
