"""Unit contracts for starting the Web-to-TUI M5 observation window."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from scripts import start_web_to_tui_observation as observation
from scripts.web_to_tui_candidate_binding import CandidateBinding

NOW = datetime(2026, 7, 28, 12, 10, tzinfo=UTC)


def _evidence() -> dict[str, Any]:
    """Build a minimal cutover evidence fixture."""

    return {
        "source_sha256": "a" * 64,
        "candidate": {
            "stable_version": None,
            "candidate_commit": None,
            "released_at": None,
            "observation_end": None,
        },
        "defects": {"open_p0": 1},
        "telemetry": {"tasks": [{"task_key": "old"}]},
        "rollback": {
            "passed": True,
            "environment": "local",
            "production_registry_backup": {"location": "artifact://old"},
        },
        "review_snapshot": {"evidence": "old", "sha256": "b" * 64},
        "approvals": {"owner": {"name": "old"}, "reviewer": {"name": "old-2"}},
    }


def _attestation_payload() -> dict[str, Any]:
    """Build synthetic, fresh deployment proof for unit testing only."""

    return {
        "version": observation.DEPLOYMENT_ATTESTATION_VERSION,
        "environment": "production",
        "release": {
            "stable_version": "0.9.0-rc1",
            "release_id": "source-20260728115000",
            "source_commit": "c" * 40,
            "deployed_at": "2026-07-28T11:50:00+00:00",
        },
        "oci_image": {
            "image_id": f"sha256:{'d' * 64}",
            "revision": "c" * 40,
        },
        "production_health": {
            "checked_at": "2026-07-28T12:00:00+00:00",
            "health": {
                "http_status": 200,
                "status": "ok",
                "response_sha256": "e" * 64,
            },
            "readiness": {
                "http_status": 200,
                "status": "ok",
                "response_sha256": "f" * 64,
            },
        },
        "verified_at": "2026-07-28T12:01:00+00:00",
    }


def _deployment(
    payload: dict[str, Any] | None = None,
    *,
    now: datetime = NOW,
    evidence: str = "evidence/deployment-preflight.json",
) -> observation.DeploymentPreflight:
    """Parse synthetic proof through the production validator."""

    return observation.parse_deployment_preflight(
        payload or _attestation_payload(),
        now=now,
        evidence=evidence,
        evidence_sha256="1" * 64,
    )


def _candidate_binding(
    deployment: observation.DeploymentPreflight | None = None,
) -> CandidateBinding:
    """Build the candidate identity paired with synthetic deployment proof."""

    selected = deployment or _deployment()
    return {
        "version": "web-to-tui-candidate-binding.v1",
        "candidate_version": selected.stable_version,
        "candidate_commit": selected.source_commit,
        "matrix_sha256": "2" * 64,
        "graph_sha256": "3" * 64,
        "schema_version": "tui-operation-graph.v1",
        "runtime_version": "agomtui-runtime.v1",
        "runtime_build_id": "build-20260728",
        "runtime_manifest_sha256": "4" * 64,
    }


def test_deployment_preflight_schema_accepts_the_contract() -> None:
    """The published schema and runtime parser accept the same valid structure."""

    schema_path = (
        observation.ROOT
        / "config/tui/schema/web_to_tui_deployment_preflight_attestation.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(_attestation_payload())
    assert _deployment().released_at.isoformat() == "2026-07-28"


def test_preflight_rejects_caller_time_and_semantically_ignored_fields() -> None:
    """A caller cannot inject released_at into otherwise valid deployment proof."""

    payload = _attestation_payload()
    payload["released_at"] = "2026-07-01"

    with pytest.raises(observation.ObservationStartError, match=r"extra=\['released_at'\]"):
        _deployment(payload)


def test_preflight_rejects_stale_proof_instead_of_backfilling() -> None:
    """Historical production proof cannot retroactively start an observation window."""

    with pytest.raises(observation.ObservationStartError, match="stale"):
        _deployment(now=NOW + timedelta(hours=1))


def test_preflight_rejects_old_deployment_even_with_new_health_claims() -> None:
    """Fresh probes cannot make an old deployment into a newly released candidate."""

    payload = _attestation_payload()
    payload["release"]["deployed_at"] = "2026-07-27T11:00:00+00:00"

    with pytest.raises(observation.ObservationStartError, match="deployment is too old"):
        _deployment(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("oci_image", "revision", "a" * 40), "OCI revision"),
        (("production_health", "health", "status", "degraded"), "healthy production"),
        (("production_health", "readiness", "http_status", 503), "healthy production"),
    ],
)
def test_preflight_rejects_identity_or_health_mismatch(
    mutation: tuple[str, ...],
    message: str,
) -> None:
    """OCI identity and both production probes are mandatory, exact bindings."""

    payload = _attestation_payload()
    target: dict[str, Any] = payload
    for key in mutation[:-2]:
        target = target[key]
    target[mutation[-2]] = mutation[-1]

    with pytest.raises(observation.ObservationStartError, match=message):
        _deployment(payload)


def test_preflight_requires_monotonic_timezone_aware_timestamps() -> None:
    """Future, naive, or causally inverted proof timestamps fail closed."""

    naive = _attestation_payload()
    naive["verified_at"] = "2026-07-28T12:01:00"
    with pytest.raises(observation.ObservationStartError, match="timezone offset"):
        _deployment(naive)

    inverted = _attestation_payload()
    inverted["production_health"]["checked_at"] = "2026-07-28T11:40:00+00:00"
    with pytest.raises(observation.ObservationStartError, match="not monotonic"):
        _deployment(inverted)


def test_prepare_starts_fourteen_day_window_and_clears_stale_evidence() -> None:
    """A proven deployment starts a full window without old production proof."""

    deployment = _deployment()
    prepared = observation.prepare_observation_evidence(
        _evidence(),
        deployment=deployment,
        candidate_binding=_candidate_binding(deployment),
        replace=False,
    )

    assert prepared["candidate"] == {
        "stable_version": "0.9.0-rc1",
        "candidate_commit": "c" * 40,
        "released_at": "2026-07-28",
        "observation_end": "2026-08-11",
        "binding": _candidate_binding(deployment),
        "deployment_preflight": {
            "version": observation.DEPLOYMENT_ATTESTATION_VERSION,
            "evidence": "evidence/deployment-preflight.json",
            "evidence_sha256": "1" * 64,
            "release_id": "source-20260728115000",
            "source_commit": "c" * 40,
            "deployed_at": "2026-07-28T11:50:00+00:00",
            "image_id": f"sha256:{'d' * 64}",
            "oci_revision": "c" * 40,
            "health_checked_at": "2026-07-28T12:00:00+00:00",
            "health_response_sha256": "e" * 64,
            "readiness_response_sha256": "f" * 64,
            "verified_at": "2026-07-28T12:01:00+00:00",
        },
    }
    assert prepared["defects"]["open_p0"] is None
    assert prepared["telemetry"]["tasks"] == []
    assert prepared["rollback"]["production_registry_backup"] is None
    assert prepared["review_snapshot"] == {"evidence": None, "sha256": None}
    assert prepared["approvals"] == {"owner": None, "reviewer": None}


def test_prepare_is_idempotent_for_same_deployment_proof() -> None:
    """Repeating the exact proof preserves evidence collected for its candidate."""

    deployment = _deployment()
    initial = observation.prepare_observation_evidence(
        _evidence(),
        deployment=deployment,
        candidate_binding=_candidate_binding(deployment),
        replace=False,
    )
    initial["telemetry"]["tasks"] = [{"task_key": "current"}]
    initial["candidate"]["retained_observation"] = {
        "version": "web-to-tui-retained-observation-binding.v1",
        "evidence": "docs/deployment/retained.json",
        "evidence_sha256": "9" * 64,
        "first_retained_sample_at": "2026-07-28T12:00:00Z",
        "minimum_observation_seconds": 1209600,
        "eligible_at": "2026-08-11T12:00:00Z",
    }

    repeated = observation.prepare_observation_evidence(
        initial,
        deployment=deployment,
        candidate_binding=_candidate_binding(deployment),
        replace=False,
    )

    assert repeated["telemetry"]["tasks"] == [{"task_key": "current"}]
    assert (
        repeated["candidate"]["retained_observation"]
        == initial["candidate"]["retained_observation"]
    )


def test_prepare_requires_replace_for_different_deployment_proof() -> None:
    """A new proof cannot silently reuse a previous candidate window."""

    deployment = _deployment()
    existing = observation.prepare_observation_evidence(
        _evidence(),
        deployment=deployment,
        candidate_binding=_candidate_binding(deployment),
        replace=False,
    )
    payload = _attestation_payload()
    payload["release"]["release_id"] = "source-20260728115500"
    replacement = _deployment(payload, evidence="evidence/replacement.json")

    with pytest.raises(observation.ObservationStartError, match="--replace"):
        observation.prepare_observation_evidence(
            existing,
            deployment=replacement,
            candidate_binding=_candidate_binding(replacement),
            replace=False,
        )


def test_prepare_replace_resets_previous_candidate_evidence() -> None:
    """Explicit replacement restarts the window and clears old proof."""

    deployment = _deployment()
    existing = observation.prepare_observation_evidence(
        _evidence(),
        deployment=deployment,
        candidate_binding=_candidate_binding(deployment),
        replace=False,
    )
    existing["uat"] = {"candidate_binding": _candidate_binding(deployment), "evidence": "old"}
    existing["cleanup"] = {
        "candidate_binding": _candidate_binding(deployment),
        "evidence": "old",
    }
    existing["rollback"] = {
        "candidate_binding": _candidate_binding(deployment),
        "passed": True,
        "environment": "local",
        "production_registry_backup": {"location": "artifact://old"},
    }
    existing["telemetry"]["tasks"] = [{"task_key": "previous-candidate"}]
    payload = _attestation_payload()
    payload["release"]["release_id"] = "source-20260728115500"
    replacement = _deployment(payload, evidence="evidence/replacement.json")

    replaced = observation.prepare_observation_evidence(
        existing,
        deployment=replacement,
        candidate_binding=_candidate_binding(replacement),
        replace=True,
    )

    assert replaced["candidate"]["observation_end"] == "2026-08-11"
    assert replaced["candidate"]["binding"] == _candidate_binding(replacement)
    assert replaced["uat"]["candidate_binding"] is None
    assert replaced["uat"]["passed_route_pages"] == []
    assert replaced["cleanup"]["candidate_binding"] is None
    assert replaced["cleanup"]["route_rollback_commits"] == {}
    assert replaced["rollback"]["candidate_binding"] is None
    assert replaced["rollback"]["passed"] is None
    assert replaced["telemetry"]["tasks"] == []


def test_loader_rejects_uncommitted_or_drifted_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only byte-exact proof already committed at HEAD can start observation."""

    attestation = tmp_path / "deployment.json"
    attestation.write_text(json.dumps(_attestation_payload()), encoding="utf-8")

    monkeypatch.setattr(
        observation.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=[], returncode=1),
    )
    with pytest.raises(observation.ObservationStartError, match="must be committed"):
        observation._load_committed_deployment_preflight(
            attestation,
            now=NOW,
            root=tmp_path,
        )

    monkeypatch.setattr(
        observation.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"different"
        ),
    )
    with pytest.raises(observation.ObservationStartError, match="differs"):
        observation._load_committed_deployment_preflight(
            attestation,
            now=NOW,
            root=tmp_path,
        )


