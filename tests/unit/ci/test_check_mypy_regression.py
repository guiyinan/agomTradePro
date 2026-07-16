"""Contract tests for incremental mypy debt governance."""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[3] / "scripts" / "check_mypy_regression.py"
    spec = importlib.util.spec_from_file_location("check_mypy_regression", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_mypy_regression = _load_module()


def test_mypy_regression_parser_groups_errors_by_module_and_code():
    counts = check_mypy_regression.parse_error_counts(
        "apps/example.py:10: error: Missing annotation [no-untyped-def]\n"
        "apps/example.py:20:3: error: Missing annotation [no-untyped-def]\n"
        "apps/other.py:7: error: Any return [no-any-return]\n"
    )

    assert counts == {
        "apps/example.py": Counter({"no-untyped-def": 2}),
        "apps/other.py": Counter({"no-any-return": 1}),
    }


def test_mypy_regression_gate_rejects_only_error_count_growth():
    observed = {"apps/example.py": Counter({"no-untyped-def": 2, "type-arg": 1})}
    baseline = {"apps/example.py": {"no-untyped-def": 2}}

    assert check_mypy_regression.find_regressions(observed, baseline) == [
        "apps/example.py: type-arg increased from 0 to 1"
    ]
