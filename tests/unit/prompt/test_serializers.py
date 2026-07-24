"""Prompt interface serializer contract tests."""

from apps.prompt.interface.serializers import (
    ChatRequestSerializer,
    ChatSessionSerializer,
    PlaceholderSerializer,
)


def test_placeholder_required_remains_an_external_boolean_field() -> None:
    """Keep the public field while avoiding DRF's internal ``required`` attribute."""

    serializer = PlaceholderSerializer(data={"name": "asset", "type": "simple"})

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["required"] is True
    assert "required" in serializer.fields


def test_chat_request_context_remains_writable() -> None:
    """Accept structured chat context under the established API field name."""

    context = {"history": [{"role": "user", "content": "prior question"}]}
    serializer = ChatRequestSerializer(data={"message": "hello", "context": context})

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["context"] == context


def test_chat_session_context_remains_read_only_output() -> None:
    """Serialize persisted context without replacing DRF serializer state."""

    serializer = ChatSessionSerializer(
        {
            "id": 1,
            "session_id": "session-1",
            "user_message": "hello",
            "ai_response": "world",
            "context": {"source": "test"},
            "created_at": "2026-07-23T00:00:00Z",
        }
    )

    assert serializer.data["context"] == {"source": "test"}
