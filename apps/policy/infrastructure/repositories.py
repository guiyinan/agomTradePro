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
        return_orm: bool = False,
        **kwargs
    ):
        """
        保存政策事件

        Args:
            event: 政策事件实体
            return_orm: 是否返回ORM对象（含ID），默认返回Domain实体
            **kwargs: 额外字段（如info_category, audit_status, ai_confidence等）

        Returns:
            Union[PolicyEvent, PolicyLog]: 根据return_orm参数返回Domain实体或ORM对象
        """
        # 转换 level 枚举
        level_value = (
            event.level.value if isinstance(event.level, PolicyLevel)
            else event.level
        )

        # 控制参数（不落库）
        upsert_by_date = kwargs.pop("_upsert_by_date", False)
        update_id = kwargs.pop("_update_id", None)

        # 检查是否已存在（优先使用更安全的唯一键）
        existing = None
        rss_item_guid = kwargs.get("rss_item_guid")
        if update_id:
            existing = self._model.objects.filter(id=update_id).first()
        elif rss_item_guid:
            existing = self._model.objects.filter(rss_item_guid=rss_item_guid).first()
        elif upsert_by_date:
            # 兼容旧行为：按日期更新（仅用于明确更新场景）
            existing = self._model.objects.filter(event_date=event.event_date).first()
        else:
            # 默认安全行为：同日不同事件不应互相覆盖
            existing = self._model.objects.filter(
                event_date=event.event_date,
                title=event.title,
                evidence_url=event.evidence_url
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

        if return_orm:
            return orm_obj
        return self._orm_to_entity(orm_obj)

    def get_event_by_date(
        self,
        event_date: date
    ) -> Optional[PolicyEvent]:
        """
        按日期获取政策事件（返回第一个匹配）

        注意：如果同一天有多个事件，只返回第一个。
        如需获取全部，请使用 get_events_by_date 方法。

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

    def get_events_by_date(
        self,
        event_date: date
    ) -> List[PolicyEvent]:
        """
        按日期获取所有政策事件

        Args:
            event_date: 事件日期

        Returns:
            List[PolicyEvent]: 该日期的所有事件列表
        """
        query = self._model.objects.filter(
            event_date=event_date
        ).order_by('created_at')

        return [self._orm_to_entity(obj) for obj in query]

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

        重要：仅查询 event_type='policy' AND gate_effective=True 的事件。
        热点情绪事件（hotspot/sentiment）不影响政策档位。

        Args:
            as_of_date: 截止日期（None 表示最新）

        Returns:
            PolicyLevel: 当前政策档位
        """
        query = self._model.objects.filter(
            event_type='policy',
            gate_effective=True
        )

        if as_of_date:
            query = query.filter(event_date__lte=as_of_date)

        orm_obj = query.order_by('-event_date', '-effective_at').first()

        if orm_obj:
            return PolicyLevel(orm_obj.level)

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
        删除指定日期的所有事件

        警告：此方法会删除同一天的所有事件！
        如需删除单个事件，请使用 delete_event_by_id 方法。

        Args:
            event_date: 事件日期

        Returns:
            bool: 是否成功删除
        """
        count, _ = self._model.objects.filter(
            event_date=event_date
        ).delete()
        return count > 0

    def delete_event_by_id(self, event_id: int) -> bool:
        """
        按 ID 删除单个事件

        Args:
            event_id: 事件 ID

        Returns:
            bool: 是否成功删除
        """
        try:
            obj = self._model.objects.get(pk=event_id)
            obj.delete()
            return True
        except self._model.DoesNotExist:
            return False

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
        return PolicyLog._default_manager.filter(evidence_url=link).exists()

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


def get_policy_repository() -> DjangoPolicyRepository:
    """Backward-compatible repository factory."""
    return DjangoPolicyRepository()


class WorkbenchRepository:
    """
    工作台数据仓储

    提供工作台专用的数据访问操作。
    """

    def __init__(self):
        self._model = PolicyLog
        from .models import (
            PolicyIngestionConfig,
            SentimentGateConfig,
            GateActionAuditLog
        )
        self._ingestion_config_model = PolicyIngestionConfig
        self._gate_config_model = SentimentGateConfig
        self._audit_log_model = GateActionAuditLog

    # ========== 工作台事件查询 ==========

    def get_pending_review_events(
        self,
        event_type: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 50
    ) -> List[PolicyLog]:
        """
        获取待审核事件列表

        Args:
            event_type: 事件类型筛选（policy/hotspot/sentiment/mixed）
            level: 档位筛选（P0/P1/P2/P3）
            limit: 返回数量限制

        Returns:
            List[PolicyLog]: 待审核事件列表
        """
        query = self._model.objects.filter(
            audit_status='pending_review'
        )

        if event_type:
            query = query.filter(event_type=event_type)
        if level:
            query = query.filter(level=level)

        return list(query.order_by('-created_at')[:limit])

    def get_effective_events(
        self,
        event_type: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 50
    ) -> List[PolicyLog]:
        """
        获取已生效事件列表

        Args:
            event_type: 事件类型筛选
            start_date: 起始日期
            end_date: 结束日期
            limit: 返回数量限制

        Returns:
            List[PolicyLog]: 已生效事件列表
        """
        query = self._model.objects.filter(gate_effective=True)

        if event_type:
            query = query.filter(event_type=event_type)
        if start_date:
            query = query.filter(event_date__gte=start_date)
        if end_date:
            query = query.filter(event_date__lte=end_date)

        return list(query.order_by('-effective_at')[:limit])

    def get_pending_review_count(self) -> int:
        """获取待审核事件数量"""
        return self._model.objects.filter(audit_status='pending_review').count()

    def get_sla_exceeded_count(self, p23_sla_hours: int = 2, normal_sla_hours: int = 24) -> int:
        """
        获取 SLA 超时事件数量

        Args:
            p23_sla_hours: P2/P3 的 SLA 小时数
            normal_sla_hours: P0/P1 的 SLA 小时数

        Returns:
            int: 超时事件数量
        """
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()

        # P2/P3 超时
        p23_cutoff = now - timedelta(hours=p23_sla_hours)
        p23_count = self._model.objects.filter(
            audit_status='pending_review',
            level__in=['P2', 'P3'],
            created_at__lt=p23_cutoff
        ).count()

        # P0/P1 超时
        normal_cutoff = now - timedelta(hours=normal_sla_hours)
        normal_count = self._model.objects.filter(
            audit_status='pending_review',
            level__in=['P0', 'P1'],
            created_at__lt=normal_cutoff
        ).count()

        return p23_count + normal_count

    def get_global_heat_sentiment(self) -> tuple[Optional[float], Optional[float]]:
        """
        获取全局热度与情绪评分

        计算所有已生效热点情绪事件的平均热度与情绪

        Returns:
            tuple: (热度评分, 情绪评分)
        """
        from django.db.models import Avg

        effective_events = self._model.objects.filter(
            gate_effective=True,
            event_type__in=['hotspot', 'sentiment', 'mixed']
        )

        result = effective_events.aggregate(
            avg_heat=Avg('heat_score'),
            avg_sentiment=Avg('sentiment_score')
        )

        return result['avg_heat'], result['avg_sentiment']

    def get_effective_today_count(self) -> int:
        """获取今日生效事件数量"""
        from django.utils import timezone

        today = timezone.now().date()
        return self._model.objects.filter(
            gate_effective=True,
            effective_at__date=today
        ).count()

    # ========== 事件操作 ==========

    def approve_event(
        self,
        event_id: int,
        user_id: int,
        reason: str = ""
    ) -> Optional[PolicyLog]:
        """
        审核通过事件

        Args:
            event_id: 事件 ID
            user_id: 操作用户 ID
            reason: 审核原因

        Returns:
            PolicyLog: 更新后的事件，失败返回 None
        """
        try:
            event = self._model.objects.get(pk=event_id)
            before_state = self._get_event_state(event)

            event.gate_effective = True
            event.effective_at = timezone.now()
            event.effective_by_id = user_id
            event.audit_status = 'manual_approved'
            event.review_notes = reason
            event.save()

            after_state = self._get_event_state(event)
            self._create_audit_log(
                event=event,
                action='approve',
                operator_id=user_id,
                before_state=before_state,
                after_state=after_state,
                reason=reason
            )

            return event
        except self._model.DoesNotExist:
            return None

    def reject_event(
        self,
        event_id: int,
        user_id: int,
        reason: str
    ) -> Optional[PolicyLog]:
        """
        审核拒绝事件

        Args:
            event_id: 事件 ID
            user_id: 操作用户 ID
            reason: 拒绝原因（必填）

        Returns:
            PolicyLog: 更新后的事件，失败返回 None
        """
        try:
            event = self._model.objects.get(pk=event_id)
            before_state = self._get_event_state(event)

            event.audit_status = 'rejected'
            event.review_notes = reason
            event.reviewed_by_id = user_id
            event.reviewed_at = timezone.now()
            event.save()

            after_state = self._get_event_state(event)
            self._create_audit_log(
                event=event,
                action='reject',
                operator_id=user_id,
                before_state=before_state,
                after_state=after_state,
                reason=reason
            )

            return event
        except self._model.DoesNotExist:
            return None

    def rollback_event(
        self,
        event_id: int,
        user_id: int,
        reason: str
    ) -> Optional[PolicyLog]:
        """
        回滚事件生效状态

        Args:
            event_id: 事件 ID
            user_id: 操作用户 ID
            reason: 回滚原因（必填）

        Returns:
            PolicyLog: 更新后的事件，失败返回 None
        """
        try:
            event = self._model.objects.get(pk=event_id)
            before_state = self._get_event_state(event)

            event.gate_effective = False
            event.rollback_reason = reason
            event.save()

            after_state = self._get_event_state(event)
            self._create_audit_log(
                event=event,
                action='rollback',
                operator_id=user_id,
                before_state=before_state,
                after_state=after_state,
                reason=reason
            )

            return event
        except self._model.DoesNotExist:
            return None

    def override_event(
        self,
        event_id: int,
        user_id: int,
        reason: str,
        new_level: Optional[str] = None
    ) -> Optional[PolicyLog]:
        """
        临时豁免事件

        Args:
            event_id: 事件 ID
            user_id: 操作用户 ID
            reason: 豁免原因（必填）
            new_level: 新档位（可选）

        Returns:
            PolicyLog: 更新后的事件，失败返回 None
        """
        try:
            event = self._model.objects.get(pk=event_id)
            before_state = self._get_event_state(event)

            if new_level:
                event.level = new_level
            event.review_notes = f"[豁免] {reason}"
            event.save()

            after_state = self._get_event_state(event)
            self._create_audit_log(
                event=event,
                action='override',
                operator_id=user_id,
                before_state=before_state,
                after_state=after_state,
                reason=reason
            )

            return event
        except self._model.DoesNotExist:
            return None

    # ========== 配置管理 ==========

    def get_ingestion_config(self) -> 'PolicyIngestionConfig':
        """获取摄入配置（单例）"""
        return self._ingestion_config_model.get_config()

    def update_ingestion_config(self, **kwargs) -> 'PolicyIngestionConfig':
        """更新摄入配置"""
        config = self.get_ingestion_config()
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        config.version = (config.version or 0) + 1
        config.save()
        return config

    def get_gate_config(self, asset_class: str = 'all') -> Optional['SentimentGateConfig']:
        """获取闸门配置"""
        return self._gate_config_model.objects.filter(
            asset_class=asset_class,
            enabled=True
        ).first()

    def get_all_gate_configs(self) -> List['SentimentGateConfig']:
        """获取所有闸门配置"""
        return list(self._gate_config_model.objects.filter(enabled=True).all())

    # ========== 辅助方法 ==========

    def _get_event_state(self, event: PolicyLog) -> dict:
        """获取事件状态快照"""
        return {
            'level': event.level,
            'gate_level': event.gate_level,
            'gate_effective': event.gate_effective,
            'audit_status': event.audit_status,
            'effective_at': str(event.effective_at) if event.effective_at else None,
        }

    def _create_audit_log(
        self,
        event: PolicyLog,
        action: str,
        operator_id: Optional[int],
        before_state: dict,
        after_state: dict,
        reason: str
    ) -> 'GateActionAuditLog':
        """创建审计日志"""
        return self._audit_log_model.objects.create(
            event=event,
            action=action,
            operator_id=operator_id,
            before_state=before_state,
            after_state=after_state,
            reason=reason,
            rule_version='1.0'  # TODO: 从配置获取
        )


def get_workbench_repository() -> WorkbenchRepository:
    """工作台仓储工厂函数"""
    return WorkbenchRepository()

