"""Contract tests for the local AI-Native release gate."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_ai_native_release_gate import evaluate_release_gate

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/ai_native/ai_native_release_gate.v1.json"


def test_local_assets_pass_but_missing_external_evidence_denies() -> None:
    result = evaluate_release_gate(config_path=CONFIG, repo_root=ROOT)

    assert result.decision == "DENY"
    assert "staging_evidence" in result.reasons
    assert "manual_signoff" in result.reasons
    assert all(
        check.passed
        for check in result.checks
        if check.key not in {"staging_evidence", "manual_signoff"}
    )


def test_complete_evidence_requires_matching_candidate(tmp_path: Path) -> None:
    commit = "a" * 40
    staging = tmp_path / "staging.json"
    signoff = tmp_path / "signoff.json"
    staging.write_text(
        json.dumps(
            {
                "environment": "staging",
                "status": "PASS",
                "candidate_commit": commit,
                "test_manifest_sha256": "b" * 64,
            }
        ),
        encoding="utf-8",
    )
    signoff.write_text(
        json.dumps(
            {
                "status": "APPROVED",
                "candidate_commit": commit,
                "owner": "owner@example.invalid",
                "reviewer": "reviewer@example.invalid",
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_release_gate(
        config_path=CONFIG,
        repo_root=ROOT,
        staging_evidence=staging,
        manual_signoff=signoff,
    )

    assert result.decision == "ALLOW"
    assert "candidate_binding" not in result.reasons


def test_missing_asset_is_fail_closed(tmp_path: Path) -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config["required_assets"][0]["paths"].append("apps/agent_runtime/missing.py")
    altered = tmp_path / "gate.json"
    altered.write_text(json.dumps(config), encoding="utf-8")

    result = evaluate_release_gate(config_path=altered, repo_root=ROOT)

    assert result.decision == "DENY"
    assert "agent_runtime_api" in result.reasons
