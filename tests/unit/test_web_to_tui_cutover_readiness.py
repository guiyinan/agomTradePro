"""Unit contracts for the Web-to-TUI M5 machine cutover gate."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from scripts.check_web_to_tui_cutover_readiness import (
    _load_catalog,
    evaluate_readiness,
    required_route_pages,
    required_task_keys,
)

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
CATALOG_PATH = ROOT / "config/tui/migration/web_to_tui_telemetry.v1.json"
EVIDENCE_PATH = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"


def _evidence_digest(relative_path: str) -> str:
    """Return the SHA-256 of one checked-in synthetic evidence fixture."""

    return hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()


def _repository_head() -> str:
    """Return a real candidate commit for positive cutover fixtures."""

    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    ).strip()


def _complete_evidence() -> dict[str, Any]:
    """Build a complete synthetic evidence bundle from machine truth."""

    catalog = _load_catalog(CATALOG_PATH)
    candidate_commit = _repository_head()
    source_sha256 = catalog["source_sha256"]
    readiness_evidence = "docs/plans/web-to-tui-m5-readiness-2026-07-27.md"
    readiness_sha256 = _evidence_digest(readiness_evidence)
    uat_evidence = "docs/plans/web-to-tui-m5-browser-uat-evidence-2026-07-27.md"
    rollback_evidence = "docs/plans/web-to-tui-m5-rollback-drill-evidence-2026-07-27.md"
    route_pages = sorted(required_route_pages(MATRIX_PATH))
    task_records = [
        {
            "task_key": task_key,
            "classic_entries": 1,
            "tui_entries": 19,
            "classic_task_requests": 20,
            "tui_task_requests": 20,
            "classic_task_errors": 0,
            "tui_task_errors": 0,
            "low_frequency_exception": None,
        }
        for task_key in sorted(required_task_keys(catalog))
    ]
    return {
        "version": "web-to-tui-cutover-evidence.v1",
        "source_sha256": source_sha256,
        "candidate": {
            "stable_version": "0.9.0-rc1",
            "candidate_commit": candidate_commit,
            "released_at": "2026-07-26",
            "observation_end": "2026-08-09",
        },
        "uat": {
            "evidence": uat_evidence,
            "evidence_sha256": _evidence_digest(uat_evidence),
            "passed_route_pages": route_pages,
        },
        "cleanup": {
            "evidence": readiness_evidence,
            "evidence_sha256": readiness_sha256,
            "passed_route_pages": route_pages,
            "scope_coverage": {
                scope: {"all_required": True, "route_pages": []}
                for scope in (
                    "primary_task",
                    "permission",
                    "empty_state",
                    "error_state",
                    "legacy_url",
                    "rollback",
                )
            },
            "route_rollback_commits": dict.fromkeys(route_pages, candidate_commit),
        },
        "defects": {
            "candidate_version": "0.9.0-rc1",
            "candidate_commit": candidate_commit,
            "source_sha256": source_sha256,
            "window_start": "2026-07-26",
            "window_end": "2026-08-09",
            "new_p0": 0,
            "new_p1": 0,
            "open_p0": 0,
            "open_p1": 0,
            "evidence": readiness_evidence,
            "query_scope": "created_or_open_during_candidate_window",
            "query_filter": "candidate=0.9.0-rc1 priority in (P0,P1)",
            "snapshot_sha256": readiness_sha256,
            "queried_at": "2026-08-09",
        },
        "telemetry": {
            "window_start": "2026-07-26",
            "window_end": "2026-08-09",
            "collected_at": "2026-08-09",
            "environment": "production",
            "evidence": readiness_evidence,
            "snapshot_sha256": readiness_sha256,
            "tasks": task_records,
        },
        "rollback": {
            "passed": True,
            "environment": "local",
            "performed_at": "2026-07-27",
            "evidence": rollback_evidence,
            "evidence_sha256": _evidence_digest(rollback_evidence),
            "production_registry_backup": {
                "evidence": readiness_evidence,
                "evidence_sha256": readiness_sha256,
                "location": "artifact://tui-registry/pre-cutover.json",
                "payload_sha256": "c" * 64,
                "registry_generation": 42,
                "graph_hash": "d" * 64,
                "schema_version": "tui-metadata.v3",
                "runtime_version": "agomtui-runtime-0.2.0",
                "candidate_version": "0.9.0-rc1",
                "candidate_commit": candidate_commit,
                "source_sha256": source_sha256,
                "created_at": "2026-08-09",
                "restore_dry_run_passed": True,
                "restore_verified_at": "2026-08-09",
                "verified_by": "independent-reviewer",
                "retention_until": "2026-09-09",
            },
        },
        "review_snapshot": {
            "evidence": readiness_evidence,
            "sha256": readiness_sha256,
        },
        "approvals": {
            "owner": {
                "name": "terminal-owner",
                "decision": "approve",
                "approved_at": "2026-08-09",
                "candidate_version": "0.9.0-rc1",
                "candidate_commit": candidate_commit,
                "source_sha256": source_sha256,
                "evidence_snapshot_sha256": readiness_sha256,
            },
            "reviewer": {
                "name": "independent-reviewer",
                "decision": "approve",
                "approved_at": "2026-08-09",
                "candidate_version": "0.9.0-rc1",
                "candidate_commit": candidate_commit,
                "source_sha256": source_sha256,
                "evidence_snapshot_sha256": readiness_sha256,
            },
        },
    }


def _evaluate(tmp_path: Path, payload: dict[str, Any]):
    """Evaluate one temporary evidence payload at the earliest valid date."""

    from datetime import date

    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return evaluate_readiness(
        matrix_path=MATRIX_PATH,
        catalog_path=CATALOG_PATH,
        evidence_path=path,
        as_of=date(2026, 8, 9),
    )


def test_checked_in_evidence_is_explicitly_denied() -> None:
    """Incomplete production evidence must never look cutover-ready."""

    from datetime import date

    result = evaluate_readiness(
        matrix_path=MATRIX_PATH,
        catalog_path=CATALOG_PATH,
        evidence_path=EVIDENCE_PATH,
        as_of=date(2026, 7, 27),
    )
    gates = {gate.key: gate for gate in result.gates}

    assert result.decision == "DENY"
    assert result.required_route_pages == 108
    assert result.required_tasks == 101
    assert gates["source_consistency"].passed is True
    assert gates["route_task_uat"].passed is True
    assert "covered=108/108" in gates["route_task_uat"].detail
    assert gates["route_cleanup_readiness"].passed is False
    assert gates["rollback_drill"].passed is True


def test_complete_independent_evidence_allows_cutover(tmp_path: Path) -> None:
    """Every explicit gate can pass only with full machine evidence."""

    result = _evaluate(tmp_path, _complete_evidence())

    assert result.decision == "ALLOW"
    assert all(gate.passed for gate in result.gates)


def test_candidate_commit_must_resolve_in_repository(tmp_path: Path) -> None:
    """A formatted but invented commit cannot start the stable window."""

    payload = _complete_evidence()
    invented_commit = "a" * 40
    payload["candidate"]["candidate_commit"] = invented_commit
    payload["rollback"]["production_registry_backup"]["candidate_commit"] = invented_commit
    payload["approvals"]["owner"]["candidate_commit"] = invented_commit
    payload["approvals"]["reviewer"]["candidate_commit"] = invented_commit

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "stable_version_window").passed is False
    )


def test_blocking_defects_rejects_new_issue_even_when_closed(tmp_path: Path) -> None:
    """A P0/P1 opened during the window cannot pass merely because it was later closed."""

    payload = _complete_evidence()
    payload["defects"]["new_p1"] = 1

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "blocking_defects").passed is False


def test_blocking_defects_require_candidate_binding_and_full_scope(tmp_path: Path) -> None:
    """A zero-count snapshot for another scope or source cannot pass the defect gate."""

    payload = _complete_evidence()
    payload["defects"]["source_sha256"] = "f" * 64
    payload["defects"]["query_scope"] = "open_at_end_only"

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "blocking_defects").passed is False


def test_route_cleanup_requires_exact_route_coverage(tmp_path: Path) -> None:
    """A missing or extra route prevents the post-observation cleanup phase."""

    payload = _complete_evidence()
    missing_route = payload["cleanup"]["passed_route_pages"].pop()
    payload["cleanup"]["route_rollback_commits"].pop(missing_route)

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "route_cleanup_readiness").passed is False
    )


def test_route_cleanup_requires_all_review_scopes(tmp_path: Path) -> None:
    """Primary-task success cannot replace permission, state, URL, and rollback review."""

    payload = _complete_evidence()
    del payload["cleanup"]["scope_coverage"]["error_state"]

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "route_cleanup_readiness").passed is False
    )


def test_route_cleanup_requires_resolvable_rollback_commits(tmp_path: Path) -> None:
    """Every route must retain a rollback commit that exists in this repository."""

    payload = _complete_evidence()
    first_route = payload["cleanup"]["passed_route_pages"][0]
    payload["cleanup"]["route_rollback_commits"][first_route] = "a" * 40

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "route_cleanup_readiness").passed is False
    )


def test_legacy_ratio_above_five_percent_denies_cutover(tmp_path: Path) -> None:
    """A qualified task above the Classic usage threshold blocks cleanup."""

    payload = _complete_evidence()
    first_task = payload["telemetry"]["tasks"][0]
    first_task["classic_entries"] = 2
    first_task["tui_entries"] = 18

    result = _evaluate(tmp_path, payload)
    telemetry_gate = next(gate for gate in result.gates if gate.key == "production_telemetry")

    assert result.decision == "DENY"
    assert telemetry_gate.passed is False
    assert "invalid=1" in telemetry_gate.detail


def test_error_regression_above_half_point_denies_cutover(tmp_path: Path) -> None:
    """A TUI task error regression above 0.5 percentage point blocks cleanup."""

    payload = _complete_evidence()
    first_task = payload["telemetry"]["tasks"][0]
    first_task["tui_task_errors"] = 1

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "production_telemetry").passed is False


def test_low_frequency_entry_share_requires_independent_dual_signoff(
    tmp_path: Path,
) -> None:
    """A low entry sample can waive only the Classic share comparison."""

    payload = _complete_evidence()
    first_task = payload["telemetry"]["tasks"][0]
    first_task["tui_entries"] = 18

    denied = _evaluate(tmp_path, payload)
    assert denied.decision == "DENY"

    first_task["low_frequency_exception"] = {
        "reason": "Naturally low-frequency governance task",
        "owner": "task-owner",
        "reviewer": "independent-reviewer",
    }
    allowed = _evaluate(tmp_path, payload)
    assert allowed.decision == "ALLOW"


def test_low_frequency_exception_cannot_waive_error_samples(tmp_path: Path) -> None:
    """Every task still needs comparable error samples on both surfaces."""

    payload = _complete_evidence()
    first_task = payload["telemetry"]["tasks"][0]
    first_task["tui_entries"] = 18
    first_task["classic_task_requests"] = 10
    first_task["tui_task_requests"] = 10
    first_task["low_frequency_exception"] = {
        "reason": "Naturally low-frequency governance task",
        "owner": "task-owner",
        "reviewer": "independent-reviewer",
    }

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "production_telemetry").passed is False


def test_backup_placeholder_string_cannot_allow_cutover(tmp_path: Path) -> None:
    """A non-empty backup placeholder must not satisfy integrity requirements."""

    payload = _complete_evidence()
    payload["rollback"]["production_registry_backup"] = "artifact://tui-registry/pre-cutover.json"

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "production_registry_backup").passed
        is False
    )


def test_backup_must_bind_to_candidate_and_source_snapshot(tmp_path: Path) -> None:
    """A valid-looking backup for another candidate must remain unusable."""

    payload = _complete_evidence()
    payload["rollback"]["production_registry_backup"]["candidate_commit"] = "e" * 40

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "production_registry_backup").passed
        is False
    )


def test_backup_requires_external_locator_and_positive_generation(tmp_path: Path) -> None:
    """A local-looking placeholder and generation zero cannot represent production backup."""

    payload = _complete_evidence()
    backup = payload["rollback"]["production_registry_backup"]
    backup["location"] = "pre-cutover.json"
    backup["registry_generation"] = 0

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "production_registry_backup").passed
        is False
    )


def test_backup_must_follow_window_and_remain_retained(tmp_path: Path) -> None:
    """A pre-window or already expired backup cannot protect the cutover."""

    payload = _complete_evidence()
    backup = payload["rollback"]["production_registry_backup"]
    backup["created_at"] = "2026-08-08"
    backup["retention_until"] = "2026-08-09"

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "production_registry_backup").passed
        is False
    )


def test_approvals_must_bind_to_exact_candidate_snapshot(tmp_path: Path) -> None:
    """Names alone or stale approvals cannot authorize Classic cleanup."""

    payload = _complete_evidence()
    payload["approvals"] = {
        "owner": "terminal-owner",
        "reviewer": "independent-reviewer",
    }

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "cutover_approvals").passed is False


def test_approvals_must_follow_observation_window(tmp_path: Path) -> None:
    """Pre-approval before the final observation evidence is invalid."""

    payload = _complete_evidence()
    payload["approvals"]["owner"]["approved_at"] = "2026-08-08"

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "cutover_approvals").passed is False


def test_production_gates_require_existing_bounded_evidence_files(tmp_path: Path) -> None:
    """Traversal and missing evidence paths must fail closed."""

    payload = _complete_evidence()
    payload["defects"]["evidence"] = "../outside-defect-snapshot.json"
    payload["telemetry"]["evidence"] = "missing-production-telemetry.json"

    result = _evaluate(tmp_path, payload)
    gates = {gate.key: gate for gate in result.gates}

    assert result.decision == "DENY"
    assert gates["blocking_defects"].passed is False
    assert gates["production_telemetry"].passed is False


def test_uat_and_rollback_evidence_digests_must_match_files(tmp_path: Path) -> None:
    """Replacing an evidence file without updating its digest must fail closed."""

    payload = _complete_evidence()
    payload["uat"]["evidence_sha256"] = "e" * 64
    payload["rollback"]["evidence_sha256"] = "f" * 64

    result = _evaluate(tmp_path, payload)
    gates = {gate.key: gate for gate in result.gates}

    assert result.decision == "DENY"
    assert gates["route_task_uat"].passed is False
    assert gates["rollback_drill"].passed is False


def test_approvals_require_verified_review_snapshot(tmp_path: Path) -> None:
    """Matching approval strings cannot bless an unverifiable review snapshot."""

    payload = _complete_evidence()
    invalid_digest = "e" * 64
    payload["review_snapshot"]["sha256"] = invalid_digest
    payload["approvals"]["owner"]["evidence_snapshot_sha256"] = invalid_digest
    payload["approvals"]["reviewer"]["evidence_snapshot_sha256"] = invalid_digest

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "cutover_approvals").passed is False
