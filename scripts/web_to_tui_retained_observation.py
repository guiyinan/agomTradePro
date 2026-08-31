#!/usr/bin/env python
"""Bind an exact retained-monitoring start to Web-to-TUI cutover evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"
BINDING_VERSION = "web-to-tui-retained-observation-binding.v1"
CHECKPOINT_VERSION = "tui02-production-retained-observation-checkpoint.v1"
MINIMUM_OBSERVATION_SECONDS = 14 * 24 * 60 * 60
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class RetainedObservationError(RuntimeError):
    """Raised when retained monitoring cannot safely start the M5 time gate."""


@dataclass(frozen=True)
class RetainedObservationBinding:
    """Validated exact start and eligibility timestamps for one candidate."""

    evidence: str
    evidence_sha256: str
    first_retained_sample_at: datetime
    eligible_at: datetime
    minimum_observation_seconds: int


def _mapping(value: object) -> dict[str, Any]:
    """Narrow one dynamic JSON value to a mapping."""

    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def parse_utc_timestamp(value: object, *, field: str) -> datetime:
    """Parse one required timezone-aware UTC timestamp."""

    if not isinstance(value, str) or not value.strip():
        raise RetainedObservationError(f"Missing UTC timestamp: {field}")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise RetainedObservationError(f"Invalid UTC timestamp: {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise RetainedObservationError(f"{field} must include an explicit UTC offset")
    return parsed.astimezone(UTC)


def utc_text(value: datetime) -> str:
    """Serialize one aware timestamp as canonical UTC text."""

    if value.tzinfo is None:
        raise RetainedObservationError("Cannot serialize a naive retained-observation timestamp")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_retained_observation(candidate: dict[str, Any]) -> RetainedObservationBinding:
    """Validate the exact retained-observation projection on a candidate."""

    raw = _mapping(candidate.get("retained_observation"))
    if raw.get("version") != BINDING_VERSION:
        raise RetainedObservationError("Candidate lacks a supported retained-observation binding")
    evidence = str(raw.get("evidence") or "").strip()
    evidence_sha256 = str(raw.get("evidence_sha256") or "").strip()
    if not evidence or Path(evidence).is_absolute():
        raise RetainedObservationError("Retained-observation evidence must be repository-relative")
    if not SHA256_PATTERN.fullmatch(evidence_sha256):
        raise RetainedObservationError("Retained-observation evidence SHA-256 is invalid")
    minimum_seconds = raw.get("minimum_observation_seconds")
    if (
        isinstance(minimum_seconds, bool)
        or not isinstance(minimum_seconds, int)
        or minimum_seconds != MINIMUM_OBSERVATION_SECONDS
    ):
        raise RetainedObservationError(
            f"minimum_observation_seconds must equal {MINIMUM_OBSERVATION_SECONDS}"
        )
    first_sample = parse_utc_timestamp(
        raw.get("first_retained_sample_at"),
        field="candidate.retained_observation.first_retained_sample_at",
    )
    eligible_at = parse_utc_timestamp(
        raw.get("eligible_at"),
        field="candidate.retained_observation.eligible_at",
    )
    if eligible_at != first_sample + timedelta(seconds=minimum_seconds):
        raise RetainedObservationError(
            "Retained-observation eligibility must be exactly 14 days after the first sample"
        )
    return RetainedObservationBinding(
        evidence=evidence,
        evidence_sha256=evidence_sha256,
        first_retained_sample_at=first_sample,
        eligible_at=eligible_at,
        minimum_observation_seconds=minimum_seconds,
    )


def _repository_evidence_path(value: str, *, root: Path) -> Path:
    """Resolve one existing repository evidence path without traversal."""

    relative = Path(value)
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if (
        relative.is_absolute()
        or not resolved.is_relative_to(resolved_root)
        or not resolved.is_file()
    ):
        raise RetainedObservationError("Retained-observation evidence path is unavailable")
    return resolved


def validate_retained_observation_checkpoint(
    candidate: dict[str, Any],
    *,
    root: Path = ROOT,
) -> RetainedObservationBinding:
    """Validate the hash-bound production checkpoint behind one binding."""

    binding = parse_retained_observation(candidate)
    path = _repository_evidence_path(binding.evidence, root=root)
    if hashlib.sha256(path.read_bytes()).hexdigest() != binding.evidence_sha256:
        raise RetainedObservationError("Retained-observation checkpoint SHA-256 mismatch")
    payload_value = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload_value, dict):
        raise RetainedObservationError("Retained-observation checkpoint must be a JSON object")
    payload = cast(dict[str, Any], payload_value)
    if payload.get("version") != CHECKPOINT_VERSION:
        raise RetainedObservationError("Unsupported retained-observation checkpoint version")
    if payload.get("environment") != "production" or payload.get("collection_mode") != "read_only":
        raise RetainedObservationError(
            "Retained-observation checkpoint is not production read-only"
        )

    checkpoint_candidate = _mapping(payload.get("candidate"))
    expected = _mapping(checkpoint_candidate.get("expected"))
    observed = _mapping(checkpoint_candidate.get("observed"))
    deployment = _mapping(candidate.get("deployment_preflight"))
    stable_version = str(candidate.get("stable_version") or "").strip()
    candidate_commit = str(candidate.get("candidate_commit") or "").strip()
    image_id = str(deployment.get("image_id") or "").strip()
    identity_ok = bool(
        stable_version
        and candidate_commit
        and image_id
        and expected.get("release_id") == stable_version
        and observed.get("release_id") == stable_version
        and expected.get("commit") == candidate_commit
        and observed.get("commit") == candidate_commit
        and expected.get("image_id") == image_id
        and observed.get("image_id") == image_id
        and checkpoint_candidate.get("candidate_drift") is False
    )
    if not identity_ok:
        raise RetainedObservationError("Checkpoint identity does not match the cutover candidate")

    observation = _mapping(payload.get("observation"))
    if (
        parse_utc_timestamp(
            observation.get("first_retained_raw_sample_at"),
            field="checkpoint.observation.first_retained_raw_sample_at",
        )
        != binding.first_retained_sample_at
        or parse_utc_timestamp(
            observation.get("earliest_full_14d_telemetry_at"),
            field="checkpoint.observation.earliest_full_14d_telemetry_at",
        )
        != binding.eligible_at
        or observation.get("minimum_observation_seconds") != binding.minimum_observation_seconds
        or observation.get("historical_backfill_used") is not False
        or observation.get("synthetic_zero_used") is not False
        or observation.get("window_reset_required") is not False
    ):
        raise RetainedObservationError(
            "Checkpoint observation window is not an exact real-sample binding"
        )

    gate = _mapping(payload.get("gate"))
    required_true = (
        "candidate_unchanged",
        "target_ok",
        "rules_ok",
        "retention_ok",
        "storage_ok",
        "protected_query_ok",
    )
    if (
        any(gate.get(key) is not True for key in required_true)
        or gate.get("prometheus_unexpected_restart") is not False
        or gate.get("window_reset_required") is not False
        or gate.get("tui02_final_authorized") is not False
    ):
        raise RetainedObservationError(
            "Checkpoint monitoring gates do not support the retained window"
        )
    side_effects = _mapping(payload.get("side_effects"))
    expected_side_effects = {
        "remote_write",
        "deployment",
        "restart",
        "configuration_change",
        "backup",
        "load_test",
        "business_request",
    }
    if set(side_effects) != expected_side_effects or any(
        side_effects.get(key) is not False for key in expected_side_effects
    ):
        raise RetainedObservationError("Checkpoint is not a side-effect-free read-only observation")
    return binding


def _projection_from_checkpoint(
    checkpoint: dict[str, Any],
    *,
    evidence: str,
    evidence_sha256: str,
) -> dict[str, Any]:
    """Build a canonical retained-observation projection from one checkpoint."""

    observation = _mapping(checkpoint.get("observation"))
    first_sample = parse_utc_timestamp(
        observation.get("first_retained_raw_sample_at"),
        field="checkpoint.observation.first_retained_raw_sample_at",
    )
    minimum_seconds = observation.get("minimum_observation_seconds")
    if minimum_seconds != MINIMUM_OBSERVATION_SECONDS:
        raise RetainedObservationError("Checkpoint does not require the exact 14-day window")
    eligible_at = first_sample + timedelta(seconds=MINIMUM_OBSERVATION_SECONDS)
    return {
        "version": BINDING_VERSION,
        "evidence": evidence,
        "evidence_sha256": evidence_sha256,
        "first_retained_sample_at": utc_text(first_sample),
        "minimum_observation_seconds": MINIMUM_OBSERVATION_SECONDS,
        "eligible_at": utc_text(eligible_at),
    }


def _clear_post_window_evidence(payload: dict[str, Any]) -> None:
    """Clear only evidence that becomes stale when the retained window restarts."""

    payload["defects"] = {
        "candidate_commit": None,
        "candidate_version": None,
        "evidence": None,
        "new_p0": None,
        "new_p1": None,
        "open_p0": None,
        "open_p1": None,
        "queried_at": None,
        "query_filter": None,
        "query_scope": None,
        "snapshot_sha256": None,
        "source_sha256": None,
        "window_end": None,
        "window_start": None,
    }
    payload["telemetry"] = {
        "collected_at": None,
        "environment": None,
        "evidence": None,
        "snapshot_sha256": None,
        "tasks": [],
        "window_end": None,
        "window_start": None,
    }
    rollback = _mapping(payload.get("rollback"))
    rollback["production_registry_backup"] = None
    payload["rollback"] = rollback
    payload["review_snapshot"] = {"evidence": None, "sha256": None}
    payload["approvals"] = {"owner": None, "reviewer": None}


def bind_retained_observation(
    evidence: dict[str, Any],
    *,
    checkpoint_path: Path,
    replace: bool,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Return cutover evidence bound to one validated retained checkpoint."""

    resolved = checkpoint_path.resolve()
    resolved_root = root.resolve()
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise RetainedObservationError("Checkpoint must be an existing repository file")
    relative = resolved.relative_to(resolved_root).as_posix()
    checkpoint_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
    checkpoint_value = cast(Any, json.loads(resolved.read_text(encoding="utf-8")))
    if not isinstance(checkpoint_value, dict):
        raise RetainedObservationError("Checkpoint must be a JSON object")
    checkpoint = cast(dict[str, Any], checkpoint_value)
    prepared = copy.deepcopy(evidence)
    candidate = _mapping(prepared.get("candidate"))
    projection = _projection_from_checkpoint(
        checkpoint,
        evidence=relative,
        evidence_sha256=checkpoint_sha256,
    )
    current = candidate.get("retained_observation")
    if current is not None and current != projection and not replace:
        raise RetainedObservationError(
            "A different retained-observation binding exists; use --replace to reset post-window evidence"
        )
    changed = current != projection
    candidate["retained_observation"] = projection
    candidate["observation_end"] = (
        parse_utc_timestamp(
            projection["eligible_at"], field="candidate.retained_observation.eligible_at"
        )
        .date()
        .isoformat()
    )
    prepared["candidate"] = candidate
    validate_retained_observation_checkpoint(candidate, root=root)
    if changed:
        _clear_post_window_evidence(prepared)
    return prepared


def _load_object(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk."""

    value = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(value, dict):
        raise RetainedObservationError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], value)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Atomically replace one JSON evidence file."""

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Run the retained-observation binding CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--write-evidence", action="store_true")
    args = parser.parse_args()
    try:
        evidence_path = args.evidence.resolve()
        prepared = bind_retained_observation(
            _load_object(evidence_path),
            checkpoint_path=args.checkpoint.resolve(),
            replace=args.replace,
        )
        if args.write_evidence:
            _write_json_atomic(evidence_path, prepared)
        binding = parse_retained_observation(_mapping(prepared.get("candidate")))
    except (OSError, ValueError, json.JSONDecodeError, RetainedObservationError) as exc:
        print(f"Web-to-TUI retained observation: FAIL - {exc}")
        return 1
    mode = "WRITTEN" if args.write_evidence else "READY (dry-run)"
    print(
        f"Web-to-TUI retained observation: {mode} - "
        f"first_sample={utc_text(binding.first_retained_sample_at)} "
        f"eligible_at={utc_text(binding.eligible_at)} "
        f"checkpoint_sha256={binding.evidence_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
