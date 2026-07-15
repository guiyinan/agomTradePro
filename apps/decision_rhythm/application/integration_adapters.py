"""Register Decision Rhythm implementations behind consumer-owned gateways."""

from __future__ import annotations

from typing import Any


def _refresh_default_workspace_recommendations() -> Any:
    from . import workspace_services
    from .dtos import RefreshRecommendationsRequestDTO

    return workspace_services.refresh_workspace_recommendations(
        RefreshRecommendationsRequestDTO(
            account_id="default",
            security_codes=None,
            force=True,
            async_mode=False,
        )
    )


def _get_decision_execution_ref(request_id: str) -> dict[str, Any] | None:
    from .repository_provider import get_decision_request_repository

    decision_request = get_decision_request_repository().get_by_id(request_id)
    return getattr(decision_request, "execution_ref", None)


def register_decision_rhythm_integrations() -> None:
    """Register Decision Rhythm adapters with all current consumers."""

    from apps.alpha.application.workspace_refresh_gateway import (
        register_default_workspace_refresh_provider,
    )
    from apps.alpha_trigger.application.decision_execution_gateway import (
        register_decision_execution_ref_provider,
    )
    from apps.simulated_trading.application.decision_rhythm_exit_gateway import (
        register_decision_rhythm_exit_advisor_builder,
    )
    from core.integration.decision_request_registry import (
        register_decision_request_repository_factory,
    )

    from .exit_advisors import build_decision_rhythm_exit_advisor
    from .repository_provider import get_decision_request_repository

    register_default_workspace_refresh_provider(_refresh_default_workspace_recommendations)
    register_decision_execution_ref_provider(_get_decision_execution_ref)
    register_decision_rhythm_exit_advisor_builder(build_decision_rhythm_exit_advisor)
    register_decision_request_repository_factory(get_decision_request_repository)


__all__ = ["register_decision_rhythm_integrations"]
