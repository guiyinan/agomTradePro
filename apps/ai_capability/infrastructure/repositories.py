"""
AI Capability Catalog Infrastructure Repositories.
"""

from datetime import UTC, datetime, timezone
from typing import Any, List, Optional

from django.contrib.auth import get_user_model
from django.db import transaction

from ..domain.entities import (
    CapabilityDefinition,
    CapabilityRoutingLog,
    CapabilitySyncLog,
)
from .models import (
    CapabilityCatalogModel,
    CapabilityRoutingLogModel,
    CapabilitySyncLogModel,
)


class DjangoCapabilityRepository:
    """Django ORM implementation of capability repository."""

    def list_capabilities(
        self,
        *,
        source_type: str | None = None,
        route_group: str | None = None,
        category: str | None = None,
        enabled_only: bool = True,
    ) -> list[CapabilityDefinition]:
        """List capabilities with optional filters."""
        models = CapabilityCatalogModel.objects.all()

        if enabled_only:
            models = models.filter(enabled_for_routing=True)
        if source_type:
            models = models.filter(source_type=source_type)
        if route_group:
            models = models.filter(route_group=route_group)
        if category:
            models = models.filter(category=category)

        return [m.to_entity() for m in models]

    def get_by_key(self, capability_key: str) -> CapabilityDefinition | None:
        """Get a capability by its key."""
        try:
            model = CapabilityCatalogModel.objects.get(capability_key=capability_key)
            return model.to_entity()
        except CapabilityCatalogModel.DoesNotExist:
            return None

    def get_all_enabled(self) -> list[CapabilityDefinition]:
        """Get all enabled capabilities."""
        return self.list_capabilities(enabled_only=True)

    def get_by_source_type(self, source_type: str) -> list[CapabilityDefinition]:
        """Get capabilities by source type."""
        return self.list_capabilities(source_type=source_type, enabled_only=False)

    def get_by_route_group(self, route_group: str) -> list[CapabilityDefinition]:
        """Get capabilities by route group."""
        return self.list_capabilities(route_group=route_group, enabled_only=False)

    def get_all_for_routing(self) -> list[CapabilityDefinition]:
        """Get all capabilities eligible for routing."""
        return self.list_capabilities(enabled_only=True)

    def save(self, capability: CapabilityDefinition) -> CapabilityDefinition:
        """Save a capability (upsert by key)."""
        now = datetime.now(UTC)
        model, created = CapabilityCatalogModel.objects.update_or_create(
            capability_key=capability.capability_key,
            defaults={
                "source_type": capability.source_type.value,
                "source_ref": capability.source_ref,
                "name": capability.name,
                "summary": capability.summary,
                "description": capability.description,
                "route_group": capability.route_group.value,
                "category": capability.category,
                "tags": list(capability.tags),
                "when_to_use": list(capability.when_to_use),
                "when_not_to_use": list(capability.when_not_to_use),
                "examples": list(capability.examples),
                "input_schema": dict(capability.input_schema),
                "execution_kind": capability.execution_kind.value,
                "execution_target": dict(capability.execution_target),
                "risk_level": capability.risk_level.value,
                "requires_mcp": capability.requires_mcp,
                "requires_confirmation": capability.requires_confirmation,
                "enabled_for_routing": capability.enabled_for_routing,
                "enabled_for_terminal": capability.enabled_for_terminal,
                "enabled_for_chat": capability.enabled_for_chat,
                "enabled_for_agent": capability.enabled_for_agent,
                "visibility": capability.visibility.value,
                "auto_collected": capability.auto_collected,
                "review_status": capability.review_status.value,
                "priority_weight": capability.priority_weight,
                "last_synced_at": now,
            },
        )
        return model.to_entity()

    def bulk_upsert(
        self,
        capabilities: list[CapabilityDefinition],
    ) -> dict[str, int]:
        """Bulk upsert capabilities. Returns counts."""
        created_count = 0
        updated_count = 0
        now = datetime.now(UTC)

        with transaction.atomic():
            for cap in capabilities:
                _, created = CapabilityCatalogModel.objects.update_or_create(
                    capability_key=cap.capability_key,
                    defaults={
                        "source_type": cap.source_type.value,
                        "source_ref": cap.source_ref,
                        "name": cap.name,
                        "summary": cap.summary,
                        "description": cap.description,
                        "route_group": cap.route_group.value,
                        "category": cap.category,
                        "tags": list(cap.tags),
                        "when_to_use": list(cap.when_to_use),
                        "when_not_to_use": list(cap.when_not_to_use),
                        "examples": list(cap.examples),
                        "input_schema": dict(cap.input_schema),
                        "execution_kind": cap.execution_kind.value,
                        "execution_target": dict(cap.execution_target),
                        "risk_level": cap.risk_level.value,
                        "requires_mcp": cap.requires_mcp,
                        "requires_confirmation": cap.requires_confirmation,
                        "enabled_for_routing": cap.enabled_for_routing,
                        "enabled_for_terminal": cap.enabled_for_terminal,
                        "enabled_for_chat": cap.enabled_for_chat,
                        "enabled_for_agent": cap.enabled_for_agent,
                        "visibility": cap.visibility.value,
                        "auto_collected": cap.auto_collected,
                        "review_status": cap.review_status.value,
                        "priority_weight": cap.priority_weight,
                        "last_synced_at": now,
                    },
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

        return {
            "created": created_count,
            "updated": updated_count,
            "total": created_count + updated_count,
        }

    def disable_missing(
        self,
        source_type: str,
        existing_keys: list[str],
    ) -> int:
        """Disable capabilities that are no longer in source."""
        qs = CapabilityCatalogModel.objects.filter(
            source_type=source_type,
        ).exclude(
            capability_key__in=existing_keys,
        )
        count = qs.count()
        qs.update(enabled_for_routing=False)
        return count

    def get_stats(self) -> dict[str, Any]:
        """Get catalog statistics."""
        total = CapabilityCatalogModel.objects.count()
        enabled = CapabilityCatalogModel.objects.filter(enabled_for_routing=True).count()

        by_source = {}
        for source_type in ["builtin", "terminal_command", "mcp_tool", "api"]:
            by_source[source_type] = CapabilityCatalogModel.objects.filter(
                source_type=source_type,
            ).count()

        by_route_group = {}
        for route_group in ["builtin", "tool", "read_api", "write_api", "unsafe_api"]:
            by_route_group[route_group] = CapabilityCatalogModel.objects.filter(
                route_group=route_group,
            ).count()

        return {
            "total": total,
            "enabled": enabled,
            "disabled": total - enabled,
            "by_source": by_source,
            "by_route_group": by_route_group,
        }


class DjangoRoutingLogRepository:
    """Django ORM implementation of routing log repository."""

    def save(self, log: CapabilityRoutingLog) -> CapabilityRoutingLog:
        """Save a routing log."""
        model = CapabilityRoutingLogModel.objects.create(
            entrypoint=log.entrypoint,
            user_id=log.user_id,
            session_id=log.session_id,
            raw_message=log.raw_message,
            retrieved_candidates=list(log.retrieved_candidates),
            selected_capability_key=log.selected_capability_key,
            confidence=log.confidence,
            decision=log.decision.value,
            fallback_reason=log.fallback_reason,
            execution_result=log.execution_result,
        )
        return model.to_entity()

    def get_by_session(self, session_id: str) -> list[CapabilityRoutingLog]:
        """Get logs by session ID."""
        models = CapabilityRoutingLogModel.objects.filter(session_id=session_id)
        return [m.to_entity() for m in models]


class DjangoSyncLogRepository:
    """Django ORM implementation of sync log repository."""

    def save(self, log: CapabilitySyncLog) -> CapabilitySyncLog:
        """Save a sync log."""
        model = CapabilitySyncLogModel.objects.create(
            sync_type=log.sync_type,
            started_at=log.started_at,
            finished_at=log.finished_at,
            total_discovered=log.total_discovered,
            created_count=log.created_count,
            updated_count=log.updated_count,
            disabled_count=log.disabled_count,
            error_count=log.error_count,
            summary_payload=dict(log.summary_payload),
        )
        return model.to_entity()

    def get_latest(self, sync_type: str) -> CapabilitySyncLog | None:
        """Get the latest sync log of a given type."""
        try:
            model = (
                CapabilitySyncLogModel.objects.filter(
                    sync_type=sync_type,
                )
                .order_by("-started_at")
                .first()
            )
            return model.to_entity() if model else None
        except CapabilitySyncLogModel.DoesNotExist:
            return None


class DjangoCapabilityExecutionSupportRepository:
    """Helpers for application-layer execution support concerns."""

    def get_user_by_id(self, user_id: int) -> Any | None:
        """Return one auth user instance by id, or None if missing."""
        user_model = get_user_model()
        try:
            return user_model._default_manager.get(pk=user_id)
        except user_model.DoesNotExist:
            return None


def get_capability_execution_support_repository() -> DjangoCapabilityExecutionSupportRepository:
    """Return execution support repository instance."""
    return DjangoCapabilityExecutionSupportRepository()


__all__ = [
    "DjangoCapabilityRepository",
    "DjangoRoutingLogRepository",
    "DjangoSyncLogRepository",
    "DjangoCapabilityExecutionSupportRepository",
    "get_capability_execution_support_repository",
]
