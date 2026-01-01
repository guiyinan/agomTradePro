"""
Repositories for Policy Events.

Infrastructure layer implementation using Django ORM.
"""

from datetime import date
from typing import List, Optional
from django.utils import timezone
from django.db import models, transaction

from ..domain.entities import PolicyEvent, PolicyLevel, PolicyLevelKeywordRule
from .models import PolicyLog, RSSSourceConfigModel, PolicyLevelKeywordModel, RSSFetchLog


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
        event: PolicyEvent,
        **kwargs
    ) -> PolicyEvent:
        """
        保存政策事件

        Args:
            event: 政策事件实体
            **kwargs: 额外字段（如info_category, audit_status, ai_confidence等）

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
            # 更新额外字段
            for key, value in kwargs.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            existing.save()
            orm_obj = existing
        else:
            # 新建
            create_data = {
                'event_date': event.event_date,
                'level': level_value,
                'title': event.title,
                'description': event.description,
                'evidence_url': event.evidence_url,
            }
            # 添加额外字段
            create_data.update(kwargs)
            orm_obj = self._model.objects.create(**create_data)

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


class RSSRepository:
    """
    RSS数据仓储

    提供RSS源配置、抓取日志和关键词规则的数据访问操作。
    """

    def __init__(self):
        self._source_model = RSSSourceConfigModel
        self._keyword_model = PolicyLevelKeywordModel
        self._log_model = RSSFetchLog

    # ========== RSS源配置 ==========

    def get_active_sources(self) -> List[RSSSourceConfigModel]:
        """获取所有启用的RSS源"""
        return list(self._source_model.objects.filter(is_active=True).all())

    def get_source_by_id(self, source_id: int) -> Optional[RSSSourceConfigModel]:
        """根据ID获取RSS源"""
        return self._source_model.objects.filter(id=source_id).first()

    def get_all_sources(self) -> List[RSSSourceConfigModel]:
        """获取所有RSS源"""
        return list(self._source_model.objects.all())

    def create_source(self, **kwargs) -> RSSSourceConfigModel:
        """创建RSS源"""
        return self._source_model.objects.create(**kwargs)

    def update_source(self, source_id: int, **kwargs) -> bool:
        """更新RSS源"""
        count = self._source_model.objects.filter(id=source_id).update(**kwargs)
        return count > 0

    def update_source_last_fetch(
        self,
        source_id: int,
        status: str,
        error_msg: str = None
    ) -> bool:
        """更新源的抓取状态"""
        count = self._source_model.objects.filter(id=source_id).update(
            last_fetch_at=timezone.now(),
            last_fetch_status=status,
            last_error_message=error_msg or ''
        )
        return count > 0

    # ========== 抓取日志 ==========

    def save_fetch_log(
        self,
        source_id: int,
        status: str,
        items_count: int,
        new_items_count: int,
        error_message: str = None,
        duration: float = None
    ) -> RSSFetchLog:
        """保存抓取日志"""
        return self._log_model.objects.create(
            source_id=source_id,
            status=status,
            items_count=items_count,
            new_items_count=new_items_count,
            error_message=error_message or '',
            fetch_duration_seconds=duration
        )

    def get_fetch_logs(
        self,
        source_id: Optional[int] = None,
        limit: int = 100
    ) -> List[RSSFetchLog]:
        """获取抓取日志"""
        query = self._log_model.objects.all()
        if source_id:
            query = query.filter(source_id=source_id)
        return list(query.order_by('-fetched_at')[:limit])

    def cleanup_old_logs(self, days_to_keep: int = 90) -> int:
        """清理旧的抓取日志"""
        from django.utils import timezone
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(days=days_to_keep)
        count, _ = self._log_model.objects.filter(fetched_at__lt=cutoff).delete()
        return count

    # ========== 去重检查 ==========

    def is_item_exists(self, link: str, guid: Optional[str] = None) -> bool:
        """
        检查RSS条目是否已存在（去重）

        通过PolicyLog的evidence_url去重

        Args:
            link: RSS条目链接
            guid: RSS条目GUID（可选）

        Returns:
            bool: 是否已存在
        """
        return PolicyLog.objects.filter(evidence_url=link).exists()

    # ========== 关键词规则 ==========

    def get_active_keyword_rules(
        self,
        category: Optional[str] = None
    ) -> List[PolicyLevelKeywordRule]:
        """
       获取启用的关键词规则

        Args:
            category: RSS源分类（可选），None表示获取所有规则

        Returns:
            List[PolicyLevelKeywordRule]: 关键词规则列表
        """
        query = self._keyword_model.objects.filter(is_active=True)

        if category:
            # 获取通用规则（category为空）和指定分类的规则
            query = query.filter(
                models.Q(category__isnull=True) | models.Q(category__exact='') | models.Q(category=category)
            )

        rules_orm = list(query.order_by('-weight', 'level'))

        # 转换为Domain实体
        rules = []
        for orm_obj in rules_orm:
            level = PolicyLevel(orm_obj.level)
            rule = PolicyLevelKeywordRule(
                level=level,
                keywords=orm_obj.keywords,
                weight=orm_obj.weight,
                category=orm_obj.category
            )
            rules.append(rule)

        return rules

    def create_keyword_rule(self, **kwargs) -> PolicyLevelKeywordModel:
        """创建关键词规则"""
        return self._keyword_model.objects.create(**kwargs)

    def update_keyword_rule(self, rule_id: int, **kwargs) -> bool:
        """更新关键词规则"""
        count = self._keyword_model.objects.filter(id=rule_id).update(**kwargs)
        return count > 0

    def delete_keyword_rule(self, rule_id: int) -> bool:
        """删除关键词规则"""
        count, _ = self._keyword_model.objects.filter(id=rule_id).delete()
        return count > 0
