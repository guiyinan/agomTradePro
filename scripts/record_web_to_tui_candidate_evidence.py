#!/usr/bin/env python
"""Record candidate-bound M5 UAT, cleanup, and rollback evidence.

The command never accepts a caller-supplied pass flag. UAT and cleanup are
derived from fixed pytest suites and parsed JUnit results; rollback is derived
from the real isolated drill. The cutover projection is written only after the
raw report, route coverage, summary, and immutable candidate binding agree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any, cast

if __package__:
    from scripts.build_web_to_tui_rollback_catalog import (
        REQUIRED_CLEANUP_SCOPES,
        build_rollback_catalog,
        synchronize_candidate_evidence,
    )
    from scripts.drill_web_to_tui_rollback import run_drill
    from scripts.web_to_tui_candidate_binding import (
        CandidateBinding,
        binding_matches,
        build_candidate_binding,
    )
else:
    from build_web_to_tui_rollback_catalog import (  # type: ignore[no-redef]
        REQUIRED_CLEANUP_SCOPES,
        build_rollback_catalog,
        synchronize_candidate_evidence,
    )
    from drill_web_to_tui_rollback import run_drill
    from web_to_tui_candidate_binding import (
        CandidateBinding,
        binding_matches,
        build_candidate_binding,
    )

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
DEFAULT_EVIDENCE = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"
DEFAULT_GRAPH = ROOT / "config/tui/published/tui_operation_graph.published.json"
DEFAULT_RUNTIME_MANIFEST = ROOT / "config/tui/agomtui-runtime.manifest.json"
DEFAULT_REPORT_DIR = ROOT / "config/tui/migration/evidence"
UAT_SUITE = "tests/playwright/tests/uat/test_web_to_tui_m5.py"
CLEANUP_SUITE = "tests/component/test_web_to_tui_route_closure.py"
UAT_REPORT_VERSION = "web-to-tui-candidate-uat-report.v2"
CLEANUP_REPORT_VERSION = "web-to-tui-candidate-cleanup-report.v1"
ROLLBACK_REPORT_VERSION = "web-to-tui-candidate-rollback-report.v1"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

UAT_REQUIRED_CASES = frozenset(
    {
        "test_account_read_missing_fields_and_confirmation_cancel",
        "test_operator_group_can_open_queue_but_regular_user_cannot",
        "test_tui_core_layout_has_no_horizontal_overflow",
        "test_every_migrated_route_resolves_its_reviewed_tui_deep_link",
        "test_role_appropriate_direct_read_primary_tasks_complete",
        "test_parameterized_read_primary_tasks_complete",
        "test_strategy_create_detail_update_lifecycle_completes",
        "test_personal_ai_provider_detail_update_lifecycle_completes",
        "test_policy_admin_create_flows_complete",
        "test_governance_and_screening_confirmed_flows_complete",
        "test_local_fixture_detail_and_lifecycle_routes_complete",
        "test_sentiment_external_ai_primary_task_completes",
        "test_terminal_external_ai_primary_task_completes",
    }
)
UAT_EXPECTED_TESTS = 15
PRODUCTION_SAFE_UAT_REQUIRED_CASES = frozenset(
    {
        "test_account_read_missing_fields_and_confirmation_cancel",
        "test_operator_group_can_open_queue_but_regular_user_cannot",
        "test_tui_core_layout_has_no_horizontal_overflow",
        "test_every_migrated_route_resolves_its_reviewed_tui_deep_link",
        "test_role_appropriate_direct_read_primary_tasks_complete",
        "test_parameterized_read_primary_tasks_complete",
        "test_strategy_create_detail_update_lifecycle_completes",
        "test_personal_ai_provider_detail_update_lifecycle_completes",
    }
)
PRODUCTION_SAFE_UAT_EXPECTED_TESTS = 10
CLEANUP_REQUIRED_CASES = frozenset(
    {
        "test_all_classic_routes_preserve_the_anonymous_auth_boundary",
        "test_classic_compatibility_surfaces_publish_reviewed_tui_destinations",
        "test_route_actions_preserve_admin_and_operator_role_boundaries",
        "test_login_only_routes_require_authentication_for_their_visible_actions",
        "test_mixed_role_routes_keep_reads_available_and_admin_actions_restricted",
        "test_shared_research_routes_enforce_the_authenticated_backend_boundary",
        "test_every_migrated_route_has_task_level_empty_state_guidance",
        "test_every_migrated_route_has_bounded_task_level_error_recovery",
    }
)
CLEANUP_EXPECTED_TESTS = 8


class CandidateEvidenceError(RuntimeError):
    """Raised when raw evidence cannot safely update the cutover projection."""


@dataclass(frozen=True)
class CandidateContext:
    """Current cutover document and its verified immutable candidate identity."""

    evidence: dict[str, Any]
    binding: CandidateBinding
    routes: frozenset[str]


@dataclass(frozen=True)
class UatProfile:
    """Fixed suite and receipt contract for one recorder profile."""

    name: str
    required_cases: frozenset[str]
    expected_tests: int
    requires_external_ai: bool
    required_receipt_entities: frozenset[str]


UAT_PROFILES = {
    "full": UatProfile(
        name="full",
        required_cases=UAT_REQUIRED_CASES,
        expected_tests=UAT_EXPECTED_TESTS,
        requires_external_ai=True,
        required_receipt_entities=frozenset(),
    ),
    "production-safe": UatProfile(
        name="production-safe",
        required_cases=PRODUCTION_SAFE_UAT_REQUIRED_CASES,
        expected_tests=PRODUCTION_SAFE_UAT_EXPECTED_TESTS,
        requires_external_ai=False,
        required_receipt_entities=frozenset({"strategy", "ai_provider"}),
    ),
}


def _mapping(value: object) -> dict[str, Any]:
    """Narrow a JSON boundary value to a mapping."""

    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _load_object(path: Path) -> dict[str, Any]:
    """Load one JSON object or reject a non-object root."""

    value = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(value, dict):
        raise CandidateEvidenceError(f"JSON root must be an object: {path}")
    return cast(dict[str, Any], value)


def _normalized_bytes(path: Path) -> bytes:
    """Return text bytes using the same LF normalization as candidate binding."""

    text = path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _candidate_commit_contains_paths(commit: str, paths: Sequence[Path]) -> bool:
    """Return whether candidate stores the exact current content of every path."""

    if not COMMIT_PATTERN.fullmatch(commit):
        return False
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if ancestor.returncode:
        return False
    for path in paths:
        try:
            relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            return False
        result = subprocess.run(
            ["git", "show", f"{commit}:{relative}"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        if (
            result.returncode
            or hashlib.sha256(result.stdout).digest()
            != hashlib.sha256(_normalized_bytes(path)).digest()
        ):
            return False
    return True


def load_candidate_context(
    *,
    evidence_path: Path = DEFAULT_EVIDENCE,
    matrix_path: Path = DEFAULT_MATRIX,
    graph_path: Path = DEFAULT_GRAPH,
    runtime_manifest_path: Path = DEFAULT_RUNTIME_MANIFEST,
) -> CandidateContext:
    """Load a candidate only when its binding and committed sources are exact."""

    evidence = _load_object(evidence_path)
    candidate = _mapping(evidence.get("candidate"))
    stable_version = str(candidate.get("stable_version") or "").strip()
    candidate_commit = str(candidate.get("candidate_commit") or "").strip()
    if not stable_version or not candidate_commit:
        raise CandidateEvidenceError("cutover candidate version/commit is not established")
    binding = build_candidate_binding(
        stable_version=stable_version,
        candidate_commit=candidate_commit,
        matrix_path=matrix_path,
        graph_path=graph_path,
        runtime_manifest_path=runtime_manifest_path,
    )
    if not binding_matches(candidate.get("binding"), binding):
        raise CandidateEvidenceError("cutover candidate binding does not match current sources")
    if str(evidence.get("source_sha256") or "").strip() != binding["matrix_sha256"]:
        raise CandidateEvidenceError("cutover source_sha256 does not match candidate matrix")
    if not _candidate_commit_contains_paths(
        candidate_commit,
        (matrix_path, graph_path, runtime_manifest_path),
    ):
        raise CandidateEvidenceError("candidate commit does not contain current bound sources")
    catalog = build_rollback_catalog(matrix_path)
    return CandidateContext(evidence=evidence, binding=binding, routes=frozenset(catalog))


def _tag_name(element: ET.Element) -> str:
    """Return an XML tag without an optional namespace."""

    return element.tag.rsplit("}", 1)[-1]


def parse_junit_cases(path: Path) -> list[dict[str, Any]]:
    """Parse individual JUnit outcomes without trusting aggregate counters."""

    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise CandidateEvidenceError(f"invalid JUnit report: {exc}") from exc
    cases: list[dict[str, Any]] = []
    for element in root.iter():
        if _tag_name(element) != "testcase":
            continue
        name = str(element.attrib.get("name") or "").strip()
        classname = str(element.attrib.get("classname") or "").strip()
        if not name:
            raise CandidateEvidenceError("JUnit testcase is missing name")
        children = {_tag_name(child) for child in element}
        if "failure" in children:
            status = "failed"
        elif "error" in children:
            status = "error"
        elif "skipped" in children:
            status = "skipped"
        else:
            status = "passed"
        raw_duration = str(element.attrib.get("time") or "0").strip()
        try:
            duration = float(raw_duration)
        except ValueError as exc:
            raise CandidateEvidenceError(f"invalid JUnit duration for {name}") from exc
        if duration < 0:
            raise CandidateEvidenceError(f"negative JUnit duration for {name}")
        cases.append(
            {
                "classname": classname,
                "name": name,
                "status": status,
                "duration_seconds": duration,
            }
        )
    if not cases:
        raise CandidateEvidenceError("JUnit report contains no testcases")
    return cases


def _base_case_name(value: object) -> str:
    """Remove a pytest parameter suffix from a JUnit testcase name."""

    return str(value or "").split("[", 1)[0].strip()


def validate_suite_cases(
    cases: object,
    *,
    required_cases: frozenset[str],
    expected_tests: int,
) -> list[dict[str, Any]]:
    """Require the fixed complete suite with no failures, errors, or skips."""

    if not isinstance(cases, list):
        raise CandidateEvidenceError("suite cases must be an array")
    normalized = [_mapping(value) for value in cases]
    if len(normalized) != expected_tests:
        raise CandidateEvidenceError(
            f"suite executed {len(normalized)} tests; expected exactly {expected_tests}"
        )
    names = {_base_case_name(value.get("name")) for value in normalized}
    if names != required_cases:
        missing = sorted(required_cases - names)
        extra = sorted(names - required_cases)
        raise CandidateEvidenceError(f"suite case set mismatch: missing={missing}; extra={extra}")
    bad = [
        str(value.get("name") or "<unnamed>")
        for value in normalized
        if value.get("status") != "passed"
    ]
    if bad:
        raise CandidateEvidenceError(f"suite contains non-passing cases: {bad}")
    return normalized


def _route_result_paths(value: object) -> tuple[list[dict[str, Any]], set[str]]:
    """Return structured route results and their unique paths."""

    if not isinstance(value, list):
        raise CandidateEvidenceError("route_results must be an array")
    results = [_mapping(item) for item in value]
    paths = {str(item.get("template_path") or "").strip() for item in results}
    if "" in paths or len(paths) != len(results):
        raise CandidateEvidenceError("route_results contains blank or duplicate paths")
    return results, paths


def _uat_profile(name: str) -> UatProfile:
    """Return one fixed UAT profile or fail closed."""

    profile = UAT_PROFILES.get(str(name or "").strip())
    if profile is None:
        raise CandidateEvidenceError(f"unknown UAT profile: {name}")
    return profile


def _contains_sensitive_receipt_key(value: object) -> bool:
    """Return whether a receipt attempts to persist credential material."""

    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if any(token in normalized for token in ("password", "api_key", "token", "secret")):
                return True
            if _contains_sensitive_receipt_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_receipt_key(item) for item in value)
    return False


def validate_controlled_write_receipts(
    receipts: object,
    *,
    profile: UatProfile,
) -> list[dict[str, Any]]:
    """Validate exact actor-owned write/readback/cleanup receipts for a profile."""

    if not isinstance(receipts, list):
        raise CandidateEvidenceError("controlled write receipts must be an array")
    normalized = [_mapping(receipt) for receipt in receipts]
    if not profile.required_receipt_entities:
        if normalized:
            raise CandidateEvidenceError("full UAT does not accept partial controlled receipts")
        return normalized
    if len(normalized) != len(profile.required_receipt_entities):
        raise CandidateEvidenceError("controlled write receipt count mismatch")
    entities = {str(receipt.get("entity_type") or "").strip() for receipt in normalized}
    if entities != set(profile.required_receipt_entities):
        raise CandidateEvidenceError("controlled write receipt entity set mismatch")
    run_ids = {str(receipt.get("run_id") or "").strip() for receipt in normalized}
    if len(run_ids) != 1 or not next(iter(run_ids), ""):
        raise CandidateEvidenceError("controlled write receipts require one non-empty run ID")
    expected_actions = {
        "strategy": [
            "strategy.workbench-create",
            "strategy.workbench-update",
            "strategy.workbench-delete",
        ],
        "ai_provider": [
            "ai-ops.create-my-provider",
            "ai-ops.update-my-provider",
            "ai-ops.delete-my-provider",
        ],
    }
    expected_cleanup = {
        "strategy": "strategy.workbench-delete",
        "ai_provider": "ai-ops.delete-my-provider",
    }
    for receipt in normalized:
        entity = str(receipt.get("entity_type") or "")
        if receipt.get("version") != "web-to-tui-controlled-write-receipt.v1":
            raise CandidateEvidenceError(f"controlled write receipt version mismatch: {entity}")
        if _contains_sensitive_receipt_key(receipt):
            raise CandidateEvidenceError(
                f"controlled write receipt contains sensitive keys: {entity}"
            )
        entity_id = receipt.get("entity_id")
        if not isinstance(entity_id, int) or isinstance(entity_id, bool) or entity_id <= 0:
            raise CandidateEvidenceError(f"controlled write receipt entity ID invalid: {entity}")
        if not str(receipt.get("entity_name") or "").strip():
            raise CandidateEvidenceError(f"controlled write receipt entity name missing: {entity}")
        if (
            receipt.get("actor_username") != "m5_uat_regular"
            or receipt.get("owner_username") != "m5_uat_regular"
        ):
            raise CandidateEvidenceError(f"controlled write receipt actor/owner mismatch: {entity}")
        if receipt.get("write_actions") != expected_actions[entity]:
            raise CandidateEvidenceError(f"controlled write receipt action set mismatch: {entity}")
        confirmation = _mapping(receipt.get("confirmation"))
        if confirmation != {"cleanup": True, "create": True, "update": True}:
            raise CandidateEvidenceError(f"controlled write confirmation mismatch: {entity}")
        readback = _mapping(receipt.get("readback"))
        if (
            readback.get("created") is not True
            or readback.get("updated") is not True
            or not str(readback.get("updated_description") or "").strip()
        ):
            raise CandidateEvidenceError(f"controlled write readback mismatch: {entity}")
        settlement = _mapping(receipt.get("settlement"))
        if settlement.get("slo_ms") != 60_000:
            raise CandidateEvidenceError(f"controlled write settlement SLO mismatch: {entity}")
        for key in ("create_ms", "update_ms"):
            elapsed = settlement.get(key)
            if (
                not isinstance(elapsed, int)
                or isinstance(elapsed, bool)
                or elapsed < 0
                or elapsed > 60_000
            ):
                raise CandidateEvidenceError(
                    f"controlled write settlement observation invalid: {entity}/{key}"
                )
        cleanup = _mapping(receipt.get("cleanup"))
        if cleanup != {
            "action": expected_cleanup[entity],
            "deleted": True,
            "residual_count": 0,
        }:
            raise CandidateEvidenceError(f"controlled write cleanup mismatch: {entity}")
    return sorted(normalized, key=lambda receipt: str(receipt.get("entity_type") or ""))


def build_uat_report(
    *,
    binding: CandidateBinding,
    routes: frozenset[str],
    cases: list[dict[str, Any]],
    recorded_at: datetime,
    profile_name: str = "full",
    write_receipts: object = None,
) -> dict[str, Any]:
    """Build a UAT report solely from a verified full-suite JUnit result."""

    profile = _uat_profile(profile_name)
    checked_cases = validate_suite_cases(
        cases,
        required_cases=profile.required_cases,
        expected_tests=profile.expected_tests,
    )
    checked_receipts = validate_controlled_write_receipts(
        [] if write_receipts is None else write_receipts,
        profile=profile,
    )
    route_results = [{"template_path": route, "status": "passed"} for route in sorted(routes)]
    return {
        "version": UAT_REPORT_VERSION,
        "candidate_binding": binding,
        "recorded_at": _aware_iso(recorded_at),
        "profile": profile.name,
        "suite": {"path": UAT_SUITE, "cases": checked_cases},
        "route_results": route_results,
        "controlled_write_receipts": checked_receipts,
        "summary": {
            "executed_tests": len(checked_cases),
            "passed_tests": len(checked_cases),
            "failed_tests": 0,
            "skipped_tests": 0,
            "required_routes": len(routes),
            "passed_routes": len(routes),
            "controlled_write_receipts": len(checked_receipts),
        },
    }


def validate_uat_report(
    report: object,
    *,
    binding: CandidateBinding,
    routes: frozenset[str],
    expected_profile: str | None = None,
) -> None:
    """Recompute UAT route coverage and summary before projection."""

    value = _mapping(report)
    if value.get("version") != UAT_REPORT_VERSION:
        raise CandidateEvidenceError("unexpected UAT report version")
    if not binding_matches(value.get("candidate_binding"), binding):
        raise CandidateEvidenceError("UAT report candidate binding mismatch")
    profile = _uat_profile(str(value.get("profile") or ""))
    if expected_profile is not None and profile.name != expected_profile:
        raise CandidateEvidenceError("UAT report profile mismatch")
    suite = _mapping(value.get("suite"))
    if suite.get("path") != UAT_SUITE:
        raise CandidateEvidenceError("UAT report suite path mismatch")
    cases = validate_suite_cases(
        suite.get("cases"),
        required_cases=profile.required_cases,
        expected_tests=profile.expected_tests,
    )
    receipts = validate_controlled_write_receipts(
        value.get("controlled_write_receipts"),
        profile=profile,
    )
    route_results, paths = _route_result_paths(value.get("route_results"))
    if paths != set(routes) or any(item.get("status") != "passed" for item in route_results):
        raise CandidateEvidenceError("UAT route results do not exactly pass required routes")
    expected_summary = {
        "executed_tests": len(cases),
        "passed_tests": len(cases),
        "failed_tests": 0,
        "skipped_tests": 0,
        "required_routes": len(routes),
        "passed_routes": len(routes),
        "controlled_write_receipts": len(receipts),
    }
    if value.get("summary") != expected_summary:
        raise CandidateEvidenceError("UAT report summary does not match raw results")


def synchronize_uat_projection(
    evidence: dict[str, Any],
    *,
    binding: CandidateBinding,
    routes: frozenset[str],
    report_path: str,
    report_sha256: str,
    recorded_at: datetime,
) -> dict[str, Any]:
    """Replace UAT projection with recorder-derived candidate evidence."""

    evidence["uat"] = {
        "candidate_binding": binding,
        "evidence": report_path,
        "evidence_sha256": report_sha256,
        "performed_at": recorded_at.date().isoformat(),
        "passed_route_pages": sorted(routes),
    }
    return evidence


def _validate_bound_uat_projection(
    evidence: dict[str, Any],
    *,
    binding: CandidateBinding,
    routes: frozenset[str],
    root: Path,
) -> str:
    """Require cleanup to consume a recorder-generated UAT for this candidate."""

    uat = _mapping(evidence.get("uat"))
    if not binding_matches(uat.get("candidate_binding"), binding):
        raise CandidateEvidenceError("cleanup requires UAT bound to the same candidate")
    if set(uat.get("passed_route_pages") or []) != set(routes):
        raise CandidateEvidenceError("cleanup requires exact UAT route coverage")
    report_path = _resolve_repo_path(uat.get("evidence"), root=root)
    digest = str(uat.get("evidence_sha256") or "").strip()
    if report_path is None or not SHA256_PATTERN.fullmatch(digest):
        raise CandidateEvidenceError("cleanup requires a structured UAT report")
    if _file_sha256(report_path) != digest:
        raise CandidateEvidenceError("UAT report digest mismatch")
    report = _load_object(report_path)
    validate_uat_report(report, binding=binding, routes=routes)
    return digest


def build_cleanup_report(
    *,
    binding: CandidateBinding,
    routes: frozenset[str],
    cases: list[dict[str, Any]],
    catalog: dict[str, str],
    uat_evidence_sha256: str,
    recorded_at: datetime,
) -> dict[str, Any]:
    """Build six-scope cleanup evidence from fixed suites and rollback catalog."""

    checked_cases = validate_suite_cases(
        cases,
        required_cases=CLEANUP_REQUIRED_CASES,
        expected_tests=CLEANUP_EXPECTED_TESTS,
    )
    if set(catalog) != set(routes):
        raise CandidateEvidenceError("rollback catalog does not match required routes")
    scopes = list(REQUIRED_CLEANUP_SCOPES)
    route_results = [
        {
            "template_path": route,
            "status": "passed",
            "scopes": scopes,
            "rollback_commit": catalog[route],
        }
        for route in sorted(routes)
    ]
    return {
        "version": CLEANUP_REPORT_VERSION,
        "candidate_binding": binding,
        "recorded_at": _aware_iso(recorded_at),
        "suite": {"path": CLEANUP_SUITE, "cases": checked_cases},
        "uat_evidence_sha256": uat_evidence_sha256,
        "route_results": route_results,
        "summary": {
            "executed_tests": len(checked_cases),
            "passed_tests": len(checked_cases),
            "required_routes": len(routes),
            "fully_closed_routes": len(routes),
            "scope_counts": {scope: len(routes) for scope in scopes},
        },
    }


def validate_cleanup_report(
    report: object,
    *,
    binding: CandidateBinding,
    routes: frozenset[str],
    catalog: dict[str, str],
    uat_evidence_sha256: str,
) -> None:
    """Recompute all cleanup scopes and rollback mapping before projection."""

    value = _mapping(report)
    if value.get("version") != CLEANUP_REPORT_VERSION:
        raise CandidateEvidenceError("unexpected cleanup report version")
    if not binding_matches(value.get("candidate_binding"), binding):
        raise CandidateEvidenceError("cleanup report candidate binding mismatch")
    if value.get("uat_evidence_sha256") != uat_evidence_sha256:
        raise CandidateEvidenceError("cleanup report UAT digest mismatch")
    suite = _mapping(value.get("suite"))
    if suite.get("path") != CLEANUP_SUITE:
        raise CandidateEvidenceError("cleanup report suite path mismatch")
    cases = validate_suite_cases(
        suite.get("cases"),
        required_cases=CLEANUP_REQUIRED_CASES,
        expected_tests=CLEANUP_EXPECTED_TESTS,
    )
    route_results, paths = _route_result_paths(value.get("route_results"))
    if paths != set(routes):
        raise CandidateEvidenceError("cleanup report route set mismatch")
    expected_scopes = list(REQUIRED_CLEANUP_SCOPES)
    for item in route_results:
        route = str(item.get("template_path") or "")
        if (
            item.get("status") != "passed"
            or item.get("scopes") != expected_scopes
            or item.get("rollback_commit") != catalog.get(route)
        ):
            raise CandidateEvidenceError(f"cleanup route result mismatch: {route}")
    expected_summary = {
        "executed_tests": len(cases),
        "passed_tests": len(cases),
        "required_routes": len(routes),
        "fully_closed_routes": len(routes),
        "scope_counts": {scope: len(routes) for scope in expected_scopes},
    }
    if value.get("summary") != expected_summary:
        raise CandidateEvidenceError("cleanup report summary does not match raw results")


def build_rollback_report(
    *,
    binding: CandidateBinding,
    drill: dict[str, Any],
    recorded_at: datetime,
) -> dict[str, Any]:
    """Wrap one newly executed drill in the exact candidate identity."""

    summary = _rollback_summary(drill)
    report = {
        "version": ROLLBACK_REPORT_VERSION,
        "candidate_binding": binding,
        "recorded_at": _aware_iso(recorded_at),
        "drill": drill,
        "summary": summary,
    }
    validate_rollback_report(report, binding=binding)
    return report


def validate_rollback_report(report: object, *, binding: CandidateBinding) -> None:
    """Require drill v2 to match its binding and internally derived manifests."""

    value = _mapping(report)
    if value.get("version") != ROLLBACK_REPORT_VERSION:
        raise CandidateEvidenceError("unexpected rollback report version")
    if not binding_matches(value.get("candidate_binding"), binding):
        raise CandidateEvidenceError("rollback report candidate binding mismatch")
    drill = _mapping(value.get("drill"))
    if drill.get("version") != "web-to-tui-rollback-drill.v2":
        raise CandidateEvidenceError("unexpected rollback drill version")
    if not binding_matches(drill.get("candidate_binding"), binding):
        raise CandidateEvidenceError("rollback drill candidate binding mismatch")
    candidate_contract = _mapping(drill.get("candidate_contract"))
    candidate_runtime = _mapping(drill.get("candidate_runtime"))
    if (
        drill.get("ok") is not True
        or drill.get("working_tree_read_as_candidate") is not False
        or drill.get("working_tree_unchanged") is not True
    ):
        raise CandidateEvidenceError("rollback drill did not complete cleanly")
    for key in ("wave", "scope", "migration_anchor_path"):
        if not str(drill.get(key) or "").strip():
            raise CandidateEvidenceError(f"rollback drill {key} is missing")
    for key in ("migration_commit", "baseline_commit"):
        commit = str(drill.get(key) or "").strip()
        if not COMMIT_PATTERN.fullmatch(commit):
            raise CandidateEvidenceError(f"rollback drill {key} is invalid")
    if drill.get("migration_commit") == drill.get("baseline_commit"):
        raise CandidateEvidenceError("rollback drill migration and baseline commits are identical")
    rollback_commits = _mapping(drill.get("matrix_rollback_commits"))
    if not rollback_commits or any(
        not isinstance(path, str)
        or not path.strip()
        or not isinstance(commit, str)
        or not COMMIT_PATTERN.fullmatch(commit)
        for path, commit in rollback_commits.items()
    ):
        raise CandidateEvidenceError("rollback drill matrix rollback commits are invalid")
    manifests = drill.get("artifact_manifest")
    if not isinstance(manifests, list) or not manifests:
        raise CandidateEvidenceError("rollback drill artifact manifest is empty")
    manifest_rows = [_mapping(item) for item in manifests]
    manifest_paths = {str(item.get("path") or "").strip() for item in manifest_rows}
    if "" in manifest_paths or len(manifest_paths) != len(manifest_rows):
        raise CandidateEvidenceError("rollback drill artifact paths are blank or duplicated")
    transition_counts = dict.fromkeys(("added", "modified", "deleted", "unchanged"), 0)
    for item in manifest_rows:
        transition = str(item.get("transition") or "")
        if transition not in transition_counts:
            raise CandidateEvidenceError("rollback drill artifact transition is invalid")
        baseline_sha = item.get("baseline_sha256")
        candidate_sha = item.get("candidate_sha256")
        baseline_ok = isinstance(baseline_sha, str) and bool(SHA256_PATTERN.fullmatch(baseline_sha))
        candidate_ok = isinstance(candidate_sha, str) and bool(
            SHA256_PATTERN.fullmatch(candidate_sha)
        )
        transition_valid = {
            "added": baseline_sha is None and candidate_ok,
            "modified": baseline_ok and candidate_ok and baseline_sha != candidate_sha,
            "deleted": baseline_ok and candidate_sha is None,
            "unchanged": baseline_ok and candidate_ok and baseline_sha == candidate_sha,
        }[transition]
        if not transition_valid:
            raise CandidateEvidenceError(
                f"rollback drill artifact digest transition mismatch: {item.get('path')}"
            )
        transition_counts[transition] += 1
    if drill.get("transition_counts") != transition_counts:
        raise CandidateEvidenceError("rollback drill transition summary mismatch")
    patch_sha = drill.get("patch_sha256")
    if not isinstance(patch_sha, str) or not SHA256_PATTERN.fullmatch(patch_sha):
        raise CandidateEvidenceError("rollback drill patch digest is invalid")
    if drill.get("candidate_graph_hash") != binding["graph_sha256"]:
        raise CandidateEvidenceError("rollback drill graph hash mismatch")
    if candidate_contract.get("schema_version") != binding["schema_version"]:
        raise CandidateEvidenceError("rollback drill schema version mismatch")
    for key in ("screens", "actions"):
        count = candidate_contract.get(key)
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise CandidateEvidenceError(f"rollback drill candidate {key} count is invalid")
    if (
        candidate_runtime.get("version") != binding["runtime_version"]
        or candidate_runtime.get("build_id") != binding["runtime_build_id"]
        or candidate_runtime.get("manifest_sha256") != binding["runtime_manifest_sha256"]
    ):
        raise CandidateEvidenceError("rollback drill runtime binding mismatch")
    verified_files = candidate_runtime.get("verified_files")
    if (
        isinstance(verified_files, bool)
        or not isinstance(verified_files, int)
        or verified_files <= 0
    ):
        raise CandidateEvidenceError("rollback drill runtime verified_files is invalid")
    baseline_hash = drill.get("baseline_graph_hash")
    if not isinstance(baseline_hash, str) or not SHA256_PATTERN.fullmatch(baseline_hash):
        raise CandidateEvidenceError("rollback drill baseline graph hash is invalid")
    for key in ("rollback_seconds", "restore_seconds", "total_seconds"):
        value_seconds = drill.get(key)
        if (
            isinstance(value_seconds, bool)
            or not isinstance(value_seconds, (int, float))
            or value_seconds < 0
        ):
            raise CandidateEvidenceError(f"rollback drill {key} is invalid")
    expected_summary = _rollback_summary(drill)
    if value.get("summary") != expected_summary:
        raise CandidateEvidenceError("rollback report summary does not match drill")


def _rollback_summary(drill: dict[str, Any]) -> dict[str, Any]:
    """Derive the compact rollback projection from raw drill v2 fields."""

    manifests = drill.get("artifact_manifest")
    artifact_count = len(manifests) if isinstance(manifests, list) else 0
    return {
        "passed": drill.get("ok") is True,
        "wave": drill.get("wave"),
        "candidate_commit": _mapping(drill.get("candidate_binding")).get("candidate_commit"),
        "baseline_commit": drill.get("baseline_commit"),
        "migration_commit": drill.get("migration_commit"),
        "artifact_count": artifact_count,
        "transition_counts": drill.get("transition_counts"),
        "patch_sha256": drill.get("patch_sha256"),
        "candidate_graph_hash": drill.get("candidate_graph_hash"),
        "schema_version": _mapping(drill.get("candidate_contract")).get("schema_version"),
    }


def synchronize_rollback_projection(
    evidence: dict[str, Any],
    *,
    binding: CandidateBinding,
    report_path: str,
    report_sha256: str,
    recorded_at: datetime,
) -> dict[str, Any]:
    """Replace rollback projection while preserving same-candidate backup evidence."""

    existing = _mapping(evidence.get("rollback"))
    evidence["rollback"] = {
        "candidate_binding": binding,
        "passed": True,
        "environment": "local",
        "performed_at": recorded_at.date().isoformat(),
        "evidence": report_path,
        "evidence_sha256": report_sha256,
        "production_registry_backup": existing.get("production_registry_backup"),
    }
    return evidence


def _aware_iso(value: datetime) -> str:
    """Return a UTC ISO timestamp and reject naive clocks."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise CandidateEvidenceError("recorded_at must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _file_sha256(path: Path) -> str:
    """Return the exact on-disk SHA-256 used by readiness for JSON evidence."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_repo_path(value: object, *, root: Path = ROOT) -> Path | None:
    """Resolve one repository-contained existing evidence path."""

    if not isinstance(value, str) or not value.strip():
        return None
    relative = Path(value.strip())
    if relative.is_absolute():
        return None
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        return None
    return resolved


def _relative_report_path(path: Path, *, root: Path = ROOT) -> str:
    """Return a POSIX repository-relative report path or fail closed."""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise CandidateEvidenceError(
            "evidence report must be stored inside the repository"
        ) from exc


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    """Write one deterministic JSON report and return its exact byte digest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _file_sha256(path)


