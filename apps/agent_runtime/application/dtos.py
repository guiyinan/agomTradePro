"""
Application Layer DTOs for Agent Runtime.

WP-M1-04: Data Transfer Objects for agent runtime module.
See: docs/plans/ai-native/schema-contract.md

DTOs are used to transfer data between layers without exposing
domain entities to the interface layer.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum


# ============================================================================
# Request DTOs (Input)
# ============================================================================

@dataclass
class TaskCreateDTO:
    """
    Input DTO for creating a new AgentTask.

    Attributes:
        task_domain: Task domain (research/monitoring/decision/execution/ops)
        task_type: Task subtype (e.g., macro_portfolio_review)
        input_payload: JSON input payload for the task
        schema_version: Schema version (default v1)
    """
    task_domain: str
    task_type: str
    input_payload: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "v1"


@dataclass
class TaskUpdateDTO:
    """
    Input DTO for updating an existing AgentTask.

    Attributes:
        status: New task status (optional)
        current_step: Current step key (optional)
        last_error: Structured error payload (optional)
        requires_human: Whether human intervention is needed (optional)
    """
    status: Optional[str] = None
    current_step: Optional[str] = None
    last_error: Optional[Dict[str, Any]] = None
    requires_human: Optional[bool] = None


@dataclass
class TaskQueryDTO:
    """
    Input DTO for querying tasks.

    Attributes:
        status: Filter by status (optional)
        task_domain: Filter by domain (optional)
        task_type: Filter by type (optional)
        requires_human: Filter by human intervention flag (optional)
        search: Search in request_id or task_type (optional)
        limit: Max results (default 50)
        offset: Pagination offset (default 0)
    """
    status: Optional[str] = None
    task_domain: Optional[str] = None
    task_type: Optional[str] = None
    requires_human: Optional[bool] = None
    search: Optional[str] = None
    limit: int = 50
    offset: int = 0


@dataclass
class TaskApprovalDTO:
    """
    Input DTO for task approval/rejection.

    Attributes:
        action: Either 'approve' or 'reject'
        reason: Optional reason for the decision
    """
    action: str  # 'approve' or 'reject'
    reason: Optional[str] = None


@dataclass
class TaskExecutionDTO:
    """
    Input DTO for task execution.

    Attributes:
        input_payload: Additional/updated input payload
        force: Force execution even if task is not in ready state
    """
    input_payload: Dict[str, Any] = field(default_factory=dict)
    force: bool = False


@dataclass
class ProposalCreateDTO:
    """
    Input DTO for creating a proposal.

    Attributes:
        task_id: Linked task ID (optional)
        proposal_type: Type of proposal
        risk_level: Risk level (default medium)
        approval_required: Whether approval is required
        proposal_payload: Execution payload
        approval_reason: Human/system explanation
    """
    task_id: Optional[int] = None
    proposal_type: str = ""
    risk_level: str = "medium"
    approval_required: bool = True
    proposal_payload: Dict[str, Any] = field(default_factory=dict)
    approval_reason: Optional[str] = None


# ============================================================================
# Response DTOs (Output)
# ============================================================================

@dataclass
class TaskDetailDTO:
    """
    Output DTO for task detail.

    Attributes:
        id: Task ID
        request_id: Stable request trace id
        schema_version: Schema version
        task_domain: Task domain
        task_type: Task subtype
        status: Current task status
        input_payload: JSON input payload
        current_step: Current step key
        last_error: Structured error payload
        requires_human: Whether human intervention is needed
        created_by: User id
        created_by_username: User username
        created_at: Server timestamp
        updated_at: Server timestamp
        steps_count: Number of steps
        proposals_count: Number of proposals
        artifacts_count: Number of artifacts
        timeline_events_count: Number of timeline events
    """
    id: int
    request_id: str
    schema_version: str
    task_domain: str
    task_domain_display: str
    task_type: str
    status: str
    status_display: str
    input_payload: Dict[str, Any]
    current_step: Optional[str]
    last_error: Optional[Dict[str, Any]]
    requires_human: bool
    created_by: Optional[int]
    created_by_username: Optional[str]
    created_at: datetime
    updated_at: datetime
    steps_count: int = 0
    proposals_count: int = 0
    artifacts_count: int = 0
    timeline_events_count: int = 0

    def to_response_dict(self) -> Dict[str, Any]:
        """Convert to API response dict with ISO timestamps."""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "task_domain": self.task_domain,
            "task_domain_display": self.task_domain_display,
            "task_type": self.task_type,
            "status": self.status,
            "status_display": self.status_display,
            "input_payload": self.input_payload,
            "current_step": self.current_step,
            "last_error": self.last_error,
            "requires_human": self.requires_human,
            "created_by": self.created_by,
            "created_by_username": self.created_by_username,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "steps_count": self.steps_count,
            "proposals_count": self.proposals_count,
            "artifacts_count": self.artifacts_count,
            "timeline_events_count": self.timeline_events_count,
        }


@dataclass
class TaskListDTO:
    """
    Output DTO for task list.

    Attributes:
        tasks: List of task summary items
        total: Total count (for pagination)
        limit: Limit used
        offset: Offset used
    """
    tasks: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


@dataclass
class TaskListItemDTO:
    """
    Lightweight task item for list views.

    Attributes:
        id: Task ID
        request_id: Stable request trace id
        schema_version: Schema version
        task_domain: Task domain
        task_domain_display: Display name for domain
        task_type: Task subtype
        status: Current task status
        status_display: Display name for status
        current_step: Current step key
        requires_human: Whether human intervention is needed
        created_at: Server timestamp
        updated_at: Server timestamp
    """
    id: int
    request_id: str
    schema_version: str
    task_domain: str
    task_domain_display: str
    task_type: str
    status: str
    status_display: str
    current_step: Optional[str]
    requires_human: bool
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict with ISO timestamps."""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "task_domain": self.task_domain,
            "task_domain_display": self.task_domain_display,
            "task_type": self.task_type,
            "status": self.status,
            "status_display": self.status_display,
            "current_step": self.current_step,
            "requires_human": self.requires_human,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class TaskTimelineDTO:
    """
    Output DTO for task timeline events.

    Attributes:
        task_id: Task ID
        request_id: Trace id
        events: List of timeline events
    """
    task_id: int
    request_id: str
    events: List[Dict[str, Any]]


