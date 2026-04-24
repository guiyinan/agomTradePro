"""Infrastructure support repositories for policy interface consumers."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.db import models, transaction
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import (
    PolicyAuditQueue,
    PolicyLog,
    RSSFetchLog,
    RSSHubGlobalConfig,
    RSSSourceConfigModel,
    SentimentGateConfig,
)


class PolicyAdminInterfaceRepository:
    """Data access helpers used by the policy admin interface."""

    def bulk_update_policy_logs(
        self,
        policy_log_ids: list[int],
        **fields: Any,
    ) -> int:
        """Update one batch of policy log rows."""

        if not policy_log_ids:
            return 0
        return PolicyLog._default_manager.filter(id__in=policy_log_ids).update(**fields)

    def approve_policy_logs(
        self,
        policy_log_ids: list[int],
        *,
        reviewer_id: int,
    ) -> int:
        """Approve pending policy logs and clear audit queue rows."""

        if not policy_log_ids:
            return 0

        reviewed_at = timezone.now()
        with transaction.atomic():
            pending_ids = list(
                PolicyLog._default_manager.filter(
                    id__in=policy_log_ids,
                    audit_status="pending_review",
                ).values_list("id", flat=True)
            )
            if not pending_ids:
                return 0

            updated = PolicyLog._default_manager.filter(id__in=pending_ids).update(
                audit_status="manual_approved",
                reviewed_by_id=reviewer_id,
                reviewed_at=reviewed_at,
            )
            PolicyAuditQueue._default_manager.filter(policy_log_id__in=pending_ids).delete()
            return updated

    def reject_policy_logs(
        self,
        policy_log_ids: list[int],
        *,
        reviewer_id: int,
        review_notes: str,
    ) -> int:
        """Reject pending policy logs and clear audit queue rows."""

        if not policy_log_ids:
            return 0

        reviewed_at = timezone.now()
        with transaction.atomic():
            pending_ids = list(
                PolicyLog._default_manager.filter(
                    id__in=policy_log_ids,
                    audit_status="pending_review",
                ).values_list("id", flat=True)
            )
            if not pending_ids:
                return 0

            updated = PolicyLog._default_manager.filter(id__in=pending_ids).update(
                audit_status="rejected",
                reviewed_by_id=reviewer_id,
                reviewed_at=reviewed_at,
                review_notes=review_notes,
            )
            PolicyAuditQueue._default_manager.filter(policy_log_id__in=pending_ids).delete()
            return updated

    def get_policy_log_statistics(self) -> dict[str, Any]:
        """Return aggregate policy log statistics for admin rendering."""

        queryset = PolicyLog._default_manager.all()
        return {
            "total": queryset.count(),
            "level_counts": {
                row["level"]: row["count"]
                for row in queryset.values("level")
                .annotate(count=models.Count("id"))
                .order_by("level")
            },
            "category_counts": {
                row["info_category"]: row["count"]
                for row in queryset.values("info_category")
                .annotate(count=models.Count("id"))
                .order_by("info_category")
            },
            "audit_counts": {
                row["audit_status"]: row["count"]
                for row in queryset.values("audit_status")
                .annotate(count=models.Count("id"))
                .order_by("audit_status")
            },
        }

    def has_rsshub_global_config(self) -> bool:
        """Return whether the RSSHub singleton exists."""

        return RSSHubGlobalConfig._default_manager.exists()

    def get_rsshub_global_config_id(self) -> int | None:
        """Return the singleton config primary key when present."""

        return (
            RSSHubGlobalConfig._default_manager.values_list("pk", flat=True).first()
        )


class PolicyWorkbenchInterfaceRepository:
    """Data access helpers used by policy workbench interface views."""

    def list_active_source_options(self) -> list[dict[str, Any]]:
        """Return active RSS source options for workbench filters."""

        return list(
            RSSSourceConfigModel._default_manager.filter(is_active=True)
            .values("id", "name", "category")
            .order_by("name")
        )

    def get_workbench_filter_options(self) -> dict[str, Any]:
        """Return static and dynamic filter options for the workbench."""

        return {
            "event_types": [
                {"value": value, "label": label}
                for value, label in PolicyLog.EVENT_TYPE_CHOICES
            ],
            "levels": [
                {"value": value, "label": label}
                for value, label in PolicyLog.POLICY_LEVELS
            ],
            "gate_levels": [
                {"value": value, "label": label}
                for value, label in PolicyLog.GATE_LEVEL_CHOICES
            ],
            "asset_classes": ["equity", "bond", "commodity", "fx", "crypto", "all"],
            "sources": self.list_active_source_options(),
        }

    def get_recent_sentiment_trend(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Return the last 30d sentiment trend."""

        return list(
            PolicyLog._default_manager.filter(
                gate_effective=True,
                event_type__in=["hotspot", "sentiment", "mixed"],
                event_date__gte=start_date,
                event_date__lte=end_date,
            )
            .annotate(day=TruncDate("event_date"))
            .values("day")
            .annotate(
                avg_heat=models.Avg("heat_score"),
                avg_sentiment=models.Avg("sentiment_score"),
                count=models.Count("id"),
            )
            .order_by("day")
        )

    def get_recent_effective_events_trend(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Return effective event counts grouped by day and event type."""

        return list(
            PolicyLog._default_manager.filter(
                gate_effective=True,
                event_date__gte=start_date,
                event_date__lte=end_date,
            )
            .annotate(day=TruncDate("event_date"))
            .values("day", "event_type")
            .annotate(count=models.Count("id"))
            .order_by("day", "event_type")
        )

    def get_recent_fetch_errors(self, *, limit: int = 5) -> list[dict[str, Any]]:
        """Return recent RSS fetch failures."""

        return list(
            RSSFetchLog._default_manager.filter(status="error")
            .order_by("-fetched_at")[:limit]
            .values("fetched_at", "source__name", "error_message")
        )

    def get_latest_fetch_log(self) -> RSSFetchLog | None:
        """Return the latest RSS fetch log."""

        return RSSFetchLog._default_manager.select_related("source").order_by("-fetched_at").first()

    def get_trend_data(self) -> dict[str, Any]:
        """Return workbench trend payload for the recent 30 days."""

        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=30)
        return {
            "sentiment_recent_30d": self.get_recent_sentiment_trend(
                start_date=start_date,
                end_date=end_date,
            ),
            "effective_events_recent_30d": self.get_recent_effective_events_trend(
                start_date=start_date,
                end_date=end_date,
            ),
        }

    def get_fetch_status(self) -> dict[str, Any]:
        """Return current RSS fetch status payload."""

        last_fetch_log = self.get_latest_fetch_log()
        return {
            "last_fetch_at": last_fetch_log.fetched_at if last_fetch_log else None,
            "last_fetch_status": last_fetch_log.status if last_fetch_log else None,
            "recent_fetch_errors": self.get_recent_fetch_errors(),
        }

    def upsert_gate_config(
        self,
        *,
        payload: dict[str, Any],
        updated_by_id: int,
    ) -> tuple[SentimentGateConfig, bool]:
        """Create or update one sentiment gate config row."""

        asset_class = payload["asset_class"]
        with transaction.atomic():
            config = (
                SentimentGateConfig._default_manager.select_for_update()
                .filter(asset_class=asset_class)
                .first()
            )
            if config is None:
                config = SentimentGateConfig._default_manager.create(
                    **payload,
                    updated_by_id=updated_by_id,
                    version=1,
                )
                return config, True

            for key, value in payload.items():
                if key != "asset_class":
                    setattr(config, key, value)
            config.updated_by_id = updated_by_id
            config.version = (config.version or 0) + 1
            config.save()
            return config, False

    def get_workbench_item_detail(self, event_id: int) -> dict[str, Any] | None:
        """Return one workbench item detail payload."""

        event = (
            PolicyLog._default_manager.select_related(
                "rss_source",
                "effective_by",
                "reviewed_by",
            )
            .filter(pk=event_id)
            .first()
        )
        if event is None:
            return None

        return {
            "id": event.id,
            "event_date": event.event_date,
            "event_type": event.event_type,
            "level": event.level,
            "gate_level": event.gate_level,
            "title": event.title,
            "description": event.description,
            "evidence_url": event.evidence_url,
            "ai_confidence": event.ai_confidence,
            "heat_score": event.heat_score,
            "sentiment_score": event.sentiment_score,
            "structured_data": event.structured_data or {},
            "gate_effective": event.gate_effective,
            "effective_at": event.effective_at,
            "effective_by_id": event.effective_by_id,
            "effective_by_name": event.effective_by.username if event.effective_by else None,
            "audit_status": event.audit_status,
            "reviewed_by_id": event.reviewed_by_id,
            "reviewed_by_name": event.reviewed_by.username if event.reviewed_by else None,
            "reviewed_at": event.reviewed_at,
            "review_notes": event.review_notes or "",
            "asset_class": event.asset_class,
            "asset_scope": event.asset_scope or [],
            "rollback_reason": event.rollback_reason or "",
            "rss_source_id": event.rss_source_id,
            "rss_source_name": event.rss_source.name if event.rss_source else None,
            "rss_item_guid": event.rss_item_guid or "",
            "created_at": event.created_at,
        }
