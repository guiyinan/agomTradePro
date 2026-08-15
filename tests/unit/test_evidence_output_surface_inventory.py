"""Tests for the first-batch decision-facing output inventory."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from scripts.check_evidence_output_surfaces import (
    DEFAULT_INVENTORY,
    load_inventory,
    parse_inventory,
    validate_inventory,
)


def test_repository_evidence_output_inventory_is_exact() -> None:
    assert validate_inventory(load_inventory()) == {
        "surface_count": 66,
        "direct_position_surface_count": 15,
        "marked_surface_count": 53,
        "dynamic_surface_count": 18,
    }


def test_account_sizing_output_is_direct_but_hard_blocked_until_evidence_binding() -> None:
    inventory = load_inventory()
    sizing = next(
        surface
        for surface in inventory.surfaces
        if surface.source_symbol.endswith("::SizingContextOutput")
    )

    assert sizing.owner_app == "account"
    assert sizing.position_impact == "direct"
    assert sizing.current_gate_state == "not_evidence_integrated_hard_blocked"
    assert sizing.required_fields == {
        "as_of_date",
        "multiplier_result",
        "portfolio_id",
        "warnings",
    }


def test_real_portfolio_transition_surfaces_are_frozen_before_evidence_integration() -> None:
    inventory = load_inventory()
    portfolio = {
        surface.source_symbol.rsplit("::", 1)[-1]: surface
        for surface in inventory.surfaces
        if surface.source_symbol.startswith("apps/portfolio/domain/entities.py::")
    }

    assert set(portfolio) == {"OrderDraft", "TransitionPlan"}
    assert all(
        surface.position_impact == "direct"
        and surface.current_gate_state == "not_evidence_integrated_legacy_ungated"
        for surface in portfolio.values()
    )
    assert portfolio["TransitionPlan"].composite_fields == {
        "constraints",
        "metadata",
        "orders",
    }


def test_advisor_order_intent_records_hard_blocked_execution_consumer() -> None:
    inventory = load_inventory()
    advisor = next(
        surface
        for surface in inventory.surfaces
        if surface.source_symbol.endswith("::AdvisorOrderIntent")
    )

    assert advisor.position_impact == "direct"
    assert advisor.current_gate_state == "not_evidence_integrated_hard_blocked"


def test_parser_rejects_unclassified_claim_kind() -> None:
    payload = json.loads(DEFAULT_INVENTORY.read_text(encoding="utf-8"))
    payload["surfaces"][0]["claim_kind"] = "unclassified"

    with pytest.raises(ValueError, match="unclassified evidence output surface"):
        parse_inventory(payload)


def test_parser_rejects_missing_required_classification_field() -> None:
    payload = json.loads(DEFAULT_INVENTORY.read_text(encoding="utf-8"))
    del payload["surfaces"][0]["method_kind"]

    with pytest.raises(ValueError, match="method_kind must be non-empty text"):
        parse_inventory(payload)


def test_parser_rejects_composite_field_outside_required_contract() -> None:
    payload = json.loads(DEFAULT_INVENTORY.read_text(encoding="utf-8"))
    bundle = next(
        surface
        for surface in payload["surfaces"]
        if surface["source_symbol"].endswith("::GovernedOptimizationRunBundle")
    )
    bundle["composite_fields"] = ["missing_component"]

    with pytest.raises(ValueError, match="composite_fields must be required fields"):
        parse_inventory(payload)


def test_quote_surface_records_legacy_display_only_adapter() -> None:
    inventory = load_inventory()
    quote = next(
        surface
        for surface in inventory.surfaces
        if surface.source_symbol.endswith("::QuoteResponse")
    )

    assert quote.current_gate_state == "legacy_evidence_wrapped_display_only"


def test_guard_rejects_unregistered_marked_surface() -> None:
    inventory = load_inventory()
    retained = tuple(
        surface
        for surface in inventory.surfaces
        if not surface.source_symbol.endswith("::ScenarioProbabilityResearchPacket")
    )

    with pytest.raises(ValueError, match="unclassified marked evidence output surfaces"):
        validate_inventory(replace(inventory, surfaces=retained))


def test_guard_rejects_registered_contract_field_drift() -> None:
    inventory = load_inventory()
    first = inventory.surfaces[0]
    changed = replace(first, required_fields=first.required_fields | {"missing_gate_field"})

    with pytest.raises(ValueError, match="changed evidence output contract"):
        validate_inventory(replace(inventory, surfaces=(changed, *inventory.surfaces[1:])))


def test_guard_rejects_unregistered_dynamic_surface() -> None:
    inventory = load_inventory()
    missing = next(iter(inventory.dynamic_surfaces))

    with pytest.raises(ValueError, match="unclassified dynamic evidence output surfaces"):
        validate_inventory(
            replace(inventory, dynamic_surfaces=inventory.dynamic_surfaces - {missing})
        )


def test_guard_rejects_stale_dynamic_surface() -> None:
    inventory = load_inventory()

    with pytest.raises(ValueError, match="stale dynamic evidence output surfaces"):
        validate_inventory(
            replace(
                inventory,
                dynamic_surfaces=inventory.dynamic_surfaces
                | {"apps/broker_execution/application/query_services.py::Missing.output"},
            )
        )


def test_r1_r6_research_outputs_remain_non_evidence_integrated() -> None:
    inventory = load_inventory()
    audited_fragments = (
        "ForecastBaselineEvaluationPreflightResult",
        "ForecastBaselineTrialResult",
        "R2ResearchControlPreflightResult",
        "R3GovernedReadAssessment",
        "MacroFactorResearchAssessment",
        "R4ResearchControlPreflightResult",
        "R5ResearchControlPreflightResult",
        "FixedIncomeResearchPreview",
        "FixedIncomePortfolioRiskAssessment",
        "R5RelativeValueAssessment",
        "R6ManualActivationPreflightResult",
        "R6ActiveStateModelProjection",
        "StateModelQualificationAssessment",
    )

    audited = tuple(
        surface
        for surface in inventory.surfaces
        if any(fragment in surface.source_symbol for fragment in audited_fragments)
    )

    assert len(audited) == len(audited_fragments)
    assert all(
        surface.current_gate_state == "not_evidence_integrated_research_only"
        and surface.position_impact == "indirect"
        for surface in audited
    )


def test_r7_r8_denominator_freeze_does_not_claim_evidence_integration() -> None:
    inventory = load_inventory()
    research_only_symbols = {
        "apps/portfolio/application/constrained_optimization.py::OptimizationResearchReport",
        "apps/portfolio/application/governed_optimization.py::GovernedOptimizationAssembly",
        "apps/portfolio/application/governed_optimization.py::GovernedOptimizationRunBundle",
        "apps/research/application/scenario_probability_research.py::ScenarioProbabilityResearchPacket",
        "apps/research/domain/r7_post_promotion_monitoring.py::R7PostPromotionMonitoringAssessment",
        "apps/research/domain/r7_research_result_persistence.py::PersistedR7ResearchResult",
        "apps/research/domain/r7_result_family_lifecycle.py::R7FamilyLifecycleSnapshot",
    }
    governed_input_symbols = {
        "apps/portfolio/domain/canonical_snapshots.py::CanonicalPortfolioSnapshot",
        "apps/portfolio/domain/canonical_snapshots.py::PortfolioExecutionFeedback",
    }
    surfaces = {surface.source_symbol: surface for surface in inventory.surfaces}

    assert research_only_symbols <= surfaces.keys()
    assert governed_input_symbols <= surfaces.keys()
    assert all(
        surfaces[symbol].current_gate_state == "not_evidence_integrated_research_only"
        and surfaces[symbol].position_impact == "indirect"
        for symbol in research_only_symbols
    )
    assert all(
        surfaces[symbol].current_gate_state == "not_evidence_integrated_governed_input"
        and surfaces[symbol].position_impact == "indirect"
        for symbol in governed_input_symbols
    )
    bundle = surfaces[
        "apps/portfolio/application/governed_optimization.py::GovernedOptimizationRunBundle"
    ]
    assert bundle.composite_fields == frozenset({"lifecycle_root", "result"})
