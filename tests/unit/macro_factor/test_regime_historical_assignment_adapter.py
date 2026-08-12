"""Narrow R3 read adapter over Regime-owned historical assignments."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from apps.macro_factor.domain.governed_read import (
    R3RegimeObservationEvidence,
    build_regime_segment_report,
)
from apps.macro_factor.infrastructure.regime_historical_assignment_adapter import (
    RegimeHistoricalAssignmentReportAdapter,
)
from apps.macro_factor.r3_regime_assignment_composition import (
    build_macro_factor_r3_regime_assignment_read_runtime,
)
from apps.regime.domain.historical_assignment import (
    CanonicalRegimeSourceFact,
    HistoricalRegimeAssignment,
    HistoricalRegimeAssignmentReceipt,
    RegimeAssignmentFactRole,
)
from apps.regime.infrastructure.historical_assignment_repository import (
    DjangoHistoricalRegimeAssignmentReadRepository,
)
from tests.unit.macro_factor.test_governed_read import _case


class _AssignmentReader:
    unit_of_work_key = "django:default"

    def __init__(self, receipt: HistoricalRegimeAssignmentReceipt) -> None:
        self.receipt = receipt
        self.calls: list[tuple[str, str, datetime]] = []

    def get_exact_receipt(
        self,
        *,
        artifact_id: str,
        expected_artifact_hash: str,
        as_of: datetime,
    ) -> HistoricalRegimeAssignmentReceipt:
        self.calls.append((artifact_id, expected_artifact_hash, as_of))
        return self.receipt


class _ArtifactReader:
    unit_of_work_key = "django:default"

    def __init__(self, artifact: object) -> None:
        self.artifact = artifact
        self.calls: list[str] = []

    def get_artifact(self, artifact_id: str) -> object:
        self.calls.append(artifact_id)
        return self.artifact


def _receipt() -> HistoricalRegimeAssignmentReceipt:
    case = _case()
    artifact = case.ledger.artifact
    assignments: list[HistoricalRegimeAssignment] = []
    for index, observation in enumerate(case.report.observations, start=1):
        actual = CanonicalRegimeSourceFact(
            role=RegimeAssignmentFactRole.ACTUAL,
            dataset_key="macro-growth-actual",
            business_key=f"{observation.row_id}:actual",
            fact_id=observation.actual_fact_id,
            fact_version="fact.v1",
            content_hash=str(index) * 64,
            pit_manifest_id=artifact.pit_manifest_id,
            pit_manifest_hash=artifact.pit_manifest_hash,
            effective_at=observation.observation_at,
            available_at=observation.actual_available_at,
            owner_recorded_at=observation.actual_available_at,
            value=observation.actual_value,
            unit="index",
            verified=True,
        )
        growth = CanonicalRegimeSourceFact(
            role=RegimeAssignmentFactRole.GROWTH,
            dataset_key="macro-growth-input",
            business_key=f"{observation.row_id}:growth",
            fact_id=f"growth:{observation.row_id}",
            fact_version="fact.v1",
            content_hash="a" * 64,
            pit_manifest_id=artifact.pit_manifest_id,
            pit_manifest_hash=artifact.pit_manifest_hash,
            effective_at=observation.regime_effective_at,
            available_at=observation.regime_available_at,
            owner_recorded_at=observation.regime_available_at,
            value=Decimal("1"),
            unit="index",
            verified=True,
        )
        inflation = CanonicalRegimeSourceFact(
            role=RegimeAssignmentFactRole.INFLATION,
            dataset_key="macro-inflation-input",
            business_key=f"{observation.row_id}:inflation",
            fact_id=f"inflation:{observation.row_id}",
            fact_version="fact.v1",
            content_hash="b" * 64,
            pit_manifest_id=artifact.pit_manifest_id,
            pit_manifest_hash=artifact.pit_manifest_hash,
            effective_at=observation.regime_effective_at,
            available_at=observation.regime_available_at,
            owner_recorded_at=observation.regime_available_at,
            value=Decimal("-1"),
            unit="index",
            verified=True,
        )
        assignments.append(
            HistoricalRegimeAssignment(
                fold_id=observation.fold_id,
                row_id=observation.row_id,
                observation_at=observation.observation_at,
                predicted_value=observation.predicted_value,
                actual_value=observation.actual_value,
                actual_fact=actual,
                growth_fact=growth,
                inflation_fact=inflation,
                regime_code=observation.regime_code,
                regime_version=observation.regime_version,
                regime_content_hash=observation.regime_content_hash,
            )
        )
    return HistoricalRegimeAssignmentReceipt(
        receipt_id="c" * 64,
        receipt_version="receipt.v1",
        definition_id="regime-definition:r3",
        definition_version="definition.v1",
        definition_content_hash="d" * 64,
        artifact_id=artifact.artifact_id,
        artifact_hash=artifact.content_hash,
        source_result_hash=artifact.source_result_hash,
        pit_manifest_id=artifact.pit_manifest_id,
        pit_manifest_hash=artifact.pit_manifest_hash,
        pit_as_of=case.report.evaluated_at,
        recorded_at=case.report.evaluated_at,
        assignments=tuple(assignments),
    )


def test_public_read_runtime_can_directly_compose_without_recursive_write_capability() -> None:
    runtime = build_macro_factor_r3_regime_assignment_read_runtime()

    assert isinstance(
        runtime.report_provider._assignment_reader,
        DjangoHistoricalRegimeAssignmentReadRepository,
    )
    for value in _walk_object_graph(runtime):
        assert not any(
            hasattr(value, capability)
            for capability in (
                "append_definition",
                "append_receipt",
                "append_bundle",
                "append_lifecycle_event",
                "atomic",
            )
        )
        assert all(
            "token" not in name.lower() and "writer" not in name.lower()
            for name in _stored_attribute_names(value)
        )


def test_exact_receipt_projection_recalculates_the_complete_regime_report() -> None:
    case = _case()
    receipt = _receipt()
    assignment_reader = _AssignmentReader(receipt)
    artifact_reader = _ArtifactReader(case.ledger.artifact)
    adapter = RegimeHistoricalAssignmentReportAdapter(
        assignment_reader=assignment_reader,
        ledger=artifact_reader,
    )

    report = adapter.get_report(
        artifact_id=receipt.artifact_id,
        expected_artifact_hash=receipt.artifact_hash,
        as_of=receipt.recorded_at,
    )

    observations = tuple(
        R3RegimeObservationEvidence(
            owner="regime",
            artifact_id=receipt.artifact_id,
            artifact_hash=receipt.artifact_hash,
            fold_id=item.fold_id,
            row_id=item.row_id,
            observation_at=item.observation_at,
            actual_available_at=item.actual_fact.available_at,
            actual_value=item.actual_value,
            actual_fact_id=item.actual_fact.fact_id,
            actual_fact_hash=item.actual_fact.evidence_hash,
            predicted_value=item.predicted_value,
            regime_code=item.regime_code,
            regime_version=item.regime_version,
            regime_content_hash=item.regime_content_hash,
            regime_effective_at=max(
                item.growth_fact.effective_at,
                item.inflation_fact.effective_at,
            ),
            regime_available_at=max(
                item.growth_fact.available_at,
                item.inflation_fact.available_at,
            ),
        )
        for item in receipt.assignments
    )
    assert report == build_regime_segment_report(
        case.ledger.artifact,
        observations,
        evaluated_at=receipt.recorded_at,
    )
    assert assignment_reader.calls == [
        (receipt.artifact_id, receipt.artifact_hash, receipt.recorded_at)
    ]
    assert artifact_reader.calls == [receipt.artifact_id]


def _walk_object_graph(root: object) -> tuple[object, ...]:
    pending = [root]
    values: list[object] = []
    visited: set[int] = set()
    while pending:
        value = pending.pop()
        if id(value) in visited or isinstance(
            value,
            (str, bytes, int, float, bool, type(None)),
        ):
            continue
        visited.add(id(value))
        values.append(value)
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, (tuple, list, set, frozenset)):
            pending.extend(value)
        else:
            pending.extend(
                getattr(value, name)
                for name in _stored_attribute_names(value)
                if hasattr(value, name)
            )
    return tuple(values)


def _stored_attribute_names(value: object) -> tuple[str, ...]:
    names = set(getattr(value, "__dict__", ()))
    for model_type in type(value).__mro__:
        slots = getattr(model_type, "__slots__", ())
        names.update((slots,) if isinstance(slots, str) else slots)
    return tuple(sorted(name for name in names if name not in {"__dict__", "__weakref__"}))
