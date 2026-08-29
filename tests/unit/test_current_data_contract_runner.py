"""Unit tests for manifest-driven current-data contract execution."""

from __future__ import annotations

import json
from pathlib import Path

import scripts.run_current_data_contract_tests as runner


def test_registered_nodeids_are_stable_and_deduplicated(tmp_path: Path) -> None:
    """Repeated evidence entries must execute one nodeid only once."""

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "contracts": [
                    {
                        "required_tests": [
                            {"test_file": "tests/test_one.py", "test_function": "test_one"},
                            {"test_file": "tests/test_one.py", "test_function": "test_one"},
                            {"test_file": "tests/test_two.py", "test_function": "test_two"},
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert runner._registered_nodeids(manifest) == [
        "tests/test_one.py::test_one",
        "tests/test_two.py::test_two",
    ]


def test_registered_nodeids_include_pytest_class_methods() -> None:
    """Manifest methods inside test classes must become executable nodeids."""

    nodes = runner._registered_nodeids(Path("governance/current_data_contracts.json"))

    assert (
        "tests/unit/data_center/test_use_cases.py::TestQueryLatestQuoteUseCase::"
        "test_marks_stale_quote_as_non_decision_grade"
    ) in nodes


def test_nodeid_batches_preserve_order_within_command_budget() -> None:
    """Long registries must be partitioned without dropping or reordering tests."""

    base_command = ["python", "-m", "pytest"]
    nodeids = [f"tests/test_contract.py::test_case_{index}_{'x' * 24}" for index in range(5)]

    batches = runner._nodeid_batches(
        base_command,
        nodeids,
        max_command_chars=120,
    )

    assert len(batches) > 1
    assert [nodeid for batch in batches for nodeid in batch] == nodeids
    assert all(
        len(runner.subprocess.list2cmdline([*base_command, *batch])) <= 120 or len(batch) == 1
        for batch in batches
    )


def test_runner_refuses_to_execute_an_invalid_manifest(monkeypatch, tmp_path: Path) -> None:
    """Static manifest violations must block test execution."""

    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    called = False

    def _unexpected_call(*_args: object, **_kwargs: object) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(runner.subprocess, "call", _unexpected_call)
    assert runner.run_registered_tests(manifest) == 1
    assert called is False
