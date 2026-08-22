"""Focused tests for the candidate-bound QLib worker memory evidence guard."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from apps.agent_runtime.application.terminal_runtime_worker_memory_evidence import (
    TerminalRuntimeWorkerMemoryEvidenceBinding,
    TerminalRuntimeWorkerMemoryEvidenceError,
    validate_terminal_runtime_worker_memory_evidence,
)

ARTIFACT = Path("docs/deployment/tar01-qlib-batch-memory-remediation-2026-08-22.json")
EXPECTED = TerminalRuntimeWorkerMemoryEvidenceBinding(
    candidate_commit="c7ea5a9fc914e0a464e7286388477cb167079927",
    candidate_release="20260822091112",
    image_id="sha256:b6b5db3326f4fa6cb03a015f036d90b9a1591ac6cf1ee951de7b819ce7ed24a0",
)


def _payload() -> dict[str, object]:
    """Load a fresh copy of the committed current-candidate artifact."""

    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_current_qlib_memory_artifact_is_candidate_bound_and_capacity_denied() -> None:
    """The real artifact validates without claiming a capacity or decision pass."""

    report = validate_terminal_runtime_worker_memory_evidence(
        _payload(), expected_candidate=EXPECTED
    )

    assert report.candidate_bound is True
    assert report.window_seconds == 22 * 60 + 34
    assert report.batch_count == 12
    assert report.task_outcome == "success"
    assert report.stored == 1
    assert report.observed_max_memory_bytes <= report.memory_limit_bytes
    assert report.health_status == 200
    assert report.ready_status == 200
    assert report.decision_ready_status == 503
    assert report.decision_ready_must_not_use_for_decision is True
    assert report.runtime_flags_changed is False
    assert report.business_canary_submitted is False
    assert report.tar01_exit_decision == "BLOCKED"
    assert report.safety_ready is True
    assert report.capacity_ready is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_commit", "d" * 40),
        ("candidate_release", "20260822091113"),
        ("image_id", "sha256:" + "d" * 64),
    ],
)
def test_candidate_substitution_is_rejected(field: str, value: str) -> None:
    """A report cannot be rebound to a different source, release, or image."""

    expected = TerminalRuntimeWorkerMemoryEvidenceBinding(
        candidate_commit=value if field == "candidate_commit" else EXPECTED.candidate_commit,
        candidate_release=value if field == "candidate_release" else EXPECTED.candidate_release,
        image_id=value if field == "image_id" else EXPECTED.image_id,
    )
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match="candidate"):
        validate_terminal_runtime_worker_memory_evidence(_payload(), expected_candidate=expected)


def test_artifact_candidate_release_and_image_tag_must_match() -> None:
    """The candidate object cannot report a mismatched release tag or image tag."""

    payload = _payload()
    candidate = payload["candidate"]
    assert isinstance(candidate, dict)
    candidate["image_tag"] = "agomtradepro-web:20260822091113"
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match="image_tag"):
        validate_terminal_runtime_worker_memory_evidence(payload, expected_candidate=EXPECTED)


def test_observation_window_must_be_aware_increasing_and_consistent() -> None:
    """Naive, backwards, or text-mismatched windows are not observations."""

    payload = _payload()
    observation = payload["post_deploy_observation"]
    assert isinstance(observation, dict)
    observation["window_start"] = "2026-08-22T01:25:12"
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match="timezone-aware"):
        validate_terminal_runtime_worker_memory_evidence(payload, expected_candidate=EXPECTED)

    payload = _payload()
    observation = payload["post_deploy_observation"]
    assert isinstance(observation, dict)
    observation["window_end"] = "2026-08-22T01:25:11Z"
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match="not increasing"):
        validate_terminal_runtime_worker_memory_evidence(payload, expected_candidate=EXPECTED)

    payload = _payload()
    observation = payload["post_deploy_observation"]
    assert isinstance(observation, dict)
    observation["window"] = "22m35s"
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match="does not match"):
        validate_terminal_runtime_worker_memory_evidence(payload, expected_candidate=EXPECTED)


def test_worker_contract_is_bounded_to_four_gib_one_child_and_500_batch() -> None:
    """Resource settings cannot drift while retaining the same evidence label."""

    payload = _payload()
    worker = payload["worker_contract"]
    assert isinstance(worker, dict)
    worker["memory_limit_bytes"] = 2 * 1024**3
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match="memory_limit_bytes"):
        validate_terminal_runtime_worker_memory_evidence(payload, expected_candidate=EXPECTED)

    payload = _payload()
    worker = payload["worker_contract"]
    assert isinstance(worker, dict)
    worker["qlib_prediction_batch_size"] = 250
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match="batch size"):
        validate_terminal_runtime_worker_memory_evidence(payload, expected_candidate=EXPECTED)


def test_memory_range_and_worker_error_counters_must_stay_safe() -> None:
    """An over-limit range or any restart/OOM/error invalidates the report."""

    payload = _payload()
    observation = payload["post_deploy_observation"]
    assert isinstance(observation, dict)
    observation["worker_memory_range"] = "835.6MiB..4.1GiB / 4GiB"
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match="exceeds"):
        validate_terminal_runtime_worker_memory_evidence(payload, expected_candidate=EXPECTED)

    payload = _payload()
    observation = payload["post_deploy_observation"]
    assert isinstance(observation, dict)
    observation["sigkill_count"] = 1
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match="sigkill_count"):
        validate_terminal_runtime_worker_memory_evidence(payload, expected_candidate=EXPECTED)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("batch_count", 11, "batch_count"),
        ("outcome", "failed", "outcome"),
        ("stored", 0, "stored"),
    ],
)
def test_successful_task_must_cover_all_twelve_batches(
    field: str, value: object, message: str
) -> None:
    """Partial, failed, or unpersisted QLib work is rejected."""

    payload = _payload()
    observation = payload["post_deploy_observation"]
    assert isinstance(observation, dict)
    task = observation["successful_task"]
    assert isinstance(task, dict)
    task[field] = value
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match=message):
        validate_terminal_runtime_worker_memory_evidence(payload, expected_candidate=EXPECTED)


def test_decision_ready_and_gate_fields_cannot_be_overridden() -> None:
    """The artifact must preserve fail-closed decision and capacity semantics."""

    payload = _payload()
    api = payload["api_observation"]
    assert isinstance(api, dict)
    api["decision_ready_status"] = 200
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match="decision-ready"):
        validate_terminal_runtime_worker_memory_evidence(payload, expected_candidate=EXPECTED)

    payload = _payload()
    gate = payload["gate"]
    assert isinstance(gate, dict)
    gate["capacity_ready"] = True
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match="capacity-blocked"):
        validate_terminal_runtime_worker_memory_evidence(payload, expected_candidate=EXPECTED)


def test_flags_canary_and_ci_must_remain_candidate_bound() -> None:
    """No runtime mutation or unrelated CI head may be hidden in the artifact."""

    payload = _payload()
    api = payload["api_observation"]
    assert isinstance(api, dict)
    api["runtime_flags_changed"] = True
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match="flag/canary"):
        validate_terminal_runtime_worker_memory_evidence(payload, expected_candidate=EXPECTED)

    payload = _payload()
    ci = payload["ci"]
    assert isinstance(ci, dict)
    ci["head"] = "d" * 40
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match="ci.head"):
        validate_terminal_runtime_worker_memory_evidence(payload, expected_candidate=EXPECTED)


def test_unknown_or_secret_fields_fail_closed() -> None:
    """The closed-world envelope prevents extension and secret retention."""

    payload = _payload()
    payload["unexpected"] = "value"
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match="keys must be exactly"):
        validate_terminal_runtime_worker_memory_evidence(payload, expected_candidate=EXPECTED)

    payload = _payload()
    trigger = payload["trigger_and_correction"]
    assert isinstance(trigger, dict)
    trigger["trigger"] = "password-recorded"
    with pytest.raises(TerminalRuntimeWorkerMemoryEvidenceError, match="secret material"):
        validate_terminal_runtime_worker_memory_evidence(payload, expected_candidate=EXPECTED)


def test_worker_memory_validator_has_no_runtime_enabling_dependencies() -> None:
    """The validator remains pure Application code and performs no remote I/O."""

    path = Path("apps/agent_runtime/application/terminal_runtime_worker_memory_evidence.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any(
        forbidden in name
        for name in imported
        for forbidden in ("django", "celery", "requests", "subprocess", "socket", "redis")
    )


def test_test_fixture_is_not_mutated_between_validation_cases() -> None:
    """The committed artifact remains unchanged when tests mutate copies."""

    first = _payload()
    second = copy.deepcopy(first)
    second_gate = second["gate"]
    first_gate = first["gate"]
    assert isinstance(second_gate, dict)
    assert isinstance(first_gate, dict)
    second_gate["capacity_ready"] = True
    assert first_gate["capacity_ready"] is False
