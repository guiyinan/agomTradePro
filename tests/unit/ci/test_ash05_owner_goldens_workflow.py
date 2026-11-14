"""Missing or skipped owner goldens must fail the actual CI evidence guard."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[3]


def _guard() -> tuple[str, set[str]]:
    workflow = yaml.safe_load(
        (_ROOT / ".github/workflows/ci-ash05-owner-goldens.yml").read_text(encoding="utf-8")
    )
    step = next(
        item
        for item in workflow["jobs"]["ordinary-owner"]["steps"]
        if item.get("name") == "Reject missing, failed or skipped golden journeys"
    )
    script = step["run"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    tree = ast.parse(script)
    expected = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "expected" for target in node.targets)
    )
    assert isinstance(expected, set) and len(expected) == 21
    return script, expected


@pytest.mark.parametrize("defect", [None, "missing", "skipped", "failure", "error", "no_xml"])
def test_actual_ci_guard_requires_all_successful_non_skipped_owner_journeys(
    tmp_path: Path, defect: str | None
) -> None:
    script, expected = _guard()
    suite = ElementTree.Element("testsuite")
    for index, name in enumerate(sorted(expected)):
        if defect == "missing" and index == 0:
            continue
        case = ElementTree.SubElement(suite, "testcase", name=name)
        if defect in {"skipped", "failure", "error"} and index == 0:
            ElementTree.SubElement(case, defect)
    if defect != "no_xml":
        ElementTree.ElementTree(suite).write(tmp_path / "ash05-owner-goldens.xml")
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert (result.returncode == 0) is (defect is None)


def test_ci_guard_names_resolve_to_actual_native_test_definitions() -> None:
    _, expected = _guard()
    component = _ROOT / "tests/component/simulated_trading"
    found = {
        node.name
        for path in component.glob("test_*.py")
        for node in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.name in expected
    }
    assert found == expected
