"""Unit contracts for exact retained-monitoring observation binding."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import web_to_tui_retained_observation as retained

COMMIT = "a" * 40
IMAGE = f"sha256:{'b' * 64}"


def _checkpoint() -> dict[str, Any]:
    """Build one valid production read-only retained checkpoint."""

    return {
        "version": retained.CHECKPOINT_VERSION,
        "environment": "production",
        "collection_mode": "read_only",
        "candidate": {
            "expected": {
                "commit": COMMIT,
                "release_id": "release-1",
                "image_id": IMAGE,
            },
            "observed": {
                "commit": COMMIT,
                "release_id": "release-1",
                "image_id": IMAGE,
            },
            "candidate_drift": False,
        },
        "observation": {
            "first_retained_raw_sample_at": "2026-08-30T15:09:35.034000Z",
            "minimum_observation_seconds": retained.MINIMUM_OBSERVATION_SECONDS,
            "earliest_full_14d_telemetry_at": "2026-09-13T15:09:35.034000Z",
            "historical_backfill_used": False,
            "synthetic_zero_used": False,
            "window_reset_required": False,
        },
        "gate": {
            "candidate_unchanged": True,
            "prometheus_unexpected_restart": False,
            "target_ok": True,
            "rules_ok": True,
            "retention_ok": True,
            "storage_ok": True,
            "protected_query_ok": True,
            "window_reset_required": False,
            "tui02_final_authorized": False,
        },
        "side_effects": {
            "remote_write": False,
            "deployment": False,
            "restart": False,
            "configuration_change": False,
            "backup": False,
            "load_test": False,
            "business_request": False,
        },
    }


def _evidence() -> dict[str, Any]:
    """Build cutover evidence with stale post-window results."""

    return {
        "candidate": {
            "stable_version": "release-1",
            "candidate_commit": COMMIT,
            "released_at": "2026-08-30",
            "observation_end": "2026-09-13",
            "deployment_preflight": {"image_id": IMAGE},
        },
        "defects": {"open_p0": 0},
        "telemetry": {"tasks": [{"task_key": "stale"}]},
        "rollback": {"production_registry_backup": {"location": "artifact://stale"}},
        "review_snapshot": {"evidence": "stale", "sha256": "c" * 64},
        "approvals": {"owner": {"name": "stale"}, "reviewer": None},
    }


def _write_checkpoint(tmp_path: Path, payload: dict[str, Any] | None = None) -> Path:
    """Write one synthetic checkpoint under the supplied repository root."""

    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(payload or _checkpoint()), encoding="utf-8")
    return path


def _reset_artifact(checkpoint: Path) -> dict[str, Any]:
    """Build one candidate-bound read-only restart artifact."""

    checkpoint_sha256 = hashlib.sha256(
        checkpoint.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n").encode()
    ).hexdigest()
    return {
        "version": retained.RESET_VERSION,
        "environment": "production",
        "collection_mode": "read_only",
        "checked_at": "2026-09-02T15:53:33.776786Z",
        "candidate": {
            "expected": {"commit": COMMIT, "release_id": "release-1", "image_id": IMAGE},
            "observed": {"commit": COMMIT, "release_id": "release-1", "image_id": IMAGE},
            "candidate_drift": False,
        },
        "reset": {
            "reason_code": "controlled_web_restart_after_liveness_incident",
            "reset_at": "2026-09-02T15:38:21.178433901Z",
            "web_container_id": "d" * 64,
            "web_started_at": "2026-09-02T15:38:21.178433901Z",
            "web_status": "running",
            "web_health": "healthy",
            "web_restart_count": 0,
            "prometheus_restart_count": 0,
            "prometheus_unexpected_restart": False,
        },
        "public_probes": {
            "health": {"http_status": 200},
            "ready": {"http_status": 200},
            "decision_ready": {"http_status": 503, "must_not_use_for_decision": True},
        },
        "previous_observation": {
            "checkpoint": "checkpoint.json",
            "checkpoint_sha256": checkpoint_sha256,
            "first_retained_sample_at": "2026-08-30T15:09:35.034000Z",
            "eligible_at": "2026-09-13T15:09:35.034000Z",
        },
        "observation": {
            "window_reset_required": True,
            "new_sample_required": True,
            "post_reset_sample_observed": False,
        },
        "production_claim": False,
        "production_ready": False,
        "runtime_enablement": "not_authorized",
        "side_effects": {
            "remote_restart": True,
            "remote_deploy": False,
            "remote_database_write": False,
            "remote_configuration_change": False,
            "load_or_chaos_test": False,
            "authority_or_approval_mutation": False,
        },
    }


def _evidence_with_retained_checkpoint(checkpoint: Path) -> dict[str, Any]:
    """Build candidate evidence already bound to the checkpoint under test."""

    checkpoint_sha256 = hashlib.sha256(
        checkpoint.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n").encode()
    ).hexdigest()
    evidence = _evidence()
    evidence["candidate"]["retained_observation"] = {
        "version": retained.BINDING_VERSION,
        "evidence": "checkpoint.json",
        "evidence_sha256": checkpoint_sha256,
        "first_retained_sample_at": "2026-08-30T15:09:35.034000Z",
        "minimum_observation_seconds": retained.MINIMUM_OBSERVATION_SECONDS,
        "eligible_at": "2026-09-13T15:09:35.034000Z",
    }
    return evidence


def test_binds_exact_sample_and_clears_only_post_window_results(tmp_path: Path) -> None:
    """A real first sample becomes the sole exact 14-day clock source."""

    prepared = retained.bind_retained_observation(
        _evidence(),
        checkpoint_path=_write_checkpoint(tmp_path),
        replace=False,
        root=tmp_path,
    )

    candidate = prepared["candidate"]
    binding = retained.validate_retained_observation_checkpoint(candidate, root=tmp_path)
    assert retained.utc_text(binding.first_retained_sample_at) == "2026-08-30T15:09:35.034000Z"
    assert retained.utc_text(binding.eligible_at) == "2026-09-13T15:09:35.034000Z"
    assert candidate["observation_end"] == "2026-09-13"
    assert prepared["defects"]["open_p0"] is None
    assert prepared["telemetry"]["tasks"] == []
    assert prepared["rollback"]["production_registry_backup"] is None
    assert prepared["review_snapshot"] == {"evidence": None, "sha256": None}
    assert prepared["approvals"] == {"owner": None, "reviewer": None}


def test_checkpoint_hash_drift_fails_closed(tmp_path: Path) -> None:
    """A projection cannot survive mutation of its retained source evidence."""

    checkpoint = _write_checkpoint(tmp_path)
    prepared = retained.bind_retained_observation(
        _evidence(),
        checkpoint_path=checkpoint,
        replace=False,
        root=tmp_path,
    )
    checkpoint.write_text(json.dumps({**_checkpoint(), "changed": True}), encoding="utf-8")

    with pytest.raises(retained.RetainedObservationError, match="SHA-256 mismatch"):
        retained.validate_retained_observation_checkpoint(
            prepared["candidate"],
            root=tmp_path,
        )


def test_checkpoint_hash_is_stable_across_checkout_line_endings(tmp_path: Path) -> None:
    """A Git-canonical evidence digest survives a Windows CRLF checkout."""

    checkpoint = _write_checkpoint(tmp_path)
    prepared = retained.bind_retained_observation(
        _evidence(),
        checkpoint_path=checkpoint,
        replace=False,
        root=tmp_path,
    )
    canonical = checkpoint.read_bytes()
    checkpoint.write_bytes(canonical.replace(b"\n", b"\r\n"))

    binding = retained.validate_retained_observation_checkpoint(
        prepared["candidate"],
        root=tmp_path,
    )
    assert (
        binding.evidence_sha256 == prepared["candidate"]["retained_observation"]["evidence_sha256"]
    )


def test_candidate_or_monitoring_drift_cannot_start_the_clock(tmp_path: Path) -> None:
    """Candidate identity and every retained-source health gate remain mandatory."""

    wrong_candidate = _checkpoint()
    wrong_candidate["candidate"]["observed"]["commit"] = "d" * 40
    with pytest.raises(retained.RetainedObservationError, match="identity"):
        retained.bind_retained_observation(
            _evidence(),
            checkpoint_path=_write_checkpoint(tmp_path, wrong_candidate),
            replace=False,
            root=tmp_path,
        )

    unhealthy = _checkpoint()
    unhealthy["gate"]["target_ok"] = False
    with pytest.raises(retained.RetainedObservationError, match="monitoring gates"):
        retained.bind_retained_observation(
            _evidence(),
            checkpoint_path=_write_checkpoint(tmp_path, unhealthy),
            replace=False,
            root=tmp_path,
        )

    side_effecting = _checkpoint()
    side_effecting["side_effects"]["restart"] = True
    with pytest.raises(retained.RetainedObservationError, match="side-effect-free"):
        retained.bind_retained_observation(
            _evidence(),
            checkpoint_path=_write_checkpoint(tmp_path, side_effecting),
            replace=False,
            root=tmp_path,
        )


def test_projection_rejects_shortened_eligibility() -> None:
    """Editing the eligibility timestamp cannot shorten the exact duration."""

    candidate = _evidence()["candidate"]
    candidate["retained_observation"] = {
        "version": retained.BINDING_VERSION,
        "evidence": "checkpoint.json",
        "evidence_sha256": "e" * 64,
        "first_retained_sample_at": "2026-08-30T15:09:35.034000Z",
        "minimum_observation_seconds": retained.MINIMUM_OBSERVATION_SECONDS,
        "eligible_at": "2026-09-13T15:09:35.033999Z",
    }

    with pytest.raises(retained.RetainedObservationError, match="exactly 14 days"):
        retained.parse_retained_observation(candidate)


def test_restart_reset_invalidates_previous_window_and_clears_post_window_evidence(
    tmp_path: Path,
) -> None:
    """A verified web restart forces a new real retained sample before cutover."""

    checkpoint = _write_checkpoint(tmp_path)
    artifact = tmp_path / "reset.json"
    artifact.write_text(json.dumps(_reset_artifact(checkpoint)), encoding="utf-8")

    prepared = retained.bind_observation_reset(
        _evidence_with_retained_checkpoint(checkpoint),
        reset_artifact_path=artifact,
        root=tmp_path,
    )

    candidate = prepared["candidate"]
    assert candidate["retained_observation"] is None
    assert candidate["observation_end"] is None
    marker = retained.validate_observation_reset(candidate, root=tmp_path)
    assert retained.utc_text(marker.reset_at) == "2026-09-02T15:38:21.178433Z"
    assert prepared["defects"]["open_p0"] is None
    assert prepared["telemetry"]["tasks"] == []
    assert prepared["rollback"]["production_registry_backup"] is None
    assert prepared["review_snapshot"] == {"evidence": None, "sha256": None}
    assert prepared["approvals"] == {"owner": None, "reviewer": None}


def test_restart_reset_is_idempotent_after_binding(tmp_path: Path) -> None:
    """The same reset artifact can be dry-run or written again after binding."""

    checkpoint = _write_checkpoint(tmp_path)
    artifact = tmp_path / "reset.json"
    artifact.write_text(json.dumps(_reset_artifact(checkpoint)), encoding="utf-8")
    first = retained.bind_observation_reset(
        _evidence_with_retained_checkpoint(checkpoint),
        reset_artifact_path=artifact,
        root=tmp_path,
    )

    second = retained.bind_observation_reset(
        first,
        reset_artifact_path=artifact,
        root=tmp_path,
    )

    assert second == first


def test_restart_reset_rejects_artifact_with_wrong_previous_checkpoint(tmp_path: Path) -> None:
    """A reset cannot silently detach from the retained source it invalidates."""

    checkpoint = _write_checkpoint(tmp_path)
    artifact_payload = _reset_artifact(checkpoint)
    artifact_payload["previous_observation"][
        "first_retained_sample_at"
    ] = "2026-08-30T15:09:35.033999Z"
    artifact = tmp_path / "reset.json"
    artifact.write_text(json.dumps(artifact_payload), encoding="utf-8")

    with pytest.raises(retained.RetainedObservationError, match="previous checkpoint"):
        retained.bind_observation_reset(
            _evidence_with_retained_checkpoint(checkpoint),
            reset_artifact_path=artifact,
            root=tmp_path,
        )


def test_retained_sample_before_reset_marker_is_rejected(tmp_path: Path) -> None:
    """A stale retained projection cannot be restored beside a reset marker."""

    checkpoint = _write_checkpoint(tmp_path)
    artifact = tmp_path / "reset.json"
    artifact.write_text(json.dumps(_reset_artifact(checkpoint)), encoding="utf-8")
    prepared = retained.bind_observation_reset(
        _evidence_with_retained_checkpoint(checkpoint),
        reset_artifact_path=artifact,
        root=tmp_path,
    )
    prepared["candidate"]["retained_observation"] = prepared["candidate"]["observation_reset"][
        "previous_retained_observation"
    ]

    with pytest.raises(retained.RetainedObservationError, match="predates"):
        retained.parse_retained_observation(prepared["candidate"])
