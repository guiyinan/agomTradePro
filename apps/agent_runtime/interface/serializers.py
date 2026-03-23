"""
DRF Serializers for Agent Runtime API.

WP-M1-04: Serializers for Agent Runtime Module
See: docs/plans/ai-native/schema-contract.md
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from rest_framework import serializers

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
from apps.agent_runtime.infrastructure.models import (
    AgentArtifactModel,
    AgentContextSnapshotModel,
    AgentExecutionRecordModel,
    AgentGuardrailDecisionModel,
    AgentHandoffModel,
    AgentProposalModel,
    AgentTaskModel,
    AgentTaskStepModel,
    AgentTimelineEventModel,
)
from shared.infrastructure.sanitization import sanitize_plain_text


class AgentTaskSerializer(serializers.ModelSerializer):
    """
    Serializer for AgentTaskModel - full task detail output.

    Includes all fields with display values for enums.
    """

    # Display values for enums
    task_domain_display = serializers.CharField(source='get_task_domain_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)

    # Counters for related objects
    steps_count = serializers.SerializerMethodField()
    proposals_count = serializers.SerializerMethodField()
    artifacts_count = serializers.SerializerMethodField()
    timeline_events_count = serializers.SerializerMethodField()

    class Meta:
        model = AgentTaskModel
        fields = [
            'id',
            'request_id',
            'schema_version',
            'task_domain',
            'task_domain_display',
            'task_type',
            'status',
            'status_display',
            'input_payload',
            'current_step',
            'last_error',
            'requires_human',
            'created_by',
            'created_by_username',
            'created_at',
            'updated_at',
            # Related counts
            'steps_count',
            'proposals_count',
            'artifacts_count',
            'timeline_events_count',
        ]
        read_only_fields = [
            'id',
            'request_id',
            'schema_version',
            'created_at',
            'updated_at',
            'created_by',
        ]

    def get_steps_count(self, obj: AgentTaskModel) -> int:
        return obj.steps.count()

    def get_proposals_count(self, obj: AgentTaskModel) -> int:
        return obj.proposals.count()

    def get_artifacts_count(self, obj: AgentTaskModel) -> int:
        return obj.artifacts.count()

    def get_timeline_events_count(self, obj: AgentTaskModel) -> int:
        return obj.timeline_events.count()


class AgentTaskCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a new AgentTask.

    Input validation for task creation.
    """

    task_domain = serializers.ChoiceField(
        choices=[d.value for d in TaskDomain],
        required=True,
        help_text="Task domain: research/monitoring/decision/execution/ops"
    )
    task_type = serializers.CharField(
        max_length=100,
        required=True,
        help_text="Task subtype (e.g., macro_portfolio_review)"
    )
    input_payload = serializers.JSONField(
        default=dict,
        required=False,
        help_text="JSON input payload for the task"
    )

    def validate_task_domain(self, value: str) -> str:
        """Validate and normalize task domain."""
        value = sanitize_plain_text(value)
        try:
            TaskDomain(value)
        except ValueError:
            raise serializers.ValidationError(
                f"Invalid task_domain. Must be one of: {[d.value for d in TaskDomain]}"
            )
        return value

    def validate_task_type(self, value: str) -> str:
        """Validate task type with XSS sanitization."""
        value = sanitize_plain_text(value)
        if not value or len(value.strip()) < 2:
            raise serializers.ValidationError(
                "task_type must be at least 2 characters"
            )
        return value

    def validate_input_payload(self, value: dict[str, Any]) -> dict[str, Any]:
        """Validate input payload is a dict."""
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "input_payload must be a JSON object"
            )
        return value


class AgentTaskListSerializer(serializers.ModelSerializer):
    """
    Serializer for task list output.

    Lightweight version for list views.
    """

    task_domain_display = serializers.CharField(source='get_task_domain_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AgentTaskModel
        fields = [
            'id',
            'request_id',
            'schema_version',
            'task_domain',
            'task_domain_display',
            'task_type',
            'status',
            'status_display',
            'current_step',
            'requires_human',
            'created_at',
            'updated_at',
        ]


class AgentTaskUpdateSerializer(serializers.Serializer):
    """
    Serializer for updating an existing AgentTask.

    Supports status transitions and step updates.
    """

    status = serializers.ChoiceField(
        choices=[s.value for s in TaskStatus],
        required=False,
        help_text="New task status"
    )
    current_step = serializers.CharField(
        max_length=100,
        required=False,
        allow_null=True,
        help_text="Current step key"
    )
    last_error = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="Structured error payload"
    )
    requires_human = serializers.BooleanField(
        required=False,
        help_text="Whether human intervention is needed"
    )

    def validate_status(self, value: str | None) -> str | None:
        """Validate status transition."""
        if value is not None:
            try:
                TaskStatus(value)
            except ValueError:
                raise serializers.ValidationError(
                    f"Invalid status. Must be one of: {[s.value for s in TaskStatus]}"
                )
        return value

    def validate_current_step(self, value: str | None) -> str | None:
        """Validate current step with XSS sanitization."""
        if value is not None:
            value = sanitize_plain_text(value)
        return value


