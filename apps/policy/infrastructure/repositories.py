"""
Repositories for Policy Events.

Infrastructure layer implementation using Django ORM.
"""

from datetime import date
from typing import Any, Optional

from django.db import models, transaction
from django.utils import timezone

from ..domain.entities import PolicyEvent, PolicyLevel, PolicyLevelKeywordRule
from .models import PolicyLevelKeywordModel, PolicyLog, RSSFetchLog, RSSSourceConfigModel


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
    ) -> PolicyEvent | None:
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
    ) -> list[PolicyEvent]:
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
        before_date: date | None = None
    ) -> PolicyEvent | None:
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
    ) -> list[PolicyEvent]:
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
        start_date: date | None = None,
        end_date: date | None = None
    ) -> list[PolicyEvent]:
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
        as_of_date: date | None = None
    ) -> PolicyLevel:
        """
        获取当前政策档位

        重要：查询所有已生效事件（gate_effective=True），包括 policy/hotspot/sentiment/mixed。
        任何类型的已生效事件都会影响政策档位。

        Args:
            as_of_date: 截止日期（None 表示最新）

        Returns:
            PolicyLevel: 当前政策档位
        """
        query = self._model.objects.filter(
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
        as_of_date: date | None = None
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
        as_of_date: date | None = None
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
        start_date: date | None = None,
        end_date: date | None = None
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

    def delete_events_before(self, cutoff_date: date) -> int:
        """Delete policy events older than the cutoff date."""

        return self._model._default_manager.filter(event_date__lt=cutoff_date).delete()[0]

    def get_category_stats(self) -> dict[str, int]:
        """Return aggregate counts grouped by info category."""

        return self._model._default_manager.aggregate(
            macro=models.Count("id", filter=models.Q(info_category="macro")),
            sector=models.Count("id", filter=models.Q(info_category="sector")),
            individual=models.Count("id", filter=models.Q(info_category="individual")),
            sentiment=models.Count("id", filter=models.Q(info_category="sentiment")),
            other=models.Count("id", filter=models.Q(info_category="other")),
        )

    def list_blacklist_policies(self, asset_code: str) -> list[dict[str, Any]]:
        """Return blacklist and high-risk macro policies affecting one asset."""

        direct_blacklist = list(
            self._model._default_manager.filter(
                is_blacklist=True,
                structured_data__affected_stocks__contains=asset_code,
            ).values("id", "title", "level", "info_category", "structured_data")
        )
        high_risk_macro = list(
            self._model._default_manager.filter(
                info_category="macro",
                level__in=["P2", "P3"],
                risk_impact="high_risk",
            ).values("id", "title", "level", "info_category", "structured_data")
        )
        return direct_blacklist + high_risk_macro

    def list_whitelist_policies(self, asset_code: str) -> list[dict[str, Any]]:
        """Return whitelist policies affecting one asset."""

        return list(
            self._model._default_manager.filter(
                is_whitelist=True,
                structured_data__affected_stocks__contains=asset_code,
            ).values("id", "title", "level", "info_category", "structured_data")
        )

    def list_recent_sector_policies(self, cutoff_datetime) -> list[dict[str, Any]]:
        """Return recent approved sector policies."""

        return list(
            self._model._default_manager.filter(
                info_category="sector",
                audit_status__in=["auto_approved", "manual_approved"],
                created_at__gte=cutoff_datetime,
            ).values("id", "title", "level", "info_category", "structured_data")
        )

    def list_recent_sentiment_policies(
        self,
        *,
        asset_code: str,
        cutoff_datetime,
    ) -> list[dict[str, Any]]:
        """Return recent approved individual sentiment policies for one asset."""

        return list(
            self._model._default_manager.filter(
                info_category="individual",
                audit_status__in=["auto_approved", "manual_approved"],
                structured_data__affected_stocks__contains=asset_code,
                created_at__gte=cutoff_datetime,
            ).values("id", "title", "level", "info_category", "structured_data")
        )

    def get_existing_for_update(
        self,
        event_id: int | None = None,
        event_date: date | None = None
    ) -> dict | None:
        """
        获取现有事件用于更新检查

        Args:
            event_id: 事件 ID（优先使用）
            event_date: 事件日期（当 event_id 为 None 时使用）

        Returns:
            Optional[dict]: 包含 id, event_date 的字典，不存在则返回 None
        """
        if event_id is not None:
            obj = self._model.objects.filter(id=event_id).first()
        elif event_date is not None:
            obj = self._model.objects.filter(event_date=event_date).first()
        else:
            return None

        if obj:
            return {
                'id': obj.id,
                'event_date': obj.event_date,
            }
        return None

    def create_raw_rss_policy_log(
        self,
        *,
        event_date: date,
        title: str,
        description: str,
        evidence_url: str,
        rss_source_id: int,
        rss_item_guid: str,
        processing_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create the initial raw RSS policy log row before classification."""

        orm_obj = self._model._default_manager.create(
            event_date=event_date,
            level="PX",
            title=title,
            description=description,
            evidence_url=evidence_url,
            info_category="other",
            audit_status="pending_review",
            ai_confidence=None,
            structured_data={},
            risk_impact="unknown",
            rss_source_id=rss_source_id,
            rss_item_guid=rss_item_guid,
            processing_metadata=processing_metadata or {"processing_stage": "raw_ingested"},
        )
        return {
            "id": orm_obj.id,
            "processing_metadata": orm_obj.processing_metadata or {},
        }

    def update_policy_log_fields(self, policy_log_id: int, **fields) -> bool:
        """Update one policy log row by id."""

        return self._model._default_manager.filter(id=policy_log_id).update(**fields) > 0

    def append_policy_log_processing_metadata(
        self,
        policy_log_id: int,
        metadata: dict[str, Any],
    ) -> bool:
        """Merge processing metadata onto an existing policy log row."""

        orm_obj = self._model._default_manager.filter(id=policy_log_id).first()
        if orm_obj is None:
            return False

        orm_obj.processing_metadata = {
            **(orm_obj.processing_metadata or {}),
            **metadata,
        }
        orm_obj.save(update_fields=["processing_metadata"])
        return True

    def ensure_audit_queue_item(
        self,
        *,
        policy_log_id: int,
        priority: str,
    ) -> dict[str, Any]:
        """Ensure one audit queue row exists for a policy log."""

        from .models import PolicyAuditQueue

        queue_item, created = PolicyAuditQueue._default_manager.get_or_create(
            policy_log_id=policy_log_id,
            defaults={"priority": priority},
        )
        return {"id": queue_item.id, "created": created}

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

    def get_active_sources(self) -> list[RSSSourceConfigModel]:
        """获取所有启用的RSS源"""
        return list(self._source_model.objects.filter(is_active=True).all())

    def get_source_by_id(self, source_id: int) -> RSSSourceConfigModel | None:
        """根据ID获取RSS源"""
        return self._source_model.objects.filter(id=source_id).first()

    def get_all_sources(self) -> list[RSSSourceConfigModel]:
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
        source_id: int | None = None,
        limit: int = 100
    ) -> list[RSSFetchLog]:
        """获取抓取日志"""
        query = self._log_model.objects.all()
        if source_id:
            query = query.filter(source_id=source_id)
        return list(query.order_by('-fetched_at')[:limit])

    def cleanup_old_logs(self, days_to_keep: int = 90) -> int:
        """清理旧的抓取日志"""
        from datetime import timedelta

        from django.utils import timezone

        cutoff = timezone.now() - timedelta(days=days_to_keep)
        count, _ = self._log_model.objects.filter(fetched_at__lt=cutoff).delete()
        return count

    # ========== 去重检查 ==========

    def is_item_exists(self, link: str, guid: str | None = None) -> bool:
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
        category: str | None = None
    ) -> list[PolicyLevelKeywordRule]:
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
        from .models import GateActionAuditLog, PolicyIngestionConfig, SentimentGateConfig
        self._ingestion_config_model = PolicyIngestionConfig
        self._gate_config_model = SentimentGateConfig
        self._audit_log_model = GateActionAuditLog

    # ========== 工作台事件查询 ==========

    def get_pending_review_events(
        self,
        event_type: str | None = None,
        level: str | None = None,
        limit: int = 50
    ) -> list[PolicyLog]:
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
        event_type: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 50
    ) -> list[PolicyLog]:
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

    def list_audit_queue_items(
        self,
        *,
        assigned_user_id: int,
        status: str = "pending_review",
        priority: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return assigned audit queue items for one reviewer."""

        from .models import PolicyAuditQueue

        queryset = PolicyAuditQueue._default_manager.filter(
            policy_log__audit_status=status,
            assigned_to_id=assigned_user_id,
        ).select_related("policy_log", "assigned_to")

        if priority:
            queryset = queryset.filter(priority=priority)

        priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
        rows = list(queryset[:limit])
        rows.sort(key=lambda item: priority_order.get(item.priority, 99))

        return [
            {
                "id": item.policy_log.id,
                "title": item.policy_log.title,
                "description": item.policy_log.description[:200] + "..."
                if len(item.policy_log.description) > 200
                else item.policy_log.description,
                "level": item.policy_log.level,
                "info_category": item.policy_log.info_category,
                "ai_confidence": item.policy_log.ai_confidence,
                "structured_data": item.policy_log.structured_data,
                "priority": item.priority,
                "created_at": item.policy_log.created_at.isoformat(),
                "assigned_at": item.assigned_at.isoformat() if item.assigned_at else None,
                "rss_source": item.policy_log.rss_source.name
                if item.policy_log.rss_source
                else None,
            }
            for item in rows
        ]

    def list_unassigned_audit_queue_ids(self) -> list[int]:
        """Return pending unassigned audit queue ids ordered by recency."""

        from .models import PolicyAuditQueue

        return list(
            PolicyAuditQueue._default_manager.filter(
                assigned_to__isnull=True,
                policy_log__audit_status="pending_review",
            )
            .order_by("-created_at")
            .values_list("id", flat=True)
        )

    def list_staff_auditor_ids(self) -> list[int]:
        """Return staff user ids eligible for audit assignment."""

        from django.contrib.auth.models import User

        return list(
            User._default_manager.filter(is_staff=True)
            .values_list("id", flat=True)
            .distinct()
        )

    def get_pending_assignment_counts(self, auditor_ids: list[int]) -> dict[int, int]:
        """Return pending assignment counts keyed by auditor id."""

        from .models import PolicyAuditQueue

        if not auditor_ids:
            return {}

        rows = (
            PolicyAuditQueue._default_manager.filter(
                assigned_to_id__in=auditor_ids,
                policy_log__audit_status="pending_review",
            )
            .values("assigned_to_id")
            .annotate(count=models.Count("id"))
        )
        return {row["assigned_to_id"]: row["count"] for row in rows}

    def assign_audit_queue_item(
        self,
        *,
        queue_id: int,
        auditor_id: int,
        assigned_at,
    ) -> bool:
        """Assign one audit queue item to an auditor."""

        from .models import PolicyAuditQueue

        updated = PolicyAuditQueue._default_manager.filter(
            id=queue_id,
            assigned_to__isnull=True,
            policy_log__audit_status="pending_review",
        ).update(
            assigned_to_id=auditor_id,
            assigned_at=assigned_at,
        )
        return updated > 0

    def delete_reviewed_queue_before(self, cutoff_datetime) -> int:
        """Delete audit queue rows whose related policy was reviewed before cutoff."""

        from .models import PolicyAuditQueue

        return PolicyAuditQueue._default_manager.filter(
            policy_log__reviewed_at__lt=cutoff_datetime
        ).delete()[0]

    def get_sla_exceeded_count(self, p23_sla_hours: int = 2, normal_sla_hours: int = 24) -> int:
        """
        获取 SLA 超时事件数量

        Args:
            p23_sla_hours: P2/P3 的 SLA 小时数
            normal_sla_hours: P0/P1 的 SLA 小时数

        Returns:
            int: 超时事件数量
        """
        from datetime import timedelta

        from django.utils import timezone

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

    def get_sla_exceeded_breakdown(
        self,
        *,
        p23_sla_hours: int = 2,
        normal_sla_hours: int = 24,
    ) -> dict[str, int]:
        """Return SLA-exceeded counts split by severity bucket."""

        from datetime import timedelta

        now = timezone.now()
        p23_cutoff = now - timedelta(hours=p23_sla_hours)
        normal_cutoff = now - timedelta(hours=normal_sla_hours)

        p23_count = self._model.objects.filter(
            audit_status="pending_review",
            level__in=["P2", "P3"],
            created_at__lt=p23_cutoff,
        ).count()
        normal_count = self._model.objects.filter(
            audit_status="pending_review",
            level__in=["P0", "P1"],
            created_at__lt=normal_cutoff,
        ).count()
        return {
            "p23_exceeded": p23_count,
            "normal_exceeded": normal_count,
            "total_exceeded": p23_count + normal_count,
        }

    def get_global_heat_sentiment(self) -> tuple[float | None, float | None]:
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

    def get_daily_policy_summary(self, target_date: date) -> dict[str, Any]:
        """Return daily policy summary grouped by level/category/audit status."""

        from .models import PolicyAuditQueue

        today_policies = self._model._default_manager.filter(created_at__date=target_date)
        summary = {
            "date": target_date.isoformat(),
            "total_new": today_policies.count(),
            "by_level": {},
            "by_category": {},
            "by_audit_status": {},
            "pending_review": PolicyAuditQueue._default_manager.filter(
                policy_log__audit_status="pending_review"
            ).count(),
            "ai_classified": today_policies.filter(
                models.Q(audit_status="auto_approved") | models.Q(audit_status="pending_review"),
                ai_confidence__isnull=False,
            ).count(),
        }

        for level_code, level_name in self._model.POLICY_LEVELS:
            count = today_policies.filter(level=level_code).count()
            if count > 0:
                summary["by_level"][level_name] = count

        for cat_code, cat_name in self._model.INFO_CATEGORY_CHOICES:
            count = today_policies.filter(info_category=cat_code).count()
            if count > 0:
                summary["by_category"][cat_name] = count

        for status_code, status_name in self._model.AUDIT_STATUS_CHOICES:
            count = today_policies.filter(audit_status=status_code).count()
            if count > 0:
                summary["by_audit_status"][status_name] = count

        return summary

    def get_latest_effective_policy_title(self) -> str | None:
        """Return the title of the latest effective policy event."""

        return (
            self._model._default_manager.filter(event_type="policy", gate_effective=True)
            .order_by("-event_date", "-effective_at")
            .values_list("title", flat=True)
            .first()
        )

    def get_last_fetch_at(self):
        """Return the latest RSS fetch timestamp."""

        return (
            RSSFetchLog._default_manager.order_by("-fetched_at")
            .values_list("fetched_at", flat=True)
            .first()
        )

    def list_workbench_items(
        self,
        *,
        tab: str = "pending",
        event_type: str | None = None,
        level: str | None = None,
        gate_level: str | None = None,
        asset_class: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return filtered workbench items and total count."""

        query = self._model._default_manager.all()

        if tab == "pending":
            query = query.filter(audit_status="pending_review")
        elif tab == "effective":
            query = query.filter(gate_effective=True)

        if event_type:
            query = query.filter(event_type=event_type)
        if level:
            query = query.filter(level=level)
        if gate_level:
            query = query.filter(gate_level=gate_level)
        if asset_class:
            query = query.filter(asset_class=asset_class)
        if start_date:
            query = query.filter(event_date__gte=start_date)
        if end_date:
            query = query.filter(event_date__lte=end_date)
        if search:
            query = query.filter(
                models.Q(title__icontains=search)
                | models.Q(description__icontains=search)
            )

        if tab == "pending":
            query = query.order_by("-created_at")
        elif tab == "effective":
            query = query.order_by("-effective_at")
        else:
            query = query.order_by("-event_date", "-created_at")

        total = query.count()
        items = query[offset : offset + limit]

        return {
            "total": total,
            "items": [
                {
                    "id": item.id,
                    "event_date": item.event_date.isoformat() if item.event_date else None,
                    "event_type": item.event_type,
                    "level": item.level,
                    "gate_level": item.gate_level,
                    "title": item.title,
                    "description": item.description[:200] + "..."
                    if len(item.description) > 200
                    else item.description,
                    "evidence_url": item.evidence_url,
                    "ai_confidence": item.ai_confidence,
                    "heat_score": item.heat_score,
                    "sentiment_score": item.sentiment_score,
                    "gate_effective": item.gate_effective,
                    "asset_class": item.asset_class,
                    "asset_scope": item.asset_scope,
                    "audit_status": item.audit_status,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "effective_at": item.effective_at.isoformat() if item.effective_at else None,
                    "effective_by_id": item.effective_by_id,
                    "review_notes": item.review_notes,
                    "rollback_reason": item.rollback_reason,
                }
                for item in items
            ],
        }

    # ========== 事件操作 ==========

    def approve_event(
        self,
        event_id: int,
        user_id: int,
        reason: str = ""
    ) -> PolicyLog | None:
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
    ) -> PolicyLog | None:
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
    ) -> PolicyLog | None:
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
        new_level: str | None = None
    ) -> PolicyLog | None:
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

    def review_policy_item(
        self,
        *,
        policy_log_id: int,
        approved: bool,
        reviewer_id: int,
        notes: str = "",
        modifications: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Approve or reject one pending policy item and clear its audit queue rows."""

        from .models import PolicyAuditQueue

        event = self._model._default_manager.filter(id=policy_log_id).first()
        if event is None:
            return None

        with transaction.atomic():
            update_fields = ["audit_status", "reviewed_by_id", "reviewed_at", "review_notes"]
            event.reviewed_by_id = reviewer_id
            event.reviewed_at = timezone.now()

            if approved:
                event.audit_status = "manual_approved"
                event.review_notes = notes
                if modifications:
                    structured_data = dict(event.structured_data or {})
                    structured_data.update(modifications)
                    event.structured_data = structured_data
                    update_fields.append("structured_data")
            else:
                event.audit_status = "rejected"
                event.review_notes = notes or "人工拒绝"

            event.save(update_fields=update_fields)
            PolicyAuditQueue._default_manager.filter(policy_log_id=event.id).delete()

        return {"id": event.id, "audit_status": event.audit_status}

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

    def get_all_gate_configs(self) -> list['SentimentGateConfig']:
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
        operator_id: int | None,
        before_state: dict,
        after_state: dict,
        reason: str,
        rule_version: str = '1.0',
    ) -> 'GateActionAuditLog':
        """创建审计日志"""
        return self._audit_log_model.objects.create(
            event=event,
            action=action,
            operator_id=operator_id,
            before_state=before_state,
            after_state=after_state,
            reason=reason,
            rule_version=rule_version,
        )


def get_workbench_repository() -> WorkbenchRepository:
    """工作台仓储工厂函数"""
    return WorkbenchRepository()


class HedgePositionRepository:
    """Repository for hedge position records."""

    def create_hedge_position(
        self,
        *,
        portfolio_id: int,
        instrument_code: str,
        instrument_type: str,
        hedge_ratio: float,
        hedge_value,
        policy_level: str,
        status: str,
        notes: str,
        execution_price=None,
        opening_cost=None,
        total_cost=None,
        executed_at=None,
    ) -> dict[str, Any]:
        """Create one hedge position row and return a lightweight snapshot."""

        from .models import HedgePositionModel

        hedge = HedgePositionModel._default_manager.create(
            portfolio_id=portfolio_id,
            instrument_code=instrument_code,
            instrument_type=instrument_type,
            hedge_ratio=hedge_ratio,
            hedge_value=hedge_value,
            policy_level=policy_level,
            status=status,
            notes=notes,
            execution_price=execution_price,
            opening_cost=opening_cost,
            total_cost=total_cost,
            executed_at=executed_at,
        )
        return {
            "id": hedge.id,
            "instrument_code": hedge.instrument_code,
            "hedge_ratio": hedge.hedge_ratio,
            "hedge_value": hedge.hedge_value,
            "execution_price": hedge.execution_price,
            "status": hedge.status,
            "executed_at": hedge.executed_at,
            "total_cost": hedge.total_cost,
            "opening_cost": hedge.opening_cost,
            "closing_cost": hedge.closing_cost,
            "beta_before": hedge.beta_before,
            "beta_after": hedge.beta_after,
            "hedge_profit": hedge.hedge_profit,
        }

    def get_hedge_position(self, *, hedge_id: int, portfolio_id: int) -> dict[str, Any] | None:
        """Return one hedge position snapshot by id and portfolio."""

        from .models import HedgePositionModel

        hedge = HedgePositionModel._default_manager.filter(
            id=hedge_id,
            portfolio_id=portfolio_id,
        ).first()
        if hedge is None:
            return None
        return {
            "id": hedge.id,
            "portfolio_id": hedge.portfolio_id,
            "instrument_code": hedge.instrument_code,
            "instrument_type": hedge.instrument_type,
            "hedge_ratio": hedge.hedge_ratio,
            "hedge_value": hedge.hedge_value,
            "policy_level": hedge.policy_level,
            "status": hedge.status,
            "execution_price": hedge.execution_price,
            "executed_at": hedge.executed_at,
            "opening_cost": hedge.opening_cost,
            "closing_cost": hedge.closing_cost,
            "total_cost": hedge.total_cost,
            "beta_before": hedge.beta_before,
            "beta_after": hedge.beta_after,
            "hedge_profit": hedge.hedge_profit,
            "notes": hedge.notes,
        }

    def update_beta_metrics(
        self,
        *,
        hedge_id: int,
        beta_before: float,
        beta_after: float,
    ) -> bool:
        """Persist computed beta metrics for one hedge position."""

        from .models import HedgePositionModel

        return HedgePositionModel._default_manager.filter(id=hedge_id).update(
            beta_before=beta_before,
            beta_after=beta_after,
        ) > 0

