"""
AI Capability Catalog Domain Entities.

System-level capability catalog for unified AI routing.
Follows DDD principles - pure Python, no external dependencies.
"""

import math
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SourceType(str, Enum):
    """Capability source type"""

    BUILTIN = "builtin"
    TERMINAL_COMMAND = "terminal_command"
    MCP_TOOL = "mcp_tool"
    API = "api"


class RouteGroup(str, Enum):
    """Route group for capability classification"""

    BUILTIN = "builtin"
    TOOL = "tool"
    READ_API = "read_api"
    WRITE_API = "write_api"
    UNSAFE_API = "unsafe_api"


class RiskLevel(str, Enum):
    """Risk level for capability execution"""

    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionKind(str, Enum):
    """Execution kind for capability"""

    SYNC = "sync"
    ASYNC = "async"
    STREAMING = "streaming"


class Visibility(str, Enum):
    """Visibility level for capability"""

    PUBLIC = "public"
    INTERNAL = "internal"
    ADMIN = "admin"
    HIDDEN = "hidden"


class ReviewStatus(str, Enum):
    """Review status for capability"""

    AUTO = "auto"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CapabilityDecision(str, Enum):
    """AI decision type"""

    CAPABILITY = "capability"
    ASK_CONFIRMATION = "ask_confirmation"
    CHAT = "chat"
    FALLBACK = "fallback"


