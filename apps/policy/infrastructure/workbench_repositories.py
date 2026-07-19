"""Workbench-focused policy repositories."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.db import models, transaction
from django.utils import timezone

from .models import (
    GateActionAuditLog,
    PolicyAuditQueue,
    PolicyIngestionConfig,
    PolicyLog,
    RSSFetchLog,
    SentimentGateConfig,
)


class WorkbenchRepository:
    """
    工作台数据仓储

    提供工作台专用的数据访问操作。
    """

    def __init__(self):
        self._model = PolicyLog
        self._ingestion_config_model = PolicyIngestionConfig
        self._gate_config_model = SentimentGateConfig
        self._audit_log_model = GateActionAuditLog

    def get_pending_review_events(
        self,
        event_type: str | None = None,
        level: str | None = None,
        limit: int = 50,
    ) -> list[PolicyLog]:
        """获取待审核事件列表"""
        query = self._model.objects.filter(audit_status="pending_review")

        if event_type:
            query = query.filter(event_type=event_type)
        if level:
            query = query.filter(level=level)

        return list(query.order_by("-created_at")[:limit])

    def get_effective_events(
        self,
        event_type: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 50,
    ) -> list[PolicyLog]:
        """获取已生效事件列表"""
        query = self._model.objects.filter(gate_effective=True)

        if event_type:
            query = query.filter(event_type=event_type)
        if start_date:
            query = query.filter(event_date__gte=start_date)
        if end_date:
            query = query.filter(event_date__lte=end_date)

        return list(query.order_by("-effective_at")[:limit])

    def get_pending_review_count(self) -> int:
        """获取待审核事件数量"""
        return self._model.objects.filter(audit_status="pending_review").count()

    def list_audit_queue_items(
        self,
        *,
        assigned_user_id: int,
        status: str = "pending_review",
        priority: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return assigned audit queue items for one reviewer."""
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
                "rss_source": item.policy_log.rss_source.name if item.policy_log.rss_source else None,
            }
            for item in rows
        ]

    def list_unassigned_audit_queue_ids(self) -> list[int]:
        """Return pending unassigned audit queue ids ordered by recency."""
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
            User._default_manager.filter(is_staff=True).values_list("id", flat=True).distinct()
        )

    def get_pending_assignment_counts(self, auditor_ids: list[int]) -> dict[int, int]:
        """Return pending assignment counts keyed by auditor id."""
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
        return PolicyAuditQueue._default_manager.filter(
            policy_log__reviewed_at__lt=cutoff_datetime
        ).delete()[0]

    def get_sla_exceeded_count(self, p23_sla_hours: int = 2, normal_sla_hours: int = 24) -> int:
        """获取 SLA 超时事件数量"""
        now = timezone.now()
        p23_cutoff = now - timedelta(hours=p23_sla_hours)
        p23_count = self._model.objects.filter(
            audit_status="pending_review",
            level__in=["P2", "P3"],
            created_at__lt=p23_cutoff,
        ).count()

        normal_cutoff = now - timedelta(hours=normal_sla_hours)
        normal_count = self._model.objects.filter(
            audit_status="pending_review",
            level__in=["P0", "P1"],
            created_at__lt=normal_cutoff,
        ).count()
        return p23_count + normal_count

    def get_sla_exceeded_breakdown(
        self,
        *,
        p23_sla_hours: int = 2,
        normal_sla_hours: int = 24,
    ) -> dict[str, int]:
        """Return SLA-exceeded counts split by severity bucket."""
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
        """获取全局热度与情绪评分"""
        from django.db.models import Avg

        effective_events = self._model.objects.filter(
            gate_effective=True,
            event_type__in=["hotspot", "sentiment", "mixed"],
        )
        result = effective_events.aggregate(
            avg_heat=Avg("heat_score"),
            avg_sentiment=Avg("sentiment_score"),
        )
        return result["avg_heat"], result["avg_sentiment"]

    def get_effective_today_count(self) -> int:
        """获取今日生效事件数量"""
        today = timezone.now().date()
        return self._model.objects.filter(gate_effective=True, effective_at__date=today).count()

    def get_daily_policy_summary(self, target_date: date) -> dict[str, Any]:
        """Return daily policy summary grouped by level/category/audit status."""
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
                models.Q(title__icontains=search) | models.Q(description__icontains=search)
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

    def approve_event(
        self,
        event_id: int,
        user_id: int,
        reason: str = "",
    ) -> PolicyLog | None:
        """审核通过事件"""
        try:
            event = self._model.objects.get(pk=event_id)
            before_state = self._get_event_state(event)

            event.gate_effective = True
            event.effective_at = timezone.now()
            event.effective_by_id = user_id
            event.audit_status = "manual_approved"
            event.review_notes = reason
            event.save()

            after_state = self._get_event_state(event)
            self._create_audit_log(
                event=event,
                action="approve",
                operator_id=user_id,
                before_state=before_state,
                after_state=after_state,
                reason=reason,
            )
            return event
        except self._model.DoesNotExist:
            return None

    def reject_event(
        self,
        event_id: int,
        user_id: int,
        reason: str,
    ) -> PolicyLog | None:
        """审核拒绝事件"""
        try:
            event = self._model.objects.get(pk=event_id)
            before_state = self._get_event_state(event)

            event.audit_status = "rejected"
            event.review_notes = reason
            event.reviewed_by_id = user_id
            event.reviewed_at = timezone.now()
            event.save()

            after_state = self._get_event_state(event)
            self._create_audit_log(
                event=event,
                action="reject",
                operator_id=user_id,
                before_state=before_state,
                after_state=after_state,
                reason=reason,
            )
            return event
        except self._model.DoesNotExist:
            return None

    def rollback_event(
        self,
        event_id: int,
        user_id: int,
        reason: str,
    ) -> PolicyLog | None:
        """回滚事件生效状态"""
        try:
            event = self._model.objects.get(pk=event_id)
            before_state = self._get_event_state(event)

            event.gate_effective = False
            event.rollback_reason = reason
            event.save()

            after_state = self._get_event_state(event)
            self._create_audit_log(
                event=event,
                action="rollback",
                operator_id=user_id,
                before_state=before_state,
                after_state=after_state,
                reason=reason,
            )
            return event
        except self._model.DoesNotExist:
            return None

    def override_event(
        self,
        event_id: int,
        user_id: int,
        reason: str,
        new_level: str | None = None,
    ) -> PolicyLog | None:
        """临时豁免事件"""
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
                action="override",
                operator_id=user_id,
                before_state=before_state,
                after_state=after_state,
                reason=reason,
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

    def get_ingestion_config(self) -> PolicyIngestionConfig:
        """获取摄入配置（单例）"""
        return self._ingestion_config_model.get_config()

    def update_ingestion_config(self, **kwargs) -> PolicyIngestionConfig:
        """更新摄入配置"""
        config = self.get_ingestion_config()
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        config.version = (config.version or 0) + 1
        config.save()
        return config

    def get_gate_config(self, asset_class: str = "all") -> SentimentGateConfig | None:
        """获取闸门配置"""
        return self._gate_config_model.objects.filter(asset_class=asset_class, enabled=True).first()

    def get_all_gate_configs(self) -> list[SentimentGateConfig]:
        """获取所有闸门配置"""
        return list(self._gate_config_model.objects.filter(enabled=True).all())

    def _get_event_state(self, event: PolicyLog) -> dict:
        """获取事件状态快照"""
        return {
            "level": event.level,
            "gate_level": event.gate_level,
            "gate_effective": event.gate_effective,
            "audit_status": event.audit_status,
            "effective_at": str(event.effective_at) if event.effective_at else None,
        }

    def _create_audit_log(
        self,
        event: PolicyLog,
        action: str,
        operator_id: int | None,
        before_state: dict,
        after_state: dict,
        reason: str,
        rule_version: str = "1.0",
    ) -> GateActionAuditLog:
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
