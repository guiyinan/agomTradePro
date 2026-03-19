"""
AI Capability Catalog Infrastructure ORM Models.
"""

from django.conf import settings
from django.db import models

from ..domain.entities import (
    CapabilityDecision,
    CapabilityDefinition,
    CapabilityRoutingLog,
    CapabilitySyncLog,
    ExecutionKind,
    ReviewStatus,
    RiskLevel,
    RouteGroup,
    SourceType,
    Visibility,
)


class CapabilityCatalogModel(models.Model):
    """System-level capability catalog for AI routing."""

    SOURCE_TYPE_CHOICES = [(t.value, t.value) for t in SourceType]
    ROUTE_GROUP_CHOICES = [(g.value, g.value) for g in RouteGroup]
    RISK_LEVEL_CHOICES = [(r.value, r.value) for r in RiskLevel]
    EXECUTION_KIND_CHOICES = [(k.value, k.value) for k in ExecutionKind]
    VISIBILITY_CHOICES = [(v.value, v.value) for v in Visibility]
    REVIEW_STATUS_CHOICES = [(s.value, s.value) for s in ReviewStatus]

    capability_key = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique capability identifier (e.g., builtin.system_status)",
    )
    source_type = models.CharField(
        max_length=30,
        choices=SOURCE_TYPE_CHOICES,
        db_index=True,
        help_text="Source type: builtin, terminal_command, mcp_tool, api",
    )
    source_ref = models.CharField(
        max_length=255,
        help_text="Reference to original source (e.g., tool name, API path)",
    )
    name = models.CharField(
        max_length=255,
        help_text="Human-readable capability name",
    )
    summary = models.TextField(
        help_text="Short summary for AI routing",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Detailed description",
    )
    route_group = models.CharField(
        max_length=20,
        choices=ROUTE_GROUP_CHOICES,
        default=RouteGroup.TOOL.value,
        db_index=True,
        help_text="Routing group: builtin, tool, read_api, write_api, unsafe_api",
    )
    category = models.CharField(
        max_length=100,
        default="general",
        db_index=True,
        help_text="Capability category",
    )
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text="List of tags for search",
    )
    when_to_use = models.JSONField(
        default=list,
        blank=True,
        help_text="List of usage scenarios",
    )
    when_not_to_use = models.JSONField(
        default=list,
        blank=True,
        help_text="List of non-usage scenarios",
    )
    examples = models.JSONField(
        default=list,
        blank=True,
        help_text="List of example queries",
    )
    input_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON Schema for input parameters",
    )
    execution_kind = models.CharField(
        max_length=20,
        choices=EXECUTION_KIND_CHOICES,
        default=ExecutionKind.SYNC.value,
        help_text="Execution type: sync, async, streaming",
    )
    execution_target = models.JSONField(
        default=dict,
        blank=True,
        help_text="Execution target configuration",
    )
    risk_level = models.CharField(
        max_length=20,
        choices=RISK_LEVEL_CHOICES,
        default=RiskLevel.SAFE.value,
        db_index=True,
        help_text="Risk level: safe, low, medium, high, critical",
    )
    requires_mcp = models.BooleanField(
        default=False,
        help_text="Requires MCP permission",
    )
    requires_confirmation = models.BooleanField(
        default=False,
        help_text="Requires user confirmation before execution",
    )
    enabled_for_routing = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Enabled for AI routing",
    )
    enabled_for_terminal = models.BooleanField(
        default=True,
        help_text="Enabled for terminal entrypoint",
    )
    enabled_for_chat = models.BooleanField(
        default=True,
        help_text="Enabled for chat entrypoint",
    )
    enabled_for_agent = models.BooleanField(
        default=True,
        help_text="Enabled for agent entrypoint",
    )
    visibility = models.CharField(
        max_length=20,
        choices=VISIBILITY_CHOICES,
        default=Visibility.PUBLIC.value,
        db_index=True,
        help_text="Visibility level: public, internal, admin, hidden",
    )
    auto_collected = models.BooleanField(
        default=False,
        help_text="Automatically collected from source",
    )
    review_status = models.CharField(
        max_length=20,
        choices=REVIEW_STATUS_CHOICES,
        default=ReviewStatus.AUTO.value,
        db_index=True,
        help_text="Review status: auto, pending, approved, rejected",
    )
    priority_weight = models.FloatField(
        default=1.0,
        help_text="Priority weight for scoring (higher = more important)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last synchronization timestamp",
    )

    class Meta:
        db_table = "ai_capability_catalog"
        ordering = ["-priority_weight", "name"]
        verbose_name = "AI Capability"
        verbose_name_plural = "AI Capability Catalog"
        indexes = [
            models.Index(fields=["source_type", "enabled_for_routing"]),
            models.Index(fields=["route_group", "enabled_for_routing"]),
            models.Index(fields=["category", "enabled_for_routing"]),
            models.Index(fields=["risk_level", "enabled_for_routing"]),
            models.Index(fields=["review_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.capability_key} ({self.source_type})"

    def to_entity(self) -> CapabilityDefinition:
        """Map ORM model to domain entity."""
        return CapabilityDefinition(
            capability_key=self.capability_key,
            source_type=SourceType(self.source_type),
            source_ref=self.source_ref,
            name=self.name,
            summary=self.summary,
            description=self.description,
            route_group=RouteGroup(self.route_group),
            category=self.category,
            tags=list(self.tags or []),
            when_to_use=list(self.when_to_use or []),
            when_not_to_use=list(self.when_not_to_use or []),
            examples=list(self.examples or []),
            input_schema=dict(self.input_schema or {}),
            execution_kind=ExecutionKind(self.execution_kind),
            execution_target=dict(self.execution_target or {}),
            risk_level=RiskLevel(self.risk_level),
            requires_mcp=self.requires_mcp,
            requires_confirmation=self.requires_confirmation,
            enabled_for_routing=self.enabled_for_routing,
            enabled_for_terminal=self.enabled_for_terminal,
            enabled_for_chat=self.enabled_for_chat,
            enabled_for_agent=self.enabled_for_agent,
            visibility=Visibility(self.visibility),
            auto_collected=self.auto_collected,
            review_status=ReviewStatus(self.review_status),
            priority_weight=self.priority_weight,
            created_at=self.created_at,
            updated_at=self.updated_at,
            last_synced_at=self.last_synced_at,
        )

    @classmethod
    def from_entity(cls, entity: CapabilityDefinition) -> "CapabilityCatalogModel":
        """Map domain entity to ORM model."""
        return cls(
            capability_key=entity.capability_key,
            source_type=entity.source_type.value,
            source_ref=entity.source_ref,
            name=entity.name,
            summary=entity.summary,
            description=entity.description,
            route_group=entity.route_group.value,
            category=entity.category,
            tags=list(entity.tags),
            when_to_use=list(entity.when_to_use),
            when_not_to_use=list(entity.when_not_to_use),
            examples=list(entity.examples),
            input_schema=dict(entity.input_schema),
            execution_kind=entity.execution_kind.value,
            execution_target=dict(entity.execution_target),
            risk_level=entity.risk_level.value,
            requires_mcp=entity.requires_mcp,
            requires_confirmation=entity.requires_confirmation,
            enabled_for_routing=entity.enabled_for_routing,
            enabled_for_terminal=entity.enabled_for_terminal,
            enabled_for_chat=entity.enabled_for_chat,
            enabled_for_agent=entity.enabled_for_agent,
            visibility=entity.visibility.value,
            auto_collected=entity.auto_collected,
            review_status=entity.review_status.value,
            priority_weight=entity.priority_weight,
        )


class CapabilityRoutingLogModel(models.Model):
    """Log of capability routing decisions and executions."""

    DECISION_CHOICES = [(d.value, d.value) for d in CapabilityDecision]

    entrypoint = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Entrypoint: terminal, chat, agent",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    session_id = models.CharField(
        max_length=100,
        db_index=True,
    )
    raw_message = models.TextField()
    retrieved_candidates = models.JSONField(
        default=list,
        help_text="List of retrieved capability keys",
    )
    selected_capability_key = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
    )
    confidence = models.FloatField(default=0.0)
    decision = models.CharField(
        max_length=30,
        choices=DECISION_CHOICES,
        default=CapabilityDecision.CHAT.value,
    )
    fallback_reason = models.TextField(blank=True, default="")
    execution_result = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ai_capability_routing_log"
        ordering = ["-created_at"]
        verbose_name = "Capability Routing Log"
        verbose_name_plural = "Capability Routing Logs"

    def __str__(self) -> str:
        return f"{self.entrypoint}:{self.decision} [{self.confidence:.2f}]"

    def to_entity(self) -> CapabilityRoutingLog:
        """Map ORM model to domain entity."""
        return CapabilityRoutingLog(
            entrypoint=self.entrypoint,
            user_id=self.user_id,
            session_id=self.session_id,
            raw_message=self.raw_message,
            retrieved_candidates=list(self.retrieved_candidates or []),
            selected_capability_key=self.selected_capability_key,
            confidence=self.confidence,
            decision=CapabilityDecision(self.decision),
            fallback_reason=self.fallback_reason,
            execution_result=self.execution_result,
            created_at=self.created_at,
        )


class CapabilitySyncLogModel(models.Model):
    """Log of capability synchronization operations."""

    SYNC_TYPE_CHOICES = [
        ("full", "Full Sync"),
        ("incremental", "Incremental Sync"),
        ("init", "Initialization"),
    ]

    sync_type = models.CharField(
        max_length=30,
        choices=SYNC_TYPE_CHOICES,
        db_index=True,
    )
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    total_discovered = models.IntegerField(default=0)
    created_count = models.IntegerField(default=0)
    updated_count = models.IntegerField(default=0)
    disabled_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    summary_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "ai_capability_sync_log"
        ordering = ["-started_at"]
        verbose_name = "Capability Sync Log"
        verbose_name_plural = "Capability Sync Logs"

    def __str__(self) -> str:
        return f"{self.sync_type} at {self.started_at}"

    def to_entity(self) -> CapabilitySyncLog:
        """Map ORM model to domain entity."""
        return CapabilitySyncLog(
            sync_type=self.sync_type,
            started_at=self.started_at,
            finished_at=self.finished_at,
            total_discovered=self.total_discovered,
            created_count=self.created_count,
            updated_count=self.updated_count,
            disabled_count=self.disabled_count,
            error_count=self.error_count,
            summary_payload=dict(self.summary_payload or {}),
        )


__all__ = [
    "CapabilityCatalogModel",
    "CapabilityRoutingLogModel",
    "CapabilitySyncLogModel",
]
