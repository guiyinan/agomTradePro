"""Unit contracts for the Web-to-TUI M5 machine cutover gate."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from scripts.build_web_to_tui_defect_evidence import build_defect_evidence
from scripts.build_web_to_tui_production_telemetry import (
    APPROVED_QUERIES,
    build_production_telemetry_evidence,
)
from scripts.build_web_to_tui_review_snapshot import build_review_snapshot
from scripts.check_web_to_tui_cutover_readiness import (
    _load_catalog,
    _normalized_source_bytes,
    _verified_repo_evidence,
    evaluate_readiness,
    required_route_pages,
    required_task_keys,
)
from scripts.record_web_to_tui_cutover_approval import build_approval_attestation
from scripts.web_to_tui_candidate_binding import build_candidate_binding

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
CATALOG_PATH = ROOT / "config/tui/migration/web_to_tui_telemetry.v1.json"
EVIDENCE_PATH = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"


def _file_digest(path: Path) -> str:
    """Return the SHA-256 of one synthetic evidence fixture."""

    content = (
        _normalized_source_bytes(path)
        if path.suffix.lower() in {".csv", ".md", ".txt"}
        else path.read_bytes()
    )
    return hashlib.sha256(content).hexdigest()


def _repository_head() -> str:
    """Return a real candidate commit for positive cutover fixtures."""

    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    ).strip()


def _repository_commit_with_different_matrix() -> str:
    """Return one real ancestor whose migration matrix differs from the current scope."""

    relative_matrix = MATRIX_PATH.relative_to(ROOT).as_posix()
    commits = subprocess.check_output(
        ["git", "log", "--format=%H", "--", relative_matrix],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    ).splitlines()
    current_digest = hashlib.sha256(_normalized_source_bytes(MATRIX_PATH)).digest()
    for commit in commits:
        result = subprocess.run(
            ["git", "show", f"{commit}:{relative_matrix}"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0 and hashlib.sha256(result.stdout).digest() != current_digest:
            return commit
    raise AssertionError("Repository history lacks a different migration matrix fixture")


def _matrix_rollback_commits() -> dict[str, str]:
    """Return the exact checked-in rollback mapping for migrated route pages."""

    with MATRIX_PATH.open("r", encoding="utf-8", newline="") as handle:
        return {
            str(row["template_path"]): str(row["rollback_commit"])
            for row in csv.DictReader(handle)
            if row.get("template_role") == "route_page"
            and row.get("destination_class") in {"A", "B"}
            and row.get("status") in {"migrated", "deleted"}
        }


def _write_fixture(root: Path, name: str, payload: object) -> tuple[str, str]:
    """Write one bounded synthetic evidence file and return path plus digest."""

    path = root / name
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return name, _file_digest(path)


def _write_plan_registry(
    root: Path,
    *,
    tui_status: str = "awaiting_production",
    tar_status: str = "completed",
) -> Path:
    """Write the canonical dependency slice needed by the M5 gate."""

    path = root / "active-plan-registry.json"
    path.write_text(
        json.dumps(
            {
                "closure_backlog": {
                    "units": [
                        {"id": "TAR-03", "status": tar_status, "depends_on": []},
                        {
                            "id": "TUI-01",
                            "status": tui_status,
                            "depends_on": ["TAR-03"],
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def _sync_telemetry_snapshot(evidence_root: Path, payload: dict[str, Any]) -> None:
    """Synchronize mutated task records back into their structured snapshot."""

    telemetry = payload["telemetry"]
    path = evidence_root / telemetry["evidence"]
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    snapshot["tasks"] = telemetry["tasks"]
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    telemetry["snapshot_sha256"] = _file_digest(path)


def _sync_defect_snapshot(
    evidence_root: Path,
    payload: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    """Rebuild denormalized defect evidence from mutated issue records."""

    defects = payload["defects"]
    path = evidence_root / defects["evidence"]
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    snapshot["issues"] = issues
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prepared = build_defect_evidence(
        snapshot=snapshot,
        evidence=payload,
        snapshot_evidence_path=defects["evidence"],
        snapshot_sha256=_file_digest(path),
        as_of=date(2026, 8, 9),
    )
    payload["defects"] = prepared["defects"]


def _complete_evidence(evidence_root: Path) -> dict[str, Any]:
    """Build a complete synthetic evidence bundle from machine truth."""

    catalog = _load_catalog(CATALOG_PATH)
    raw_catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    candidate_commit = _repository_head()
    source_sha256 = catalog["source_sha256"]
    candidate_binding = build_candidate_binding(
        stable_version="0.9.0-rc1",
        candidate_commit=candidate_commit,
        matrix_path=MATRIX_PATH,
        graph_path=ROOT / "config/tui/published/tui_operation_graph.published.json",
        runtime_manifest_path=ROOT / "config/tui/agomtui-runtime.manifest.json",
    )
    readiness_evidence, readiness_sha256 = _write_fixture(
        evidence_root,
        "readiness.md",
        "synthetic M5 readiness review\n",
    )
    uat_evidence, uat_sha256 = _write_fixture(
        evidence_root,
        "uat.md",
        "synthetic route UAT evidence\n",
    )
    rollback_evidence, rollback_sha256 = _write_fixture(
        evidence_root,
        "rollback.md",
        "synthetic rollback drill evidence\n",
    )
    backup_attestation = {
        "version": "web-to-tui-production-registry-backup-attestation.v1",
        "location": "artifact://tui-registry/pre-cutover.json",
        "bundle_sha256": "b" * 64,
        "payload_sha256": "c" * 64,
        "registry_generation": 42,
        "graph_hash": candidate_binding["graph_sha256"],
        "schema_version": candidate_binding["schema_version"],
        "runtime_version": candidate_binding["runtime_version"],
        "runtime_build_id": candidate_binding["runtime_build_id"],
        "candidate_version": "0.9.0-rc1",
        "candidate_commit": candidate_commit,
        "source_sha256": source_sha256,
        "created_at": "2026-08-09",
        "restore_dry_run_passed": True,
        "restore_verified_at": "2026-08-09",
        "verified_by": "independent-reviewer",
        "retention_until": "2026-09-09",
    }
    backup_evidence, backup_sha256 = _write_fixture(
        evidence_root,
        "backup.json",
        backup_attestation,
    )
    backup_projection = dict(backup_attestation)
    backup_projection.pop("version")
    backup_projection["evidence"] = backup_evidence
    backup_projection["evidence_sha256"] = backup_sha256
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
    payload: dict[str, Any] = {
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
            "evidence_sha256": uat_sha256,
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
            "route_rollback_commits": _matrix_rollback_commits(),
        },
        "defects": {},
        "telemetry": {},
        "rollback": {
            "passed": True,
            "environment": "local",
            "performed_at": "2026-07-27",
            "evidence": rollback_evidence,
            "evidence_sha256": rollback_sha256,
            "production_registry_backup": backup_projection,
        },
        "review_snapshot": {"evidence": None, "sha256": None},
        "approvals": {"owner": None, "reviewer": None},
    }
    payload["candidate"]["binding"] = candidate_binding
    payload["uat"]["candidate_binding"] = candidate_binding
    payload["cleanup"]["candidate_binding"] = candidate_binding
    payload["rollback"]["candidate_binding"] = candidate_binding

    defect_snapshot = {
        "version": "web-to-tui-blocking-defect-snapshot.v1",
        "candidate_version": "0.9.0-rc1",
        "candidate_commit": candidate_commit,
        "source_sha256": source_sha256,
        "window_start": "2026-07-26",
        "window_end": "2026-08-09",
        "queried_at": "2026-08-09",
        "query_scope": "created_or_open_during_candidate_window",
        "tracker": {
            "system": "github",
            "project": "agom/agomTradePro",
            "endpoint": "https://github.example.test",
            "query_filter": "candidate=0.9.0-rc1 priority in (P0,P1)",
            "queried_by": "independent-reviewer",
        },
        "issues": [],
    }
    defect_path, defect_sha256 = _write_fixture(
        evidence_root,
        "defects.json",
        defect_snapshot,
    )
    payload = build_defect_evidence(
        snapshot=defect_snapshot,
        evidence=payload,
        snapshot_evidence_path=defect_path,
        snapshot_sha256=defect_sha256,
        as_of=date(2026, 8, 9),
    )

    telemetry_snapshot = {
        "version": "web-to-tui-production-telemetry-snapshot.v1",
        "environment": "production",
        "candidate_version": "0.9.0-rc1",
        "candidate_commit": candidate_commit,
        "source_sha256": source_sha256,
        "window_start": "2026-07-26",
        "window_end": "2026-08-09",
        "collected_at": "2026-08-09",
        "collection": {
            "system": "prometheus",
            "endpoint": "https://prometheus.example.test",
            "queries": APPROVED_QUERIES,
        },
        "tasks": task_records,
    }
    telemetry_path, telemetry_sha256 = _write_fixture(
        evidence_root,
        "telemetry.json",
        telemetry_snapshot,
    )
    payload = build_production_telemetry_evidence(
        snapshot=telemetry_snapshot,
        catalog=raw_catalog,
        evidence=payload,
        snapshot_evidence_path=telemetry_path,
        snapshot_sha256=telemetry_sha256,
        as_of=date(2026, 8, 9),
    )

    pre_review_path = evidence_root / "pre-review-evidence.json"
    pre_review_path.write_text(json.dumps(payload), encoding="utf-8")
    readiness = evaluate_readiness(
        matrix_path=MATRIX_PATH,
        catalog_path=CATALOG_PATH,
        evidence_path=pre_review_path,
        as_of=date(2026, 8, 9),
        plan_registry_path=_write_plan_registry(evidence_root),
        evidence_root=evidence_root,
    )
    review_snapshot = build_review_snapshot(
        evidence=payload,
        readiness=readiness,
        reviewed_at=date(2026, 8, 9),
    )
    review_reference, review_sha256 = _write_fixture(
        evidence_root,
        "review.json",
        review_snapshot,
    )
    payload["review_snapshot"] = {
        "evidence": review_reference,
        "sha256": review_sha256,
    }

    for role, name in (
        ("owner", "terminal-owner"),
        ("reviewer", "independent-reviewer"),
    ):
        attestation = build_approval_attestation(
            evidence=payload,
            review_snapshot=review_snapshot,
            review_reference=review_reference,
            review_sha256=review_sha256,
            role=role,
            name=name,
            approved_at=date(2026, 8, 9),
            as_of=date(2026, 8, 9),
        )
        approval_reference, approval_sha256 = _write_fixture(
            evidence_root,
            f"{role}-approval.json",
            attestation,
        )
        projection = dict(attestation)
        projection.pop("version")
        projection["evidence"] = approval_reference
        projection["evidence_sha256"] = approval_sha256
        payload["approvals"][role] = projection
    return payload


def _evaluate(
    tmp_path: Path,
    payload: dict[str, Any],
    *,
    plan_registry_path: Path | None = None,
):
    """Evaluate one temporary evidence payload at the earliest valid date."""

    from datetime import date

    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return evaluate_readiness(
        matrix_path=MATRIX_PATH,
        catalog_path=CATALOG_PATH,
        evidence_path=path,
        as_of=date(2026, 8, 9),
        plan_registry_path=plan_registry_path or _write_plan_registry(tmp_path),
        evidence_root=tmp_path,
    )


def test_checked_in_evidence_is_explicitly_denied() -> None:
    """Current machine evidence passes five gates while cutover stays denied."""

    from datetime import date

    result = evaluate_readiness(
        matrix_path=MATRIX_PATH,
        catalog_path=CATALOG_PATH,
        evidence_path=EVIDENCE_PATH,
        as_of=date(2026, 8, 30),
    )
    gates = {gate.key: gate for gate in result.gates}

    assert result.decision == "DENY"
    assert result.required_route_pages == 108
    assert result.required_tasks == 101
    assert gates["source_consistency"].passed is True
    assert gates["execution_dependency"].passed is True
    assert gates["route_task_uat"].passed is True
    assert "covered=108/108" in gates["route_task_uat"].detail
    assert "binding=true" in gates["route_task_uat"].detail
    assert gates["route_cleanup_readiness"].passed is True
    assert "covered=108/108" in gates["route_cleanup_readiness"].detail
    assert "candidate_binding=true" in gates["route_cleanup_readiness"].detail
    assert gates["rollback_drill"].passed is True
    assert "binding=true" in gates["rollback_drill"].detail
    assert gates["stable_version_window"].passed is False
    assert gates["blocking_defects"].passed is False
    assert gates["production_telemetry"].passed is False
    assert gates["production_registry_backup"].passed is False
    assert gates["cutover_approvals"].passed is False
    assert sum(gate.passed for gate in result.gates) == 5


def test_cutover_waits_for_terminal_runtime_dependency(tmp_path: Path) -> None:
    payload = _complete_evidence(tmp_path)
    plan_registry_path = _write_plan_registry(
        tmp_path,
        tui_status="waiting_dependency",
        tar_status="active",
    )

    result = _evaluate(
        tmp_path,
        payload,
        plan_registry_path=plan_registry_path,
    )

    gate = next(gate for gate in result.gates if gate.key == "execution_dependency")
    assert gate.passed is False
    assert "TUI-01=waiting_dependency" in gate.detail
    assert "TAR-03:active" in gate.detail


def test_text_evidence_digest_normalizes_windows_line_endings(tmp_path: Path) -> None:
    """Checked-in text evidence must verify identically on Windows and Linux."""

    evidence = tmp_path / "review.md"
    evidence.write_bytes(b"reviewed\r\npassed\r\n")
    expected = hashlib.sha256(b"reviewed\npassed\n").hexdigest()

    assert (
        _verified_repo_evidence(
            evidence.name,
            expected,
            root=tmp_path,
        )
        == evidence
    )


def test_complete_independent_evidence_allows_cutover(tmp_path: Path) -> None:
    """Every explicit gate can pass only with full machine evidence."""

    result = _evaluate(tmp_path, _complete_evidence(tmp_path))

    assert result.decision == "ALLOW"
    assert all(gate.passed for gate in result.gates)


@pytest.mark.parametrize(
    ("section", "gate_key"),
    (
        ("uat", "route_task_uat"),
        ("cleanup", "route_cleanup_readiness"),
        ("rollback", "rollback_drill"),
    ),
)
def test_candidate_bound_gates_reject_stale_source_snapshot(
    tmp_path: Path,
    section: str,
    gate_key: str,
) -> None:
    """A valid old result cannot pass after graph/runtime identity changes."""

    payload = _complete_evidence(tmp_path)
    payload[section]["candidate_binding"] = {
        **payload[section]["candidate_binding"],
        "graph_sha256": "e" * 64,
    }

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == gate_key).passed is False


def test_candidate_commit_must_resolve_in_repository(tmp_path: Path) -> None:
    """A formatted but invented commit cannot start the stable window."""

    payload = _complete_evidence(tmp_path)
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


def test_candidate_commit_must_contain_current_migration_matrix(tmp_path: Path) -> None:
    """An existing ancestor for an older migration scope cannot start this window."""

    payload = _complete_evidence(tmp_path)
    payload["candidate"]["candidate_commit"] = _repository_commit_with_different_matrix()

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "stable_version_window").passed is False
    )


def test_blocking_defects_rejects_new_issue_even_when_closed(tmp_path: Path) -> None:
    """A P0/P1 opened during the window cannot pass merely because it was later closed."""

    payload = _complete_evidence(tmp_path)
    _sync_defect_snapshot(
        tmp_path,
        payload,
        [
            {
                "id": "P1-closed-during-window",
                "priority": "P1",
                "state": "closed",
                "created_at": "2026-07-30",
                "closed_at": "2026-08-01",
            }
        ],
    )

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "blocking_defects").passed is False


def test_blocking_defects_require_candidate_binding_and_full_scope(tmp_path: Path) -> None:
    """A zero-count snapshot for another scope or source cannot pass the defect gate."""

    payload = _complete_evidence(tmp_path)
    payload["defects"]["source_sha256"] = "f" * 64
    payload["defects"]["query_scope"] = "open_at_end_only"

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "blocking_defects").passed is False


def test_route_cleanup_requires_exact_route_coverage(tmp_path: Path) -> None:
    """A missing or extra route prevents the post-observation cleanup phase."""

    payload = _complete_evidence(tmp_path)
    missing_route = payload["cleanup"]["passed_route_pages"].pop()
    payload["cleanup"]["route_rollback_commits"].pop(missing_route)

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "route_cleanup_readiness").passed is False
    )


def test_route_cleanup_requires_all_review_scopes(tmp_path: Path) -> None:
    """Primary-task success cannot replace permission, state, URL, and rollback review."""

    payload = _complete_evidence(tmp_path)
    del payload["cleanup"]["scope_coverage"]["error_state"]

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "route_cleanup_readiness").passed is False
    )


def test_route_cleanup_requires_resolvable_rollback_commits(tmp_path: Path) -> None:
    """Every route must retain a rollback commit that exists in this repository."""

    payload = _complete_evidence(tmp_path)
    first_route = payload["cleanup"]["passed_route_pages"][0]
    payload["cleanup"]["route_rollback_commits"][first_route] = "a" * 40

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "route_cleanup_readiness").passed is False
    )


def test_route_cleanup_rollback_mapping_must_match_matrix(tmp_path: Path) -> None:
    """A valid but unrelated ancestor cannot replace a route's recorded rollback commit."""

    payload = _complete_evidence(tmp_path)
    head = _repository_head()
    first_route = next(
        route
        for route, rollback_commit in payload["cleanup"]["route_rollback_commits"].items()
        if rollback_commit != head
    )
    payload["cleanup"]["route_rollback_commits"][first_route] = head

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "route_cleanup_readiness").passed is False
    )


