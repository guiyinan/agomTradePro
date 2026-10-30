"""Narrow selection of one configured QMT binding for owner order matching."""

from __future__ import annotations

import pytest

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.infrastructure import owner_order_operation_targets

_BINDING_ID = "10000000-0000-4000-8000-000000000001"


def _binding(
    *,
    binding_id: str = _BINDING_ID,
    assets: object = ["600000.SH"],
    paired: object = True,
    enabled: object = True,
    revoked: object = False,
) -> dict[str, object]:
    """Build one dynamic public-list response without granting source qualification."""

    return {
        "binding_id": binding_id,
        "assets": assets,
        "paired": paired,
        "enabled": enabled,
        "revoked": revoked,
        "freshness": "stale_or_missing",
        "reliability": "unverified",
        "must_not_use_for_decision": True,
        "blocked_reason": "qmt_bridge_requires_publication_validation",
    }


def test_binding_selection_uses_only_unique_owner_asset_state() -> None:
    """Stale list hints do not select or reject an otherwise exact configured binding."""

    selected = owner_order_operation_targets._select_qmt_binding_id(
        [
            _binding(binding_id="20000000-0000-4000-8000-000000000002", assets=["000001.SZ"]),
            _binding(assets=["600000.SH", "600519.SH"]),
        ],
        asset_code="600000.SH",
    )

    assert selected == _BINDING_ID


def test_binding_selection_requires_exactly_one_paired_enabled_nonrevoked_match() -> None:
    """Missing, paused, unpaired, revoked, or ambiguous bindings remain blocked."""

    no_match_sets: tuple[list[dict[str, object]], ...] = (
        [],
        [_binding(paired=False)],
        [_binding(enabled=False)],
        [_binding(revoked=True)],
        [
            _binding(),
            _binding(binding_id="20000000-0000-4000-8000-000000000002"),
        ],
    )

    for bindings in no_match_sets:
        with pytest.raises(SimulatedTradeExecutionBlocked):
            owner_order_operation_targets._select_qmt_binding_id(
                bindings,
                asset_code="600000.SH",
            )


@pytest.mark.parametrize(
    "bindings",
    [
        None,
        {},
        [object()],
        [_binding(binding_id="not-a-uuid")],
        [_binding(assets="600000.SH")],
        [_binding(assets=["600000.SH", 1])],
        [_binding(paired=1)],
        [_binding(enabled=None)],
        [_binding(revoked="false")],
    ],
)
def test_binding_selection_rejects_malformed_dynamic_service_output(
    bindings: object,
) -> None:
    """Malformed fields cannot be narrowed by truthiness or silent filtering."""

    with pytest.raises(SimulatedTradeExecutionBlocked):
        owner_order_operation_targets._select_qmt_binding_id(
            bindings,
            asset_code="600000.SH",
        )
