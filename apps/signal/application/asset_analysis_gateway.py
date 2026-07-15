"""Signal-owned adapter for Asset Analysis screening context."""

from __future__ import annotations

from typing import Any

from apps.asset_analysis.application.signal_context_gateway import (
    register_signal_context_gateway,
)

from .repository_provider import get_signal_repository


class DjangoSignalContextGateway:
    """Read active signals through the owning Signal repository provider."""

    def list_active_signals(self) -> list[Any]:
        return list(get_signal_repository().get_active_signals())


def register_asset_analysis_signal_gateway() -> None:
    """Register Signal context access with Asset Analysis."""

    register_signal_context_gateway(DjangoSignalContextGateway())


__all__ = ["DjangoSignalContextGateway", "register_asset_analysis_signal_gateway"]