def test_legacy_ratio_above_five_percent_denies_cutover(tmp_path: Path) -> None:
    """A qualified task above the Classic usage threshold blocks cleanup."""

    payload = _complete_evidence(tmp_path)
    first_task = payload["telemetry"]["tasks"][0]
    first_task["classic_entries"] = 2
    first_task["tui_entries"] = 18
    _sync_telemetry_snapshot(tmp_path, payload)

    result = _evaluate(tmp_path, payload)
    telemetry_gate = next(gate for gate in result.gates if gate.key == "production_telemetry")

    assert result.decision == "DENY"
    assert telemetry_gate.passed is False
    assert "invalid=1" in telemetry_gate.detail


def test_error_regression_above_half_point_denies_cutover(tmp_path: Path) -> None:
    """A TUI task error regression above 0.5 percentage point blocks cleanup."""

    payload = _complete_evidence(tmp_path)
    first_task = payload["telemetry"]["tasks"][0]
    first_task["tui_task_errors"] = 1
    _sync_telemetry_snapshot(tmp_path, payload)

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "production_telemetry").passed is False


def test_low_frequency_entry_share_requires_independent_dual_signoff(
    tmp_path: Path,
) -> None:
    """A low entry sample can waive only the Classic share comparison."""

    payload = _complete_evidence(tmp_path)
    first_task = payload["telemetry"]["tasks"][0]
    first_task["tui_entries"] = 18
    _sync_telemetry_snapshot(tmp_path, payload)

    denied = _evaluate(tmp_path, payload)
    assert denied.decision == "DENY"

    first_task["low_frequency_exception"] = {
        "reason": "Naturally low-frequency governance task",
        "owner": "task-owner",
        "reviewer": "independent-reviewer",
    }
    _sync_telemetry_snapshot(tmp_path, payload)
    allowed = _evaluate(tmp_path, payload)
    assert allowed.decision == "ALLOW"


