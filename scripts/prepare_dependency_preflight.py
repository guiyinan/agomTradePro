"""Prepare and verify a native dependency preflight without editing the checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PIN_COUNT = 134
CONSTRAINT_PIN_COUNT = 132
TWISTED_NAME = "twisted"
TWISTED_EXTRA = "tls"
TWISTED_BASELINE_VERSION = "26.4.0"
TWISTED_CANDIDATE_VERSION = "26.10.0rc1"
DRF_NAME = "djangorestframework"
DRF_BASELINE_VERSION = "3.17.2"
DRF_CANDIDATE_VERSION = "3.18.3"
PIN_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[(?P<extras>[A-Za-z0-9._,-]+)\])?"
    r"==(?P<version>[^\s;]+)(?:\s*;\s*(?P<marker>.+))?$"
)


@dataclass(frozen=True, slots=True)
class LockedPin:
    """One normalized pin parsed from a pip-compile requirements file."""

    name: str
    version: str
    extras: tuple[str, ...]
    marker: str | None


def _canonical_name(name: str) -> str:
    """Normalize a Python distribution name according to PEP 503."""

    return re.sub(r"[-_.]+", "-", name).lower()


def _canonical_extra(extra: str) -> str:
    """Normalize one requirement extra for stable lock comparisons."""

    return re.sub(r"[-_.]+", "-", extra).lower()


def parse_locked_pins(lock_text: str) -> dict[str, LockedPin]:
    """Parse strict, one-pin-per-line pip-compile output without third-party tools."""

    pins: dict[str, LockedPin] = {}
    for line_number, raw_line in enumerate(lock_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"Lock line {line_number} is not a single exact pin")
        name = _canonical_name(match.group("name"))
        if name in pins:
            raise ValueError(f"Lock contains duplicate distribution {name}")
        raw_extras = match.group("extras")
        extras = (
            tuple(sorted(_canonical_extra(value) for value in raw_extras.split(",")))
            if raw_extras
            else ()
        )
        pins[name] = LockedPin(
            name=name,
            version=match.group("version"),
            extras=extras,
            marker=match.group("marker"),
        )
    if not pins:
        raise ValueError("Lock contains no exact pins")
    return pins


def _require_baseline_pins(pins: dict[str, LockedPin]) -> None:
    """Require the exact committed lock shape used by this bounded experiment."""

    if len(pins) != BASELINE_PIN_COUNT:
        raise ValueError(f"Expected {BASELINE_PIN_COUNT} committed pins, found {len(pins)}")
    twisted = pins.get(TWISTED_NAME)
    drf = pins.get(DRF_NAME)
    if twisted is None or twisted.version != TWISTED_BASELINE_VERSION:
        raise ValueError("Committed lock does not contain the expected Twisted baseline")
    if twisted.extras != (TWISTED_EXTRA,):
        raise ValueError("Committed lock does not contain the Twisted TLS extra")
    if drf is None or drf.version != DRF_BASELINE_VERSION or drf.extras:
        raise ValueError("Committed lock does not contain the expected DRF baseline")


def build_constraints(lock_text: str) -> str:
    """Keep every committed pin except the two packages under review as constraints."""

    pins = parse_locked_pins(lock_text)
    _require_baseline_pins(pins)
    lines: list[str] = []
    for raw_line in lock_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN_LINE.fullmatch(line)
        if match is None:
            raise ValueError("Committed lock changed after pin parsing")
        name = _canonical_name(match.group("name"))
        if name not in {TWISTED_NAME, DRF_NAME}:
            lines.append(line)
    if len(lines) != CONSTRAINT_PIN_COUNT:
        raise ValueError(f"Expected {CONSTRAINT_PIN_COUNT} constraints, found {len(lines)}")
    return "\n".join(lines) + "\n"


def build_trial_pyproject(source_text: str) -> str:
    """Change only the exact DRF and Twisted requirements in a temporary pyproject."""

    original = tomllib.loads(source_text)
    project = original.get("project")
    if not isinstance(project, dict):
        raise ValueError("Committed pyproject.toml has no [project] table")
    raw_dependencies = project.get("dependencies")
    if not isinstance(raw_dependencies, list) or not all(
        isinstance(item, str) for item in raw_dependencies
    ):
        raise ValueError("Committed project dependencies are not a string list")
    dependencies = list(raw_dependencies)
    drf_line = '    "djangorestframework",'
    daphne_line = '    "daphne>=4.2.2,<4.3",'
    if source_text.count(drf_line) != 1 or source_text.count(daphne_line) != 1:
        raise ValueError("Committed pyproject dependency anchors are not unique")

    newline = "\r\n" if "\r\n" in source_text else "\n"
    had_final_newline = source_text.endswith(("\n", "\r"))
    lines = [line.rstrip("\r\n") for line in source_text.splitlines(keepends=True)]
    drf_index = next(index for index, line in enumerate(lines) if line == drf_line)
    daphne_index = next(index for index, line in enumerate(lines) if line == daphne_line)
    lines[drf_index] = '    "djangorestframework==3.18.3",'
    lines.insert(daphne_index + 1, '    "Twisted[tls]==26.10.0rc1",')
    candidate_text = newline.join(lines)
    if had_final_newline:
        candidate_text += newline

    candidate = tomllib.loads(candidate_text)
    candidate_project = candidate.get("project")
    candidate_dependencies = (
        candidate_project.get("dependencies") if isinstance(candidate_project, dict) else None
    )
    expected_dependencies = list(dependencies)
    old_drf_index = expected_dependencies.index("djangorestframework")
    expected_dependencies[old_drf_index] = "djangorestframework==3.18.3"
    expected_dependencies.insert(
        expected_dependencies.index("daphne>=4.2.2,<4.3") + 1,
        "Twisted[tls]==26.10.0rc1",
    )
    if candidate_dependencies != expected_dependencies:
        raise ValueError("Temporary pyproject changed dependencies outside the two targets")
    return candidate_text


def verify_resolved_lock(original_text: str, candidate_text: str) -> dict[str, object]:
    """Reject any resolved lock change beyond the two explicitly selected pins."""

    baseline = parse_locked_pins(original_text)
    _require_baseline_pins(baseline)
    candidate = parse_locked_pins(candidate_text)
    if set(candidate) != set(baseline):
        added = sorted(set(candidate) - set(baseline))
        removed = sorted(set(baseline) - set(candidate))
        raise ValueError(f"Resolved package set changed; added={added}, removed={removed}")
    if len(candidate) != BASELINE_PIN_COUNT:
        raise ValueError("Resolved lock does not contain all 134 package pins")

    changed: list[str] = []
    for name, old_pin in baseline.items():
        new_pin = candidate[name]
        if new_pin.marker != old_pin.marker:
            raise ValueError(f"Resolved lock changed a platform marker: {name}")
        if name == TWISTED_NAME:
            if new_pin.version != TWISTED_CANDIDATE_VERSION or new_pin.extras != (TWISTED_EXTRA,):
                raise ValueError("Resolved lock does not pin the requested Twisted TLS release")
            changed.append(name)
        elif name == DRF_NAME:
            if new_pin.version != DRF_CANDIDATE_VERSION or new_pin.extras:
                raise ValueError("Resolved lock does not pin the requested DRF release")
            changed.append(name)
        elif new_pin.version != old_pin.version or new_pin.extras != old_pin.extras:
            raise ValueError(f"Resolved lock changed an unrelated pin: {name}")
    if sorted(changed) != [DRF_NAME, TWISTED_NAME]:
        raise ValueError("Resolved lock did not change exactly the two intended pins")
    return {
        "status": "verified",
        "baseline_pin_count": len(baseline),
        "candidate_pin_count": len(candidate),
        "constraint_pin_count": CONSTRAINT_PIN_COUNT,
        "changed_distributions": sorted(changed),
        "twisted_version": candidate[TWISTED_NAME].version,
        "djangorestframework_version": candidate[DRF_NAME].version,
    }


def verify_audit_report(lock_text: str, report_text: str) -> dict[str, object]:
    """Require the raw audit report to cover every exact lock pin without skips."""

    expected = parse_locked_pins(lock_text)
    if len(expected) != BASELINE_PIN_COUNT:
        raise ValueError("Candidate lock does not contain all 134 package pins")
    parsed: object = json.loads(report_text)
    if not isinstance(parsed, dict) or not all(isinstance(key, str) for key in parsed):
        raise ValueError("pip-audit report is not a string-keyed JSON object")
    report = cast(dict[str, object], parsed)
    if report.get("skipped"):
        raise ValueError("pip-audit reported skipped packages")
    raw_dependencies = report.get("dependencies")
    if not isinstance(raw_dependencies, list):
        raise ValueError("pip-audit report has no dependency list")

    seen: dict[str, str] = {}
    finding_count = 0
    for raw_dependency in raw_dependencies:
        if not isinstance(raw_dependency, dict) or not all(
            isinstance(key, str) for key in raw_dependency
        ):
            raise ValueError("pip-audit dependency record is malformed")
        dependency = cast(dict[str, object], raw_dependency)
        if dependency.get("skip_reason") or dependency.get("skipped"):
            raise ValueError("pip-audit reported a skipped dependency")
        raw_name = dependency.get("name")
        raw_version = dependency.get("version")
        raw_vulnerabilities = dependency.get("vulns")
        if not isinstance(raw_name, str) or not isinstance(raw_version, str):
            raise ValueError("pip-audit dependency record lacks its name or version")
        if not isinstance(raw_vulnerabilities, list):
            raise ValueError("pip-audit dependency record lacks a vulnerability list")
        name = _canonical_name(raw_name)
        if name not in expected:
            raise ValueError(f"pip-audit reported an unexpected distribution: {name}")
        if name in seen:
            raise ValueError(f"pip-audit reported a duplicate distribution: {name}")
        if raw_version != expected[name].version:
            raise ValueError(f"pip-audit version does not match the lock for {name}")
        seen[name] = raw_version
        finding_count += len(raw_vulnerabilities)
    if set(seen) != set(expected):
        missing = sorted(set(expected) - set(seen))
        raise ValueError(f"pip-audit report omitted locked distributions: {missing}")
    return {
        "status": "coverage_verified",
        "locked_pin_count": len(expected),
        "reported_pin_count": len(seen),
        "finding_count": finding_count,
    }


def audit_report_status(report: dict[str, object]) -> int:
    """Return failure when a coverage-verified audit report contains findings."""

    finding_count = report.get("finding_count")
    if not isinstance(finding_count, int) or isinstance(finding_count, bool) or finding_count < 0:
        raise ValueError("Audit coverage result has an invalid finding count")
    return 1 if finding_count else 0


def _sha256(data: bytes) -> str:
    """Return the SHA-256 hex digest for one input blob."""

    return hashlib.sha256(data).hexdigest()


def _read_head_blob(repo_root: Path, commit: str, relative_path: str) -> bytes:
    """Read one source file from the committed tree, never from a dirty checkout."""

    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=repo_root,
        capture_output=True,
        check=False,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not read committed input {relative_path}")
    return result.stdout


def _head_commit(repo_root: Path) -> str:
    """Return and validate the current checkout commit identifier."""

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    commit = result.stdout.strip()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise RuntimeError("Could not identify the checked-out source commit")
    return commit


def _write_json(path: Path, document: dict[str, object]) -> None:
    """Write one deterministic, UTF-8 JSON record inside the runner temp directory."""

    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def prepare_inputs(repo_root: Path, work_dir: Path, expected_commit: str | None) -> None:
    """Stage committed inputs and run the official projection script in runner temp."""

    commit = _head_commit(repo_root)
    if expected_commit is not None and expected_commit != commit:
        raise ValueError("GITHUB_SHA does not match the checked-out HEAD")
    if work_dir.exists():
        raise FileExistsError("Dependency preflight output directory already exists")

    pyproject_bytes = _read_head_blob(repo_root, commit, "pyproject.toml")
    sync_bytes = _read_head_blob(repo_root, commit, "scripts/sync_dependency_projections.py")
    lock_bytes = _read_head_blob(repo_root, commit, "requirements-prod.lock")
    pyproject_text = pyproject_bytes.decode("utf-8")
    lock_text = lock_bytes.decode("utf-8")
    constraints = build_constraints(lock_text)
    candidate_pyproject = build_trial_pyproject(pyproject_text)

    project_dir = work_dir / "candidate-project"
    sync_path = project_dir / "scripts" / "sync_dependency_projections.py"
    sync_path.parent.mkdir(parents=True, exist_ok=True)
    project_dir.joinpath("pyproject.toml").write_text(candidate_pyproject, encoding="utf-8")
    sync_path.write_bytes(sync_bytes)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "requirements-prod.original.lock").write_bytes(lock_bytes)
    (work_dir / "constraints.txt").write_text(constraints, encoding="utf-8")
    (work_dir / "requirements-prod.lock.pending").write_text(
        "No resolved lock yet; pip-compile must succeed before this is accepted.\n",
        encoding="utf-8",
    )

    projection = subprocess.run(
        [sys.executable, str(sync_path)],
        cwd=project_dir,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    (work_dir / "projection-sync.log").write_text(
        projection.stdout + projection.stderr,
        encoding="utf-8",
    )
    if projection.returncode != 0:
        raise RuntimeError("Official dependency projection generation failed")

    projection_bytes = (project_dir / "requirements-prod.txt").read_bytes()
    projection_lines = projection_bytes.decode("utf-8").splitlines()
    for expected in ("djangorestframework==3.18.3", "Twisted[tls]==26.10.0rc1"):
        if expected not in projection_lines:
            raise ValueError("Official projection omitted an exact target requirement")

    metadata: dict[str, object] = {
        "status": "inputs_prepared",
        "source_commit": commit,
        "source_inputs": {
            "pyproject.toml_sha256": _sha256(pyproject_bytes),
            "sync_dependency_projections.py_sha256": _sha256(sync_bytes),
            "requirements-prod.lock_sha256": _sha256(lock_bytes),
        },
        "candidate_inputs": {
            "pyproject.toml_sha256": _sha256(candidate_pyproject.encode("utf-8")),
            "requirements-prod.txt_sha256": _sha256(projection_bytes),
            "constraints.txt_sha256": _sha256(constraints.encode("utf-8")),
        },
        "baseline_pin_count": BASELINE_PIN_COUNT,
        "constraints_pin_count": CONSTRAINT_PIN_COUNT,
        "requested_pins": {
            "twisted[tls]": TWISTED_CANDIDATE_VERSION,
            DRF_NAME: DRF_CANDIDATE_VERSION,
        },
        "projection_command": "python scripts/sync_dependency_projections.py",
    }
    _write_json(work_dir / "dependency-preflight-inputs.json", metadata)


def verify_work_dir(work_dir: Path) -> dict[str, object]:
    """Verify the generated candidate lock and record its hash and exact pin delta."""

    original_text = (work_dir / "requirements-prod.original.lock").read_text(encoding="utf-8")
    lock_path = work_dir / "requirements-prod.lock"
    candidate_text = lock_path.read_text(encoding="utf-8")
    result = verify_resolved_lock(original_text, candidate_text)
    document = dict(result)
    document["candidate_lock_sha256"] = _sha256(lock_path.read_bytes())
    inputs_path = work_dir / "dependency-preflight-inputs.json"
    inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    if not isinstance(inputs, dict):
        raise ValueError("Preparation metadata is malformed")
    document["source_commit"] = inputs.get("source_commit")
    _write_json(work_dir / "resolved-lock-verification.json", document)
    (work_dir / "requirements-prod.lock.sha256").write_text(
        f"{document['candidate_lock_sha256']}  requirements-prod.lock\n",
        encoding="utf-8",
    )
    pending_path = work_dir / "requirements-prod.lock.pending"
    if pending_path.exists():
        pending_path.unlink()
    return document


def verify_audit_work_dir(work_dir: Path) -> dict[str, object]:
    """Verify the audit JSON covers the complete resolved lock and record its hash."""

    lock_path = work_dir / "requirements-prod.lock"
    report_path = work_dir / "pip-audit.json"
    result = verify_audit_report(
        lock_path.read_text(encoding="utf-8"),
        report_path.read_text(encoding="utf-8"),
    )
    document = dict(result)
    document["candidate_lock_sha256"] = _sha256(lock_path.read_bytes())
    document["audit_report_sha256"] = _sha256(report_path.read_bytes())
    _write_json(work_dir / "pip-audit-coverage.json", document)
    return document


def _runner_temp_path(path: Path) -> Path:
    """Require output to stay below GitHub Actions' runner temporary directory."""

    runner_temp = os.environ.get("RUNNER_TEMP")
    if not runner_temp:
        raise ValueError("RUNNER_TEMP is required for dependency preflight output")
    root = Path(runner_temp).resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Dependency preflight output must stay under RUNNER_TEMP") from exc
    if resolved == root:
        raise ValueError("Dependency preflight output must use a child directory")
    return resolved


