"""Tests for governed multi-scope coverage report generation."""

import json
from pathlib import Path

from scripts.generate_coverage_reports import (
    SCOPE_INCLUDES,
    generate_reports,
    write_inventory,
    write_manifest,
)


def test_scope_includes_keep_python_surfaces_separate() -> None:
    """The SDK and server scopes must remain independently reportable."""
    assert SCOPE_INCLUDES == {
        "apps": ("apps/*",),
        "core": ("core/*",),
        "shared": ("shared/*",),
        "sdk": ("sdk/agomtradepro/*", "sdk/agomtradepro_mcp/*"),
    }


def test_generate_reports_preserves_the_governed_final_report_name(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The merged report keeps the long-standing coverage-final.xml contract."""

    class FakeCoverage:
        def __init__(self, **_kwargs) -> None:
            self.loaded = False

        def load(self) -> None:
            self.loaded = True

        def xml_report(self, *, outfile: str, include=None) -> None:
            assert self.loaded is True
            Path(outfile).write_text("<coverage />", encoding="utf-8")

        def json_report(self, *, outfile: str, pretty_print: bool) -> None:
            assert self.loaded is True
            assert pretty_print is True
            Path(outfile).write_text('{"files": {}}', encoding="utf-8")

    monkeypatch.setattr("scripts.generate_coverage_reports.Coverage", FakeCoverage)

    reports = generate_reports(
        data_file=tmp_path / ".coverage",
        config_file=tmp_path / ".coveragerc",
        output_dir=tmp_path,
    )

    assert reports["combined"] == tmp_path / "coverage-final.xml"
    assert reports["combined"].exists()


def test_write_inventory_aggregates_scope_module_layer_and_missing_evidence(
    tmp_path: Path,
) -> None:
    """The risk inventory retains exact misses and useful architecture totals."""
    details_path = tmp_path / "coverage-final-details.json"
    details_path.write_text(
        json.dumps(
            {
                "files": {
                    "apps/account/application/use_cases.py": {
                        "summary": {
                            "covered_lines": 7,
                            "num_statements": 10,
                            "covered_branches": 2,
                            "num_branches": 4,
                        },
                        "missing_lines": [11, 12, 13],
                        "missing_branches": [[20, 25], [20, 30]],
                    },
                    "core/settings/base.py": {
                        "summary": {
                            "covered_lines": 3,
                            "num_statements": 5,
                            "covered_branches": 0,
                            "num_branches": 0,
                        },
                        "missing_lines": [4, 5],
                        "missing_branches": [],
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    inventory_path = write_inventory(
        details_path=details_path,
        output_dir=tmp_path,
    )

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    assert inventory["scopes"]["apps"]["line_percent"] == 70.0
    assert inventory["modules"]["account"]["missing_lines"] == 3
    assert inventory["architecture_layers"]["application"]["branch_percent"] == 50.0
    assert inventory["files"][0]["missing_line_numbers"] == [11, 12, 13]
    assert inventory["files"][0]["missing_branch_arcs"] == [[20, 25], [20, 30]]


def test_write_manifest_records_branch_mode_and_report_digests(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Coverage evidence records its exact source commit and immutable digests."""
    data_file = tmp_path / ".coverage"
    config_file = tmp_path / ".coveragerc"
    report = tmp_path / "coverage-apps.xml"
    data_file.write_bytes(b"coverage-data")
    config_file.write_text("[run]\nbranch = true\n", encoding="utf-8")
    report.write_text("<coverage />", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.generate_coverage_reports._git_commit",
        lambda: "fixed-commit",
    )
    monkeypatch.setattr(
        "scripts.generate_coverage_reports._git_is_dirty",
        lambda: False,
    )

    manifest_path = write_manifest(
        reports={"apps": report},
        data_file=data_file,
        config_file=config_file,
        output_dir=tmp_path,
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["commit"] == "fixed-commit"
    assert payload["git_dirty"] is False
    assert payload["branch_measurement"] is True
    assert payload["reports"]["apps"]["path"] == str(report.resolve())
    assert len(payload["reports"]["apps"]["sha256"]) == 64
