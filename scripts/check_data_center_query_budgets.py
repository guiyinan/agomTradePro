"""Validate Data Center query-budget governance and executable evidence."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "governance" / "data_center_query_budgets.json"


def _function_names(path: Path) -> set[str]:
    """Return top-level and nested Python function names from one source file."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def main() -> int:
    """Validate budget bounds, unique keys, and test evidence paths."""

    try:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"query budget manifest unreadable: {exc}") from exc
    if payload.get("schema_version") != "1.0":
        raise SystemExit("query budget schema_version must be 1.0")
    budgets = payload.get("budgets")
    if not isinstance(budgets, list) or not budgets:
        raise SystemExit("query budget manifest must contain budgets")
    seen: set[str] = set()
    for budget in budgets:
        if not isinstance(budget, dict):
            raise SystemExit("query budget entry must be an object")
        key = str(budget.get("budget_key") or "").strip()
        if not key or key in seen:
            raise SystemExit(f"query budget key is empty or duplicated: {key}")
        seen.add(key)
        max_queries = budget.get("max_queries")
        max_p95_ms = budget.get("max_p95_ms")
        if isinstance(max_queries, bool) or not isinstance(max_queries, int) or max_queries < 0:
            raise SystemExit(f"{key}: max_queries must be a non-negative integer")
        if (
            not isinstance(max_p95_ms, (int, float))
            or isinstance(max_p95_ms, bool)
            or max_p95_ms < 0
        ):
            raise SystemExit(f"{key}: max_p95_ms must be non-negative")
        evidence = str(budget.get("evidence_test") or "")
        if "::" not in evidence:
            raise SystemExit(f"{key}: evidence_test must use path::function")
        test_path_raw, test_name = evidence.split("::", 1)
        test_path = ROOT / test_path_raw
        if not test_path.is_file() or test_name not in _function_names(test_path):
            raise SystemExit(f"{key}: missing executable evidence {evidence}")
    print(f"Data Center query budgets validated: {len(budgets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