@dataclass
class TimelineEventDTO:
    """
    Single timeline event.

    Attributes:
        id: Event ID
        request_id: Trace id
        task_id: Task ID
        proposal_id: Linked proposal ID (optional)
        event_type: Event type
        event_type_display: Display name for event type
        event_source: Source of event
        event_source_display: Display name for source
        step_index: Step sequence number
        event_payload: Event details
        created_at: Server timestamp
    """
    id: int
    request_id: str
    task_id: int
    proposal_id: Optional[int]
    event_type: str
    event_type_display: str
    event_source: str
    event_source_display: str
    step_index: Optional[int]
    event_payload: Dict[str, Any]
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict with ISO timestamp."""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "task_id": self.task_id,
            "proposal_id": self.proposal_id,
            "event_type": self.event_type,
            "event_type_display": self.event_type_display,
            "event_source": self.event_source,
            "event_source_display": self.event_source_display,
            "step_index": self.step_index,
            "event_payload": self.event_payload,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class TaskArtifactsDTO:
    """
    Output DTO for task artifacts.

    Attributes:
        task_id: Task ID
        request_id: Trace id
        artifacts: List of artifacts
    """
    task_id: int
    request_id: str
    artifacts: List[Dict[str, Any]]


@dataclass
class ArtifactDTO:
    """
    Single artifact.

    Attributes:
        id: Artifact ID
        request_id: Trace id
        task_id: Task ID
        artifact_type: Type of artifact
        artifact_name: Artifact name
        artifact_data: Artifact content
        file_path: Path to file if stored externally
        content_type: MIME type
        created_at: Server timestamp
    """
    id: int
    request_id: str
    task_id: int
    artifact_type: str
    artifact_name: str
    artifact_data: Optional[Dict[str, Any]]
    file_path: Optional[str]
    content_type: str
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict with ISO timestamp."""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "task_id": self.task_id,
            "artifact_type": self.artifact_type,
            "artifact_name": self.artifact_name,
            "artifact_data": self.artifact_data,
            "file_path": self.file_path,
            "content_type": self.content_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class ProposalDetailDTO:
    """
    Output DTO for proposal detail.

    Attributes:
        id: Proposal ID
        request_id: Trace id
        schema_version: Schema version
        task_id: Linked task ID
        proposal_type: Type of proposal
        status: Proposal status
        status_display: Display name for status
        risk_level: Risk level
        risk_level_display: Display name for risk level
        approval_required: Whether approval is required
        approval_status: Current approval status
        approval_status_display: Display name for approval status
        approval_reason: Human/system explanation
        proposal_payload: Execution payload
        created_by: User id
        created_by_username: User username
        created_at: Server timestamp
        updated_at: Server timestamp
    """
    id: int
    request_id: str
    schema_version: str
    task_id: Optional[int]
    proposal_type: str
    status: str
    status_display: str
    risk_level: str
    risk_level_display: str
    approval_required: bool
    approval_status: str
    approval_status_display: str
    approval_reason: Optional[str]
    proposal_payload: Dict[str, Any]
    created_by: Optional[int]
    created_by_username: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass
