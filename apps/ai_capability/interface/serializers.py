"""
AI Capability Catalog Interface Serializers.
"""

from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
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
    context = serializers.DictField(
        required=False,
        default=dict,
        help_text="Additional context",
    )


class CapabilitySummarySerializer(serializers.Serializer):
    """Serializer for capability summary."""

    capability_key = serializers.CharField()
    name = serializers.CharField()
    summary = serializers.CharField()
    category = serializers.CharField()
    risk_level = serializers.CharField()
    requires_confirmation = serializers.BooleanField()


class RouteResponseSerializer(serializers.Serializer):
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


class CapabilityDetailSerializer(serializers.Serializer):
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


class CapabilityPublicDetailSerializer(serializers.Serializer):
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


class SyncResultSerializer(serializers.Serializer):
    """Serializer for sync result."""

    sync_type = serializers.CharField()
    total_discovered = serializers.IntegerField()
    created_count = serializers.IntegerField()
    updated_count = serializers.IntegerField()
    disabled_count = serializers.IntegerField()
    error_count = serializers.IntegerField()
    duration_seconds = serializers.FloatField()
    summary = serializers.DictField()


class CatalogStatsSerializer(serializers.Serializer):
    """Serializer for catalog statistics."""

    total = serializers.IntegerField()
    enabled = serializers.IntegerField()
    disabled = serializers.IntegerField()
    by_source = serializers.DictField()
    by_route_group = serializers.DictField()


class WebChatRequestSerializer(serializers.Serializer):
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
    context = serializers.DictField(
        required=False,
        default=dict,
        help_text="Additional context including history",
    )


class SuggestedActionSerializer(serializers.Serializer):
    """Serializer for suggested action object."""

    action_type = serializers.CharField(help_text="Action type: execute_capability")
    capability_key = serializers.CharField(help_text="Target capability key")
    command = serializers.CharField(help_text="Suggested command string")
    intent = serializers.CharField(help_text="Detected intent")
    label = serializers.CharField(help_text="Display label for the action")
    description = serializers.CharField(help_text="Action description")
    payload = serializers.DictField(help_text="Additional payload for execution")


class AnswerChainSerializer(serializers.Serializer):
    """Serializer for answer chain."""

    label = serializers.CharField()
    visibility = serializers.CharField()
    steps = serializers.ListField(child=serializers.DictField())


class WebChatMetadataSerializer(serializers.Serializer):
    """Serializer for web chat metadata."""

    provider = serializers.CharField()
    model = serializers.CharField()
    tokens = serializers.IntegerField(default=0)
    answer_chain = AnswerChainSerializer(required=False, allow_null=True)


class WebChatResponseSerializer(serializers.Serializer):
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