def main(argv: Sequence[str] | None = None) -> int:
    """Prepare the native trial inputs or verify a resolved candidate lock."""

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_command = commands.add_parser("prepare")
    prepare_command.add_argument("--work-dir", type=Path, required=True)
    verify_command = commands.add_parser("verify-lock")
    verify_command.add_argument("--work-dir", type=Path, required=True)
    audit_command = commands.add_parser("verify-audit")
    audit_command.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        work_dir = _runner_temp_path(args.work_dir)
        if args.command == "prepare":
            expected = os.environ.get("DEPENDENCY_PREFLIGHT_SOURCE_SHA")
            prepare_inputs(REPO_ROOT, work_dir, expected)
            print(f"Prepared dependency trial inputs for {_head_commit(REPO_ROOT)}")
        elif args.command == "verify-lock":
            result = verify_work_dir(work_dir)
            raw_changed_distributions = result.get("changed_distributions")
            if not isinstance(raw_changed_distributions, list) or not all(
                isinstance(value, str) for value in raw_changed_distributions
            ):
                raise ValueError("Lock verification result has invalid changed distributions")
            changed_distributions = cast(list[str], raw_changed_distributions)
            print("Resolved lock verified: " + ", ".join(changed_distributions))
        else:
            result = verify_audit_work_dir(work_dir)
            audit_status = audit_report_status(result)
            print(
                "Audit coverage verified: "
                f"{result['reported_pin_count']} pins, "
                f"{result['finding_count']} findings"
            )
            if audit_status != 0:
                print("::error::pip-audit found known vulnerabilities", file=sys.stderr)
                return audit_status
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(
            f"Dependency preflight preparation failed ({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
