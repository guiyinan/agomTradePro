"""Unit contracts for exact retained-monitoring observation binding."""

from __future__ import annotations

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
