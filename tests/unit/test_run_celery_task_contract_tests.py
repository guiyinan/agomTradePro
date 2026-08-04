"""Tests for the executable Celery contract manifest runner."""

import json

from scripts import run_celery_task_contract_tests as runner


def test_registered_nodeids_include_nested_pytest_class(tmp_path, monkeypatch) -> None:
    test_file = tmp_path / "test_contracts.py"
    test_file.write_text(
        "class TestTasks:\n"
        "    def test_all_success(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "celery.json"
    manifest.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "required_cases": {
                            "all_success": {
                                "test_file": "test_contracts.py",
                                "test_function": "test_all_success",
                            }
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)

    assert runner._registered_nodeids(manifest) == [
        "test_contracts.py::TestTasks::test_all_success"
    ]
