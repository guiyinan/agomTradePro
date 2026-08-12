"""Fail-closed contracts for candidate-bound M5 evidence recording."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from scripts.build_web_to_tui_rollback_catalog import synchronize_candidate_evidence
from scripts.record_web_to_tui_candidate_evidence import (
    CLEANUP_REQUIRED_CASES,
    UAT_REQUIRED_CASES,
    CandidateEvidenceError,
    build_cleanup_report,
    build_rollback_report,
    build_uat_report,
    parse_junit_cases,
    synchronize_rollback_projection,
    synchronize_uat_projection,
    validate_cleanup_report,
    validate_rollback_report,
    validate_suite_cases,
    validate_uat_report,
)
from scripts.web_to_tui_candidate_binding import CandidateBinding

NOW = datetime(2026, 8, 13, 8, 30, tzinfo=timezone.utc)
ROUTES = frozenset({"templates/one.html", "templates/two.html"})
CATALOG = {route: "a" * 40 for route in ROUTES}


def _binding(*, commit: str = "b" * 40) -> CandidateBinding:
    """Build a complete synthetic immutable candidate identity."""

    return {
        "version": "web-to-tui-candidate-binding.v1",
        "candidate_version": "0.9.0-rc1",
        "candidate_commit": commit,
        "matrix_sha256": "1" * 64,
        "graph_sha256": "2" * 64,
        "schema_version": "tui_metadata.v3",
        "runtime_version": "0.2.0",
        "runtime_build_id": "agomtui-runtime-test",
        "runtime_manifest_sha256": "3" * 64,
    }


def _cases(required: frozenset[str], *, layout_parameters: bool = False) -> list[dict[str, Any]]:
    """Return fixed-suite passing JUnit cases."""

    values: list[dict[str, Any]] = []
    for name in sorted(required):
        names = (
            [f"{name}[desktop]", f"{name}[tablet]", f"{name}[mobile]"]
            if layout_parameters and name == "test_tui_core_layout_has_no_horizontal_overflow"
            else [name]
        )
        values.extend(
            {
                "classname": "candidate-suite",
                "name": case_name,
                "status": "passed",
                "duration_seconds": 0.1,
            }
            for case_name in names
        )
    return values


def _uat_cases() -> list[dict[str, Any]]:
    return _cases(UAT_REQUIRED_CASES, layout_parameters=True)


def _cleanup_cases() -> list[dict[str, Any]]:
    return _cases(CLEANUP_REQUIRED_CASES)


def _drill(binding: CandidateBinding) -> dict[str, Any]:
    """Return a successful raw rollback drill matching production manifests."""

    return {
        "version": "web-to-tui-rollback-drill.v2",
        "ok": True,
        "wave": "M4-simulated-accounts-w51",
        "scope": "isolated candidate rollback",
        "candidate_binding": binding,
        "migration_anchor_path": "apps/example/new.py",
        "migration_commit": "d" * 40,
        "baseline_commit": "e" * 40,
        "matrix_rollback_commits": {"templates/one.html": "a" * 40},
        "artifact_manifest": [
            {
                "path": "apps/example/new.py",
                "transition": "added",
                "baseline_sha256": None,
                "candidate_sha256": "5" * 64,
            },
            {
                "path": "config/tui/example.json",
                "transition": "modified",
                "baseline_sha256": "6" * 64,
                "candidate_sha256": "7" * 64,
            },
        ],
        "transition_counts": {"added": 1, "modified": 1, "deleted": 0, "unchanged": 0},
        "patch_sha256": "8" * 64,
        "baseline_graph_hash": "4" * 64,
        "candidate_graph_hash": binding["graph_sha256"],
        "baseline_contract": {
            "schema_version": "old",
            "schema_sha256": "9" * 64,
            "screens": 1,
            "actions": 1,
        },
        "candidate_contract": {
            "schema_version": binding["schema_version"],
            "schema_sha256": "a" * 64,
            "screens": 10,
            "actions": 20,
        },
        "baseline_runtime": {
            "version": "0.1.0",
            "build_id": "baseline",
            "manifest_sha256": "b" * 64,
            "verified_files": 1,
        },
        "candidate_runtime": {
            "version": binding["runtime_version"],
            "build_id": binding["runtime_build_id"],
            "manifest_sha256": binding["runtime_manifest_sha256"],
            "verified_files": 2,
        },
        "rollback_seconds": 1.0,
        "restore_seconds": 1.5,
        "total_seconds": 2.5,
        "working_tree_read_as_candidate": False,
        "working_tree_unchanged": True,
    }


def test_junit_parser_and_suite_validation_reject_skips() -> None:
    """Aggregate counters cannot hide a skipped external-provider UAT case."""

    junit = Path(".tmp_m5_candidate_recorder_uat.xml")
    try:
        junit.write_text(
            "<testsuite tests='1' failures='0' errors='0' skipped='0'>"
            "<testcase classname='uat' name='external'><skipped/></testcase>"
            "</testsuite>",
            encoding="utf-8",
        )
        cases = parse_junit_cases(junit)
    finally:
        junit.unlink(missing_ok=True)

    assert cases[0]["status"] == "skipped"
    with pytest.raises(CandidateEvidenceError, match="non-passing"):
        validate_suite_cases(
            cases,
            required_cases=frozenset({"external"}),
            expected_tests=1,
        )


def test_uat_report_recomputes_route_coverage_summary_and_projection() -> None:
    """Only exact passing routes and raw-suite counts reach cutover evidence."""

    binding = _binding()
    report = build_uat_report(
        binding=binding,
        routes=ROUTES,
        cases=_uat_cases(),
        recorded_at=NOW,
    )

    validate_uat_report(report, binding=binding, routes=ROUTES)
    evidence: dict[str, Any] = {"uat": {"passed_route_pages": ["stale"]}}
    synchronize_uat_projection(
        evidence,
        binding=binding,
        routes=ROUTES,
        report_path="config/tui/migration/evidence/uat.json",
        report_sha256="5" * 64,
        recorded_at=NOW,
    )

    assert evidence["uat"] == {
        "candidate_binding": binding,
        "evidence": "config/tui/migration/evidence/uat.json",
        "evidence_sha256": "5" * 64,
        "performed_at": "2026-08-13",
        "passed_route_pages": sorted(ROUTES),
    }

    tampered = deepcopy(report)
    tampered["summary"]["passed_routes"] = 1
    with pytest.raises(CandidateEvidenceError, match="summary"):
        validate_uat_report(tampered, binding=binding, routes=ROUTES)


def test_cleanup_report_joins_same_candidate_uat_suite_and_catalog() -> None:
    """Six cleanup scopes are derived together and replace stale projections."""

    binding = _binding()
    report = build_cleanup_report(
        binding=binding,
        routes=ROUTES,
        cases=_cleanup_cases(),
        catalog=CATALOG,
        uat_evidence_sha256="6" * 64,
        recorded_at=NOW,
    )

    validate_cleanup_report(
        report,
        binding=binding,
        routes=ROUTES,
        catalog=CATALOG,
        uat_evidence_sha256="6" * 64,
    )
    evidence: dict[str, Any] = {"cleanup": {"scope_coverage": {"stale": {}}}}
    synchronize_candidate_evidence(
        evidence,
        CATALOG,
        candidate_binding=binding,
        report_path="config/tui/migration/evidence/cleanup.json",
        report_sha256="7" * 64,
    )

    cleanup = evidence["cleanup"]
    assert cleanup["candidate_binding"] == binding
    assert cleanup["passed_route_pages"] == sorted(ROUTES)
    assert set(cleanup["scope_coverage"]) == {
        "primary_task",
        "permission",
        "empty_state",
        "error_state",
        "legacy_url",
        "rollback",
    }
    assert cleanup["route_rollback_commits"] == dict(sorted(CATALOG.items()))

    tampered = deepcopy(report)
    tampered["route_results"][0]["rollback_commit"] = "f" * 40
    with pytest.raises(CandidateEvidenceError, match="route result"):
        validate_cleanup_report(
            tampered,
            binding=binding,
            routes=ROUTES,
            catalog=CATALOG,
            uat_evidence_sha256="6" * 64,
        )


def test_rollback_report_validates_real_drill_manifests_before_projection() -> None:
    """A graph-only or path-shortened drill cannot be promoted as passed."""

    binding = _binding()
    report = build_rollback_report(binding=binding, drill=_drill(binding), recorded_at=NOW)

    validate_rollback_report(report, binding=binding)
    evidence: dict[str, Any] = {
        "rollback": {
            "production_registry_backup": {"candidate_commit": binding["candidate_commit"]}
        }
    }
    synchronize_rollback_projection(
        evidence,
        binding=binding,
        report_path="config/tui/migration/evidence/rollback.json",
        report_sha256="8" * 64,
        recorded_at=NOW,
    )

    assert evidence["rollback"]["passed"] is True
    assert evidence["rollback"]["candidate_binding"] == binding
    assert evidence["rollback"]["production_registry_backup"] == {
        "candidate_commit": binding["candidate_commit"]
    }

    tampered = deepcopy(report)
    tampered["drill"]["artifact_manifest"][1]["path"] = "apps/example/new.py"
    with pytest.raises(CandidateEvidenceError, match="artifact paths"):
        validate_rollback_report(tampered, binding=binding)


def test_candidate_change_invalidates_every_prior_report() -> None:
    """A new candidate commit can never reuse a prior candidate report."""

    old = _binding(commit="b" * 40)
    current = _binding(commit="c" * 40)
    uat_report = build_uat_report(
        binding=old,
        routes=ROUTES,
        cases=_uat_cases(),
        recorded_at=NOW,
    )
    with pytest.raises(CandidateEvidenceError, match="binding mismatch"):
        validate_uat_report(uat_report, binding=current, routes=ROUTES)

    cleanup_report = build_cleanup_report(
        binding=old,
        routes=ROUTES,
        cases=_cleanup_cases(),
        catalog=CATALOG,
        uat_evidence_sha256="6" * 64,
        recorded_at=NOW,
    )
    with pytest.raises(CandidateEvidenceError, match="binding mismatch"):
        validate_cleanup_report(
            cleanup_report,
            binding=current,
            routes=ROUTES,
            catalog=CATALOG,
            uat_evidence_sha256="6" * 64,
        )

    rollback_report = build_rollback_report(binding=old, drill=_drill(old), recorded_at=NOW)
    with pytest.raises(CandidateEvidenceError, match="binding mismatch"):
        validate_rollback_report(rollback_report, binding=current)