def test_validate_candidate_requires_matching_committed_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A commit for a different migration scope cannot start observation."""

    matrix = tmp_path / "matrix.csv"
    graph = tmp_path / "graph.json"
    runtime_manifest = tmp_path / "runtime.json"
    matrix.write_text("current", encoding="utf-8")
    graph.write_text("graph", encoding="utf-8")
    runtime_manifest.write_text("runtime", encoding="utf-8")
    evidence = {"source_sha256": hashlib.sha256(b"current").hexdigest()}
    monkeypatch.setattr(observation, "_commit_is_ancestor", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        observation,
        "_file_at_commit",
        lambda commit, path, **kwargs: b"old" if path == matrix else path.read_bytes(),
    )

    with pytest.raises(observation.ObservationStartError, match="different migration matrix"):
        observation.validate_candidate_source(
            candidate_commit="a" * 40,
            matrix_path=matrix,
            graph_path=graph,
            runtime_manifest_path=runtime_manifest,
            evidence=evidence,
            require_clean=False,
            root=tmp_path,
        )


def test_validate_candidate_rejects_dirty_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uncommitted code cannot be represented by a stable candidate commit."""

    matrix = tmp_path / "matrix.csv"
    graph = tmp_path / "graph.json"
    runtime_manifest = tmp_path / "runtime.json"
    matrix.write_bytes(b"current")
    graph.write_bytes(b"graph")
    runtime_manifest.write_bytes(b"runtime")
    evidence = {"source_sha256": hashlib.sha256(b"current").hexdigest()}
    monkeypatch.setattr(observation, "_commit_is_ancestor", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        observation,
        "_file_at_commit",
        lambda commit, path, **kwargs: path.read_bytes(),
    )
    monkeypatch.setattr(observation, "_worktree_changes", lambda **kwargs: [" M file.py"])

    with pytest.raises(observation.ObservationStartError, match="Worktree must be clean"):
        observation.validate_candidate_source(
            candidate_commit="a" * 40,
            matrix_path=matrix,
            graph_path=graph,
            runtime_manifest_path=runtime_manifest,
            evidence=evidence,
            require_clean=True,
            root=tmp_path,
        )
