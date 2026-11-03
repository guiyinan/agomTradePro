"""Domain validation for optional, replayable Scenario run snapshots."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.risk_center.application.scenario_use_cases import (
    GetScenarioRunEvidenceUseCase,
    ScenarioNotFoundError,
)
from apps.risk_center.domain.scenarios import (
    ScenarioRunEvidence,
    canonical_scenario_snapshot_json,
    scenario_run_snapshot_hash,
)
from apps.risk_center.infrastructure.scenario_repositories import (
    _snapshot_model_value,
    _snapshot_text,
)

NOW = datetime(2026, 11, 3, 2, 0, tzinfo=UTC)


def _evidence(
    *,
    result_hash: str = "a" * 64,
    input_snapshot_json: str | None = None,
    result_snapshot_json: str | None = None,
) -> ScenarioRunEvidence:
    """Build a legacy-compatible run evidence value."""

    return ScenarioRunEvidence(
        run_id="00000000-0000-0000-0000-000000000001",
        scenario_revision_id="scenario-revision-1",
        portfolio_snapshot_id="simulated-account:42:" + ("b" * 64),
        portfolio_snapshot_hash="c" * 64,
        as_of_time=NOW,
        data_evidence_ids=("source:record",),
        result_hash=result_hash,
        allocation_policy_version="profile-v1",
        code_version="code-sha256:" + ("d" * 64),
        created_at=NOW,
        input_snapshot_json=input_snapshot_json,
        result_snapshot_json=result_snapshot_json,
    )


def test_legacy_run_evidence_keeps_optional_snapshots_absent() -> None:
    """Old rows remain valid without pretending their hash is recoverable data."""

    evidence = _evidence()

    assert evidence.input_snapshot_json is None
    assert evidence.result_snapshot_json is None
    assert evidence.result_hash == "a" * 64


def test_snapshots_are_canonical_and_both_bound_by_run_hash() -> None:
    """A new run digest covers both immutable JSON objects."""

    input_json = canonical_scenario_snapshot_json({"quantity": "10", "asset": "600000.SH"})
    result_json = canonical_scenario_snapshot_json({"status": "limited", "sessions": 2})

    evidence = _evidence(
        result_hash=scenario_run_snapshot_hash(
            input_snapshot_json=input_json,
            result_snapshot_json=result_json,
        ),
        input_snapshot_json=input_json,
        result_snapshot_json=result_json,
    )

    assert evidence.input_snapshot_json == input_json
    assert evidence.result_snapshot_json == result_json


def test_json_field_mapping_preserves_canonical_snapshot_bytes() -> None:
    """JSONField object mapping round-trips to the exact canonical hash input."""

    snapshot_json = canonical_scenario_snapshot_json({"asset": "600000.SH", "amount": "12.50"})

    model_value = _snapshot_model_value(snapshot_json)

    assert model_value == {"amount": "12.50", "asset": "600000.SH"}
    assert _snapshot_text(model_value) == snapshot_json
    assert _snapshot_text(None) is None


def test_snapshot_pair_and_canonical_encoding_are_required() -> None:
    """Partial or reordered JSON cannot be accepted as complete retained evidence."""

    input_json = canonical_scenario_snapshot_json({"asset": "600000.SH"})
    result_json = canonical_scenario_snapshot_json({"status": "limited"})
    result_hash = scenario_run_snapshot_hash(
        input_snapshot_json=input_json,
        result_snapshot_json=result_json,
    )

    with pytest.raises(ValueError, match="stored together"):
        _evidence(result_hash=result_hash, input_snapshot_json=input_json)
    with pytest.raises(ValueError, match="canonical JSON"):
        _evidence(
            result_hash=result_hash,
            input_snapshot_json='{ "asset":"600000.SH"}',
            result_snapshot_json=result_json,
        )


def test_snapshot_changes_cannot_reuse_the_prior_hash() -> None:
    """A changed input or result must produce a different stored run digest."""

    input_json = canonical_scenario_snapshot_json({"asset": "600000.SH"})
    result_json = canonical_scenario_snapshot_json({"status": "limited"})
    evidence = _evidence(
        result_hash=scenario_run_snapshot_hash(
            input_snapshot_json=input_json,
            result_snapshot_json=result_json,
        ),
        input_snapshot_json=input_json,
        result_snapshot_json=result_json,
    )

    with pytest.raises(ValueError, match="must bind its snapshots"):
        _evidence(
            result_hash=evidence.result_hash,
            input_snapshot_json=canonical_scenario_snapshot_json({"asset": "600000.SH"}),
            result_snapshot_json=canonical_scenario_snapshot_json({"status": "blocked"}),
        )


def test_read_use_case_preserves_legacy_missing_snapshots() -> None:
    """The public application reader does not reconstruct legacy snapshots from hashes."""

    class Reader:
        """Return a fixture through the read-only evidence port."""

        def get_run_evidence(self, run_id: str) -> ScenarioRunEvidence | None:
            assert run_id == "00000000-0000-0000-0000-000000000001"
            return _evidence()

    evidence = GetScenarioRunEvidenceUseCase(Reader()).execute(
        "00000000-0000-0000-0000-000000000001"
    )

    assert evidence.input_snapshot_json is None
    assert evidence.result_snapshot_json is None

    with pytest.raises(ScenarioNotFoundError):
        GetScenarioRunEvidenceUseCase(Reader()).execute("not-a-uuid")
