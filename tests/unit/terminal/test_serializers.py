"""Terminal serializer contract regressions."""

from apps.terminal.interface.serializers import (
    TerminalChatRequestSerializer,
    TerminalCommandSerializer,
)


def test_terminal_command_param_count_is_computed_from_parameters() -> None:
    serializer = TerminalCommandSerializer(
        {
            "id": "cmd-1",
            "name": "inspect",
            "description": "",
            "type": "api",
            "command_type": "api",
            "parameters": [{"name": "code"}, {"name": "date"}],
            "timeout": 30,
            "risk_level": "read",
            "requires_mcp": False,
            "enabled_in_terminal": True,
            "category": "analysis",
            "is_active": True,
        }
    )

    assert serializer.data["param_count"] == 2


def test_terminal_chat_message_has_bounded_length() -> None:
    serializer = TerminalChatRequestSerializer(data={"message": "x" * 20_001})

    assert serializer.is_valid() is False
    assert "message" in serializer.errors
