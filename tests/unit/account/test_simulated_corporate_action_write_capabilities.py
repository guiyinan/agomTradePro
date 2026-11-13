"""Strict capability-set contract for versioned Account write grants."""

from __future__ import annotations

import pytest

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
    validate_simulated_corporate_action_write_capabilities,
)


def test_capability_set_requires_sorted_unique_explicit_enum_values() -> None:
    values = (
        SimulatedCorporateActionWriteCapability.TAX_ASSESS,
        SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,
        SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE,
    )

    assert validate_simulated_corporate_action_write_capabilities(values) == values


def test_new_share_and_rights_capabilities_are_explicit_known_values() -> None:
    values = tuple(
        sorted(
            (
                SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE,
                SimulatedCorporateActionWriteCapability.RIGHTS_NOT_EXERCISED,
            ),
            key=lambda capability: capability.value,
        )
    )

    assert tuple(item.value for item in values) == (
        "simulated.corporate_action_rights.not_exercised",
        "simulated.corporate_action_share.stage_write",
    )
    assert validate_simulated_corporate_action_write_capabilities(values) == values


@pytest.mark.parametrize(
    "values",
    (
        (),
        [],
        ("simulated.corporate_action_tax.assess",),
        (SimulatedCorporateActionWriteCapability.TAX_ASSESS, "unknown.permission"),
        (
            SimulatedCorporateActionWriteCapability.TAX_ASSESS,
            SimulatedCorporateActionWriteCapability.TAX_ASSESS,
        ),
        (
            SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,
            SimulatedCorporateActionWriteCapability.TAX_ASSESS,
        ),
    ),
)
def test_capability_set_rejects_empty_untyped_unknown_duplicate_or_unsorted_values(
    values: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        validate_simulated_corporate_action_write_capabilities(values)
