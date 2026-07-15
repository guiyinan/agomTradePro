"""Compatibility exports for decision-rhythm application use cases."""

from decimal import Decimal
from typing import Any

from apps.account.application.repository_provider import get_account_position_repository

from .decision_execution_use_cases import *  # noqa: F403
from .decision_execution_use_cases import __all__ as EXECUTION_ALL
from .decision_model_param_use_cases import *  # noqa: F403
from .decision_model_param_use_cases import __all__ as MODEL_PARAM_ALL
from .decision_quota_use_cases import *  # noqa: F403
from .decision_quota_use_cases import __all__ as QUOTA_ALL
from .decision_recommendation_use_cases import *  # noqa: F403
from .decision_recommendation_use_cases import __all__ as RECOMMENDATION_ALL
from .decision_workspace_use_cases import *  # noqa: F403
from .decision_workspace_use_cases import __all__ as WORKSPACE_ALL


def update_or_create_account_position(
    *,
    portfolio_id: int,
    asset_code: str,
    shares: int | float,
    avg_cost: Decimal,
    current_price: Decimal,
    source: str,
) -> Any:
    """Persist one legacy account position through the owning account repository."""

    position_repo = get_account_position_repository()
    return position_repo.update_or_create_position(
        portfolio_id=portfolio_id,
        asset_code=asset_code,
        shares=shares,
        avg_cost=avg_cost,
        current_price=current_price,
        source=source,
    )


__all__ = [
    "update_or_create_account_position",
    *QUOTA_ALL,
    *EXECUTION_ALL,
    *WORKSPACE_ALL,
    *MODEL_PARAM_ALL,
    *RECOMMENDATION_ALL,
]
