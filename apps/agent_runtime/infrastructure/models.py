"""
ORM Models for Agent Runtime.

FROZEN: Model names and field names must not change.
See: docs/plans/ai-native/schema-contract.md
"""

from typing import Any, Dict, Optional

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from apps.agent_runtime.domain.entities import (
    ApprovalStatus,
    EventSource,
    GuardrailDecision,
    ProposalStatus,
    RiskLevel,
    TaskDomain,
    TaskStatus,
    TimelineEventType,
)


class AgentTaskModel(models.Model):
    """
    FROZEN: AgentTask ORM Model.

    Represents an AI agent task with lifecycle management.
    """

    # Primary fields
    request_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Stable request trace id"
    )
    schema_version = models.CharField(
        max_length=16,
        default="v1",
        help_text="Schema version"
    )

    # Task classification
    task_domain = models.CharField(
        max_length=20,
        choices=[(d.value, d.name) for d in TaskDomain],
        db_index=True,
        help_text="Task domain: research/monitoring/decision/execution/ops"
    )
    task_type = models.CharField(
        max_length=100,
        help_text="Task subtype"
    )

    # Task state
    status = models.CharField(
        max_length=30,
        choices=[(s.value, s.name) for s in TaskStatus],
        default=TaskStatus.DRAFT.value,
        db_index=True,
        help_text="Current task status"
    )

    # Task data
    input_payload = models.JSONField(
        default=dict,
        help_text="JSON input payload"
    )
    current_step = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Current step key"
    )
    last_error = models.JSONField(
        null=True,
        blank=True,
        help_text="Structured error payload"
    )

    # Human intervention flag
    requires_human = models.BooleanField(
        default=False,
        help_text="Whether human intervention is needed"
    )

    # User association
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agent_tasks',
        help_text="User id if authenticated"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_task'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['request_id']),
            models.Index(fields=['status']),
            models.Index(fields=['task_domain']),
            models.Index(fields=['task_domain', 'status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Task {self.request_id}: {self.task_domain}/{self.task_type} [{self.status}]"

    def to_domain_entity(self):
        """Convert to domain entity."""
        from apps.agent_runtime.domain.entities import AgentTask
        return AgentTask(
            id=self.id,
            request_id=self.request_id,
            schema_version=self.schema_version,
            task_domain=TaskDomain(self.task_domain),
            task_type=self.task_type,
            status=TaskStatus(self.status),
            input_payload=self.input_payload or {},
            current_step=self.current_step,
            last_error=self.last_error,
            requires_human=self.requires_human,
            created_by=self.created_by_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class AgentTaskStepModel(models.Model):
    """AgentTaskStep ORM Model - represents a step in task execution."""

    request_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Trace id"
    )
    task = models.ForeignKey(
        AgentTaskModel,
        on_delete=models.CASCADE,
        related_name='steps',
        help_text="Linked task"
    )
    step_key = models.CharField(
        max_length=100,
        help_text="Step identifier"
    )
    step_name = models.CharField(
        max_length=200,
        help_text="Human readable step name"
    )
    step_index = models.IntegerField(
        default=0,
        help_text="Order index"
    )
    status = models.CharField(
        max_length=20,
        default='pending',
        help_text="Step status"
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Step start time"
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Step completion time"
    )
    error_message = models.TextField(
        null=True,
        blank=True,
        help_text="Error if failed"
    )
    output_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Step output"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'agent_task_step'
        ordering = ['step_index']
        indexes = [
            models.Index(fields=['request_id']),
            models.Index(fields=['task', 'step_index']),
        ]

    def __str__(self):
        return f"Step {self.step_key}: {self.status}"


class AgentContextSnapshotModel(models.Model):
    """AgentContextSnapshot ORM Model - context aggregation for tasks."""

    request_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Trace id"
    )
    task = models.OneToOneField(
        AgentTaskModel,
        on_delete=models.CASCADE,
        related_name='context_snapshot',
        help_text="Linked task"
    )
    domain = models.CharField(
        max_length=20,
        choices=[(d.value, d.name) for d in TaskDomain],
        help_text="Task domain"
    )
    snapshot_data = models.JSONField(
        default=dict,
        help_text="Aggregated context data"
    )
    generated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Snapshot generation time"
    )
    data_freshness = models.JSONField(
        null=True,
        blank=True,
        help_text="Data freshness metrics"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'agent_context_snapshot'
        indexes = [
            models.Index(fields=['request_id']),
            models.Index(fields=['domain']),
        ]

    def __str__(self):
        return f"Context for task {self.task_id}"


class AgentProposalModel(models.Model):
    """
    FROZEN: AgentProposal ORM Model.

    Represents a proposal generated by an agent for execution.
    """

    # Primary fields
    request_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Trace id"
    )
    schema_version = models.CharField(
        max_length=16,
        default="v1",
        help_text="Schema version"
    )

    # Task linkage
    task = models.ForeignKey(
        AgentTaskModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='proposals',
        help_text="Linked task"
    )

    # Proposal classification
    proposal_type = models.CharField(
        max_length=50,
        help_text="Type of proposal (e.g., rebalance, signal_write)"
    )

    # Proposal state
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.name) for s in ProposalStatus],
        default=ProposalStatus.DRAFT.value,
        db_index=True,
        help_text="Proposal status"
    )
    risk_level = models.CharField(
        max_length=20,
        choices=[(r.value, r.name) for r in RiskLevel],
        default=RiskLevel.MEDIUM.value,
        help_text="Risk level assessment"
    )

    # Approval workflow
    approval_required = models.BooleanField(
        default=True,
        help_text="Server-evaluated approval requirement"
    )
    approval_status = models.CharField(
        max_length=20,
        choices=[(a.value, a.name) for a in ApprovalStatus],
        default=ApprovalStatus.PENDING.value,
        help_text="Current approval status"
    )
    approval_reason = models.TextField(
        null=True,
        blank=True,
        help_text="Human/system explanation"
    )

    # Proposal data
    proposal_payload = models.JSONField(
        default=dict,
        help_text="Execution payload"
    )

    # User association
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agent_proposals',
        help_text="User id"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_proposal'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['request_id']),
            models.Index(fields=['status']),
            models.Index(fields=['approval_status']),
            models.Index(fields=['task']),
        ]

    def __str__(self):
        return f"Proposal {self.request_id}: {self.proposal_type} [{self.status}]"

    def to_domain_entity(self):
        """Convert to domain entity."""
        from apps.agent_runtime.domain.entities import AgentProposal
        return AgentProposal(
            id=self.id,
            request_id=self.request_id,
            schema_version=self.schema_version,
            task_id=self.task_id,
            proposal_type=self.proposal_type,
            status=ProposalStatus(self.status),
            risk_level=RiskLevel(self.risk_level),
            approval_required=self.approval_required,
            approval_status=ApprovalStatus(self.approval_status),
            proposal_payload=self.proposal_payload or {},
            approval_reason=self.approval_reason,
            created_by=self.created_by_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class AgentExecutionRecordModel(models.Model):
    """AgentExecutionRecord ORM Model - records execution results."""

    request_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Trace id"
    )
    task = models.ForeignKey(
        AgentTaskModel,
        on_delete=models.CASCADE,
        related_name='execution_records',
        help_text="Linked task"
    )
    proposal = models.ForeignKey(
        AgentProposalModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='execution_records',
        help_text="Linked proposal"
    )
    execution_status = models.CharField(
        max_length=20,
        default='pending',
        help_text="Execution result status"
    )
    execution_output = models.JSONField(
        null=True,
        blank=True,
        help_text="Execution output data"
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Execution start time"
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Execution completion time"
    )
    error_details = models.JSONField(
        null=True,
        blank=True,
        help_text="Error details if failed"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'agent_execution_record'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['request_id']),
            models.Index(fields=['task']),
            models.Index(fields=['proposal']),
        ]

    def __str__(self):
        return f"Execution {self.request_id}: {self.execution_status}"


