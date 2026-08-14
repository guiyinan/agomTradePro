"""Static zero-seed guard for the operator spec lifecycle migration."""

from __future__ import annotations

import ast
from pathlib import Path


def test_operator_spec_lifecycle_migration_is_schema_only_and_follows_0026() -> None:
    migration_path = (
        Path(__file__).parents[3]
        / "apps"
        / "research"
        / "migrations"
        / "0027_evidence_operator_spec_lifecycle.py"
    )
    source = migration_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert '("research", "0026_evidence_ledgers")' in source
    assert "RunPython" not in source
    assert "RunSQL" not in source
    create_model_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "CreateModel"
    ]
    assert len(create_model_calls) == 2
    assert "res_ev_op_active_root_uq" in source
    assert "res_ev_op_active_child_uq" in source
