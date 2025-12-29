"""
Repositories for Policy Events.

Infrastructure layer implementation using Django ORM.
"""

from datetime import date
from typing import List, Optional

from django.db import transaction

from ..domain.entities import PolicyEvent, PolicyLevel
from .models import PolicyLog


class PolicyRepositoryError(Exception):
    """政策仓储异常"""
    pass


class DjangoPolicyRepository:
    """
    Django ORM 实现的政策事件仓储

    提供政策事件的增删改查操作。
    """

    def __init__(self):
        self._model = PolicyLog

    def save_event(
        self,
        event: PolicyEvent
    ) -> PolicyEvent:
        """
        保存政策事件

        Args:
            event: 政策事件实体

        Returns:
            PolicyEvent: 保存后的事件
        """
        # 转换 level 枚举
        level_value = (
            event.level.value if isinstance(event.level, PolicyLevel)
            else event.level
        )

        # 检查是否已存在
        existing = self._model.objects.filter(
            event_date=event.event_date
        ).first()

        if existing:
            # 更新
            existing.level = level_value
            existing.title = event.title
            existing.description = event.description
            existing.evidence_url = event.evidence_url
            existing.save()
            orm_obj = existing
        else:
            # 新建
            orm_obj = self._model.objects.create(
                event_date=event.event_date,
                level=level_value,
                title=event.title,
                description=event.description,
                evidence_url=event.evidence_url
            )

        return self._orm_to_entity(orm_obj)

    def get_event_by_date(
        self,
        event_date: date
    ) -> Optional[PolicyEvent]:
        """
        按日期获取政策事件

        Args:
            event_date: 事件日期

        Returns:
            Optional[PolicyEvent]: 事件实体，不存在则返回 None
        """
        orm_obj = self._model.objects.filter(
            event_date=event_date
        ).first()

        if orm_obj:
            return self._orm_to_entity(orm_obj)
        return None

    def get_latest_event(
        self,
        before_date: Optional[date] = None
    ) -> Optional[PolicyEvent]:
        """
        获取最新政策事件

        Args:
            before_date: 截止日期（None 表示最新）

        Returns:
            Optional[PolicyEvent]: 最新事件，无数据则返回 None
        """
        query = self._model.objects.all()

        if before_date:
            query = query.filter(event_date__lte=before_date)

        orm_obj = query.order_by('-event_date').first()

        if orm_obj:
            return self._orm_to_entity(orm_obj)
        return None

    def get_events_in_range(
        self,
        start_date: date,
        end_date: date
    ) -> List[PolicyEvent]:
        """
        获取日期范围内的事件列表

        Args:
            start_date: 起始日期（包含）
            end_date: 结束日期（包含）

        Returns:
            List[PolicyEvent]: 事件列表，按时间升序排列
        """
        query = self._model.objects.filter(
            event_date__gte=start_date,
            event_date__lte=end_date
        ).order_by('event_date')

        return [self._orm_to_entity(obj) for obj in query]

    def get_events_by_level(
        self,
        level: PolicyLevel,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[PolicyEvent]:
        """
        按档位获取事件列表

        Args:
            level: 政策档位
            start_date: 起始日期（包含）
            end_date: 结束日期（包含）

        Returns:
            List[PolicyEvent]: 事件列表
        """
        level_value = level.value if isinstance(level, PolicyLevel) else level
        query = self._model.objects.filter(level=level_value)

        if start_date:
            query = query.filter(event_date__gte=start_date)
        if end_date:
            query = query.filter(event_date__lte=end_date)

        query = query.order_by('event_date')

        return [self._orm_to_entity(obj) for obj in query]

    def get_current_policy_level(
        self,
        as_of_date: Optional[date] = None
    ) -> PolicyLevel:
        """
        获取当前政策档位

        Args:
            as_of_date: 截止日期（None 表示最新）

        Returns:
            PolicyLevel: 当前政策档位
        """
        latest = self.get_latest_event(as_of_date)

        if latest:
            return latest.level

        # 默认返回 P0（常态）
        return PolicyLevel.P0

    def is_intervention_active(
        self,
        as_of_date: Optional[date] = None
    ) -> bool:
        """
        检查是否有干预性政策生效

        P2 或 P3 档位表示干预状态

        Args:
            as_of_date: 截止日期

        Returns:
            bool: 是否有干预
        """
        current_level = self.get_current_policy_level(as_of_date)
        return current_level in [PolicyLevel.P2, PolicyLevel.P3]

    def is_crisis_mode(
        self,
        as_of_date: Optional[date] = None
    ) -> bool:
        """
        检查是否处于危机模式

        P3 档位表示危机模式

        Args:
            as_of_date: 截止日期

        Returns:
            bool: 是否危机模式
        """
        current_level = self.get_current_policy_level(as_of_date)
        return current_level == PolicyLevel.P3

    def delete_event(self, event_date: date) -> bool:
        """
        删除指定日期的事件

        Args:
            event_date: 事件日期

        Returns:
            bool: 是否成功删除
        """
        count, _ = self._model.objects.filter(
            event_date=event_date
        ).delete()
        return count > 0

    def get_event_count(self) -> int:
        """
        获取事件数量

        Returns:
            int: 事件数量
        """
        return self._model.objects.count()

    def get_policy_level_stats(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> dict:
        """
        获取政策档位统计

        Args:
            start_date: 起始日期（包含）
            end_date: 结束日期（包含）

        Returns:
            dict: 各档位的事件数量和占比
        """
        query = self._model.objects.all()

        if start_date:
            query = query.filter(event_date__gte=start_date)
        if end_date:
            query = query.filter(event_date__lte=end_date)

        total = query.count()

        # 统计各档位数量
        from django.db.models import Count
        level_counts = query.values('level').annotate(
            count=Count('id')
        ).order_by('-count')

        stats = {}
        for item in level_counts:
            level = item['level']
            count = item['count']
            stats[level] = {
                'count': count,
                'percentage': count / total if total > 0 else 0
            }

        return {
            'total': total,
            'by_level': stats
        }

    @staticmethod
    def _orm_to_entity(orm_obj: PolicyLog) -> PolicyEvent:
        """将 ORM 对象转换为 Domain 实体"""
        return PolicyEvent(
            event_date=orm_obj.event_date,
            level=PolicyLevel(orm_obj.level),
            title=orm_obj.title,
            description=orm_obj.description,
            evidence_url=orm_obj.evidence_url
        )
