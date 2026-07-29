"""Tests for multi-scope quality report projection."""

import argparse
import json
from pathlib import Path

from scripts.generate_quality_report import (
    generate_nightly_report,
    load_repository_coverage_minimum,
    parse_coverage_xml,
)


def _write_coverage(path: Path, *, line_rate: float, branch_rate: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            '<?xml version="1.0" ?>\n'
            f'<coverage line-rate="{line_rate}" lines-valid="100" '
            f'lines-covered="{int(line_rate * 100)}" '
            'branches-valid="20" '
            f'branches-covered="{int(branch_rate * 20)}">'
            "<packages />"
            "</coverage>"
        ),
        encoding="utf-8",
    )


def test_parse_coverage_xml_reports_line_and_branch_metrics(tmp_path: Path) -> None:
    """Quality reports expose branches instead of silently dropping them."""
    report = tmp_path / "coverage.xml"
    _write_coverage(report, line_rate=0.85, branch_rate=0.75)

    metrics = parse_coverage_xml(str(report))

    assert metrics["coverage_percent"] == 85.0
    assert metrics["branch_coverage_percent"] == 75.0
    assert metrics["branches_covered"] == 15
    assert metrics["branches_valid"] == 20


def test_nightly_report_uses_apps_as_overall_and_keeps_scopes_separate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An average of cumulative suite reports cannot masquerade as repository coverage."""
    monkeypatch.chdir(tmp_path)
    rates = {
        "apps": (0.82, 0.72),
        "core": (0.81, 0.71),
        "shared": (0.80, 0.70),
        "sdk": (0.83, 0.73),
    }
    for scope, (line_rate, branch_rate) in rates.items():
        _write_coverage(
            tmp_path / "reports" / "quality" / f"coverage-{scope}.xml",
            line_rate=line_rate,
            branch_rate=branch_rate,
        )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"coverage": {"repository_minimum": 80.0}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.generate_quality_report.load_repository_coverage_minimum",
        lambda: load_repository_coverage_minimum(baseline),
    )

    report = generate_nightly_report(argparse.Namespace())

    assert report["overall_coverage"] == 82.0
    assert report["coverage_threshold"] == 80.0
    assert report["coverage_scopes"]["core"]["coverage_percent"] == 81.0
    assert report["coverage_scopes"]["sdk"]["branch_coverage_percent"] == 70.0
