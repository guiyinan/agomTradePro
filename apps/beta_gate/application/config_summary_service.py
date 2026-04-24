"""Beta-gate summaries used by the system config center."""

from __future__ import annotations

from typing import Any, Protocol


class BetaGateConfigSummaryRepository(Protocol):
    """Read model contract for beta-gate config summaries."""

    def get_beta_gate_summary(self) -> dict[str, Any]:
        """Return beta-gate configuration summary."""

    def get_active_config_context(self) -> dict[str, Any]:
        """Return active beta-gate context for decision workspace."""


class BetaGateConfigSummaryService:
    """Application service for config-center beta-gate summaries."""

    def __init__(self, repository: BetaGateConfigSummaryRepository):
        self.repository = repository

    def get_beta_gate_summary(self, user: Any) -> dict[str, Any]:
        """Return beta-gate configuration summary."""

        return self.repository.get_beta_gate_summary()

    def get_active_config_context(self) -> dict[str, Any]:
        """Return active beta-gate context for decision workspace."""

        return self.repository.get_active_config_context()


_config_summary_repository: BetaGateConfigSummaryRepository | None = None


def configure_beta_gate_config_summary_repository(
    repository: BetaGateConfigSummaryRepository,
) -> None:
    """Register the beta-gate config-summary repository."""

    global _config_summary_repository
    _config_summary_repository = repository


def get_beta_gate_config_summary_service() -> BetaGateConfigSummaryService:
    """Return the configured beta-gate config-summary service."""

    if _config_summary_repository is None:
        raise RuntimeError("Beta-gate config summary repository is not configured")
    return BetaGateConfigSummaryService(_config_summary_repository)
