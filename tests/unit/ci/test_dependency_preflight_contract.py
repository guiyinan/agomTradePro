from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.prepare_dependency_preflight import (
    audit_report_status,
    build_constraints,
    build_trial_pyproject,
    verify_audit_report,
    verify_resolved_lock,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "security-scan.yml"


def _baseline_lock() -> str:
    """Return the expected 134-pin baseline shape without project imports."""

    lines = [f"fixture-{index:03d}==1.0.0" for index in range(132)]
    lines.extend(("djangorestframework==3.17.2", "twisted[tls]==26.4.0"))
    return "\n".join(lines) + "\n"


def _candidate_lock(*, unrelated_version: str = "1.0.0", add_package: bool = False) -> str:
    """Build a small lock fixture with the two expected target upgrades."""

    lines = [
        f"fixture-{index:03d}=={unrelated_version if index == 0 else '1.0.0'}"
        for index in range(132)
    ]
    lines.extend(("djangorestframework==3.18.3", "twisted[tls]==26.10.0rc1"))
    if add_package:
        lines.append("unexpected-package==1.0.0")
    return "\n".join(lines) + "\n"


def test_temporary_pyproject_changes_only_the_two_reviewed_dependencies() -> None:
    """The isolated input pins Twisted TLS and DRF while preserving other requirements."""

    source = (
        "[project]\n"
        "dependencies = [\n"
        '    "django>=5.2,<6.0",\n'
        '    "djangorestframework",\n'
        '    "daphne>=4.2.2,<4.3",\n'
        "]\n"
    )

    candidate = build_trial_pyproject(source)

    assert candidate.count('"djangorestframework==3.18.3"') == 1
    assert candidate.count('"Twisted[tls]==26.10.0rc1"') == 1
    assert '"django>=5.2,<6.0"' in candidate
    assert candidate.count('"daphne>=4.2.2,<4.3"') == 1


def test_constraints_preserve_all_132_non_target_baseline_pins() -> None:
    """The old Twisted and DRF pins are omitted while all other pins remain exact."""

    constraints = build_constraints(_baseline_lock())
    lines = constraints.splitlines()

    assert len(lines) == 132
    assert lines[0] == "fixture-000==1.0.0"
    assert lines[-1] == "fixture-131==1.0.0"
    assert not any(line.startswith(("twisted", "djangorestframework")) for line in lines)


def test_lock_verification_accepts_only_the_two_target_version_changes() -> None:
    """A candidate lock must retain the complete baseline package set and other pins."""

    result = verify_resolved_lock(_baseline_lock(), _candidate_lock())

    assert result["status"] == "verified"
    assert result["baseline_pin_count"] == 134
    assert result["candidate_pin_count"] == 134
    assert result["constraint_pin_count"] == 132
    assert result["changed_distributions"] == ["djangorestframework", "twisted"]
    assert result["twisted_version"] == "26.10.0rc1"
    assert result["djangorestframework_version"] == "3.18.3"


@pytest.mark.parametrize(
    "candidate_text",
    (
        _candidate_lock(unrelated_version="2.0.0"),
        _candidate_lock(add_package=True),
        _candidate_lock().replace("djangorestframework==3.18.3", "djangorestframework==3.18.2"),
        _candidate_lock().replace(
            "twisted[tls]==26.10.0rc1",
            'twisted[tls]==26.10.0rc1; python_version >= "3.11"',
        ),
        _candidate_lock().replace(
            "fixture-000==1.0.0",
            'fixture-000==1.0.0; python_version >= "3.11"',
        ),
    ),
)
def test_lock_verification_rejects_unrelated_or_incomplete_resolution(
    candidate_text: str,
) -> None:
    """No extra package, unrelated pin drift, or wrong target version is accepted."""

    with pytest.raises(ValueError):
        verify_resolved_lock(_baseline_lock(), candidate_text)


def test_audit_report_must_cover_every_locked_name_and_version() -> None:
    """The JSON audit artifact must report every pin, including clean dependencies."""

    dependencies = [
        {"name": f"fixture-{index:03d}", "version": "1.0.0", "vulns": []} for index in range(132)
    ]
    dependencies.extend(
        (
            {"name": "djangorestframework", "version": "3.18.3", "vulns": []},
            {"name": "twisted", "version": "26.10.0rc1", "vulns": []},
        )
    )

    result = verify_audit_report(
        _candidate_lock(),
        json.dumps({"dependencies": dependencies}),
    )

    assert result["status"] == "coverage_verified"
    assert result["locked_pin_count"] == 134
    assert result["reported_pin_count"] == 134
    assert result["finding_count"] == 0


def test_complete_audit_report_with_a_finding_still_fails_the_cli_gate() -> None:
    """Full coverage does not turn a vulnerability finding into a successful audit."""

    dependencies = [
        {
            "name": f"fixture-{index:03d}",
            "version": "1.0.0",
            "vulns": [{"id": "CVE-2026-TEST"}] if index == 0 else [],
        }
        for index in range(132)
    ]
    dependencies.extend(
        (
            {"name": "djangorestframework", "version": "3.18.3", "vulns": []},
            {"name": "twisted", "version": "26.10.0rc1", "vulns": []},
        )
    )

    result = verify_audit_report(
        _candidate_lock(),
        json.dumps({"dependencies": dependencies}),
    )

    assert result["reported_pin_count"] == 134
    assert result["finding_count"] == 1
    assert audit_report_status(result) != 0


@pytest.mark.parametrize(
    "report",
    (
        {"dependencies": [{"name": "fixture-000", "version": "1.0.0", "vulns": []}]},
        {
            "dependencies": [
                {
                    "name": "fixture-000",
                    "version": "1.0.0",
                    "vulns": [],
                    "skip_reason": "unavailable",
                }
            ]
        },
    ),
)
def test_audit_report_rejects_missing_or_skipped_packages(report: dict[str, object]) -> None:
    """Partial or skipped audit output cannot be treated as a full-lock result."""

    with pytest.raises(ValueError):
        verify_audit_report(_candidate_lock(), json.dumps(report))


def test_manual_preflight_is_opt_in_and_does_not_change_existing_security_gates() -> None:
    """The new Linux experiment stays separate from default scans and summary gates."""

    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    dispatch_start = workflow.index("  workflow_dispatch:\n")
    schedule_start = workflow.index("  schedule:\n", dispatch_start)
    dispatch = workflow[dispatch_start:schedule_start]
    job_start = workflow.index("  dependency-preflight:\n")
    job_end = workflow.index("  security-summary:\n", job_start)
    job = workflow[job_start:job_end]

    assert "dependency_preflight:" in dispatch
    assert "type: boolean" in dispatch
    assert "default: false" in dispatch
    assert (
        "if: github.event_name == 'workflow_dispatch' && inputs.dependency_preflight == true" in job
    )
    assert "runs-on: ubuntu-24.04" in job
    assert "timeout-minutes: 30" in job
    assert "python-version: '3.11.14'" in job
    assert "contents: read" in job
    assert "persist-credentials: false" in job
    assert "secrets." not in job
    assert "'pip-tools==7.6.2'" in job
    assert "'pip-audit==2.9.0'" in job
    assert 'python -m venv "$RUNNER_TEMP/pip-tools-venv"' in job
    assert 'python -m venv "$RUNNER_TEMP/dependency-runtime-venv"' in job
    assert 'python -m venv "$RUNNER_TEMP/dependency-audit-venv"' in job
    assert '--expected-lock "$PREPARED/requirements-prod.lock"' in job
    assert "--no-strip-extras" in job
    assert "--ignore-vuln" not in job
    assert "--no-deps" in job
    assert "--disable-pip" in job
    assert "verify-audit" in job
    assert job.count("if: ${{ !cancelled()") == 4
    assert "needs: [bandit-scan, dependency-scan, secrets-scan, npm-audit]" in workflow
    assert workflow.count("--ignore-vuln") == 2
