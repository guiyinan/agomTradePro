"""AI Capability Catalog Interface Serializers."""

from typing import Any, TypeAlias

from rest_framework import serializers

SerializerField: TypeAlias = serializers.Field[Any, Any, Any, Any]


class MCPAccessVerificationCheckSerializer(serializers.Serializer[dict[str, Any]]):
    """One bounded MCP access readiness check."""

    key = serializers.ChoiceField(
        choices=("token", "transport", "routing", "catalog"), read_only=True
    )
    status = serializers.ChoiceField(choices=("ready", "unavailable"), read_only=True)

    def get_fields(self) -> dict[str, SerializerField]:
        """Register public detail text without overriding DRF field state."""

        fields = super().get_fields()
        fields["label"] = serializers.CharField(read_only=True)
        fields["detail"] = serializers.CharField(read_only=True)
        return fields


class MCPAccessVerificationSerializer(serializers.Serializer[dict[str, Any]]):
    """Read-only current-user MCP access verification payload."""

    state = serializers.ChoiceField(choices=("ready", "unavailable"), read_only=True)
    checks = MCPAccessVerificationCheckSerializer(many=True, read_only=True)


class RouteRequestSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for routing request."""

    message = serializers.CharField(help_text="User message to route")
    entrypoint = serializers.CharField(
        default="terminal",
        help_text="Entrypoint: terminal, chat, agent",
    )
    session_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Session ID for conversation continuity",
    )
    provider_name = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="AI provider name",
    )
    model = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="AI model name",
    )
    confirmation_id = serializers.CharField(required=False, allow_null=True)
    approved = serializers.BooleanField(required=False, allow_null=True)

    def get_fields(self) -> dict[str, SerializerField]:
        """Register request context without overriding DRF serializer state."""

        fields = super().get_fields()
        fields["context"] = serializers.DictField(
            required=False,
            default=dict,
            help_text="Additional context",
        )
        return fields


class CapabilitySummarySerializer(serializers.Serializer[Any]):
    """Serializer for capability summary."""

    capability_key = serializers.CharField()
    name = serializers.CharField()
    summary = serializers.CharField()
    category = serializers.CharField()
    risk_level = serializers.CharField()
    requires_confirmation = serializers.BooleanField()


class RouteResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for routing response."""

    decision = serializers.CharField(
        help_text="Routing decision: capability, ask_confirmation, chat"
    )
    selected_capability_key = serializers.CharField(
        allow_null=True,
        help_text="Selected capability key",
    )
    confidence = serializers.FloatField(help_text="Confidence score (0-1)")
    candidate_capabilities = CapabilitySummarySerializer(many=True)
    requires_confirmation = serializers.BooleanField()
    reply = serializers.CharField(help_text="Response text")
    session_id = serializers.CharField()
    metadata = serializers.DictField()
    answer_chain = serializers.DictField()
    reason = serializers.CharField(required=False, allow_blank=True)
    rejected_candidates = serializers.ListField(
        child=serializers.CharField(),
        required=False,
    )
    filled_params = serializers.DictField(required=False)
    missing_params = serializers.ListField(
        child=serializers.CharField(),
        required=False,
    )
    suggested_command = serializers.CharField(
        allow_null=True,
        required=False,
    )
    suggested_intent = serializers.CharField(
        allow_null=True,
        required=False,
    )
    suggestion_prompt = serializers.CharField(
        allow_null=True,
        required=False,
    )
    confirmation = serializers.DictField(required=False, allow_null=True)
    result = serializers.JSONField(required=False, allow_null=True)


class CapabilityDetailSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for detailed capability."""

    capability_key = serializers.CharField()
    source_type = serializers.CharField()
    source_ref = serializers.CharField()
    name = serializers.CharField()
    summary = serializers.CharField()
    description = serializers.CharField()
    route_group = serializers.CharField()
    category = serializers.CharField()
    tags = serializers.ListField(child=serializers.CharField())
    when_to_use = serializers.ListField(child=serializers.CharField())
    when_not_to_use = serializers.ListField(child=serializers.CharField())
    examples = serializers.ListField(child=serializers.CharField())
    input_schema = serializers.DictField()
    execution_kind = serializers.CharField()
    execution_target = serializers.DictField()
    risk_level = serializers.CharField()
    requires_mcp = serializers.BooleanField()
    requires_confirmation = serializers.BooleanField()
    enabled_for_routing = serializers.BooleanField()
    enabled_for_terminal = serializers.BooleanField()
    enabled_for_chat = serializers.BooleanField()
    enabled_for_agent = serializers.BooleanField()
    visibility = serializers.CharField()
    auto_collected = serializers.BooleanField()
    review_status = serializers.CharField()
    priority_weight = serializers.FloatField()


class CapabilityPublicDetailSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for non-admin capability detail."""

    capability_key = serializers.CharField()
    source_type = serializers.CharField()
    name = serializers.CharField()
    summary = serializers.CharField()
    description = serializers.CharField()
    route_group = serializers.CharField()
    category = serializers.CharField()
    tags = serializers.ListField(child=serializers.CharField())
    when_to_use = serializers.ListField(child=serializers.CharField())
    when_not_to_use = serializers.ListField(child=serializers.CharField())
    examples = serializers.ListField(child=serializers.CharField())
    risk_level = serializers.CharField()
    requires_mcp = serializers.BooleanField()
    requires_confirmation = serializers.BooleanField()
    enabled_for_routing = serializers.BooleanField()
    enabled_for_terminal = serializers.BooleanField()
    enabled_for_chat = serializers.BooleanField()
    enabled_for_agent = serializers.BooleanField()
    visibility = serializers.CharField()
    auto_collected = serializers.BooleanField()
    review_status = serializers.CharField()
    priority_weight = serializers.FloatField()


class SyncResultSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for sync result."""

    sync_type = serializers.CharField()
    total_discovered = serializers.IntegerField()
    created_count = serializers.IntegerField()
    updated_count = serializers.IntegerField()
    disabled_count = serializers.IntegerField()
    error_count = serializers.IntegerField()
    duration_seconds = serializers.FloatField()
    summary = serializers.DictField()


class CatalogStatsSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for catalog statistics."""

    total = serializers.IntegerField()
    enabled = serializers.IntegerField()
    disabled = serializers.IntegerField()
    by_source = serializers.DictField()
    by_route_group = serializers.DictField()


class McpToolSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for MCP governance list rows."""

    capability_key = serializers.CharField()
    name = serializers.CharField()
    module_name = serializers.CharField()
    summary = serializers.CharField()
    description = serializers.CharField()
    route_group = serializers.CharField()
    category = serializers.CharField()
    risk_level = serializers.CharField()
    review_status = serializers.CharField()
    visibility = serializers.CharField()
    requires_confirmation = serializers.BooleanField()
    enabled_for_routing = serializers.BooleanField()
    enabled_for_terminal = serializers.BooleanField()


class McpToolListSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for MCP governance list payload."""

    total_count = serializers.IntegerField()
    module_choices = serializers.ListField(child=serializers.CharField())
    search_query = serializers.CharField()
    module_filter = serializers.CharField()
    status_filter = serializers.CharField()
    latest_sync_at = serializers.DateTimeField(allow_null=True)
    latest_sync_total_discovered = serializers.IntegerField()
    tools = McpToolSerializer(many=True)


class McpToolStatsSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for MCP governance summary payload."""

    status = serializers.CharField()
    total = serializers.IntegerField()
    module_count = serializers.IntegerField()
    routing_enabled = serializers.IntegerField()
    routing_disabled = serializers.IntegerField()
    terminal_enabled = serializers.IntegerField()
    terminal_disabled = serializers.IntegerField()
    requires_confirmation = serializers.IntegerField()
    high_risk = serializers.IntegerField()
    latest_sync_at = serializers.DateTimeField(allow_null=True)
    latest_sync_total_discovered = serializers.IntegerField()
    latest_sync_created = serializers.IntegerField()
    latest_sync_updated = serializers.IntegerField()
    latest_sync_disabled = serializers.IntegerField()


class McpToolToggleResultSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for one MCP flag toggle result."""

    capability_key = serializers.CharField()
    name = serializers.CharField()
    changed_flag = serializers.CharField()
    changed_value = serializers.BooleanField()
    enabled_for_routing = serializers.BooleanField()
    enabled_for_terminal = serializers.BooleanField()


class McpToolSyncResultSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for MCP sync plus governance summary."""

    sync = SyncResultSerializer()
    governance = serializers.DictField()


class WebChatRequestSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for shared web chat request."""

    message = serializers.CharField(help_text="User message")
    session_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Session ID for conversation continuity",
    )
    provider_name = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="AI provider name",
    )
    model = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="AI model name",
    )
    confirmation_id = serializers.CharField(required=False, allow_null=True)
    approved = serializers.BooleanField(required=False, allow_null=True)

    def get_fields(self) -> dict[str, SerializerField]:
        """Register chat context without overriding DRF serializer state."""

        fields = super().get_fields()
        fields["context"] = serializers.DictField(
            required=False,
            default=dict,
            help_text="Additional context including history",
        )
        return fields


class SuggestedActionSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for suggested action object."""

    action_type = serializers.CharField(help_text="Action type: execute_capability")
    capability_key = serializers.CharField(help_text="Target capability key")
    command = serializers.CharField(help_text="Suggested command string")
    intent = serializers.CharField(help_text="Detected intent")
    payload = serializers.DictField(help_text="Additional payload for execution")

    def get_fields(self) -> dict[str, SerializerField]:
        """Register public copy fields without overriding DRF field metadata."""

        fields = super().get_fields()
        fields["label"] = serializers.CharField(help_text="Display label for the action")
        fields["description"] = serializers.CharField(help_text="Action description")
        return fields


class AnswerChainSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for answer chain."""

    visibility = serializers.CharField()
    steps = serializers.ListField(child=serializers.DictField())

    def get_fields(self) -> dict[str, SerializerField]:
        """Register the public label without overriding DRF field metadata."""

        fields = super().get_fields()
        fields["label"] = serializers.CharField()
        return fields


class WebChatMetadataSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for web chat metadata."""

    provider = serializers.CharField()
    model = serializers.CharField()
    tokens = serializers.IntegerField(default=0)
    answer_chain = AnswerChainSerializer(required=False, allow_null=True)


class WebChatResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for shared web chat response."""

    reply = serializers.CharField(help_text="AI response text")
    session_id = serializers.CharField(help_text="Session ID")
    metadata = WebChatMetadataSerializer(help_text="Response metadata")
    route_confirmation_required = serializers.BooleanField(
        default=False,
        help_text="Whether confirmation is required",
    )
    suggested_command = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Suggested command string",
    )
    suggested_intent = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Detected intent",
    )
    suggestion_prompt = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Suggestion prompt text",
    )
    suggested_action = SuggestedActionSerializer(
        allow_null=True,
        required=False,
        help_text="Structured suggested action object",
    )
    confirmation = serializers.DictField(required=False, allow_null=True)
    selected_capability_key = serializers.CharField(required=False, allow_null=True)
    result = serializers.JSONField(required=False, allow_null=True)