class TaskContextDTO:
    """
    Output DTO for task context snapshot.

    Attributes:
        task_id: Task ID
        request_id: Trace id
        domain: Task domain
        domain_display: Display name for domain
        snapshot_data: Aggregated context data
        generated_at: Snapshot generation time
        data_freshness: Data freshness metrics
        created_at: Server timestamp
    """
    task_id: int
    request_id: str
    domain: str
    domain_display: str
    snapshot_data: Dict[str, Any]
    generated_at: Optional[datetime]
    data_freshness: Optional[Dict[str, Any]]
    created_at: datetime


@dataclass
class TaskStepsDTO:
    """
    Output DTO for task steps.

    Attributes:
        task_id: Task ID
        request_id: Trace id
        steps: List of steps
    """
    task_id: int
    request_id: str
    steps: List[Dict[str, Any]]


@dataclass
class TaskStepDTO:
    """
    Single task step.

    Attributes:
        id: Step ID
        request_id: Trace id
        task_id: Task ID
        step_key: Step identifier
        step_name: Human readable step name
        step_index: Order index
        status: Step status
        started_at: Step start time
        completed_at: Step completion time
        error_message: Error if failed
        output_data: Step output
        created_at: Server timestamp
    """
    id: int
    request_id: str
    task_id: int
    step_key: str
    step_name: str
    step_index: int
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]
    output_data: Optional[Dict[str, Any]]
    created_at: datetime


# ============================================================================
# Error Response DTOs
# ============================================================================

@dataclass
class ErrorResponseDTO:
    """
    Standard error response DTO.

    Follows error contract format from schema-contract.md.

    Attributes:
        request_id: Request trace id
        error: Error details dict with code and message
        task: Optional task details if error relates to a task
    """
    request_id: str
    error: Dict[str, Any]  # {"code": "ERROR_CODE", "message": "...", "details": {...}}
    task: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to response dict."""
        result = {
            "request_id": self.request_id,
            "error": self.error,
        }
        if self.task is not None:
            result["task"] = self.task
        return result


@dataclass
class ValidationErrorDTO:
    """
    Validation error response DTO.

    Attributes:
        request_id: Request trace id
        error: Error details
        field_errors: Dict of field-specific errors
    """
    request_id: str
    error: Dict[str, Any]
    field_errors: Dict[str, List[str]]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to response dict."""
        return {
            "request_id": self.request_id,
            "error": self.error,
            "field_errors": self.field_errors,
        }


# ============================================================================
# Response Wrapper DTOs
# ============================================================================

@dataclass
class TaskCreateResponseDTO:
    """
    Response wrapper for task creation.

    Attributes:
        request_id: Request trace id
        task: Created task detail
    """
    request_id: str
    task: TaskDetailDTO

    def to_dict(self) -> Dict[str, Any]:
        """Convert to response dict."""
        return {
            "request_id": self.request_id,
            "task": self.task.to_response_dict(),
        }


@dataclass
class TaskGetResponseDTO:
    """
    Response wrapper for task retrieval.

    Attributes:
        request_id: Request trace id
        task: Task detail
    """
    request_id: str
    task: TaskDetailDTO

    def to_dict(self) -> Dict[str, Any]:
        """Convert to response dict."""
        return {
            "request_id": self.request_id,
            "task": self.task.to_response_dict(),
        }


@dataclass
class TaskListResponseDTO:
    """
    Response wrapper for task list.

    Attributes:
        request_id: Request trace id
        tasks: Task list result
    """
    request_id: str
    tasks: TaskListDTO

    def to_dict(self) -> Dict[str, Any]:
        """Convert to response dict."""
        return {
            "request_id": self.request_id,
            "tasks": {
                "items": [t.to_dict() for t in self.tasks.tasks],
                "total": self.tasks.total,
                "limit": self.tasks.limit,
                "offset": self.tasks.offset,
            }
        }
