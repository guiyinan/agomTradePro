"""
AI Capability Catalog Application DTOs.
"""

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class RouteRequestDTO:
    """Request DTO for capability routing."""

    message: str
    entrypoint: str
    session_id: str | None = None
    provider_name: str | None = None
    model: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteResponseDTO:
    """Response DTO for capability routing."""

    decision: str
    selected_capability_key: str | None = None
    confidence: float = 0.0
    candidate_capabilities: list[dict[str, Any]] = field(default_factory=list)
    requires_confirmation: bool = False
    reply: str = ""
    session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    answer_chain: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    rejected_candidates: list[str] = field(default_factory=list)
    filled_params: dict[str, Any] = field(default_factory=dict)
    missing_params: list[str] = field(default_factory=list)
    suggested_command: str | None = None
    suggested_intent: str | None = None
    suggestion_prompt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "selected_capability_key": self.selected_capability_key,
            "confidence": self.confidence,
            "candidate_capabilities": self.candidate_capabilities,
            "requires_confirmation": self.requires_confirmation,
            "reply": self.reply,
            "session_id": self.session_id,
            "metadata": self.metadata,
            "answer_chain": self.answer_chain,
            "reason": self.reason,
            "rejected_candidates": self.rejected_candidates,
            "filled_params": self.filled_params,
            "missing_params": self.missing_params,
            "suggested_command": self.suggested_command,
            "suggested_intent": self.suggested_intent,
            "suggestion_prompt": self.suggestion_prompt,
        }


@dataclass
class CapabilitySummaryDTO:
    """Summary DTO for capability listing."""

    capability_key: str
    name: str
    summary: str
    source_type: str
    route_group: str
    category: str
    risk_level: str
    enabled_for_routing: bool
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_key": self.capability_key,
            "name": self.name,
            "summary": self.summary,
            "source_type": self.source_type,
            "route_group": self.route_group,
            "category": self.category,
            "risk_level": self.risk_level,
            "enabled_for_routing": self.enabled_for_routing,
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass
class SyncResultDTO:
    """Result DTO for sync operations."""

    sync_type: str
    total_discovered: int
    created_count: int
    updated_count: int
    disabled_count: int
    error_count: int
    duration_seconds: float
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sync_type": self.sync_type,
            "total_discovered": self.total_discovered,
            "created_count": self.created_count,
            "updated_count": self.updated_count,
            "disabled_count": self.disabled_count,
            "error_count": self.error_count,
            "duration_seconds": self.duration_seconds,
            "summary": self.summary,
        }
