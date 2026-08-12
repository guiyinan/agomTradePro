"""Using-only composition for the canonical Data Center R3 PIT read adapter."""

from __future__ import annotations

from dataclasses import dataclass

from apps.data_center.macro_factor_research_source_composition import (
    build_django_macro_factor_research_source_runtime,
)
from apps.macro_factor.infrastructure.data_center_pit_projection_adapter import (
    DataCenterMacroFactorPITProjectionAdapter,
)


@dataclass(frozen=True, slots=True)
class MacroFactorR3PITReadRuntime:
    """Narrow read adapter without runner, mutation, current, or decision surfaces."""

    pit_provider: DataCenterMacroFactorPITProjectionAdapter


def build_macro_factor_r3_pit_read_runtime(
    *,
    using: str = "default",
) -> MacroFactorR3PITReadRuntime:
    """Build the production read path from a database alias only."""

    data_center = build_django_macro_factor_research_source_runtime(using=using)
    return MacroFactorR3PITReadRuntime(
        pit_provider=DataCenterMacroFactorPITProjectionAdapter(data_center.projection_provider)
    )


__all__ = ["MacroFactorR3PITReadRuntime", "build_macro_factor_r3_pit_read_runtime"]
