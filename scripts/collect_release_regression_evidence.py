"""Collect official GitHub PostgreSQL regression evidence for one candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn, cast

if TYPE_CHECKING:
    from scripts import validate_release_rehearsal as validator
elif __package__:
    from . import validate_release_rehearsal as validator
else:
    import validate_release_rehearsal as validator

REPORT_KIND = "candidate_regression_evidence"
REPORT_FILENAME = "candidate-regression-evidence.json"
BLOCKED_FILENAME = "collection-blocked.json"
PENDING_GATES = (
    "real_response_unit_replay",
    "full_universe_capacity",
    "isolated_write_rehearsal",
)
ARTIFACTS_ENDPOINT = "https://api.github.com/repos/{repository}/actions/runs/{run_id}/artifacts"


def _fail(code: str) -> NoReturn:
    """Raise a stable validator error without exposing transport details."""
    raise validator.RehearsalValidationError(code)


def _sha256(data: bytes) -> str:
    """Return the lowercase SHA-256 digest for exact artifact bytes."""
    return hashlib.sha256(data).hexdigest()


def _parse_inputs(
    *,
    candidate_sha: str,
    target_trade_date: str,
    universe_sha256: str,
    max_age_hours: float,
) -> tuple[str, timedelta]:
    """Validate bounded release identity and freshness inputs."""
    if validator.COMMIT_PATTERN.fullmatch(candidate_sha) is None:
        _fail("REHEARSAL_CANDIDATE_INVALID")
    try:
        parsed_date = date.fromisoformat(target_trade_date)
    except ValueError:
        _fail("REHEARSAL_TARGET_DATE_INVALID")
    if parsed_date.isoformat() != target_trade_date:
        _fail("REHEARSAL_TARGET_DATE_INVALID")
    if validator.SHA256_PATTERN.fullmatch(universe_sha256) is None:
        _fail("REHEARSAL_UNIVERSE_INVALID")
    if isinstance(max_age_hours, bool) or not math.isfinite(max_age_hours) or max_age_hours <= 0:
        _fail("REHEARSAL_MAX_AGE_INVALID")
    try:
        max_age = timedelta(hours=max_age_hours)
    except OverflowError:
        _fail("REHEARSAL_MAX_AGE_INVALID")
    return parsed_date.isoformat(), max_age


def _read_provider_identities(path: Path) -> tuple[list[dict[str, object]], str]:
    """Load sanitized provider identities as association context only."""
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _fail("REHEARSAL_PROVIDER_IDENTITY_INPUT_INVALID")
    digest = validator._validate_provider_identities(payload)
    if not isinstance(payload, list):
        _fail("REHEARSAL_PROVIDER_IDENTITY_INPUT_INVALID")
    identities: list[dict[str, object]] = []
    for item in cast(list[object], payload):
        if not isinstance(item, dict):
            _fail("REHEARSAL_PROVIDER_IDENTITY_INPUT_INVALID")
        identity = cast(dict[str, object], item)
        identities.append(
            {
                "endpoint_id": identity["endpoint_id"],
                "provider_id": identity["provider_id"],
                "role": identity["role"],
                "source": identity["source"],
                "version": identity["version"],
            }
        )
    return identities, digest


def _safe_text(value: object) -> str | None:
    """Return a nonempty string from an external JSON boundary."""
    return value if isinstance(value, str) and value.strip() else None


def _run_summary(run: dict[str, object]) -> dict[str, object]:
    """Keep only non-secret workflow identity fields from the official response."""
    repository_value = run.get("repository")
    repository: dict[str, object] = {}
    if isinstance(repository_value, dict):
        raw_repository = cast(dict[str, object], repository_value)
        repository["full_name"] = _safe_text(raw_repository.get("full_name"))
    run_id = run.get("id")
    return {
        "id": run_id if isinstance(run_id, int) and not isinstance(run_id, bool) else None,
        "repository": repository,
        "head_sha": _safe_text(run.get("head_sha")),
        "workflow_name": _safe_text(run.get("name")),
        "status": _safe_text(run.get("status")),
        "conclusion": _safe_text(run.get("conclusion")),
        "updated_at": _safe_text(run.get("updated_at")),
    }


def _artifact_summary(repository: str, run_id: int, candidate_sha: str) -> dict[str, object]:
    """Extract safe artifact identity metadata after shared artifact validation."""
    listing = validator._load_github_json(
        ARTIFACTS_ENDPOINT.format(repository=repository, run_id=run_id)
    )
    artifacts = listing.get("artifacts")
    if not isinstance(artifacts, list):
        _fail("REHEARSAL_GITHUB_ARTIFACT_INVALID")
    matches = [
        cast(dict[str, object], item)
        for item in cast(list[object], artifacts)
        if isinstance(item, dict)
        and item.get("name") == validator.REQUIRED_GITHUB_ARTIFACT
        and item.get("expired") is False
    ]
    if len(matches) != 1:
        _fail("REHEARSAL_GITHUB_ARTIFACT_MISSING")
    artifact = matches[0]
    workflow_run_value = artifact.get("workflow_run")
    if not isinstance(workflow_run_value, dict):
        _fail("REHEARSAL_GITHUB_ARTIFACT_CANDIDATE_MISMATCH")
    workflow_run = cast(dict[str, object], workflow_run_value)
    if workflow_run.get("id") != run_id or workflow_run.get("head_sha") != candidate_sha:
        _fail("REHEARSAL_GITHUB_ARTIFACT_CANDIDATE_MISMATCH")
    artifact_id = artifact.get("id")
    digest = artifact.get("digest")
    size = artifact.get("size_in_bytes")
    if (
        isinstance(artifact_id, bool)
        or not isinstance(artifact_id, int)
        or artifact_id <= 0
        or not isinstance(digest, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size < 0
    ):
        _fail("REHEARSAL_GITHUB_ARTIFACT_INVALID")
    return {
        "id": artifact_id,
        "name": validator.REQUIRED_GITHUB_ARTIFACT,
        "digest": digest,
        "expired": False,
        "size_in_bytes": size,
        "created_at": _safe_text(artifact.get("created_at")),
        "expires_at": _safe_text(artifact.get("expires_at")),
        "workflow_run": {"id": run_id, "head_sha": candidate_sha},
    }


def _write_exclusive(path: Path, data: bytes) -> None:
    """Create a new file without replacing an existing path."""
    with path.open("xb") as stream:
        stream.write(data)


def _write_blocked(directory: Path, code: str) -> None:
    """Leave only a safe blocked diagnostic after failed collection."""
    payload = {
        "schema": "release.candidate-regression-collection-blocked.v1",
        "kind": REPORT_KIND,
        "outcome": "blocked",
        "release_ready": False,
        "error_code": code,
    }
    try:
        _write_exclusive(
            directory / BLOCKED_FILENAME,
            (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        )
    except OSError:
        return


def _error_code(exc: Exception) -> str:
    """Map an exception to an allowlisted diagnostic code."""
    if isinstance(exc, validator.RehearsalValidationError):
        return exc.code
    if isinstance(exc, FileExistsError):
        return "REHEARSAL_OUTPUT_DIRECTORY_EXISTS"
    if isinstance(exc, OSError):
        return "REHEARSAL_OUTPUT_IO_FAILED"
    return "RELEASE_REGRESSION_COLLECTION_FAILED"


def collect_candidate_regression_evidence(
    *,
    candidate_sha: str,
    target_trade_date: str,
    universe_sha256: str,
    provider_identities_json: Path,
    github_repository: str,
    github_run_id: int,
    max_age_hours: float,
    output_dir: Path,
) -> Path:
    """Collect official PostgreSQL CI artifacts and publish only validated evidence.

    The validator is authoritative for the fixed required test set, run status,
    freshness, artifact digest, and exact JUnit bytes. This collector records
    association context only and does not verify any provider. Since the shared
    validator exposes no verified snapshot object, a successful collection
    currently makes 3 run JSON reads, 4 artifact-list reads, and 2 ZIP downloads
    to compare before/after identities and let the validator independently
    reverify exact official bytes.
    """
    target_date, max_age = _parse_inputs(
        candidate_sha=candidate_sha,
        target_trade_date=target_trade_date,
        universe_sha256=universe_sha256,
        max_age_hours=max_age_hours,
    )
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", github_repository) is None:
        _fail("REHEARSAL_GITHUB_REPOSITORY_INVALID")
    if isinstance(github_run_id, bool) or github_run_id <= 0:
        _fail("REHEARSAL_GITHUB_RUN_INVALID")
    identities, provider_digest = _read_provider_identities(provider_identities_json)
    if output_dir.exists():
        _fail("REHEARSAL_OUTPUT_DIRECTORY_EXISTS")
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        _fail("REHEARSAL_OUTPUT_DIRECTORY_EXISTS")
    except OSError:
        _fail("REHEARSAL_OUTPUT_IO_FAILED")

    report_path = output_dir / REPORT_FILENAME
    report_opened = False
    try:
        started_at = datetime.now(UTC)
        run_before = _run_summary(
            cast(dict[str, object], validator._load_github_run(github_repository, github_run_id))
        )
        artifact_before = _artifact_summary(github_repository, github_run_id, candidate_sha)

        # This call validates the official run-bound ZIP and returns exact JUnit bytes.
        # The shared final regression validator deliberately re-reads official API
        # evidence; its interfaces expose neither a cache nor verified metadata.
        junit_files = validator._load_github_junit_artifacts(
            github_repository, github_run_id, candidate_sha
        )

        local_artifacts: list[dict[str, str]] = []
        for name in sorted(validator.REQUIRED_JUNIT_FILES):
            content = junit_files.get(name)
            if not isinstance(content, bytes):
                _fail("REHEARSAL_GITHUB_ARTIFACT_INCOMPLETE")
            _write_exclusive(output_dir / name, content)
            local_artifacts.append({"path": name, "sha256": _sha256(content)})

        finished_at = datetime.now(UTC)
        report: dict[str, Any] = {
            "schema": validator.REQUIRED_REPORT_SCHEMAS[REPORT_KIND],
            "kind": REPORT_KIND,
            "candidate_sha": candidate_sha,
            "target_trade_date": target_date,
            "universe_sha256": universe_sha256,
            "provider_identities": identities,
            "provider_identities_sha256": provider_digest,
            "provider_identity_scope": "association_only_not_provider_validation",
            "evidence_mode": validator.REQUIRED_EVIDENCE_MODES[REPORT_KIND],
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "outcome": "success",
            "release_ready": False,
            "remaining_release_gates": list(PENDING_GATES),
            "github_repository": github_repository,
            "github_run_id": github_run_id,
            "github_source": {
                "run": run_before,
                "artifact": artifact_before,
                "official_junit_sha256": {item["path"]: item["sha256"] for item in local_artifacts},
                "source_snapshot_stable": False,
            },
            "required_tests": list(validator.REQUIRED_POSTGRESQL_TESTS),
            "junit_artifacts": local_artifacts,
            "postgresql_vendor_verified": True,
            "selected_by_candidate": True,
            "max_age_hours": max_age_hours,
        }
        validator._validate_common_report(
            report=report,
            kind=REPORT_KIND,
            expected_candidate=candidate_sha,
            expected_image_id="",
            expected_date=target_date,
            expected_universe=universe_sha256,
            expected_provider_digest=provider_digest,
            now=finished_at,
            max_age=max_age,
        )
        validator._validate_regression(
            report,
            output_dir,
            candidate_sha,
            github_repository,
            github_run_id,
            finished_at,
            max_age,
        )
        run_after = _run_summary(
            cast(dict[str, object], validator._load_github_run(github_repository, github_run_id))
        )
        artifact_after = _artifact_summary(github_repository, github_run_id, candidate_sha)
        if run_before != run_after or artifact_before != artifact_after:
            _fail("REHEARSAL_GITHUB_EVIDENCE_DRIFT")
        report["github_source"] = {
            **cast(dict[str, object], report["github_source"]),
            "source_snapshot_stable": True,
        }
        finished_at = datetime.now(UTC)
        report["finished_at"] = finished_at.isoformat()
        validator._validate_common_report(
            report=report,
            kind=REPORT_KIND,
            expected_candidate=candidate_sha,
            expected_image_id="",
            expected_date=target_date,
            expected_universe=universe_sha256,
            expected_provider_digest=provider_digest,
            now=finished_at,
            max_age=max_age,
        )
        encoded = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode("utf-8")
        with report_path.open("xb") as stream:
            report_opened = True
            stream.write(encoded)
        return report_path
    except Exception as exc:
        if report_opened:
            try:
                report_path.unlink(missing_ok=True)
            except OSError:
                pass
        _write_blocked(output_dir, _error_code(exc))
        raise


def _build_parser() -> argparse.ArgumentParser:
    """Build explicit CLI inputs for one candidate and one official CI run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--universe-sha256", required=True)
    parser.add_argument("--provider-identities-json", required=True, type=Path)
    parser.add_argument("--github-repository", required=True)
    parser.add_argument("--github-run-id", required=True, type=int)
    parser.add_argument("--max-age-hours", required=True, type=float)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run collection and return a process-safe exit status."""
    args = _build_parser().parse_args(argv)
    try:
        report_path = collect_candidate_regression_evidence(
            candidate_sha=args.candidate_sha,
            target_trade_date=args.target_date,
            universe_sha256=args.universe_sha256,
            provider_identities_json=args.provider_identities_json,
            github_repository=args.github_repository,
            github_run_id=args.github_run_id,
            max_age_hours=args.max_age_hours,
            output_dir=args.output_dir,
        )
    except Exception as exc:
        print(f"blocked: {_error_code(exc)}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "outcome": "success",
                "scope": REPORT_KIND,
                "release_ready": False,
                "report": str(report_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
