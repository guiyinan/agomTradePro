"""Terminal-owned adapter for AI Capability catalog and execution integration."""

from __future__ import annotations

from typing import Any

from apps.ai_capability.application.terminal_gateway import (
    register_terminal_capability_gateway,
)

from .repository_provider import (
    get_terminal_audit_repository,
    get_terminal_command_repository,
    get_terminal_runtime_settings_repository,
)
from .services import CommandExecutionService
from .use_cases import ExecuteCommandRequest, ExecuteCommandUseCase


class DjangoTerminalCapabilityGateway:
    """Adapt Terminal repositories and use cases to neutral capability payloads."""

    def get_runtime_settings(self) -> dict[str, Any]:
        return get_terminal_runtime_settings_repository().get_settings()

    def list_active_commands(self) -> list[dict[str, Any]]:
        return [
            {
                "id": str(command.id),
                "pk": str(command.id),
                "name": command.name,
                "description": command.description,
                "category": command.category,
                "tags": list(command.tags or []),
                "risk_level": command.risk_level,
                "requires_mcp": command.requires_mcp,
                "enabled_in_terminal": command.enabled_in_terminal,
            }
            for command in get_terminal_command_repository().get_all_active()
        ]

    def execute_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        use_case = ExecuteCommandUseCase(
            repository=get_terminal_command_repository(),
            execution_service=CommandExecutionService(),
            audit_repository=get_terminal_audit_repository(),
        )
        response = use_case.execute(ExecuteCommandRequest(**payload))
        return {
            "success": response.success,
            "output": response.output,
            "metadata": response.metadata,
            "error": response.error,
            "confirmation_required": response.confirmation_required,
            "confirmation_prompt": response.confirmation_prompt,
        }


def register_ai_capability_terminal_gateway() -> None:
    """Register the default Terminal adapter with AI Capability."""

    register_terminal_capability_gateway(DjangoTerminalCapabilityGateway())


__all__ = ["DjangoTerminalCapabilityGateway", "register_ai_capability_terminal_gateway"]