def _run_command(
    command: Sequence[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one fixed evidence command with captured diagnostics."""

    return subprocess.run(
        list(command),
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env=env,
    )


def _require_command_success(result: subprocess.CompletedProcess[str], *, label: str) -> None:
    """Reject a failed fixed suite without interpreting CLI claims."""

    if result.returncode:
        output = f"{result.stdout}\n{result.stderr}".strip()
        raise CandidateEvidenceError(f"{label} failed:\n{output[-4000:]}")


def record_uat(
    *,
    context: CandidateContext,
    evidence_path: Path,
    report_path: Path,
    cases: list[dict[str, Any]],
    recorded_at: datetime,
    profile_name: str = "full",
    write_receipts: object = None,
) -> None:
    """Validate raw UAT cases, write report, then update its projection."""

    report = build_uat_report(
        binding=context.binding,
        routes=context.routes,
        cases=cases,
        recorded_at=recorded_at,
        profile_name=profile_name,
        write_receipts=write_receipts,
    )
    validate_uat_report(
        report,
        binding=context.binding,
        routes=context.routes,
        expected_profile=profile_name,
    )
    digest = _write_json(report_path, report)
    synchronize_uat_projection(
        context.evidence,
        binding=context.binding,
        routes=context.routes,
        report_path=_relative_report_path(report_path),
        report_sha256=digest,
        recorded_at=recorded_at,
    )
    _write_json(evidence_path, context.evidence)


def record_cleanup(
    *,
    context: CandidateContext,
    evidence_path: Path,
    matrix_path: Path,
    report_path: Path,
    cases: list[dict[str, Any]],
    recorded_at: datetime,
) -> None:
    """Validate closure suite/UAT/catalog, write report, then update projection."""

    uat_digest = _validate_bound_uat_projection(
        context.evidence,
        binding=context.binding,
        routes=context.routes,
        root=ROOT,
    )
    catalog = build_rollback_catalog(matrix_path)
    report = build_cleanup_report(
        binding=context.binding,
        routes=context.routes,
        cases=cases,
        catalog=catalog,
        uat_evidence_sha256=uat_digest,
        recorded_at=recorded_at,
    )
    validate_cleanup_report(
        report,
        binding=context.binding,
        routes=context.routes,
        catalog=catalog,
        uat_evidence_sha256=uat_digest,
    )
    digest = _write_json(report_path, report)
    synchronize_candidate_evidence(
        context.evidence,
        catalog,
        candidate_binding=context.binding,
        report_path=_relative_report_path(report_path),
        report_sha256=digest,
    )
    _write_json(evidence_path, context.evidence)


def record_rollback(
    *,
    context: CandidateContext,
    evidence_path: Path,
    report_path: Path,
    drill: dict[str, Any],
    recorded_at: datetime,
) -> None:
    """Validate a newly executed drill, write report, then update projection."""

    report = build_rollback_report(
        binding=context.binding,
        drill=drill,
        recorded_at=recorded_at,
    )
    digest = _write_json(report_path, report)
    synchronize_rollback_projection(
        context.evidence,
        binding=context.binding,
        report_path=_relative_report_path(report_path),
        report_sha256=digest,
        recorded_at=recorded_at,
    )
    _write_json(evidence_path, context.evidence)


def _load_write_receipts(path: Path) -> list[dict[str, Any]]:
    """Load JSON-lines receipts written only by fixed browser lifecycle tests."""

    if not path.is_file():
        return []
    receipts: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = cast(Any, json.loads(line))
        except json.JSONDecodeError as exc:
            raise CandidateEvidenceError(
                f"invalid controlled write receipt JSON at line {line_number}"
            ) from exc
        if not isinstance(value, dict):
            raise CandidateEvidenceError(
                f"controlled write receipt line {line_number} must be an object"
            )
        receipts.append(cast(dict[str, Any], value))
    return receipts


def _run_uat_suite(
    args: argparse.Namespace,
    junit_path: Path,
    receipt_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute one fixed managed live-server UAT profile and parse evidence."""

    profile = _uat_profile(args.uat_profile)
    if (
        profile.requires_external_ai
        and os.environ.get("AGOM_M5_EXTERNAL_AI_UAT", "").lower() not in TRUE_VALUES
    ):
        raise CandidateEvidenceError(
            "AGOM_M5_EXTERNAL_AI_UAT=1 is required; skipped external AI tests are invalid"
        )
    run_id = os.environ.get("AGOM_REMOTE_UAT_RUN_ID", "").strip()
    if profile.required_receipt_entities and not run_id:
        raise CandidateEvidenceError(
            "production-safe UAT requires one explicit AGOM_REMOTE_UAT_RUN_ID"
        )
    command = [
        sys.executable,
        str(ROOT / "scripts/run_live_server_pytest.py"),
        "--suite-name",
        "web-to-tui-m5-candidate-uat",
        "--base-url",
        args.base_url,
        "--port",
        str(args.port),
        "--settings-module",
        args.settings_module,
        "--min-tests",
        str(profile.expected_tests),
        "--junitxml",
        str(junit_path),
    ]
    if args.skip_server:
        command.append("--skip-server")
    selected_tests = (
        [UAT_SUITE]
        if profile.name == "full"
        else [f"{UAT_SUITE}::{name}" for name in sorted(profile.required_cases)]
    )
    command.extend(
        [
            "--",
            *selected_tests,
            "--reuse-db",
            "--browser=chromium",
            "--screenshot=only-on-failure",
            "-q",
        ]
    )
    command_env = dict(os.environ)
    if profile.required_receipt_entities:
        command_env["AGOM_M5_UAT_RECEIPT_PATH"] = str(receipt_path)
    else:
        command_env.pop("AGOM_M5_UAT_RECEIPT_PATH", None)
    result = _run_command(command, env=command_env)
    _require_command_success(result, label="candidate UAT suite")
    return parse_junit_cases(junit_path), _load_write_receipts(receipt_path)


def _run_cleanup_suite(junit_path: Path) -> list[dict[str, Any]]:
    """Execute the fixed matrix-driven closure suite and parse JUnit."""

    command = [
        sys.executable,
        "-m",
        "pytest",
        CLEANUP_SUITE,
        "-q",
        f"--junitxml={junit_path}",
    ]
    result = _run_command(command)
    _require_command_success(result, label="candidate cleanup suite")
    return parse_junit_cases(junit_path)


def _build_parser() -> argparse.ArgumentParser:
    """Build CLI arguments without any caller-controlled pass state."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("uat", "cleanup", "rollback"))
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--runtime-manifest", type=Path, default=DEFAULT_RUNTIME_MANIFEST)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8766")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--settings-module", default="core.settings.playwright")
    parser.add_argument("--skip-server", action="store_true")
    parser.add_argument("--uat-profile", choices=tuple(UAT_PROFILES), default="full")
    return parser


def main() -> int:
    """Run one fixed evidence producer and update cutover evidence on success."""

    args = _build_parser().parse_args()
    evidence_path = args.evidence.resolve()
    matrix_path = args.matrix.resolve()
    report_path = (
        args.report.resolve()
        if args.report
        else (
            DEFAULT_REPORT_DIR
            / (
                f"web_to_tui_{args.kind}_candidate.{args.uat_profile}.v2.json"
                if args.kind == "uat"
                else f"web_to_tui_{args.kind}_candidate.v1.json"
            )
        ).resolve()
    )
    try:
        context = load_candidate_context(
            evidence_path=evidence_path,
            matrix_path=matrix_path,
            graph_path=args.graph.resolve(),
            runtime_manifest_path=args.runtime_manifest.resolve(),
        )
        now = datetime.now(UTC)
        with tempfile.TemporaryDirectory(prefix=f"agom-m5-{args.kind}-") as temp_dir:
            junit_path = Path(temp_dir) / "results.xml"
            receipt_path = Path(temp_dir) / "controlled-write-receipts.jsonl"
            if args.kind == "uat":
                cases, write_receipts = _run_uat_suite(args, junit_path, receipt_path)
                record_uat(
                    context=context,
                    evidence_path=evidence_path,
                    report_path=report_path,
                    cases=cases,
                    recorded_at=now,
                    profile_name=args.uat_profile,
                    write_receipts=write_receipts,
                )
            elif args.kind == "cleanup":
                cases = _run_cleanup_suite(junit_path)
                record_cleanup(
                    context=context,
                    evidence_path=evidence_path,
                    matrix_path=matrix_path,
                    report_path=report_path,
                    cases=cases,
                    recorded_at=now,
                )
            else:
                drill = run_drill(
                    candidate_version=context.binding["candidate_version"],
                    candidate_revision=context.binding["candidate_commit"],
                )
                record_rollback(
                    context=context,
                    evidence_path=evidence_path,
                    report_path=report_path,
                    drill=drill,
                    recorded_at=now,
                )
    except (CandidateEvidenceError, OSError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"Web-to-TUI candidate {args.kind} evidence: FAIL - {exc}")
        return 1
    print(
        f"Web-to-TUI candidate {args.kind} evidence: PASS - "
        f"candidate={context.binding['candidate_commit']} report={_relative_report_path(report_path)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
