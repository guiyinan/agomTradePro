#!/usr/bin/env python3
"""Plan and optionally reserve an isolated local S6 release rehearsal attempt."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import stat
import sys
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import TypedDict, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_candidate_source_module = importlib.import_module("scripts.prepare_s6_candidate_source_snapshot")
CandidateSourceSnapshotError = _candidate_source_module.CandidateSourceSnapshotError
create_candidate_source_snapshot = cast(
    Callable[..., object],
    _candidate_source_module.create_candidate_source_snapshot,
)

_CANDIDATE_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_ATTEMPT_ID_RE = re.compile(
    r"(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\Z"
)
_PLAN_SCHEMA = "release.s6-attempt-plan.v2"
_READ_ONLY_MODE = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH


class AttemptPlan(TypedDict):
    """Non-secret, deterministic resource names and paths for one S6 attempt."""

    schema: str
    candidate_sha: str
    attempt_id: str
    namespace: str
    root: str
    evidence_dir: str
    network: str
    postgres_container: str
    redis_container: str
    postgres_volume: str
    database: str
    provider_settings_export_path: str
    provider_identities_export_path: str
    candidate_source_snapshot_path: str
    candidate_source_receipt_path: str


class AttemptPlanError(ValueError):
    """An attempt-plan failure with a stable machine-readable error code."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _normalize_attempt_id(attempt_id: str | None) -> str:
    if attempt_id is None:
        return uuid.uuid4().hex
    if _ATTEMPT_ID_RE.fullmatch(attempt_id) is None:
        raise AttemptPlanError("S6_ATTEMPT_ID_INVALID")
    try:
        return uuid.UUID(attempt_id).hex
    except ValueError as exc:
        raise AttemptPlanError("S6_ATTEMPT_ID_INVALID") from exc


def build_attempt_plan(
    *,
    candidate_sha: str,
    attempts_dir: Path,
    attempt_id: str | None = None,
) -> AttemptPlan:
    """Build a deterministic local resource plan without creating any files."""
    if _CANDIDATE_SHA_RE.fullmatch(candidate_sha) is None:
        raise AttemptPlanError("S6_CANDIDATE_SHA_INVALID")

    normalized_attempt_id = _normalize_attempt_id(attempt_id)
    identity_digest = hashlib.sha256(
        f"{candidate_sha}:{normalized_attempt_id}".encode("ascii")
    ).hexdigest()
    resource_key = identity_digest[:32]
    namespace = f"agom-s6-{resource_key}"
    root_name = f"s6-{candidate_sha[:10]}-{normalized_attempt_id}"
    root = Path(os.path.abspath(os.fspath(attempts_dir))) / root_name
    export_root = PurePosixPath("/tmp") / "agomtradepro-s6" / namespace

    return {
        "schema": _PLAN_SCHEMA,
        "candidate_sha": candidate_sha,
        "attempt_id": normalized_attempt_id,
        "namespace": namespace,
        "root": str(root),
        "evidence_dir": str(root / "evidence"),
        "network": f"agom-s6-network-{resource_key}",
        "postgres_container": f"agom-s6-postgres-{resource_key}",
        "redis_container": f"agom-s6-redis-{resource_key}",
        "postgres_volume": f"agom-s6-postgres-data-{resource_key}",
        "database": f"agom_release_rehearsal_{resource_key}",
        "provider_settings_export_path": str(export_root / "provider-settings.json"),
        "provider_identities_export_path": str(export_root / "provider-identities.json"),
        "candidate_source_snapshot_path": str(root / "candidate-source"),
        "candidate_source_receipt_path": str(root / "candidate-source-receipt.json"),
    }