def _validate_confidence(value: float, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{field_name} must be finite and non-negative")


def _validate_aware_datetime(value: datetime | None, *, field_name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class CapabilityDefinition:
    """Capability definition entity (value object)

    Represents a single capability in the catalog.
    """

    capability_key: str
    source_type: SourceType
    source_ref: str
    name: str
    summary: str
    description: str = ""
    route_group: RouteGroup = RouteGroup.TOOL
    category: str = "general"
    semantic_key: str = ""
    tags: list[str] = field(default_factory=list)
    when_to_use: list[str] = field(default_factory=list)
    when_not_to_use: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    execution_kind: ExecutionKind = ExecutionKind.SYNC
    execution_target: dict[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.SAFE
    requires_mcp: bool = False
    requires_confirmation: bool = False
    enabled_for_routing: bool = True
    enabled_for_terminal: bool = True
    enabled_for_chat: bool = True
    enabled_for_agent: bool = True
    visibility: Visibility = Visibility.PUBLIC
    auto_collected: bool = False
    review_status: ReviewStatus = ReviewStatus.AUTO
    priority_weight: float = 1.0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_synced_at: datetime | None = None

    def __post_init__(self) -> None:
        if isinstance(self.source_type, str):
            object.__setattr__(self, "source_type", SourceType(self.source_type))
        if isinstance(self.route_group, str):
            object.__setattr__(self, "route_group", RouteGroup(self.route_group))
        if isinstance(self.risk_level, str):
            object.__setattr__(self, "risk_level", RiskLevel(self.risk_level))
        if isinstance(self.execution_kind, str):
            object.__setattr__(self, "execution_kind", ExecutionKind(self.execution_kind))
        if isinstance(self.visibility, str):
            object.__setattr__(self, "visibility", Visibility(self.visibility))
        if isinstance(self.review_status, str):
            object.__setattr__(self, "review_status", ReviewStatus(self.review_status))
        if (
            isinstance(self.priority_weight, bool)
            or not isinstance(self.priority_weight, (int, float))
            or not math.isfinite(self.priority_weight)
            or self.priority_weight < 0
        ):
            raise ValueError("priority_weight must be a finite non-negative number")
        _validate_aware_datetime(self.created_at, field_name="created_at")
        _validate_aware_datetime(self.updated_at, field_name="updated_at")
        _validate_aware_datetime(self.last_synced_at, field_name="last_synced_at")
        object.__setattr__(self, "tags", list(self.tags))
        object.__setattr__(self, "when_to_use", list(self.when_to_use))
        object.__setattr__(self, "when_not_to_use", list(self.when_not_to_use))
        object.__setattr__(self, "examples", list(self.examples))
        object.__setattr__(self, "input_schema", deepcopy(self.input_schema))
        object.__setattr__(self, "execution_target", deepcopy(self.execution_target))

    def to_dict(self) -> dict[str, Any]:
        """Serialize without exposing mutable entity state."""
        return {
            "capability_key": self.capability_key,
            "source_type": self.source_type.value,
            "source_ref": self.source_ref,
            "name": self.name,
            "summary": self.summary,
            "description": self.description,
            "route_group": self.route_group.value,
            "category": self.category,
            "semantic_key": self.semantic_key,
            "tags": list(self.tags),
            "when_to_use": list(self.when_to_use),
            "when_not_to_use": list(self.when_not_to_use),
            "examples": list(self.examples),
            "input_schema": deepcopy(self.input_schema),
            "execution_kind": self.execution_kind.value,
            "execution_target": deepcopy(self.execution_target),
            "risk_level": self.risk_level.value,
            "requires_mcp": self.requires_mcp,
            "requires_confirmation": self.requires_confirmation,
            "enabled_for_routing": self.enabled_for_routing,
            "enabled_for_terminal": self.enabled_for_terminal,
            "enabled_for_chat": self.enabled_for_chat,
            "enabled_for_agent": self.enabled_for_agent,
            "visibility": self.visibility.value,
            "auto_collected": self.auto_collected,
            "review_status": self.review_status.value,
            "priority_weight": self.priority_weight,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityDefinition":
        """Build a capability from its JSON-compatible persistence payload."""
        return cls(
            capability_key=data["capability_key"],
            source_type=SourceType(data.get("source_type", "tool")),
            source_ref=data.get("source_ref", ""),
            name=data["name"],
            summary=data.get("summary", ""),
            description=data.get("description", ""),
            route_group=RouteGroup(data.get("route_group", "tool")),
            category=data.get("category", "general"),
            semantic_key=data.get("semantic_key", ""),
            tags=data.get("tags", []),
            when_to_use=data.get("when_to_use", []),
            when_not_to_use=data.get("when_not_to_use", []),
            examples=data.get("examples", []),
            input_schema=data.get("input_schema", {}),
            execution_kind=ExecutionKind(data.get("execution_kind", "sync")),
            execution_target=data.get("execution_target", {}),
            risk_level=RiskLevel(data.get("risk_level", "safe")),
            requires_mcp=data.get("requires_mcp", False),
            requires_confirmation=data.get("requires_confirmation", False),
            enabled_for_routing=data.get("enabled_for_routing", True),
            enabled_for_terminal=data.get("enabled_for_terminal", True),
            enabled_for_chat=data.get("enabled_for_chat", True),
            enabled_for_agent=data.get("enabled_for_agent", True),
            visibility=Visibility(data.get("visibility", "public")),
            auto_collected=data.get("auto_collected", False),
            review_status=ReviewStatus(data.get("review_status", "auto")),
            priority_weight=data.get("priority_weight", 1.0),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            last_synced_at=data.get("last_synced_at"),
        )

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "capability_key": self.capability_key,
            "name": self.name,
            "summary": self.summary,
            "category": self.category,
            "semantic_key": self.semantic_key,
            "risk_level": self.risk_level.value,
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass(frozen=True)
class CapabilityRoutingLog:
    """Capability routing log entity (value object)

    Records routing decisions and execution results.
    """

    entrypoint: str
    user_id: int | None
    session_id: str
    raw_message: str
    retrieved_candidates: list[str] = field(default_factory=list)
    selected_capability_key: str | None = None
    confidence: float = 0.0
    decision: CapabilityDecision = CapabilityDecision.CHAT
    fallback_reason: str = ""
    execution_result: str = ""
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if isinstance(self.decision, str):
            object.__setattr__(self, "decision", CapabilityDecision(self.decision))
        _validate_confidence(self.confidence, field_name="confidence")
        _validate_aware_datetime(self.created_at, field_name="created_at")
        object.__setattr__(
            self,
            "retrieved_candidates",
            list(self.retrieved_candidates),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize without exposing the candidate list."""
        return {
            "entrypoint": self.entrypoint,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "raw_message": self.raw_message,
            "retrieved_candidates": list(self.retrieved_candidates),
            "selected_capability_key": self.selected_capability_key,
            "confidence": self.confidence,
            "decision": self.decision.value,
            "fallback_reason": self.fallback_reason,
            "execution_result": self.execution_result,
        }


@dataclass(frozen=True)
class CapabilitySyncLog:
    """Capability sync log entity (value object)

    Records synchronization operations.
    """

    sync_type: str
    started_at: datetime
    finished_at: datetime | None = None
    total_discovered: int = 0
    created_count: int = 0
    updated_count: int = 0
    disabled_count: int = 0
    error_count: int = 0
    summary_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_aware_datetime(self.started_at, field_name="started_at")
        _validate_aware_datetime(self.finished_at, field_name="finished_at")
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at cannot be earlier than started_at")
        for field_name in (
            "total_discovered",
            "created_count",
            "updated_count",
            "disabled_count",
            "error_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        object.__setattr__(self, "summary_payload", deepcopy(self.summary_payload))

    def to_dict(self) -> dict[str, Any]:
        """Serialize without exposing the mutable summary payload."""
        return {
            "sync_type": self.sync_type,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "total_discovered": self.total_discovered,
            "created_count": self.created_count,
            "updated_count": self.updated_count,
            "disabled_count": self.disabled_count,
            "error_count": self.error_count,
            "summary_payload": deepcopy(self.summary_payload),
        }


@dataclass(frozen=True)
class RoutingContext:
    """Routing context entity (value object)

    Contains context information for routing decisions.
    """

    entrypoint: str
    session_id: str
    user_id: int | None = None
    user_is_admin: bool = False
    mcp_enabled: bool = True
    provider_name: str | None = None
    model: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    answer_chain_enabled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", deepcopy(self.context))


@dataclass(frozen=True)
class RoutingDecision:
    """Routing decision result entity (value object)

    Contains the routing decision and execution metadata.
    """

    decision: CapabilityDecision
    selected_capability_key: str | None = None
    confidence: float = 0.0
    candidate_capabilities: list[dict[str, Any]] = field(default_factory=list)
    requires_confirmation: bool = False
    reply: str = ""
    reason: str = ""
    filled_params: dict[str, Any] = field(default_factory=dict)
    missing_params: list[str] = field(default_factory=list)
    rejected_candidates: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    answer_chain: dict[str, Any] = field(default_factory=dict)
    result: Any = None

    def __post_init__(self) -> None:
        if isinstance(self.decision, str):
            object.__setattr__(self, "decision", CapabilityDecision(self.decision))
        _validate_confidence(self.confidence, field_name="confidence")
        object.__setattr__(
            self,
            "candidate_capabilities",
            deepcopy(self.candidate_capabilities),
        )
        object.__setattr__(self, "filled_params", deepcopy(self.filled_params))
        object.__setattr__(self, "missing_params", list(self.missing_params))
        object.__setattr__(self, "rejected_candidates", list(self.rejected_candidates))
        object.__setattr__(self, "metadata", deepcopy(self.metadata))
        object.__setattr__(self, "answer_chain", deepcopy(self.answer_chain))

    def to_response_dict(self) -> dict[str, Any]:
        """Serialize without exposing mutable routing state."""
        return {
            "decision": self.decision.value,
            "selected_capability_key": self.selected_capability_key,
            "confidence": self.confidence,
            "candidate_capabilities": deepcopy(self.candidate_capabilities),
            "requires_confirmation": self.requires_confirmation,
            "reply": self.reply,
            "metadata": deepcopy(self.metadata),
            "answer_chain": deepcopy(self.answer_chain),
            "result": self.result,
        }