def test_low_frequency_exception_cannot_waive_error_samples(tmp_path: Path) -> None:
    """Every task still needs comparable error samples on both surfaces."""

    payload = _complete_evidence(tmp_path)
    first_task = payload["telemetry"]["tasks"][0]
    first_task["tui_entries"] = 18
    first_task["classic_task_requests"] = 10
    first_task["tui_task_requests"] = 10
    first_task["low_frequency_exception"] = {
        "reason": "Naturally low-frequency governance task",
        "owner": "task-owner",
        "reviewer": "independent-reviewer",
    }
    _sync_telemetry_snapshot(tmp_path, payload)

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "production_telemetry").passed is False


def test_backup_placeholder_string_cannot_allow_cutover(tmp_path: Path) -> None:
    """A non-empty backup placeholder must not satisfy integrity requirements."""

    payload = _complete_evidence(tmp_path)
    payload["rollback"]["production_registry_backup"] = "artifact://tui-registry/pre-cutover.json"

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "production_registry_backup").passed
        is False
    )


def test_backup_gate_revalidates_structured_attestation(tmp_path: Path) -> None:
    """A digest-matched narrative cannot stand in for registry backup attestation."""

    payload = _complete_evidence(tmp_path)
    backup = payload["rollback"]["production_registry_backup"]
    backup["evidence"] = payload["cleanup"]["evidence"]
    backup["evidence_sha256"] = payload["cleanup"]["evidence_sha256"]

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "production_registry_backup").passed
        is False
    )


