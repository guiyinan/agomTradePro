import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.guardrail
def test_guardrail_governance_consistency_has_no_regressions():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_governance_consistency.py",
            "--baseline",
            "governance/governance_baseline.json",
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
    assert report["baseline_version"] == "2026-04-24.v1"
    assert report["violation_count"] == 0

    section_names = {section["name"] for section in report["sections"]}
    assert section_names == {
        "docs_consistency",
        "docs_links",
        "module_shape",
        "misplaced_app_config",
        "singular_dto_files",
        "application_third_party_imports",
    }
