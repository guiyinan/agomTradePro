"""Register Dashboard Alpha homepage access for Data Center."""

from __future__ import annotations

from typing import Any

from apps.data_center.application.business_runtime_gateway import (
    register_alpha_homepage_loader,
)

from . import alpha_homepage


def _load_alpha_homepage(
    *,
    user: Any,
    top_n: int,
    portfolio_id: int,
    pool_mode: str,
) -> Any:
    return alpha_homepage.AlphaHomepageQuery().execute(
        user=user,
        top_n=top_n,
        portfolio_id=portfolio_id,
        pool_mode=pool_mode,
    )


def register_dashboard_data_center_runtime() -> None:
    """Replace only the homepage provider in the shared Alpha runtime gateway."""

    register_alpha_homepage_loader(_load_alpha_homepage)


__all__ = ["register_dashboard_data_center_runtime"]