class AgentProposalSerializer(serializers.ModelSerializer):
    """
    Serializer for AgentProposalModel.
    """

    status_display = serializers.CharField(source='get_status_display', read_only=True)
    risk_level_display = serializers.CharField(source='get_risk_level_display', read_only=True)
    approval_status_display = serializers.CharField(source='get_approval_status_display', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)

    class Meta:
        model = AgentProposalModel
        fields = [
            'id',
            'request_id',
            'schema_version',
            'task_id',
            'proposal_type',
            'status',
            'status_display',
            'risk_level',
            'risk_level_display',
            'approval_required',
            'approval_status',
            'approval_status_display',
            'approval_reason',
            'proposal_payload',
            'created_by',
            'created_by_username',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'request_id',
            'schema_version',
            'created_at',
            'updated_at',
        ]


class AgentProposalCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a new proposal.
    """

    task_id = serializers.IntegerField(required=False, allow_null=True)
    proposal_type = serializers.CharField(max_length=50, required=True)
    risk_level = serializers.ChoiceField(
        choices=[r.value for r in RiskLevel],
        default=RiskLevel.MEDIUM.value,
        required=False
    )
    approval_required = serializers.BooleanField(default=True, required=False)
    proposal_payload = serializers.JSONField(default=dict, required=False)
    approval_reason = serializers.CharField(allow_null=True, required=False)

    def validate_proposal_type(self, value: str) -> str:
        """Validate proposal type with XSS sanitization."""
        value = sanitize_plain_text(value)
        if not value:
            raise serializers.ValidationError("proposal_type cannot be empty")
        return value

    def validate_approval_reason(self, value: str | None) -> str | None:
        """Validate approval reason with XSS sanitization."""
        if value is not None:
            value = sanitize_plain_text(value)
        return value


class AgentTimelineEventSerializer(serializers.ModelSerializer):
    """
    Serializer for AgentTimelineEventModel.

    Timeline events for task audit trail.
    """

    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    event_source_display = serializers.CharField(source='get_event_source_display', read_only=True)

    class Meta:
        model = AgentTimelineEventModel
        fields = [
            'id',
            'request_id',
            'task_id',
            'proposal_id',
            'event_type',
            'event_type_display',
            'event_source',
            'event_source_display',
            'step_index',
            'event_payload',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'request_id',
            'created_at',
        ]


class AgentArtifactSerializer(serializers.ModelSerializer):
    """
    Serializer for AgentArtifactModel.

    Task artifacts like reports, charts, etc.
    """

    class Meta:
        model = AgentArtifactModel
        fields = [
            'id',
            'request_id',
            'task_id',
            'artifact_type',
            'artifact_name',
            'artifact_data',
            'file_path',
            'content_type',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'request_id',
            'created_at',
        ]

    def validate_artifact_name(self, value: str) -> str:
        """Validate artifact name with XSS sanitization."""
        value = sanitize_plain_text(value)
        if not value:
            raise serializers.ValidationError("artifact_name cannot be empty")
        return value

    def validate_artifact_type(self, value: str) -> str:
        """Validate artifact type with XSS sanitization."""
        value = sanitize_plain_text(value)
        if not value:
            raise serializers.ValidationError("artifact_type cannot be empty")
        return value


class AgentExecutionRecordSerializer(serializers.ModelSerializer):
    """
    Serializer for AgentExecutionRecordModel.

    Records execution results for proposals.
    """

    class Meta:
        model = AgentExecutionRecordModel
        fields = [
            'id',
            'request_id',
            'task_id',
            'proposal_id',
            'execution_status',
            'execution_output',
            'started_at',
            'completed_at',
            'error_details',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'request_id',
            'created_at',
        ]


class AgentContextSnapshotSerializer(serializers.ModelSerializer):
    """
    Serializer for AgentContextSnapshotModel.
    """

    domain_display = serializers.CharField(source='get_domain_display', read_only=True)

    class Meta:
        model = AgentContextSnapshotModel
        fields = [
            'id',
            'request_id',
            'task_id',
            'domain',
            'domain_display',
            'snapshot_data',
            'generated_at',
            'data_freshness',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'request_id',
            'created_at',
        ]


class AgentTaskStepSerializer(serializers.ModelSerializer):
    """
    Serializer for AgentTaskStepModel.
    """

    class Meta:
        model = AgentTaskStepModel
        fields = [
            'id',
            'request_id',
            'task_id',
            'step_key',
            'step_name',
            'step_index',
            'status',
            'started_at',
            'completed_at',
            'error_message',
            'output_data',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'request_id',
            'created_at',
        ]

    def validate_step_name(self, value: str) -> str:
        """Validate step name with XSS sanitization."""
        value = sanitize_plain_text(value)
        if not value:
            raise serializers.ValidationError("step_name cannot be empty")
        return value


class AgentHandoffSerializer(serializers.ModelSerializer):
    """
    Serializer for AgentHandoffModel.
    """

    class Meta:
        model = AgentHandoffModel
        fields = [
            'id',
            'request_id',
            'task_id',
            'from_agent',
            'to_agent',
            'handoff_reason',
            'handoff_payload',
            'handoff_status',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'request_id',
            'created_at',
        ]

    def validate_from_agent(self, value: str) -> str:
        """Validate from_agent with XSS sanitization."""
        return sanitize_plain_text(value)

    def validate_to_agent(self, value: str) -> str:
        """Validate to_agent with XSS sanitization."""
        return sanitize_plain_text(value)

    def validate_handoff_reason(self, value: str) -> str:
        """Validate handoff_reason with XSS sanitization."""
        value = sanitize_plain_text(value)
        if not value:
            raise serializers.ValidationError("handoff_reason cannot be empty")
        return value


class AgentGuardrailDecisionSerializer(serializers.ModelSerializer):
    """
    Serializer for AgentGuardrailDecisionModel.
    """

    decision_display = serializers.CharField(source='get_decision_display', read_only=True)

    class Meta:
        model = AgentGuardrailDecisionModel
        fields = [
            'id',
            'request_id',
            'task_id',
            'proposal_id',
            'decision',
            'decision_display',
            'reason_code',
            'message',
            'evidence',
            'requires_human',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'request_id',
            'created_at',
        ]

    def validate_reason_code(self, value: str) -> str:
        """Validate reason_code with XSS sanitization."""
        value = sanitize_plain_text(value)
        if not value:
            raise serializers.ValidationError("reason_code cannot be empty")
        return value

    def validate_message(self, value: str) -> str:
        """Validate message with XSS sanitization."""
        value = sanitize_plain_text(value)
        if not value:
            raise serializers.ValidationError("message cannot be empty")
        return value


class AgentTaskListQuerySerializer(serializers.Serializer):
    """
    Serializer for task list query parameters.
    """

    status = serializers.ChoiceField(
        choices=[s.value for s in TaskStatus],
        required=False,
        allow_null=True
    )
    task_domain = serializers.ChoiceField(
        choices=[d.value for d in TaskDomain],
        required=False,
        allow_null=True
    )
    task_type = serializers.CharField(required=False, allow_null=True)
    requires_human = serializers.BooleanField(required=False, allow_null=True)
    search = serializers.CharField(required=False, allow_null=True)
    limit = serializers.IntegerField(default=50, min_value=1, max_value=500)
    offset = serializers.IntegerField(default=0, min_value=0)


class TaskApprovalRequestSerializer(serializers.Serializer):
    """
    Serializer for task approval requests.
    """

    action = serializers.ChoiceField(
        choices=['approve', 'reject'],
        required=True
    )
    reason = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def validate_reason(self, value: str | None) -> str | None:
        """Validate reason with XSS sanitization."""
        if value is not None:
            value = sanitize_plain_text(value)
        return value


class TaskExecutionRequestSerializer(serializers.Serializer):
    """
    Serializer for task execution requests.
    """

    input_payload = serializers.JSONField(required=False, default=dict)
    force = serializers.BooleanField(default=False, help_text="Force execution even if task is not in ready state")


class TaskErrorResponseSerializer(serializers.Serializer):
    """
    Serializer for task error responses.

    Follows FROZEN error contract format from schema-contract.md:151:
    {
        "request_id": "atr_20260316_000001",
        "success": false,
        "error_code": "invalid_task_domain",
        "message": "Unsupported task_domain.",
        "details": {...}  // Optional
    }
    """

    request_id = serializers.CharField()
    success = serializers.BooleanField(default=False)
    error_code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.DictField(required=False, allow_null=True)
