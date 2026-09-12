"""Terminal domain entity serialization regression tests."""

from apps.terminal.domain.entities import (
    CommandParameter,
    CommandType,
    ParameterType,
    TerminalCommand,
    TerminalRiskLevel,
)
from apps.terminal.domain.services import TerminalPermissionService


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


def test_parameter_string_type_is_coerced_to_enum() -> None:
    parameter = CommandParameter(name="limit", param_type="number")

    assert parameter.param_type is ParameterType.NUMBER


def test_command_properties_and_parameter_helpers_cover_required_and_default_paths() -> None:
    required = CommandParameter(name="symbol", param_type=ParameterType.TEXT)
    optional = CommandParameter(
        name="limit",
        param_type=ParameterType.NUMBER,
        required=False,
        default=20,
    )
    prompt = TerminalCommand(
        id="prompt-1",
        name="summarize",
        description="Summarize an asset",
        command_type="prompt",
        parameters=[required, optional],
    )
    api = TerminalCommand(
        id="api-1",
        name="status",
        description="Read status",
        command_type=CommandType.API,
        risk_level="write_low",
    )

    assert prompt.is_prompt_type is True
    assert prompt.is_api_type is False
    assert api.is_api_type is True
    assert prompt.get_missing_params({}) == [required]
    assert prompt.get_missing_params({"symbol": "000001.SZ"}) == []
    assert prompt.get_param_defaults() == {"limit": 20}
    assert api.risk_level is TerminalRiskLevel.WRITE_LOW


def test_unknown_role_falls_back_to_read_risk() -> None:
    assert TerminalPermissionService.get_max_risk_level("unknown") is TerminalRiskLevel.READ