def test_backup_attestation_projection_must_match_exactly(tmp_path: Path) -> None:
    """Hand-edited backup hashes cannot diverge from the verified attestation."""

    payload = _complete_evidence(tmp_path)
    payload["rollback"]["production_registry_backup"]["graph_hash"] = "e" * 64

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "production_registry_backup").passed
        is False
    )


def test_backup_must_bind_to_candidate_and_source_snapshot(tmp_path: Path) -> None:
    """A valid-looking backup for another candidate must remain unusable."""

    payload = _complete_evidence(tmp_path)
    payload["rollback"]["production_registry_backup"]["candidate_commit"] = "e" * 40

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert (
        next(gate for gate in result.gates if gate.key == "production_registry_backup").passed
        is False
    )


def test_backup_requires_external_locator_and_positive_generation(tmp_path: Path) -> None:
    """A local-looking placeholder and generation zero cannot represent production backup."""

    payload = _complete_evidence(tmp_path)
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

    payload = _complete_evidence(tmp_path)
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

    payload = _complete_evidence(tmp_path)
    payload["approvals"] = {
        "owner": "terminal-owner",
        "reviewer": "independent-reviewer",
    }

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "cutover_approvals").passed is False


def test_approvals_must_follow_observation_window(tmp_path: Path) -> None:
    """Pre-approval before the final observation evidence is invalid."""

    payload = _complete_evidence(tmp_path)
    payload["approvals"]["owner"]["approved_at"] = "2026-08-08"

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "cutover_approvals").passed is False


