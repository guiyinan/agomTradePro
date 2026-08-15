"""Static candidate identity consistency for the Web-to-TUI evidence set."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.web_to_tui_candidate_binding import build_candidate_binding

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "governance" / "active_plan_registry.json"
READINESS_PATH = ROOT / "docs" / "plans" / "web-to-tui-m5-readiness-2026-07-27.md"
DEPLOYMENT_PATH = ROOT / "docs" / "deployment" / "vps-deployment-evidence-2026-08-15.md"
MATRIX_PATH = ROOT / "docs" / "plans" / "web-to-tui-migration-matrix-2026-07-25.csv"
GRAPH_PATH = ROOT / "config" / "tui" / "published" / "tui_operation_graph.published.json"
RUNTIME_MANIFEST_PATH = ROOT / "config" / "tui" / "agomtui-runtime.manifest.json"

CANDIDATE_VERSION = "20260816004134"
CANDIDATE_COMMIT = "e167ab2fc748e4c93d2622f93fa8cc75442b2bb6"


def test_current_candidate_identity_is_consistent_across_registry_and_evidence() -> None:
    """Prevent stale release or runtime identity from reopening the cutover gate."""

    binding = build_candidate_binding(
        stable_version=CANDIDATE_VERSION,
        candidate_commit=CANDIDATE_COMMIT,
        matrix_path=MATRIX_PATH,
        graph_path=GRAPH_PATH,
        runtime_manifest_path=RUNTIME_MANIFEST_PATH,
    )
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    workstream = next(item for item in registry["workstreams"] if item["id"] == "web-to-tui-m5")
    next_gate = str(workstream["next_gate"])
    assert CANDIDATE_COMMIT in next_gate
    assert CANDIDATE_VERSION in next_gate

    readiness = READINESS_PATH.read_text(encoding="utf-8")
    deployment = DEPLOYMENT_PATH.read_text(encoding="utf-8")
    for value in binding.values():
        assert f"`{value}`" in readiness or value in readiness
        assert f"`{value}`" in deployment or value in deployment
