from typing import TYPE_CHECKING
"""
AgomSAAF SDK - Policy 政策事件模块

提供政策事件管理相关的 API 操作。
"""

from datetime import date
from typing import Any, Optional

from .base import BaseModule
from ..types import PolicyEvent, PolicyGear, PolicyStatus


class PolicyModule(BaseModule):
    """
    政策事件模块

    提供政策状态查询、事件管理等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Policy 模块

        Args:
            client: AgomSAAF 客户端实例
        """
        super().__init__(client, "/api/policy")

    def get_status(self) -> PolicyStatus:
        """
        获取当前政策状态

        Returns:
            当前政策状态，包括档位和最近事件

        Example:
            >>> client = AgomSAAFClient()
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
            >>> client = AgomSAAFClient()
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
            >>> client = AgomSAAFClient()
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
            >>> client = AgomSAAFClient()
            >>> event = client.policy.create_event(
            ...     event_date=date(2024, 1, 1),
            ...     event_type="interest_rate_cut",
            ...     description="央行下调基准利率 25bp",
            ...     gear="stimulus"
            ... )
            >>> print(f"事件已创建: {event.id}")
        """
        data: dict[str, Any] = {
            "event_date": event_date.isoformat(),
            "event_type": event_type,
            "description": description,
            "gear": gear,
        }

        response = self._post("events/", json=data)
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
            >>> client = AgomSAAFClient()
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
            >>> client = AgomSAAFClient()
            >>> client.policy.delete_event(123)
            >>> print("事件已删除")
        """
        self._delete(f"events/{event_id}/")

    def _parse_status(self, data: dict[str, Any]) -> PolicyStatus:
        """
        解析政策状态数据

        Args:
            data: API 返回的 JSON 数据

        Returns:
            PolicyStatus 对象
        """
        # 处理日期
        obs_date = data.get("observed_at")
        if isinstance(obs_date, str):
            from datetime import datetime

            obs_date = datetime.fromisoformat(obs_date).date()
        elif obs_date is None:
            obs_date = date.today()

        # 解析最近事件
        recent_events = []
        for event_data in data.get("recent_events", []):
            recent_events.append(self._parse_event(event_data))

        return PolicyStatus(
            current_gear=data["current_gear"],
            observed_at=obs_date,
            recent_events=recent_events,
        )

    def _parse_event(self, data: dict[str, Any]) -> PolicyEvent:
        """
        解析政策事件数据

        Args:
            data: API 返回的 JSON 数据

        Returns:
            PolicyEvent 对象
        """
        # 处理日期
        event_date = data.get("event_date")
        if isinstance(event_date, str):
            from datetime import datetime

            event_date = datetime.fromisoformat(event_date).date()
        elif event_date is None:
            event_date = date.today()

        return PolicyEvent(
            id=data["id"],
            event_date=event_date,
            event_type=data["event_type"],
            description=data["description"],
            gear=data["gear"],
        )