class AgentArtifactModel(models.Model):
    """AgentArtifact ORM Model - stores task artifacts."""

    request_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Trace id"
    )
    task = models.ForeignKey(
        AgentTaskModel,
        on_delete=models.CASCADE,
        related_name='artifacts',
        help_text="Linked task"
    )
    artifact_type = models.CharField(
        max_length=50,
        help_text="Type of artifact"
    )
    artifact_name = models.CharField(
        max_length=200,
        help_text="Artifact name"
    )
    artifact_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Artifact content"
    )
    file_path = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        help_text="Path to file if stored externally"
    )
    content_type = models.CharField(
        max_length=100,
        default='application/json',
        help_text="MIME type"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'agent_artifact'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['request_id']),
            models.Index(fields=['task']),
            models.Index(fields=['artifact_type']),
        ]

    def __str__(self):
        return f"Artifact {self.artifact_name}: {self.artifact_type}"


class AgentTimelineEventModel(models.Model):
    """
    FROZEN: AgentTimelineEvent ORM Model.

    Records all task lifecycle events for audit trail.
    """

    request_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Trace id"
    )
    task = models.ForeignKey(
        AgentTaskModel,
        on_delete=models.CASCADE,
        related_name='timeline_events',
        help_text="Linked task"
    )
    proposal = models.ForeignKey(
        AgentProposalModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='timeline_events',
        help_text="Linked proposal (optional)"
    )
    event_type = models.CharField(
        max_length=30,
        choices=[(e.value, e.name) for e in TimelineEventType],
        help_text="Event type from frozen enum"
    )
    event_source = models.CharField(
        max_length=20,
        choices=[(s.value, s.name) for s in EventSource],
        default=EventSource.SYSTEM.value,
        help_text="Source of event (api/sdk/mcp/system/human)"
    )
    step_index = models.IntegerField(
        null=True,
        blank=True,
        help_text="Step sequence number"
    )
    event_payload = models.JSONField(
        default=dict,
        help_text="Event details"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'agent_timeline_event'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['request_id']),
            models.Index(fields=['task']),
            models.Index(fields=['event_type']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Event {self.event_type} for task {self.task_id}"

    def to_domain_entity(self):
        """Convert to domain entity."""
        from apps.agent_runtime.domain.entities import AgentTimelineEvent
        return AgentTimelineEvent(
            id=self.id,
            request_id=self.request_id,
            task_id=self.task_id,
            proposal_id=self.proposal_id,
            event_type=TimelineEventType(self.event_type),
            event_source=EventSource(self.event_source),
            step_index=self.step_index,
            event_payload=self.event_payload or {},
            created_at=self.created_at,
        )


class AgentHandoffModel(models.Model):
    """AgentHandoff ORM Model - records task handoffs between agents/humans."""

    request_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Trace id"
    )
    task = models.ForeignKey(
        AgentTaskModel,
        on_delete=models.CASCADE,
        related_name='handoffs',
        help_text="Linked task"
    )
    from_agent = models.CharField(
        max_length=100,
        help_text="Source agent identifier"
    )
    to_agent = models.CharField(
        max_length=100,
        help_text="Target agent identifier"
    )
    handoff_reason = models.TextField(
        help_text="Reason for handoff"
    )
    handoff_payload = models.JSONField(
        null=True,
        blank=True,
        help_text="Context payload for handoff"
    )
    handoff_status = models.CharField(
        max_length=20,
        default='pending',
        help_text="Handoff status"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'agent_handoff'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['request_id']),
            models.Index(fields=['task']),
        ]

    def __str__(self):
        return f"Handoff {self.from_agent} -> {self.to_agent}"