def test_production_gates_require_existing_bounded_evidence_files(tmp_path: Path) -> None:
    """Traversal and missing evidence paths must fail closed."""

    payload = _complete_evidence(tmp_path)
    payload["defects"]["evidence"] = "../outside-defect-snapshot.json"
    payload["telemetry"]["evidence"] = "missing-production-telemetry.json"

    result = _evaluate(tmp_path, payload)
    gates = {gate.key: gate for gate in result.gates}

    assert result.decision == "DENY"
    assert gates["blocking_defects"].passed is False
    assert gates["production_telemetry"].passed is False


def test_defect_gate_revalidates_structured_snapshot(tmp_path: Path) -> None:
    """A digest-matched narrative file cannot stand in for a defect tracker snapshot."""

    payload = _complete_evidence(tmp_path)
    payload["defects"]["evidence"] = payload["cleanup"]["evidence"]
    payload["defects"]["snapshot_sha256"] = payload["cleanup"]["evidence_sha256"]

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "blocking_defects").passed is False


def test_telemetry_gate_revalidates_structured_snapshot(tmp_path: Path) -> None:
    """A digest-matched narrative file cannot stand in for Prometheus task records."""

    payload = _complete_evidence(tmp_path)
    payload["telemetry"]["evidence"] = payload["cleanup"]["evidence"]
    payload["telemetry"]["snapshot_sha256"] = payload["cleanup"]["evidence_sha256"]

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "production_telemetry").passed is False


