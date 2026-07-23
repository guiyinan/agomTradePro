"""Account interface serializer contract tests."""

from apps.account.interface.serializers import (
    MCPTokenAccessLevelChoiceSerializer,
    ObserverGrantSerializer,
    PositionSerializer,
)


def test_account_public_fields_do_not_override_drf_state() -> None:
    """Keep source, validity and label fields in their established payloads."""

    position = PositionSerializer({"source": "manual"})
    token_choice = MCPTokenAccessLevelChoiceSerializer({"value": "read_only", "label": "Read only"})
    observer = ObserverGrantSerializer()

    assert position.data["source"] == "manual"
    assert token_choice.data == {"value": "read_only", "label": "Read only"}
    assert "is_valid" in observer.fields
