"""Static zero-seed guard for the Risk Center operator approval migration."""

from __future__ import annotations

import ast
from pathlib import Path


def test_operator_approval_migration_is_schema_only_and_follows_0006() -> None:
    migration_path = (
        Path(__file__).parents[3]
        / "apps"
        / "risk_center"
        / "migrations"
        / "0007_evidence_operator_spec_approvals.py"
    )
    source = migration_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert '("risk_center", "0006_seed_initial_scenario_candidates")' in source
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
    assert "risk_ev_op_subj_identity_uq" in source
    assert "risk_ev_op_appr_identity_uq" in source
