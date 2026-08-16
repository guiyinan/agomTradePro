"""Static candidate identity consistency for the Web-to-TUI evidence set."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.web_to_tui_candidate_binding import build_candidate_binding

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "governance" / "active_plan_registry.json"
READINESS_PATH = ROOT / "docs" / "plans" / "web-to-tui-m5-readiness-2026-07-27.md"
DEPLOYMENT_PATH = ROOT / "docs" / "deployment" / "vps-deployment-evidence-2026-08-15.md"
PREFLIGHT_PATH = (
    ROOT / "docs" / "deployment" / "web-to-tui-deployment-preflight-20260816082603.json"
)
CUTOVER_PATH = ROOT / "config" / "tui" / "migration" / "web_to_tui_cutover_evidence.v1.json"
MATRIX_PATH = ROOT / "docs" / "plans" / "web-to-tui-migration-matrix-2026-07-25.csv"
GRAPH_PATH = ROOT / "config" / "tui" / "published" / "tui_operation_graph.published.json"
RUNTIME_MANIFEST_PATH = ROOT / "config" / "tui" / "agomtui-runtime.manifest.json"


def test_current_candidate_identity_is_consistent_across_registry_and_evidence() -> None:
    """Prevent stale release or runtime identity from reopening the cutover gate."""

    preflight = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
    release = preflight["release"]
    candidate_version = str(release["stable_version"])
    candidate_commit = str(release["source_commit"])
    assert str(preflight["oci_image"]["revision"]) == candidate_commit

    binding = build_candidate_binding(
        stable_version=candidate_version,
        candidate_commit=candidate_commit,
        matrix_path=MATRIX_PATH,
        graph_path=GRAPH_PATH,
        runtime_manifest_path=RUNTIME_MANIFEST_PATH,
    )
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    workstream = next(item for item in registry["workstreams"] if item["id"] == "web-to-tui-m5")
    next_gate = str(workstream["next_gate"])
    assert candidate_commit in next_gate
    assert candidate_version in next_gate

    readiness = READINESS_PATH.read_text(encoding="utf-8")
    deployment = DEPLOYMENT_PATH.read_text(encoding="utf-8")
    readiness_current = readiness.split("### 2026-08-16 00:46 当前候选部署复核", 1)[1]
    deployment_current = deployment.split("## 当前候选部署（2026-08-16 00:46 release）", 1)[1]
    assert candidate_commit in readiness_current
    assert candidate_version in readiness_current
    assert candidate_commit in deployment_current
    assert candidate_version in deployment_current

    cutover = json.loads(CUTOVER_PATH.read_text(encoding="utf-8"))
    cutover_candidate = cutover["candidate"]
    assert cutover_candidate["candidate_commit"] == candidate_commit
    assert cutover_candidate["stable_version"] == candidate_version
    assert cutover_candidate["deployment_preflight"]["source_commit"] == candidate_commit
    assert cutover_candidate["deployment_preflight"]["release_id"] == candidate_version
    for value in binding.values():
        assert f"`{value}`" in readiness_current or value in readiness_current
        assert f"`{value}`" in deployment_current or value in deployment_current
