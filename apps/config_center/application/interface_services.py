"""Internal application facade for Config Center-owned Alpha universes."""

from __future__ import annotations

from apps.config_center.application.repository_provider import (
    get_alpha_universe_config_repository,
)
from apps.config_center.domain.entities import AlphaUniverseConfig


def get_alpha_universe_config(universe_id: str) -> AlphaUniverseConfig | None:
    """Return one active Alpha universe definition."""

    return get_alpha_universe_config_repository().get_domain_by_universe_id(universe_id)


def resolve_alpha_universe_member_codes(universe_id: str) -> list[str]:
    """Resolve member codes for non-index Alpha universe definitions."""

    return get_alpha_universe_config_repository().resolve_member_codes(universe_id)