def _canonical_plan(plan: AttemptPlan) -> tuple[AttemptPlan, bytes]:
    """Rebuild a plan from its identity and reject edited or malformed fields."""
    try:
        root = Path(plan["root"])
        expected = build_attempt_plan(
            candidate_sha=plan["candidate_sha"],
            attempt_id=plan["attempt_id"],
            attempts_dir=root.parent,
        )
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise AttemptPlanError("S6_ATTEMPT_PLAN_INVALID") from exc
    if expected != plan:
        raise AttemptPlanError("S6_ATTEMPT_PLAN_INVALID")
    raw = (json.dumps(expected, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )
    return expected, raw


def _check_path_safety(root: Path) -> None:
    """Reject symlinks and non-directory ancestors along the planned root path."""
    for path in (root, *root.parents):
        if path.is_symlink():
            raise AttemptPlanError("S6_ATTEMPT_ROOT_SYMLINK")
        if path.exists() and not path.is_dir():
            raise AttemptPlanError("S6_ATTEMPT_PARENT_INVALID")


def _plan_file_is_read_only(path: Path) -> bool:
    return stat.S_IMODE(path.stat().st_mode) & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0


def reserve_attempt(plan: AttemptPlan) -> Path:
    """Atomically claim the attempt root and publish its immutable plan file."""
    canonical, raw = _canonical_plan(plan)
    root = Path(canonical["root"])
    _check_path_safety(root)
    try:
        root.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AttemptPlanError("S6_ATTEMPT_PARENT_INVALID") from exc
    _check_path_safety(root)

    try:
        root.mkdir(exist_ok=False)
    except FileExistsError as exc:
        if root.is_symlink():
            raise AttemptPlanError("S6_ATTEMPT_ROOT_SYMLINK") from exc
        raise AttemptPlanError("S6_ATTEMPT_ROOT_EXISTS") from exc
    except OSError as exc:
        raise AttemptPlanError("S6_ATTEMPT_RESERVE_FAILED") from exc

    plan_file = root / "attempt-plan.json"
    temporary_file = root / f".attempt-plan-{uuid.uuid4().hex}.tmp"
    try:
        with temporary_file.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary_file, plan_file)
        temporary_file.unlink()
        plan_file.chmod(_READ_ONLY_MODE)
        if not _plan_file_is_read_only(plan_file):
            raise AttemptPlanError("S6_ATTEMPT_PLAN_NOT_READ_ONLY")
    except AttemptPlanError:
        raise
    except OSError as exc:
        raise AttemptPlanError("S6_ATTEMPT_RESERVE_FAILED") from exc
    return plan_file


def reserve_prepared_attempt(
    plan: AttemptPlan,
    *,
    workspace: Path,
    container_gid: int,
) -> Path:
    """Reserve a fresh attempt and atomically bind its exact candidate source snapshot."""
    plan_file = reserve_attempt(plan)
    create_candidate_source_snapshot(
        workspace=workspace,
        candidate_sha=plan["candidate_sha"],
        destination=Path(plan["candidate_source_snapshot_path"]),
        receipt_path=Path(plan["candidate_source_receipt_path"]),
        container_gid=container_gid,
    )
    return plan_file


def resume_attempt(plan: AttemptPlan) -> Path:
    """Resume only when the reserved plan is byte-identical and remains read-only."""
    canonical, raw = _canonical_plan(plan)
    root = Path(canonical["root"])
    _check_path_safety(root)
    if root.is_symlink():
        raise AttemptPlanError("S6_ATTEMPT_ROOT_SYMLINK")
    if not root.exists():
        raise AttemptPlanError("S6_ATTEMPT_RESUME_NOT_FOUND")
    if not root.is_dir():
        raise AttemptPlanError("S6_ATTEMPT_ROOT_INVALID")

    plan_file = root / "attempt-plan.json"
    if plan_file.is_symlink():
        raise AttemptPlanError("S6_ATTEMPT_PLAN_SYMLINK")
    if not plan_file.is_file():
        raise AttemptPlanError("S6_ATTEMPT_RESUME_MISMATCH")
    try:
        existing = plan_file.read_bytes()
        read_only = _plan_file_is_read_only(plan_file)
    except OSError as exc:
        raise AttemptPlanError("S6_ATTEMPT_RESUME_MISMATCH") from exc
    if existing != raw or not read_only:
        raise AttemptPlanError("S6_ATTEMPT_RESUME_MISMATCH")
    return plan_file


def main(argv: Sequence[str] | None = None) -> int:
    """Print a plan, or reserve/resume its immutable local attempt directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--attempt-id")
    parser.add_argument("--attempts-dir", type=Path, default=Path("artifacts/s6-attempts"))
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--container-gid", type=int)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--reserve", action="store_true")
    mode.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.resume and args.attempt_id is None:
            raise AttemptPlanError("S6_ATTEMPT_RESUME_ID_REQUIRED")
        plan = build_attempt_plan(
            candidate_sha=args.candidate_sha,
            attempt_id=args.attempt_id,
            attempts_dir=args.attempts_dir,
        )
        plan_file: Path | None = None
        if args.reserve:
            if args.workspace is None or args.container_gid is None:
                raise AttemptPlanError("S6_ATTEMPT_SOURCE_SNAPSHOT_REQUIRED")
            plan_file = reserve_prepared_attempt(
                plan,
                workspace=args.workspace,
                container_gid=args.container_gid,
            )
        elif args.resume:
            plan_file = resume_attempt(plan)
        result: dict[str, object] = {"outcome": "success", "plan": plan}
        if plan_file is not None:
            result["plan_file"] = str(plan_file)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except AttemptPlanError as exc:
        print(
            json.dumps({"outcome": "failed", "error": exc.error_code}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    except CandidateSourceSnapshotError as exc:
        print(
            json.dumps({"outcome": "failed", "error": exc.error_code}, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
