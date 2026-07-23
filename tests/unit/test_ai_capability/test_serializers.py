"""AI Capability interface serializer contract tests."""

from apps.ai_capability.interface.serializers import (
    AnswerChainSerializer,
    MCPAccessVerificationCheckSerializer,
    RouteRequestSerializer,
    SuggestedActionSerializer,
    WebChatRequestSerializer,
)


def test_route_and_chat_context_fields_remain_writable() -> None:
    """Preserve both public context fields without replacing DRF state."""

    route = RouteRequestSerializer(data={"message": "route", "context": {"scope": "all"}})
    chat = WebChatRequestSerializer(data={"message": "chat", "context": {"history": []}})

    assert route.is_valid(), route.errors
    assert chat.is_valid(), chat.errors
    assert route.validated_data["context"] == {"scope": "all"}
    assert chat.validated_data["context"] == {"history": []}


def test_mcp_check_keeps_label_and_detail_output_fields() -> None:
    """Keep the established verification payload field names."""

    serializer = MCPAccessVerificationCheckSerializer(
        {"key": "routing", "label": "Routing", "status": "ready", "detail": "Ready"}
    )

    assert serializer.data == {
        "key": "routing",
        "label": "Routing",
        "status": "ready",
        "detail": "Ready",
    }


def test_action_and_answer_chain_labels_remain_public_fields() -> None:
    """Validate copy fields registered dynamically around DRF metadata."""

    action = SuggestedActionSerializer(
        data={
            "action_type": "execute_capability",
            "capability_key": "alpha.get_scores",
            "command": "/alpha scores",
            "intent": "inspect alpha",
            "label": "Inspect Alpha",
            "description": "Load current scores",
            "payload": {},
        }
    )
    chain = AnswerChainSerializer(data={"label": "Evidence", "visibility": "public", "steps": []})

    assert action.is_valid(), action.errors
    assert chain.is_valid(), chain.errors
    assert action.validated_data["label"] == "Inspect Alpha"
    assert action.validated_data["description"] == "Load current scores"
    assert chain.validated_data["label"] == "Evidence"
