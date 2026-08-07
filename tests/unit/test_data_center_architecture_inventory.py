"""Regression tests for the deterministic canonical data-center inventory."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "data_center_architecture_inventory.py"
_ARTIFACT = _ROOT / "governance" / "data_center_architecture_inventory.json"


def _load_inventory_module() -> ModuleType:
    """Load the standalone inventory script without importing the Django project."""

    spec = importlib.util.spec_from_file_location("data_center_architecture_inventory", _SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("inventory script cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inventory_artifact_is_deterministic_and_current() -> None:
    """The committed M0 evidence must match a fresh static scan exactly."""

    module = _load_inventory_module()
    expected = module._canonical_json(module.build_inventory())
    assert _ARTIFACT.read_text(encoding="utf-8") == expected


def test_inventory_separates_sdk_ownership_from_http_review() -> None:
    """Provider SDKs are centralized while generic HTTP callers remain reviewable."""

    module = _load_inventory_module()
    payload = module.build_inventory()
    assert payload["counts"]["provider_imports_outside_data_center"] == 0
    assert payload["counts"]["direct_data_center_imports_outside_data_center"] == 0
    assert payload["counts"]["external_http_imports_for_review"] > 0
    assert "generated_at" not in payload

    artifact = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    assert artifact["counts"] == payload["counts"]


def test_legacy_inventory_uses_module_identity_instead_of_symbol_substrings() -> None:
    """Same-name domain entities and account ledgers are not legacy fact access."""

    module = _load_inventory_module()
    source = """
from apps.macro.domain.entities import MacroIndicator

class CapitalFlowModel:
    pass

value = MacroIndicator
"""

    references = module._legacy_fact_references(
        tree=ast.parse(source),
        relative="apps/example/application/demo.py",
        modules={
            "apps.macro.infrastructure.models": {"MacroIndicator"},
            "apps.market.infrastructure.models": {"CapitalFlowModel"},
        },
        allowed_paths=[],
    )

    assert references == []


def test_legacy_inventory_resolves_absolute_and_relative_model_imports() -> None:
    """Actual legacy ORM imports remain visible even when aliased or relative."""

    module = _load_inventory_module()
    modules = {
        "apps.equity.infrastructure.models": {
            "FinancialDataModel",
            "ValuationModel",
        }
    }
    absolute = module._legacy_fact_references(
        tree=ast.parse(
            "from apps.equity.infrastructure.models import ValuationModel as LegacyValue\n"
            "record = LegacyValue\n"
        ),
        relative="apps/research/application/absolute.py",
        modules=modules,
        allowed_paths=[],
    )
    relative = module._legacy_fact_references(
        tree=ast.parse(
            "from ..infrastructure.models import FinancialDataModel\n"
            "record = FinancialDataModel\n"
        ),
        relative="apps/equity/application/relative.py",
        modules=modules,
        allowed_paths=[],
    )

    assert {item["symbol"] for item in absolute} == {"ValuationModel"}
    assert {item["symbol"] for item in relative} == {"FinancialDataModel"}
