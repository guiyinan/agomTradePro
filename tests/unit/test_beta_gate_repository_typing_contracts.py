"""Regression coverage for typed Beta Gate repository contracts."""

from datetime import date

import pytest

from apps.beta_gate.domain.entities import (
    GateDecision,
    GateStatus,
    RiskProfile,
    VisibilityUniverse,
)
from apps.beta_gate.infrastructure.models import (
    GateDecisionModel,
    VisibilityUniverseSnapshotModel,
)
from apps.beta_gate.infrastructure.repositories import (
    GateDecisionRepository,
    VisibilityUniverseRepository,
)


@pytest.mark.django_db
def test_decision_repository_generates_a_persistable_domain_decision_id() -> None:
    decision = GateDecision(
        status=GateStatus.PASSED,
        asset_code="000001.SH",
        asset_class="equity",
        current_regime="Recovery",
        policy_level=0,
        regime_confidence=0.8,
    )

    saved = GateDecisionRepository().save(decision)

    assert saved.decision_id.startswith("decision_")
    assert GateDecisionModel._default_manager.filter(
        decision_id=saved.decision_id
    ).exists()


@pytest.mark.django_db
def test_universe_repository_saves_the_domain_as_of_date() -> None:
    universe = VisibilityUniverse(
        as_of=date(2026, 7, 23),
        regime_snapshot_id="regime-1",
        policy_snapshot_id="policy-1",
        risk_profile=RiskProfile.BALANCED,
        current_regime="Recovery",
        policy_level=1,
        regime_confidence=0.75,
    )

    snapshot_id = VisibilityUniverseRepository().save(universe)

    saved = VisibilityUniverseSnapshotModel._default_manager.get(
        snapshot_id=snapshot_id
    )
    assert saved.as_of == universe.as_of
