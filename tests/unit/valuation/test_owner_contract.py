"""R3-lite ownership and compatibility contracts for valuation."""

from __future__ import annotations

import ast
from pathlib import Path

from apps.decision_rhythm.domain import valuation_entities as legacy_entities
from apps.decision_rhythm.domain import valuation_services as legacy_services
from apps.valuation.domain.entities import (
    ValuationMethod,
    ValuationSnapshot,
    create_valuation_snapshot,
)
from apps.valuation.domain.services import ValuationSnapshotService


def test_legacy_valuation_imports_are_identity_preserving_facades() -> None:
    """Old imports must resolve to the canonical valuation owner objects."""
    assert legacy_entities.ValuationMethod is ValuationMethod
    assert legacy_entities.ValuationSnapshot is ValuationSnapshot
    assert legacy_entities.create_valuation_snapshot is create_valuation_snapshot
    assert legacy_services.ValuationSnapshotService is ValuationSnapshotService


def test_valuation_owner_does_not_depend_on_decision_rhythm() -> None:
    """The new owner must not create a reverse dependency to its consumer."""
    root = Path("apps/valuation")
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = " ".join(alias.name for alias in node.names)
            if "apps.decision_rhythm" in module:
                offenders.append(f"{path}:{node.lineno}")
    assert offenders == []


def test_valuation_domain_uses_only_standard_library_imports() -> None:
    """Valuation domain must remain independent from Django and other apps."""
    forbidden = ("django", "apps", "pandas", "numpy", "requests")
    offenders: list[str] = []
    for path in Path("apps/valuation/domain").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith(forbidden):
                    offenders.append(f"{path}:{node.lineno}:{module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(forbidden):
                        offenders.append(f"{path}:{node.lineno}:{alias.name}")
    assert offenders == []
