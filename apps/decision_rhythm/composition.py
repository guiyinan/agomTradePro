"""Composition root for decision snapshot dependencies."""

from apps.decision_rhythm.application.input_snapshot_use_cases import (
    BuildDecisionInputSnapshotUseCase,
    GetDecisionInputSnapshotUseCase,
)
from apps.decision_rhythm.infrastructure.input_snapshot_repository import (
    DecisionInputSnapshotRepository,
)


def make_build_decision_input_snapshot_use_case() -> BuildDecisionInputSnapshotUseCase:
    """Compose the snapshot writer."""

    return BuildDecisionInputSnapshotUseCase(DecisionInputSnapshotRepository())


def make_get_decision_input_snapshot_use_case() -> GetDecisionInputSnapshotUseCase:
    """Compose the snapshot reader."""

    return GetDecisionInputSnapshotUseCase(DecisionInputSnapshotRepository())

