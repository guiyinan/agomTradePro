"""
AI Capability Catalog Domain Entities.

System-level capability catalog for unified AI routing.
Follows DDD principles - pure Python, no external dependencies.
"""

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

    def __post_init__(self):
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_key": self.capability_key,
            "source_type": self.source_type.value,
            "source_ref": self.source_ref,
            "name": self.name,
            "summary": self.summary,
            "description": self.description,
            "route_group": self.route_group.value,
            "category": self.category,
            "tags": self.tags,
            "when_to_use": self.when_to_use,
            "when_not_to_use": self.when_not_to_use,
            "examples": self.examples,
            "input_schema": self.input_schema,
            "execution_kind": self.execution_kind.value,
            "execution_target": self.execution_target,
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
        return cls(
            capability_key=data["capability_key"],
            source_type=SourceType(data.get("source_type", "tool")),
            source_ref=data.get("source_ref", ""),
            name=data["name"],
            summary=data.get("summary", ""),
            description=data.get("description", ""),
            route_group=RouteGroup(data.get("route_group", "tool")),
            category=data.get("category", "general"),
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

    def __post_init__(self):
        if isinstance(self.decision, str):
            object.__setattr__(self, "decision", CapabilityDecision(self.decision))

    def to_dict(self) -> dict[str, Any]:
        return {
            "entrypoint": self.entrypoint,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "raw_message": self.raw_message,
            "retrieved_candidates": self.retrieved_candidates,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "sync_type": self.sync_type,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "total_discovered": self.total_discovered,
            "created_count": self.created_count,
            "updated_count": self.updated_count,
            "disabled_count": self.disabled_count,
            "error_count": self.error_count,
            "summary_payload": self.summary_payload,
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

    def __post_init__(self):
        if isinstance(self.decision, str):
            object.__setattr__(self, "decision", CapabilityDecision(self.decision))

    def to_response_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "selected_capability_key": self.selected_capability_key,
            "confidence": self.confidence,
            "candidate_capabilities": self.candidate_capabilities,
            "requires_confirmation": self.requires_confirmation,
            "reply": self.reply,
            "metadata": self.metadata,
            "answer_chain": self.answer_chain,
        }
