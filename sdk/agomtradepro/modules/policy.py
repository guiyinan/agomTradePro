"""
AgomTradePro SDK - Policy 政策事件模块

提供政策事件管理相关的 API 操作。
"""

from datetime import date, datetime
from typing import Any, Optional

from .base import BaseModule
from ..types import (
    PolicyEvent,
    PolicyGear,
    PolicyStatus,
    WorkbenchSummary,
    WorkbenchEvent,
    WorkbenchItemsResult,
    SentimentGateState,
    EventType,
    PolicyLevel,
    GateLevel,
)


class PolicyModule(BaseModule):
    """
    政策事件模块

    提供政策状态查询、事件管理、工作台操作等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Policy 模块

        Args:
            client: AgomTradePro 客户端实例
        """
        super().__init__(client, "/api/policy")

    # =========================================================================
    # 基础功能
    # =========================================================================

    def get_status(self) -> PolicyStatus:
        """
        获取当前政策状态

        Returns:
            当前政策状态，包括档位和最近事件

        Example:
            >>> client = AgomTradeProClient()
            >>> status = client.policy.get_status()
            >>> print(f"当前档位: {status.current_gear}")
            >>> print(f"观测日期: {status.observed_at}")
        """
        response = self._get("status/")
        return self._parse_status(response)

    def get_events(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        event_type: Optional[str] = None,
        gear: Optional[PolicyGear] = None,
        limit: int = 100,
    ) -> list[PolicyEvent]:
        """
        获取政策事件列表

        Args:
            start_date: 开始日期过滤（可选）
            end_date: 结束日期过滤（可选）
            event_type: 事件类型过滤（可选）
            gear: 政策档位过滤（可选）
            limit: 返回数量限制

        Returns:
            政策事件列表

        Example:
            >>> from datetime import date
            >>> client = AgomTradeProClient()
            >>> events = client.policy.get_events(
            ...     start_date=date(2023, 1, 1),
            ...     gear="stimulus"
            ... )
            >>> for event in events:
            ...     print(f"{event.event_date}: {event.description}")
        """
        params: dict[str, Any] = {"limit": limit}

        if start_date is not None:
            params["start_date"] = start_date.isoformat()
        if end_date is not None:
            params["end_date"] = end_date.isoformat()
        if event_type is not None:
            params["event_type"] = event_type
        if gear is not None:
            params["gear"] = gear

        response = self._get("events/", params=params)
        results = response.get("results", response)
        return [self._parse_event(item) for item in results]

    def get_event(self, event_id: int) -> PolicyEvent:
        """
        获取单个政策事件详情

        Args:
            event_id: 事件 ID

        Returns:
            政策事件详情

        Raises:
            NotFoundError: 当事件不存在时

        Example:
            >>> client = AgomTradeProClient()
            >>> event = client.policy.get_event(123)
            >>> print(f"事件类型: {event.event_type}")
            >>> print(f"描述: {event.description}")
        """
        response = self._get(f"events/{event_id}/")
        return self._parse_event(response)

    def create_event(
        self,
        event_date: date,
        event_type: str,
        description: str,
        gear: PolicyGear,
        *,
        level: Optional[PolicyLevel] = None,
        title: Optional[str] = None,
        evidence_url: Optional[str] = None,
    ) -> PolicyEvent:
        """
        创建政策事件

        Args:
            event_date: 事件日期
            event_type: 事件类型
            description: 事件描述
            gear: 政策档位

        Returns:
            创建的政策事件

        Raises:
            ValidationError: 当参数验证失败时

        Example:
            >>> from datetime import date
            >>> client = AgomTradeProClient()
            >>> event = client.policy.create_event(
            ...     event_date=date(2024, 1, 1),
            ...     event_type="interest_rate_cut",
            ...     description="央行下调基准利率 25bp",
            ...     gear="stimulus"
            ... )
            >>> print(f"事件已创建: {event.id}")
        """
        level_value = level or self._gear_to_level(gear)
        data: dict[str, Any] = {
            "event_date": event_date.isoformat(),
            "level": level_value,
            "title": title or event_type.replace("_", " ").strip().title() or "Policy Event",
            "description": description,
            "evidence_url": evidence_url or "https://local.invalid/policy-event",
        }

        response = self._post("events/", json=data)
        if isinstance(response, dict) and "event" in response:
            response = response["event"]
        return self._parse_event(response)

    def update_event(
        self,
        event_id: int,
        event_date: Optional[date] = None,
        event_type: Optional[str] = None,
        description: Optional[str] = None,
        gear: Optional[PolicyGear] = None,
    ) -> PolicyEvent:
        """
        更新政策事件

        Args:
            event_id: 事件 ID
            event_date: 新的事件日期（可选）
            event_type: 新的事件类型（可选）
            description: 新的描述（可选）
            gear: 新的政策档位（可选）

        Returns:
            更新后的政策事件

        Raises:
            NotFoundError: 当事件不存在时
            ValidationError: 当参数验证失败时

        Example:
            >>> client = AgomTradeProClient()
            >>> event = client.policy.update_event(
            ...     event_id=123,
            ...     description="更新后的描述"
            ... )
        """
        data: dict[str, Any] = {}
        if event_date is not None:
            data["event_date"] = event_date.isoformat()
        if event_type is not None:
            data["event_type"] = event_type
        if description is not None:
            data["description"] = description
        if gear is not None:
            data["gear"] = gear

        response = self._put(f"events/{event_id}/", json=data)
        return self._parse_event(response)

    def delete_event(self, event_id: int) -> None:
        """
        删除政策事件

        Args:
            event_id: 事件 ID

        Raises:
            NotFoundError: 当事件不存在时

        Example:
            >>> client = AgomTradeProClient()
            >>> client.policy.delete_event(123)
            >>> print("事件已删除")
        """
        self._delete(f"events/{event_id}/")

    # =========================================================================
    # 工作台功能
    # =========================================================================

    def get_workbench_summary(self) -> WorkbenchSummary:
        """
        获取工作台概览

        Returns:
            工作台概览，包括双闸状态、待审核数、SLA 超时数等

        Example:
            >>> client = AgomTradeProClient()
            >>> summary = client.policy.get_workbench_summary()
            >>> print(f"政策档位: {summary.policy_level}")
            >>> print(f"闸门等级: {summary.gate_level}")
            >>> print(f"待审核: {summary.pending_review_count}")
        """
        response = self._get("workbench/summary/")
        return self._parse_workbench_summary(response)

    def get_workbench_items(
        self,
        tab: str = "pending",
        event_type: Optional[EventType] = None,
        level: Optional[PolicyLevel] = None,
        gate_level: Optional[GateLevel] = None,
        asset_class: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> WorkbenchItemsResult:
        """
        获取工作台事件列表

        Args:
            tab: 标签页 (pending/effective/all)
            event_type: 事件类型过滤 (policy/hotspot/sentiment/mixed)
            level: 政策档位过滤 (P0/P1/P2/P3)
            gate_level: 闸门等级过滤 (L0/L1/L2/L3)
            asset_class: 资产分类过滤
            search: 关键词搜索
            page: 页码
            page_size: 每页数量

        Returns:
            工作台事件列表结果

        Example:
            >>> client = AgomTradeProClient()
            >>> result = client.policy.get_workbench_items(
            ...     tab="pending",
            ...     level="P2",
            ...     page=1
            ... )
            >>> for item in result.items:
            ...     print(f"{item.event_date}: {item.title}")
        """
        params: dict[str, Any] = {
            "tab": tab,
            "page": page,
            "page_size": page_size,
        }

        if event_type is not None:
            params["event_type"] = event_type
        if level is not None:
            params["level"] = level
        if gate_level is not None:
            params["gate_level"] = gate_level
        if asset_class is not None:
            params["asset_class"] = asset_class
        if search is not None:
            params["search"] = search

        response = self._get("workbench/items/", params=params)
        return self._parse_workbench_items(response)

    def approve_event(self, event_id: int) -> dict[str, Any]:
        """
        审核通过事件

        Args:
            event_id: 事件 ID

        Returns:
            操作结果

        Raises:
            NotFoundError: 当事件不存在时
            ValidationError: 当事件状态不允许审核时

        Example:
            >>> client = AgomTradeProClient()
            >>> result = client.policy.approve_event(123)
            >>> print(f"审核结果: {result['success']}")
        """
        return self._post(f"workbench/items/{event_id}/approve/")

    def reject_event(self, event_id: int, reason: str) -> dict[str, Any]:
        """
        审核拒绝事件

        Args:
            event_id: 事件 ID
            reason: 拒绝原因（必填）

        Returns:
            操作结果

        Raises:
            NotFoundError: 当事件不存在时
            ValidationError: 当拒绝原因为空时

        Example:
            >>> client = AgomTradeProClient()
            >>> result = client.policy.reject_event(123, reason="信息不完整")
            >>> print(f"拒绝结果: {result['success']}")
        """
        return self._post(f"workbench/items/{event_id}/reject/", json={"reason": reason})

    def rollback_event(self, event_id: int, reason: str) -> dict[str, Any]:
        """
        回滚已生效事件

        Args:
            event_id: 事件 ID
            reason: 回滚原因（必填）

        Returns:
            操作结果

        Raises:
            NotFoundError: 当事件不存在时
            ValidationError: 当事件未生效时

        Example:
            >>> client = AgomTradeProClient()
            >>> result = client.policy.rollback_event(123, reason="信息有误需重新审核")
            >>> print(f"回滚结果: {result['success']}")
        """
        return self._post(f"workbench/items/{event_id}/rollback/", json={"reason": reason})

    def override_event(
        self,
        event_id: int,
        reason: str,
        expires_in_hours: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        临时豁免事件

        Args:
            event_id: 事件 ID
            reason: 豁免原因（必填）
            expires_in_hours: 豁免过期时间（小时）

        Returns:
            操作结果

        Raises:
            NotFoundError: 当事件不存在时
            ValidationError: 当豁免原因为空时

        Example:
            >>> client = AgomTradeProClient()
            >>> result = client.policy.override_event(
            ...     123,
            ...     reason="特殊情况临时豁免",
            ...     expires_in_hours=24
            ... )
            >>> print(f"豁免结果: {result['success']}")
        """
        data: dict[str, Any] = {"reason": reason}
        if expires_in_hours is not None:
            data["expires_in_hours"] = expires_in_hours

        return self._post(f"workbench/items/{event_id}/override/", json=data)

    def get_sentiment_gate_state(self, asset_class: str = "all") -> SentimentGateState:
        """
        获取热点情绪闸门状态

        Returns:
            热点情绪闸门状态

        Example:
            >>> client = AgomTradeProClient()
            >>> state = client.policy.get_sentiment_gate_state()
            >>> print(f"闸门等级: {state.gate_level}")
            >>> print(f"热度评分: {state.global_heat}")
            >>> print(f"情绪评分: {state.global_sentiment}")
        """
        response = self._get("sentiment-gate/state/", params={"asset_class": asset_class})
        return self._parse_sentiment_gate_state(response)

    # =========================================================================
    # 新增 API (2026-02-28)
    # =========================================================================

    def get_workbench_bootstrap(self) -> dict[str, Any]:
        """
        获取工作台启动数据

        一次性获取工作台初始化所需的所有数据：
        - summary: 工作台概览
        - default_list: 默认事件列表
        - filter_options: 筛选选项
        - trend: 趋势数据
        - fetch_status: 抓取状态

        Returns:
            工作台启动数据

        Example:
            >>> client = AgomTradeProClient()
            >>> bootstrap = client.policy.get_workbench_bootstrap()
            >>> print(f"政策档位: {bootstrap['summary']['policy_level']}")
            >>> print(f"事件数量: {len(bootstrap['default_list'])}")
        """
        return self._get("workbench/bootstrap/")

    def get_workbench_event_detail(self, event_id: int) -> dict[str, Any]:
        """
        获取工作台事件详情

        Args:
            event_id: 事件 ID

        Returns:
            事件详情，包括来源信息

        Raises:
            NotFoundError: 当事件不存在时

        Example:
            >>> client = AgomTradeProClient()
            >>> detail = client.policy.get_workbench_event_detail(123)
            >>> print(f"标题: {detail['title']}")
            >>> print(f"来源: {detail['rss_source_name']}")
        """
        return self._get(f"workbench/items/{event_id}/")

    def trigger_fetch(
        self,
        source_id: Optional[int] = None,
        force_refetch: bool = False,
    ) -> dict[str, Any]:
        """
        触发 RSS 抓取

        Args:
            source_id: 指定 RSS 源 ID（None 表示全部）
            force_refetch: 是否强制重新抓取

        Returns:
            抓取结果，包括处理数量、新事件数量等

        Example:
            >>> client = AgomTradeProClient()
            >>> # 抓取全部
            >>> result = client.policy.trigger_fetch()
            >>> print(f"新事件: {result['new_policy_events']}")
            >>>
            >>> # 抓取指定源
            >>> result = client.policy.trigger_fetch(source_id=1, force_refetch=True)
        """
        data: dict[str, Any] = {"force_refetch": force_refetch}
        if source_id is not None:
            data["source_id"] = source_id

        return self._post("workbench/fetch/", json=data)

    # =========================================================================
    # 解析方法
    # =========================================================================

    def _parse_status(self, data: dict[str, Any]) -> PolicyStatus:
        """解析政策状态数据"""
        obs_date = data.get("observed_at", data.get("as_of_date"))
        if isinstance(obs_date, str):
            obs_date = datetime.fromisoformat(obs_date).date()
        elif obs_date is None:
            obs_date = date.today()

        recent_events = []
        for event_data in data.get("recent_events", []):
            recent_events.append(self._parse_event(event_data))

        return PolicyStatus(
            current_gear=data.get("current_gear", data.get("current_level", "normal")),
            observed_at=obs_date,
            recent_events=recent_events,
        )

    def _parse_event(self, data: dict[str, Any]) -> PolicyEvent:
        """解析政策事件数据"""
        if "event" in data and isinstance(data["event"], dict):
            data = data["event"]
        event_date = data.get("event_date")
        if isinstance(event_date, str):
            event_date = datetime.fromisoformat(event_date).date()
        elif event_date is None:
            event_date = date.today()

        return PolicyEvent(
            id=data.get("id", data.get("event_id", 0)),
            event_date=event_date,
            event_type=data.get("event_type", "policy"),
            description=data["description"],
            gear=data.get("gear", self._level_to_gear(data.get("level"))),
        )

    @staticmethod
    def _gear_to_level(gear: PolicyGear) -> PolicyLevel:
        mapping: dict[str, PolicyLevel] = {
            "neutral": "P0",
            "tightening": "P1",
            "stimulus": "P2",
        }
        return mapping.get(str(gear), "P0")

    @staticmethod
    def _level_to_gear(level: Any) -> PolicyGear:
        mapping: dict[str, PolicyGear] = {
            "P0": "neutral",
            "P1": "tightening",
            "P2": "stimulus",
            "P3": "stimulus",
            "PX": "neutral",
        }
        return mapping.get(str(level), "neutral")

    def _parse_workbench_summary(self, data: dict[str, Any]) -> WorkbenchSummary:
        """解析工作台概览数据"""
        return WorkbenchSummary(
            policy_level=data.get("policy_level", "P0"),
            policy_level_name=data.get("policy_level_name", "常态"),
            gate_level=data.get("gate_level"),
            gate_level_name=data.get("gate_level_name"),
            global_heat=data.get("global_heat"),
            global_sentiment=data.get("global_sentiment"),
            pending_review_count=data.get("pending_review_count", 0),
            sla_exceeded_count=data.get("sla_exceeded_count", 0),
            today_events_count=data.get("today_events_count", 0),
        )

    def _parse_workbench_items(self, data: dict[str, Any]) -> WorkbenchItemsResult:
        """解析工作台事件列表数据"""
        items = []
        for item_data in data.get("results", data.get("items", [])):
            items.append(self._parse_workbench_event(item_data))

        return WorkbenchItemsResult(
            items=items,
            total_count=data.get("count", data.get("total_count", len(items))),
            page=data.get("page", 1),
            page_size=data.get("page_size", 20),
        )

    def _parse_workbench_event(self, data: dict[str, Any]) -> WorkbenchEvent:
        """解析工作台事件数据"""
        event_date = data.get("event_date")
        if isinstance(event_date, str):
            event_date = datetime.fromisoformat(event_date).date()
        elif event_date is None:
            event_date = date.today()

        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

        return WorkbenchEvent(
            id=data["id"],
            event_date=event_date,
            event_type=data.get("event_type", "policy"),
            level=data.get("level", "P0"),
            title=data.get("title", ""),
            description=data.get("description"),
            gate_level=data.get("gate_level"),
            gate_effective=data.get("gate_effective", False),
            audit_status=data.get("audit_status", "pending_review"),
            ai_confidence=data.get("ai_confidence"),
            heat_score=data.get("heat_score"),
            sentiment_score=data.get("sentiment_score"),
            asset_class=data.get("asset_class"),
            created_at=created_at,
        )

    def _parse_sentiment_gate_state(self, data: dict[str, Any]) -> SentimentGateState:
        """解析热点情绪闸门状态数据"""
        return SentimentGateState(
            gate_level=data.get("gate_level", "L0"),
            global_heat=data.get("global_heat", 0.0),
            global_sentiment=data.get("global_sentiment", 0.0),
            max_position_cap=data.get("max_position_cap"),
            signal_paused=data.get("signal_paused", False),
        )
