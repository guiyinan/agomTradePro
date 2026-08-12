"""Pure Application tests for exact Research evidence reads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apps.research.application.evidence_reads import EvidenceReadFacade
from apps.research.domain.evidence_contracts import (
    ClaimKind,
    DecisionPermission,
    EvidenceEnvelope,
    EvidenceOperatorSpec,
    MethodKind,
    TrackRecordSnapshot,
)

AS_OF = datetime(2026, 8, 12, 9, tzinfo=UTC)


def _operator() -> EvidenceOperatorSpec:
    return EvidenceOperatorSpec.create(
        operator_id="operator-1",
        operator_version="v1",
        research_family="scenario",
        output_artifact_type="scenario_forecast",
        claim_kind=ClaimKind.FORECAST,
        method_kind=MethodKind.STATISTICAL,
        required_input_roles=(),
        dependency_flags=frozenset(),
        maximum_permission=DecisionPermission.DISPLAY_ONLY,
        requires_track_record=False,
        activated_at=AS_OF - timedelta(days=1),
        valid_until=AS_OF + timedelta(days=1),
    )


class _FakeEvidenceRepository:
    def __init__(self, operator: EvidenceOperatorSpec | None) -> None:
        self.operator = operator
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get_operator_spec(
        self,
        *,
        operator_id: str,
        operator_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpec | None:
        self.calls.append(
            (
                "operator",
                {
                    "operator_id": operator_id,
                    "operator_version": operator_version,
                    "expected_content_hash": expected_content_hash,
                    "as_of": as_of,
                },
            )
        )
        return self.operator

    def get_track_record(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> TrackRecordSnapshot | None:
        self.calls.append(
            (
                "track",
                {
                    "snapshot_id": snapshot_id,
                    "snapshot_version": snapshot_version,
                    "expected_content_hash": expected_content_hash,
                    "as_of": as_of,
                },
            )
        )
        return None

    def get_envelope(
        self,
        *,
        output_owner: str,
        output_artifact_type: str,
        output_artifact_id: str,
        output_artifact_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceEnvelope | None:
        self.calls.append(
            (
                "envelope",
                {
                    "output_owner": output_owner,
                    "output_artifact_type": output_artifact_type,
                    "output_artifact_id": output_artifact_id,
                    "output_artifact_version": output_artifact_version,
                    "expected_content_hash": expected_content_hash,
                    "as_of": as_of,
                },
            )
        )
        return None


def test_facade_delegates_exact_hash_and_pit_selector_without_infrastructure_imports() -> None:
    operator = _operator()
    repository = _FakeEvidenceRepository(operator)
    facade = EvidenceReadFacade(repository)

    result = facade.get_operator_spec(
        operator_id=operator.operator_id,
        operator_version=operator.operator_version,
        expected_content_hash=operator.content_hash,
        as_of=AS_OF,
    )

    assert result is operator
    assert repository.calls == [
        (
            "operator",
            {
                "operator_id": "operator-1",
                "operator_version": "v1",
                "expected_content_hash": operator.content_hash,
                "as_of": AS_OF,
            },
        )
    ]


def test_facade_preserves_not_found_for_track_and_owner_qualified_envelope() -> None:
    repository = _FakeEvidenceRepository(None)
    facade = EvidenceReadFacade(repository)

    track = facade.get_track_record(
        snapshot_id="track-1",
        snapshot_version="v1",
        expected_content_hash="a" * 64,
        as_of=AS_OF,
    )
    envelope = facade.get_envelope(
        output_owner="research",
        output_artifact_type="scenario_forecast",
        output_artifact_id="forecast-1",
        output_artifact_version="v1",
        expected_content_hash="b" * 64,
        as_of=AS_OF,
    )

    assert track is None
    assert envelope is None
    assert repository.calls[0][0] == "track"
    assert repository.calls[1] == (
        "envelope",
        {
            "output_owner": "research",
            "output_artifact_type": "scenario_forecast",
            "output_artifact_id": "forecast-1",
            "output_artifact_version": "v1",
            "expected_content_hash": "b" * 64,
            "as_of": AS_OF,
        },
    )
