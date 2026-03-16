"""
Domain Entities for Agent Runtime.

FROZEN: These entity names and field names must not change.
See: docs/plans/ai-native/implementation-contract.md
"""

from dataclasses import dataclass, field, replace as dataclass_replace
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List


class TaskDomain(str, Enum):
    """FROZEN: Task domain values"""
    RESEARCH = "research"
    MONITORING = "monitoring"
    DECISION = "decision"
    EXECUTION = "execution"
    OPS = "ops"


class TaskStatus(str, Enum):
    """FROZEN: Task status values"""
    DRAFT = "draft"
    CONTEXT_READY = "context_ready"
    PROPOSAL_GENERATED = "proposal_generated"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_HUMAN = "needs_human"
    CANCELLED = "cancelled"


class ProposalStatus(str, Enum):
    """FROZEN: Proposal status values"""
    DRAFT = "draft"
    GENERATED = "generated"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    EXECUTION_FAILED = "execution_failed"
    EXPIRED = "expired"


class ApprovalStatus(str, Enum):
    """FROZEN: Approval status values"""
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RiskLevel(str, Enum):
    """Risk level for proposals"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EventSource(str, Enum):
    """Source of timeline events"""
    API = "api"
    SDK = "sdk"
    MCP = "mcp"
    SYSTEM = "system"
    HUMAN = "human"


class GuardrailDecision(str, Enum):
    """Guardrail decision outcomes"""
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    NEEDS_HUMAN = "needs_human"
    DEGRADED_MODE = "degraded_mode"


class TimelineEventType(str, Enum):
    """Timeline event types"""
    TASK_CREATED = "task_created"
    STATE_CHANGED = "state_changed"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    TASK_RESUMED = "task_resumed"
    TASK_CANCELLED = "task_cancelled"
    TASK_ESCALATED = "task_escalated"


@dataclass(frozen=True)
class AgentTask:
    """
    FROZEN: AgentTask entity.

    Represents an AI agent task with lifecycle management.

    Attributes:
        id: Primary key
        request_id: Stable request trace id
        schema_version: Schema version (default v1)
        task_domain: One of research/monitoring/decision/execution/ops
        task_type: Task subtype
        status: Current task status
        input_payload: JSON input payload
        current_step: Current step key
        last_error: Structured error payload
        requires_human: Whether human intervention is needed
        created_by: User id if authenticated
        created_at: Server timestamp
        updated_at: Server timestamp
    """
    id: Optional[int] = None
    request_id: str = ""
    schema_version: str = "v1"
    task_domain: TaskDomain = TaskDomain.RESEARCH
    task_type: str = ""
    status: TaskStatus = TaskStatus.DRAFT
    input_payload: Dict[str, Any] = field(default_factory=dict)
    current_step: Optional[str] = None
    last_error: Optional[Dict[str, Any]] = None
    requires_human: bool = False
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def replace(self, **changes: Any) -> "AgentTask":
        """Compatibility helper for tests and transition workflows."""
        return dataclass_replace(self, **changes)


@dataclass(frozen=True)
class AgentTaskStep:
    """
    AgentTaskStep entity - represents a step in task execution.

    Attributes:
        id: Primary key
        request_id: Trace id
        task: Linked task
        step_key: Step identifier
        step_name: Human readable step name
        step_index: Order index
        status: Step status
        started_at: Step start time
        completed_at: Step completion time
        error_message: Error if failed
        output_data: Step output
    """
    id: Optional[int] = None
    request_id: str = ""
    task_id: int = 0
    step_key: str = ""
    step_name: str = ""
    step_index: int = 0
    status: str = "pending"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    output_data: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class AgentContextSnapshot:
    """
    AgentContextSnapshot entity - context aggregation for tasks.

    Attributes:
        id: Primary key
        request_id: Trace id
        task: Linked task
        domain: Task domain
        snapshot_data: Aggregated context data
        generated_at: Snapshot generation time
        data_freshness: Data freshness metrics
    """
    id: Optional[int] = None
    request_id: str = ""
    task_id: int = 0
    domain: TaskDomain = TaskDomain.RESEARCH
    snapshot_data: Dict[str, Any] = field(default_factory=dict)
    generated_at: Optional[datetime] = None
    data_freshness: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class AgentProposal:
    """
    FROZEN: AgentProposal entity.

    Represents a proposal generated by an agent for execution.

    Attributes:
        id: Primary key
        request_id: Trace id
        schema_version: Schema version
        task_id: Linked task
        proposal_type: Type of proposal (e.g., rebalance, signal_write)
        status: Proposal status
        risk_level: Risk level assessment
        approval_required: Server-evaluated approval requirement
        approval_status: Current approval status
        proposal_payload: Execution payload
        approval_reason: Human/system explanation
        created_by: User id
        created_at: Server timestamp
        updated_at: Server timestamp
    """
    id: Optional[int] = None
    request_id: str = ""
    schema_version: str = "v1"
    task_id: Optional[int] = None
    proposal_type: str = ""
    status: ProposalStatus = ProposalStatus.DRAFT
    risk_level: RiskLevel = RiskLevel.MEDIUM
    approval_required: bool = True
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    proposal_payload: Dict[str, Any] = field(default_factory=dict)
    approval_reason: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass(frozen=True)
class AgentExecutionRecord:
    """
    AgentExecutionRecord entity - records execution results.

    Attributes:
        id: Primary key
        request_id: Trace id
        task_id: Linked task
        proposal_id: Linked proposal
        execution_status: Execution result status
        execution_output: Execution output data
        started_at: Execution start time
        completed_at: Execution completion time
        error_details: Error details if failed
    """
    id: Optional[int] = None
    request_id: str = ""
    task_id: int = 0
    proposal_id: Optional[int] = None
    execution_status: str = "pending"
    execution_output: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_details: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class AgentArtifact:
    """
    AgentArtifact entity - stores task artifacts.

    Attributes:
        id: Primary key
        request_id: Trace id
        task_id: Linked task
        artifact_type: Type of artifact
        artifact_name: Artifact name
        artifact_data: Artifact content
        file_path: Path to file if stored externally
        content_type: MIME type
        created_at: Creation timestamp
    """
    id: Optional[int] = None
    request_id: str = ""
    task_id: int = 0
    artifact_type: str = ""
    artifact_name: str = ""
    artifact_data: Optional[Dict[str, Any]] = None
    file_path: Optional[str] = None
    content_type: str = "application/json"
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class AgentTimelineEvent:
    """
    FROZEN: AgentTimelineEvent entity.

    Records all task lifecycle events for audit trail.

    Attributes:
        id: Primary key
        request_id: Trace id
        task_id: Linked task
        proposal_id: Linked proposal (optional)
        event_type: Event type from frozen enum
        event_source: Source of event (api/sdk/mcp/system/human)
        step_index: Step sequence number
        event_payload: Event details
        created_at: Server timestamp
    """
    id: Optional[int] = None
    request_id: str = ""
    task_id: int = 0
    proposal_id: Optional[int] = None
    event_type: TimelineEventType = TimelineEventType.TASK_CREATED
    event_source: EventSource = EventSource.SYSTEM
    step_index: Optional[int] = None
    event_payload: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class AgentHandoff:
    """
    AgentHandoff entity - records task handoffs between agents/humans.

    Attributes:
        id: Primary key
        request_id: Trace id
        task_id: Linked task
        from_agent: Source agent identifier
        to_agent: Target agent identifier
        handoff_reason: Reason for handoff
        handoff_payload: Context payload for handoff
        handoff_status: Handoff status
        created_at: Creation timestamp
    """
    id: Optional[int] = None
    request_id: str = ""
    task_id: int = 0
    from_agent: str = ""
    to_agent: str = ""
    handoff_reason: str = ""
    handoff_payload: Optional[Dict[str, Any]] = None
    handoff_status: str = "pending"
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class AgentGuardrailDecision:
    """
    FROZEN: AgentGuardrailDecision entity.

    Records guardrail decisions for proposals.

    Attributes:
        id: Primary key
        request_id: Trace id
        task_id: Linked task (optional)
        proposal_id: Linked proposal (optional)
        decision: Guardrail decision (allowed/blocked/needs_human/degraded_mode)
        reason_code: Stable machine-readable reason
        message: Human-readable summary
        evidence: Supporting data
        requires_human: Convenience flag
        created_at: Server timestamp
    """
    id: Optional[int] = None
    request_id: str = ""
    task_id: Optional[int] = None
    proposal_id: Optional[int] = None
    decision: GuardrailDecision = GuardrailDecision.ALLOWED
    reason_code: str = ""
    message: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    requires_human: bool = False
    created_at: Optional[datetime] = None


# Terminal states for tasks (no further transitions allowed)
TERMINAL_TASK_STATUSES = frozenset([
    TaskStatus.COMPLETED,
    TaskStatus.CANCELLED,
])

# Terminal states for proposals
TERMINAL_PROPOSAL_STATUSES = frozenset([
    ProposalStatus.EXECUTED,
    ProposalStatus.EXPIRED,
])
