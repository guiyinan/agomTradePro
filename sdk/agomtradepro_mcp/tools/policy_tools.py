"""
AgomTradePro MCP Tools - Policy 政策事件工具

提供政策事件相关的 MCP 工具。
"""

from datetime import date
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_policy_tools(server: FastMCP) -> None:
    """注册 Policy 相关的 MCP 工具"""

    # =========================================================================
    # 基础工具
    # =========================================================================

    @server.tool()
    def get_policy_status() -> dict[str, Any]:
        """
        获取当前政策状态

        Returns:
            当前政策状态，包括档位和最近事件

        Example:
            >>> status = get_policy_status()
        """
        client = AgomTradeProClient()
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
        client = AgomTradeProClient()
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
        title: str | None = None,
        level: str | None = None,
        evidence_url: str | None = None,
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
        client = AgomTradeProClient()
        parsed_date = date.fromisoformat(event_date)
        try:
            event = client.policy.create_event(
                parsed_date,
                event_type,
                description,
                gear,
                title=title,
                level=level,
                evidence_url=evidence_url,
            )
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "event_date": event_date,
                "event_type": event_type,
            }
        return {
            "success": True,
            "id": event.id,
            "event_date": event.event_date.isoformat(),
            "event_type": event.event_type,
            "description": event.description,
            "gear": event.gear,
        }

    # =========================================================================
    # 工作台工具
    # =========================================================================

    @server.tool()
    def get_workbench_summary() -> dict[str, Any]:
        """
        获取工作台概览

        Returns:
            工作台概览，包括双闸状态、待审核数、SLA 超时数等

        Example:
            >>> summary = get_workbench_summary()
            >>> print(f"政策档位: {summary['policy_level']}")
            >>> print(f"闸门等级: {summary['gate_level']}")
            >>> print(f"待审核: {summary['pending_review_count']}")
        """
        client = AgomTradeProClient()
        summary = client.policy.get_workbench_summary()
        return {
            "policy_level": summary.policy_level,
            "policy_level_name": summary.policy_level_name,
            "gate_level": summary.gate_level,
            "gate_level_name": summary.gate_level_name,
            "global_heat": summary.global_heat,
            "global_sentiment": summary.global_sentiment,
            "pending_review_count": summary.pending_review_count,
            "sla_exceeded_count": summary.sla_exceeded_count,
            "today_events_count": summary.today_events_count,
        }

    @server.tool()
    def get_workbench_items(
        tab: str = "pending",
        event_type: str | None = None,
        level: str | None = None,
        gate_level: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """
        获取工作台事件列表

        Args:
            tab: 标签页 (pending/effective/all)
            event_type: 事件类型过滤 (policy/hotspot/sentiment/mixed)
            level: 政策档位过滤 (P0/P1/P2/P3)
            gate_level: 闸门等级过滤 (L0/L1/L2/L3)
            search: 关键词搜索
            page: 页码
            page_size: 每页数量

        Returns:
            工作台事件列表结果

        Example:
            >>> result = get_workbench_items(tab="pending", level="P2")
            >>> for item in result["items"]:
            ...     print(f"{item['event_date']}: {item['title']}")
        """
        client = AgomTradeProClient()
        result = client.policy.get_workbench_items(
            tab=tab,
            event_type=event_type,
            level=level,
            gate_level=gate_level,
            search=search,
            page=page,
            page_size=page_size,
        )

        return {
            "items": [
                {
                    "id": item.id,
                    "event_date": item.event_date.isoformat(),
                    "event_type": item.event_type,
                    "level": item.level,
                    "title": item.title,
                    "description": item.description,
                    "gate_level": item.gate_level,
                    "gate_effective": item.gate_effective,
                    "audit_status": item.audit_status,
                    "ai_confidence": item.ai_confidence,
                    "heat_score": item.heat_score,
                    "sentiment_score": item.sentiment_score,
                    "asset_class": item.asset_class,
                }
                for item in result.items
            ],
            "total_count": result.total_count,
            "page": result.page,
            "page_size": result.page_size,
        }

    @server.tool()
    def approve_workbench_event(event_id: int) -> dict[str, Any]:
        """
        审核通过工作台事件

        Args:
            event_id: 事件 ID

        Returns:
            操作结果

        Example:
            >>> result = approve_workbench_event(123)
            >>> print(f"审核结果: {result['success']}")
        """
        client = AgomTradeProClient()
        return client.policy.approve_event(event_id)

    @server.tool()
    def reject_workbench_event(event_id: int, reason: str) -> dict[str, Any]:
        """
        审核拒绝工作台事件

        Args:
            event_id: 事件 ID
            reason: 拒绝原因（必填）

        Returns:
            操作结果

        Example:
            >>> result = reject_workbench_event(123, reason="信息不完整")
            >>> print(f"拒绝结果: {result['success']}")
        """
        client = AgomTradeProClient()
        return client.policy.reject_event(event_id, reason)

    @server.tool()
    def rollback_workbench_event(event_id: int, reason: str) -> dict[str, Any]:
        """
        回滚已生效的工作台事件

        Args:
            event_id: 事件 ID
            reason: 回滚原因（必填）

        Returns:
            操作结果

        Example:
            >>> result = rollback_workbench_event(123, reason="信息有误需重新审核")
            >>> print(f"回滚结果: {result['success']}")
        """
        client = AgomTradeProClient()
        try:
            return client.policy.rollback_event(event_id, reason)
        except Exception as exc:
            return {"success": False, "error": str(exc), "event_id": event_id}

    @server.tool()
    def override_workbench_event(
        event_id: int,
        reason: str,
        expires_in_hours: int | None = None,
    ) -> dict[str, Any]:
        """
        临时豁免工作台事件

        Args:
            event_id: 事件 ID
            reason: 豁免原因（必填）
            expires_in_hours: 豁免过期时间（小时）

        Returns:
            操作结果

        Example:
            >>> result = override_workbench_event(
            ...     123,
            ...     reason="特殊情况临时豁免",
            ...     expires_in_hours=24
            ... )
            >>> print(f"豁免结果: {result['success']}")
        """
        client = AgomTradeProClient()
        return client.policy.override_event(event_id, reason, expires_in_hours)

    @server.tool()
    def get_sentiment_gate_state(asset_class: str = "all") -> dict[str, Any]:
        """
        获取热点情绪闸门状态

        Returns:
            热点情绪闸门状态

        Example:
            >>> state = get_sentiment_gate_state()
            >>> print(f"闸门等级: {state['gate_level']}")
            >>> print(f"热度评分: {state['global_heat']}")
            >>> print(f"情绪评分: {state['global_sentiment']}")
        """
        client = AgomTradeProClient()
        try:
            state = client.policy.get_sentiment_gate_state(asset_class=asset_class)
            return {
                "asset_class": asset_class,
                "gate_level": state.gate_level,
                "global_heat": state.global_heat,
                "global_sentiment": state.global_sentiment,
                "max_position_cap": state.max_position_cap,
                "signal_paused": state.signal_paused,
            }
        except Exception as e:
            return {
                "success": False,
                "asset_class": asset_class,
                "error": str(e),
                "message": "sentiment gate 当前缺少对应 asset_class 的配置数据",
            }

    # =========================================================================
    # 新增工具 (2026-02-28)
    # =========================================================================

    @server.tool()
    def get_workbench_bootstrap() -> dict[str, Any]:
        """
        获取工作台启动数据

        一次性获取工作台初始化所需的所有数据，包括：
        - summary: 工作台概览（双闸状态、待审核数等）
        - default_list: 默认事件列表
        - filter_options: 筛选选项
        - trend: 近30天趋势数据
        - fetch_status: RSS抓取状态

        Returns:
            工作台启动数据

        Example:
            >>> bootstrap = get_workbench_bootstrap()
            >>> print(f"政策档位: {bootstrap['summary']['policy_level']}")
            >>> print(f"事件数量: {len(bootstrap['default_list'])}")
        """
        client = AgomTradeProClient()
        return client.policy.get_workbench_bootstrap()

    @server.tool()
    def get_workbench_event_detail(event_id: int) -> dict[str, Any]:
        """
        获取工作台事件详情

        Args:
            event_id: 事件 ID

        Returns:
            事件详情，包括来源信息、结构化数据、审核信息等

        Example:
            >>> detail = get_workbench_event_detail(123)
            >>> print(f"标题: {detail['title']}")
            >>> print(f"来源: {detail.get('rss_source_name')}")
            >>> print(f"审核状态: {detail['audit_status']}")
        """
        client = AgomTradeProClient()
        return client.policy.get_workbench_event_detail(event_id)

    @server.tool()
    def trigger_rss_fetch(
        source_id: int | None = None,
        force_refetch: bool = False,
    ) -> dict[str, Any]:
        """
        触发 RSS 抓取

        Args:
            source_id: 指定 RSS 源 ID（None 表示抓取全部）
            force_refetch: 是否强制重新抓取

        Returns:
            抓取结果，包括处理数量、新事件数量等

        Example:
            >>> # 抓取全部
            >>> result = trigger_rss_fetch()
            >>> print(f"新事件: {result['new_policy_events']}")
            >>>
            >>> # 抓取指定源
            >>> result = trigger_rss_fetch(source_id=1, force_refetch=True)
        """
        client = AgomTradeProClient()
        return client.policy.trigger_fetch(source_id, force_refetch)
