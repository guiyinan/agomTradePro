"""Database integration coverage for R7-C0 scenario forecast bindings."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.risk_center.infrastructure.models import (
    ScenarioSetMemberModel,
    ScenarioSetModel,
    ScenarioSetRevisionModel,
    StressScenarioDefinitionModel,
    StressScenarioRevisionModel,
)
from apps.signal.forecast_composition import (
    make_finalize_forecast_outcome,
    make_list_scenario_forecast_outcomes,
    make_record_forecast_entry,
)
from apps.signal.infrastructure.forecast_models import ForecastLedgerEntry


def _persist_scenario_binding() -> tuple[
    StressScenarioRevisionModel,
    ScenarioSetRevisionModel,
]:
    definition = StressScenarioDefinitionModel._default_manager.create(
        scenario_key="r7.test.tail-risk",
        name="R7 test tail risk",
        category="test",
    )
    revision = StressScenarioRevisionModel._default_manager.create(
        definition=definition,
        version=1,
        status="approved",
        scenario_type="parametric_shock",
        parameters={
            "shocks": [
                {
                    "target_kind": "asset",
                    "target": "000300.SH",
                    "shock_kind": "return",
                    "magnitude": "-0.10",
                    "unit": "percent",
                    "horizon_days": 30,
                }
            ],
            "correlation_assumption": "independent test shock",
        },
        assumptions=[],
        source_evidence=[],
        source_type="human",
        content_hash="a" * 64,
        created_by="test",
        change_reason="R7-C0 component evidence",
    )
    scenario_set = ScenarioSetModel._default_manager.create(
        set_key="r7.test.research-set",
        name="R7 research set",
        purpose="research",
    )
    set_revision = ScenarioSetRevisionModel._default_manager.create(
        scenario_set=scenario_set,
        version=1,
        status="approved",
        driver_axes=[],
        content_hash="b" * 64,
        created_by="test",
        change_reason="R7-C0 component evidence",
    )
    ScenarioSetMemberModel._default_manager.create(
        scenario_set_revision=set_revision,
        scenario_revision=revision,
        probability=Decimal("0.30"),
        probability_source="subjective",
    )
    return revision, set_revision


def _entry_payload(
    revision: StressScenarioRevisionModel,
    set_revision: ScenarioSetRevisionModel,
) -> dict[str, Any]:
    published_at = datetime(2026, 8, 1, tzinfo=UTC)
    return {
        "entry_id": "r7-component-entry",
        "published_at": published_at,
        "direction": "NEUTRAL",
        "asset_code": "000300.SH",
        "horizon_end": published_at + timedelta(days=30),
        "benchmark_asset": "000300.SH",
        "probability": 0.55,
        "invalidation_rule_version": "rule-v1",
        "decision_snapshot_id": "decision-v1",
        "pit_manifest_id": "manifest-v1",
        "source": "scenario_research",
        "scenario_revision_id": str(revision.revision_id),
        "scenario_set_revision_id": str(set_revision.revision_id),
        "subjective_probability": "0.30",
        "subjective_probability_source_version": str(set_revision.revision_id),
    }


@pytest.mark.django_db
def test_scenario_binding_scores_realization_without_reusing_directional_probability() -> None:
    revision, set_revision = _persist_scenario_binding()
    payload = _entry_payload(revision, set_revision)

    entry = make_record_forecast_entry().execute(**payload)
    outcome = make_finalize_forecast_outcome().execute(
        entry_id=entry.entry_id,
        finalized_at=payload["horizon_end"],
        outcome_type="expired",
        asset_return=None,
        benchmark_return=None,
        neutral_band=0.01,
        scenario_realized=True,
        evidence={"review": "explicit test realization"},
    )
    observations = make_list_scenario_forecast_outcomes().execute(
        scenario_revision_id=str(revision.revision_id),
        scenario_set_revision_id=str(set_revision.revision_id),
    )

    entry.refresh_from_db()
    assert entry.probability == 0.55
    assert entry.subjective_probability == Decimal("0.300000000000")
    assert entry.model_probability is None
    assert outcome.hit is None
    assert outcome.brier_score is None
    assert outcome.scenario_realized is True
    assert outcome.subjective_brier_score == pytest.approx(0.49)
    assert outcome.model_brier_score is None
    assert observations[0].entry_id == entry.entry_id
    assert observations[0].subjective_brier_score == pytest.approx(0.49)


@pytest.mark.django_db
def test_scenario_binding_rejects_revision_outside_requested_set() -> None:
    revision, set_revision = _persist_scenario_binding()
    other_definition = StressScenarioDefinitionModel._default_manager.create(
        scenario_key="r7.test.unbound",
        name="Unbound scenario",
        category="test",
    )
    other_revision = StressScenarioRevisionModel._default_manager.create(
        definition=other_definition,
        version=1,
        status="approved",
        scenario_type="parametric_shock",
        parameters={
            "shocks": [
                {
                    "target_kind": "asset",
                    "target": "000905.SH",
                    "shock_kind": "return",
                    "magnitude": "-0.08",
                    "unit": "percent",
                    "horizon_days": 30,
                }
            ],
            "correlation_assumption": "independent test shock",
        },
        assumptions=[],
        source_evidence=[],
        source_type="human",
        content_hash="c" * 64,
        created_by="test",
        change_reason="Unbound scenario",
    )
    payload = {
        **_entry_payload(revision, set_revision),
        "entry_id": "r7-invalid-membership",
        "scenario_revision_id": str(other_revision.revision_id),
    }

    with pytest.raises(ValueError, match="approved Risk Center reference"):
        make_record_forecast_entry().execute(**payload)

    assert not ForecastLedgerEntry._default_manager.filter(
        entry_id="r7-invalid-membership"
    ).exists()


@pytest.mark.django_db
def test_scenario_realization_requires_binding_and_horizon_completion() -> None:
    published_at = datetime(2026, 8, 1, tzinfo=UTC)
    entry = make_record_forecast_entry().execute(
        entry_id="directional-only-entry",
        published_at=published_at,
        direction="LONG",
        asset_code="000001.SZ",
        horizon_end=published_at + timedelta(days=30),
        benchmark_asset="000300.SH",
        probability=0.55,
        invalidation_rule_version="rule-v1",
        decision_snapshot_id="decision-v1",
        pit_manifest_id="manifest-v1",
        source="strategy",
    )

    with pytest.raises(ValueError, match="requires a scenario revision"):
        make_finalize_forecast_outcome().execute(
            entry_id=entry.entry_id,
            finalized_at=published_at + timedelta(days=30),
            outcome_type="expired",
            asset_return=None,
            benchmark_return=None,
            neutral_band=0.01,
            scenario_realized=False,
        )

    revision, set_revision = _persist_scenario_binding()
    bound_payload = {
        **_entry_payload(revision, set_revision),
        "entry_id": "bound-before-horizon",
    }
    bound_entry = make_record_forecast_entry().execute(**bound_payload)
    with pytest.raises(ValueError, match="before horizon_end"):
        make_finalize_forecast_outcome().execute(
            entry_id=bound_entry.entry_id,
            finalized_at=published_at + timedelta(days=29),
            outcome_type="expired",
            asset_return=None,
            benchmark_return=None,
            neutral_band=0.01,
            scenario_realized=False,
        )
