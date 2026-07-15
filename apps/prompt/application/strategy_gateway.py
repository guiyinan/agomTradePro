"""Prompt-owned registration point for optional Strategy context providers."""

from __future__ import annotations

from typing import Any, Protocol


class PromptStrategyGateway(Protocol):
    def build_context_providers(self) -> tuple[Any | None, Any | None, Any | None]: ...


class EmptyPromptStrategyGateway:
    def build_context_providers(self) -> tuple[None, None, None]:
        return None, None, None


_gateway: PromptStrategyGateway = EmptyPromptStrategyGateway()


def register_prompt_strategy_gateway(gateway: PromptStrategyGateway) -> None:
    global _gateway
    _gateway = gateway


def build_prompt_strategy_providers() -> tuple[Any | None, Any | None, Any | None]:
    return _gateway.build_context_providers()


__all__ = ["build_prompt_strategy_providers", "register_prompt_strategy_gateway"]
