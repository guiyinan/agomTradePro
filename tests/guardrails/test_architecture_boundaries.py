import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.guardrail
def test_guardrail_architecture_boundaries_have_no_violations():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_architecture.py",
            "--rules-file",
            "governance/architecture_rules.json",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout or result.stderr
    report = json.loads(result.stdout)
    assert report["rules_version"] == "2026-03-12.v1"
    assert report["violation_count"] == 0
    rule_ids = set()
    with open(REPO_ROOT / "governance/architecture_rules.json", "r", encoding="utf-8") as fh:
        ruleset = json.load(fh)
        rule_ids = {rule["id"] for rule in ruleset["boundary_rules"]}

    assert "regime_runtime_no_macro_impl_imports" in rule_ids
    assert "events_no_direct_downstream_models_or_handlers" in rule_ids


@pytest.mark.guardrail
def test_guardrail_module_ledger_can_be_generated(tmp_path):
    ledger_path = tmp_path / "module-ledger.md"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_architecture.py",
            "--rules-file",
            "governance/architecture_rules.json",
            "--write-ledger",
            str(ledger_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout or result.stderr
    content = ledger_path.read_text(encoding="utf-8")
    assert "# Module Ledger" in content
    assert "regime_runtime_no_macro_impl_imports" in content
    assert "`regime`" in content
    assert "No boundary violations detected." in content
