"""Tests for the governed decision-write surface freeze."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from scripts.check_decision_write_surface_freeze import (
    load_inventory,
    validate_surface_freeze,
)

M1_OWNER_RISK_POLICY_HTTP_SURFACES = frozenset(
    {
        "apps/simulated_trading/interface/m1_risk_policy_views.py::OwnerM1RiskPolicyRevisionAPIView.post",
        "apps/simulated_trading/interface/m1_risk_policy_views.py::OwnerM1RiskPolicyRevocationAPIView.post",
    }
)


def test_repository_decision_write_surface_inventory_is_exact() -> None:
    assert validate_surface_freeze(load_inventory()) == {
        "transition_plan_internal_writer_count": 10,
        "http_surface_count": 63,
        "sdk_surface_count": 18,
        "tui_decision_action_count": 25,
        "tui_mutation_action_count": 23,
        "mcp_position_write_count": 32,
    }


def test_owner_m1_risk_policy_writes_are_classified_and_required() -> None:
    inventory = load_inventory()
    assert M1_OWNER_RISK_POLICY_HTTP_SURFACES <= inventory.http_surfaces

    for surface in M1_OWNER_RISK_POLICY_HTTP_SURFACES:
        with pytest.raises(ValueError, match="unclassified HTTP mutation surfaces"):
            validate_surface_freeze(
                replace(inventory, http_surfaces=inventory.http_surfaces - {surface})
            )


@pytest.mark.parametrize("view_name", ["OwnerOrderCancelAPIView", "OwnerOrderDecisionApplyAPIView"])
def test_owner_order_writes_require_exact_http_classification(view_name: str) -> None:
    """Removing either retained-order write must close the existing freeze gate."""
    inventory = load_inventory()
    surface = (
        "apps/simulated_trading/interface/owner_order_operation_views.py::" f"{view_name}.post"
    )
    assert surface in inventory.http_surfaces
    with pytest.raises(ValueError, match="unclassified HTTP mutation surfaces"):
        validate_surface_freeze(
            replace(inventory, http_surfaces=inventory.http_surfaces - {surface})
        )


def test_guard_rejects_new_unclassified_http_surface() -> None:
    inventory = load_inventory()
    missing = next(iter(inventory.http_surfaces))

    with pytest.raises(ValueError, match="unclassified HTTP mutation surfaces"):
        validate_surface_freeze(
            replace(inventory, http_surfaces=inventory.http_surfaces - {missing})
        )


def test_fee_preview_material_write_requires_classification() -> None:
    """A financial readout still writes material and must remain a governed mutation."""

    inventory = load_inventory()
    surface = (
        "apps/simulated_trading/interface/fee_correction_views.py::FeeCorrectionPreviewAPIView.post"
    )
    assert surface in inventory.http_surfaces
    with pytest.raises(ValueError, match="unclassified HTTP mutation surfaces"):
        validate_surface_freeze(
            replace(inventory, http_surfaces=inventory.http_surfaces - {surface})
        )


def test_guard_rejects_stale_sdk_surface() -> None:
    inventory = load_inventory()

    with pytest.raises(ValueError, match="stale SDK mutation surfaces"):
        validate_surface_freeze(
            replace(
                inventory,
                sdk_mutation_surfaces=inventory.sdk_mutation_surfaces
                | {"sdk/agomtradepro/modules/missing.py::Missing.write"},
            )
        )


def test_transition_plan_internal_writers_are_classified_and_exact() -> None:
    inventory = load_inventory()

    assert [
        writer.source_symbol for writer in inventory.transition_plan_internal_writers
    ] == sorted(writer.source_symbol for writer in inventory.transition_plan_internal_writers)
    assert (
        sum(
            writer.ownership == "decision_rhythm_legacy"
            for writer in inventory.transition_plan_internal_writers
        )
        == 6
    )
    assert (
        sum(
            writer.ownership == "portfolio_canonical"
            for writer in inventory.transition_plan_internal_writers
        )
        == 4
    )
    assert all(writer.enabled_by_default for writer in inventory.transition_plan_internal_writers)
    assert all(
        writer.replacement is not None
        for writer in inventory.transition_plan_internal_writers
        if writer.ownership == "decision_rhythm_legacy"
    )
    assert all(
        writer.replacement is None
        for writer in inventory.transition_plan_internal_writers
        if writer.ownership == "portfolio_canonical"
    )


def test_legacy_transition_plan_writers_share_canonical_mode_guard() -> None:
    inventory = load_inventory()
    legacy_writers = [
        writer
        for writer in inventory.transition_plan_internal_writers
        if writer.ownership == "decision_rhythm_legacy"
    ]

    assert len(legacy_writers) == 6
    assert all(
        "_ensure_legacy_transition_plan_write_enabled" in writer.required_ast_calls
        for writer in legacy_writers
    )


def test_guard_rejects_unregistered_transition_plan_internal_writer() -> None:
    inventory = load_inventory()

    with pytest.raises(ValueError, match="unregistered transition plan internal writers"):
        validate_surface_freeze(
            replace(
                inventory,
                transition_plan_internal_writers=inventory.transition_plan_internal_writers[1:],
            )
        )


def test_guard_rejects_transition_plan_internal_writer_ast_drift() -> None:
    inventory = load_inventory()
    first = inventory.transition_plan_internal_writers[0]

    with pytest.raises(ValueError, match="internal writer AST calls changed"):
        validate_surface_freeze(
            replace(
                inventory,
                transition_plan_internal_writers=(
                    replace(first, required_ast_calls=first.required_ast_calls | {"missing.call"}),
                    *inventory.transition_plan_internal_writers[1:],
                ),
            )
        )


def test_guard_rejects_lost_conditional_transition_plan_approval_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import check_decision_write_surface_freeze as guard

    monkeypatch.setattr(guard, "_guarded_transition_plan_update", lambda _function: False)
    with pytest.raises(ValueError, match="lost its conditional canonical-mode guard"):
        guard.validate_surface_freeze(guard.load_inventory())


def test_single_attempt_sdk_writes_cannot_escape_classification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Transport retry policy must not hide a financial mutation from the guard."""
    from scripts import check_decision_write_surface_freeze as guard

    (tmp_path / "module.py").write_text(
        "class FeeModule:\n"
        "    def upload(self):\n        return self._client.post_once('/evidence/')\n"
        "    def policy(self):\n        return self._client.put_once('/policy/')\n"
        "    def head(self):\n        return self._client.get('/head/')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    assert guard.discover_sdk_surfaces(("module.py",)) == {
        "module.py::FeeModule.upload",
        "module.py::FeeModule.policy",
    }