def test_uat_and_rollback_evidence_digests_must_match_files(tmp_path: Path) -> None:
    """Replacing an evidence file without updating its digest must fail closed."""

    payload = _complete_evidence(tmp_path)
    payload["uat"]["evidence_sha256"] = "e" * 64
    payload["rollback"]["evidence_sha256"] = "f" * 64

    result = _evaluate(tmp_path, payload)
    gates = {gate.key: gate for gate in result.gates}

    assert result.decision == "DENY"
    assert gates["route_task_uat"].passed is False
    assert gates["rollback_drill"].passed is False


def test_approvals_require_verified_review_snapshot(tmp_path: Path) -> None:
    """Matching approval strings cannot bless an unverifiable review snapshot."""

    payload = _complete_evidence(tmp_path)
    invalid_digest = "e" * 64
    payload["review_snapshot"]["sha256"] = invalid_digest
    payload["approvals"]["owner"]["evidence_snapshot_sha256"] = invalid_digest
    payload["approvals"]["reviewer"]["evidence_snapshot_sha256"] = invalid_digest

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "cutover_approvals").passed is False


def test_review_snapshot_must_reproduce_current_gate_results(tmp_path: Path) -> None:
    """A digest-matched narrative cannot replace the eight-gate review snapshot."""

    payload = _complete_evidence(tmp_path)
    payload["review_snapshot"] = {
        "evidence": payload["cleanup"]["evidence"],
        "sha256": payload["cleanup"]["evidence_sha256"],
    }

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "cutover_approvals").passed is False


def test_approvals_require_role_bound_structured_attestations(tmp_path: Path) -> None:
    """Approval projection fields cannot be paired with an unrelated evidence file."""

    payload = _complete_evidence(tmp_path)
    owner = payload["approvals"]["owner"]
    owner["evidence"] = payload["cleanup"]["evidence"]
    owner["evidence_sha256"] = payload["cleanup"]["evidence_sha256"]

    result = _evaluate(tmp_path, payload)

    assert result.decision == "DENY"
    assert next(gate for gate in result.gates if gate.key == "cutover_approvals").passed is False
