"""Using-only composition for the canonical Data Center R3 PIT read adapter."""

from __future__ import annotations

from dataclasses import dataclass

from apps.macro_factor.infrastructure.data_center_pit_projection_adapter import (
    DataCenterMacroFactorPITProjectionAdapter,
)
from core.integration.r3_owner_evidence import (
    build_r3_pit_projection_provider,
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

    return MacroFactorR3PITReadRuntime(
        pit_provider=DataCenterMacroFactorPITProjectionAdapter(
            build_r3_pit_projection_provider(using=using)
        )
    )


__all__ = ["MacroFactorR3PITReadRuntime", "build_macro_factor_r3_pit_read_runtime"]