class AgentGuardrailDecisionModel(models.Model):
    """
    FROZEN: AgentGuardrailDecision ORM Model.

    Records guardrail decisions for proposals.
    """

    request_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Trace id"
    )
    task = models.ForeignKey(
        AgentTaskModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='guardrail_decisions',
        help_text="Linked task (optional)"
    )
    proposal = models.ForeignKey(
        AgentProposalModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='guardrail_decisions',
        help_text="Linked proposal (optional)"
    )
    decision = models.CharField(
        max_length=20,
        choices=[(d.value, d.name) for d in GuardrailDecision],
        default=GuardrailDecision.ALLOWED.value,
        help_text="Guardrail decision"
    )
    reason_code = models.CharField(
        max_length=50,
        help_text="Stable machine-readable reason"
    )
    message = models.TextField(
        help_text="Human-readable summary"
    )
    evidence = models.JSONField(
        default=dict,
        help_text="Supporting data"
    )
    requires_human = models.BooleanField(
        default=False,
        help_text="Convenience flag"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'agent_guardrail_decision'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['request_id']),
            models.Index(fields=['task']),
            models.Index(fields=['proposal']),
            models.Index(fields=['decision']),
        ]

    def __str__(self):
        return f"Guardrail {self.decision}: {self.reason_code}"

    def to_domain_entity(self):
        """Convert to domain entity."""
        from apps.agent_runtime.domain.entities import AgentGuardrailDecision
        return AgentGuardrailDecision(
            id=self.id,
            request_id=self.request_id,
            task_id=self.task_id,
            proposal_id=self.proposal_id,
            decision=GuardrailDecision(self.decision),
            reason_code=self.reason_code,
            message=self.message,
            evidence=self.evidence or {},
            requires_human=self.requires_human,
            created_at=self.created_at,
        )
