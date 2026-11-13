"""Explicit capabilities available to versioned simulated corporate-action grants."""

from __future__ import annotations

from enum import StrEnum
from typing import cast


class SimulatedCorporateActionWriteCapability(StrEnum):
    """One independently granted simulated corporate-action write operation."""

    CASH_STAGE_WRITE = "simulated_corporate_action_stage_write"
    SHARE_STAGE_WRITE = "simulated.corporate_action_share.stage_write"
    RIGHTS_NOT_EXERCISED = "simulated.corporate_action_rights.not_exercised"
    TAX_ASSESS = "simulated.corporate_action_tax.assess"
    TAX_WITHHOLD = "simulated.corporate_action_tax.withhold"


def validate_simulated_corporate_action_write_capabilities(
    value: object,
) -> tuple[SimulatedCorporateActionWriteCapability, ...]:
    """Require a nonempty, exact-enum tuple in canonical unique value order."""

    if type(value) is not tuple:
        raise TypeError("capabilities must be an exact tuple")
    items = cast(tuple[object, ...], value)
    if not items:
        raise ValueError("capabilities must be nonempty")

    capabilities: list[SimulatedCorporateActionWriteCapability] = []
    for item in items:
        if type(item) is not SimulatedCorporateActionWriteCapability:
            raise TypeError("capabilities must contain exact known enum values")
        capabilities.append(item)

    result = tuple(capabilities)
    if len(set(result)) != len(result):
        raise ValueError("capabilities must be unique")
    if result != tuple(sorted(result, key=lambda capability: capability.value)):
        raise ValueError("capabilities must be in canonical value order")
    return result


__all__ = [
    "SimulatedCorporateActionWriteCapability",
    "validate_simulated_corporate_action_write_capabilities",
]
