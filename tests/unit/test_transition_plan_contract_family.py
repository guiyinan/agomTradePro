"""Static and pure checks for transition-plan payload-family isolation."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_contract_module() -> ModuleType:
    path = REPO_ROOT / "core/integration/transition_plan_contracts.py"
    spec = importlib.util.spec_from_file_location("transition_plan_contracts_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("transition-plan contract module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONTRACTS = _load_contract_module()
LEGACY_TRANSITION_PLAN_FAMILY = CONTRACTS.LEGACY_TRANSITION_PLAN_FAMILY
CANONICAL_TRANSITION_PLAN_FAMILY = CONTRACTS.CANONICAL_TRANSITION_PLAN_FAMILY
require_legacy_transition_plan_family = CONTRACTS.require_legacy_transition_plan_family
require_canonical_transition_plan_family = CONTRACTS.require_canonical_transition_plan_family


def _migration_operations() -> list[ast.expr]:
    path = REPO_ROOT / "apps/portfolio/migrations/0016_transition_plan_contract_family.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    migration = next(
        node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "Migration"
    )
    assignment = next(
        node
        for node in migration.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "operations" for target in node.targets
        )
    )
    assert isinstance(assignment.value, ast.List)
    return assignment.value.elts


def test_contract_family_migration_is_nullable_schema_only() -> None:
    operations = _migration_operations()

    assert len(operations) == 1
    assert isinstance(operations[0], ast.Call)
    assert ast.unparse(operations[0].func) == "migrations.AddField"
    rendered = ast.unparse(operations[0])
    assert "null=True" in rendered
    assert "default=" not in rendered
    assert "RunPython" not in rendered
    assert "RunSQL" not in rendered


@pytest.mark.parametrize("family", [None, "", LEGACY_TRANSITION_PLAN_FAMILY])
def test_legacy_family_allows_only_legacy_or_unclassified_rows(family: str | None) -> None:
    require_legacy_transition_plan_family(family)


def test_legacy_family_rejects_canonical_rows() -> None:
    with pytest.raises(ValueError, match="cannot consume canonical payload"):
        require_legacy_transition_plan_family(CANONICAL_TRANSITION_PLAN_FAMILY)


def test_canonical_family_rejects_legacy_and_unclassified_rows() -> None:
    require_canonical_transition_plan_family(CANONICAL_TRANSITION_PLAN_FAMILY)
    for family in (None, "", LEGACY_TRANSITION_PLAN_FAMILY):
        with pytest.raises(ValueError, match="cannot consume a legacy transition plan"):
            require_canonical_transition_plan_family(family)


@pytest.mark.parametrize(
    ("relative_path", "required_fragments"),
    [
        (
            "apps/decision_rhythm/infrastructure/recommendation_repositories.py",
            (
                "plan_contract_family",
                "CONTRACT_FAMILY_LEGACY",
                "_ensure_legacy_transition_plan_row",
            ),
        ),
        (
            "apps/portfolio/infrastructure/repositories.py",
            (
                "plan_contract_family",
                "CONTRACT_FAMILY_CANONICAL",
                "require_canonical_transition_plan_family",
                "select_for_update",
            ),
        ),
    ],
)
def test_repositories_publish_and_validate_contract_family(
    relative_path: str,
    required_fragments: tuple[str, ...],
) -> None:
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    for fragment in required_fragments:
        assert fragment in source
