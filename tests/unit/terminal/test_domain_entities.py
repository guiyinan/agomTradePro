"""Terminal domain entity serialization regression tests."""

from apps.terminal.domain.entities import (
    CommandParameter,
    CommandType,
    ParameterType,
    TerminalCommand,
)


def test_parameter_serialization_does_not_expose_options_list() -> None:
    parameter = CommandParameter(
        name="mode",
        param_type=ParameterType.SELECT,
        options=["safe", "fast"],
    )

    payload = parameter.to_dict()
    payload["options"].append("unsafe")

    assert parameter.options == ["safe", "fast"]


def test_command_serialization_does_not_expose_tags_list() -> None:
    command = TerminalCommand(
        id="command-1",
        name="status",
        description="Show status",
        command_type=CommandType.API,
        tags=["readiness"],
    )

    payload = command.to_dict()
    payload["tags"].append("mutated")

    assert command.tags == ["readiness"]


def test_command_round_trip_preserves_parameter_and_governance_fields() -> None:
    command = TerminalCommand.from_dict(
        {
            "id": "command-1",
            "name": "status",
            "description": "Show status",
            "type": "api",
            "parameters": [
                {
                    "name": "scope",
                    "type": "select",
                    "options": ["all", "database"],
                }
            ],
            "risk_level": "read",
            "requires_mcp": False,
            "tags": ["readiness"],
        }
    )

    payload = command.to_dict()

    assert payload["type"] == "api"
    assert payload["risk_level"] == "read"
    assert payload["requires_mcp"] is False
    assert payload["parameters"][0]["options"] == ["all", "database"]
