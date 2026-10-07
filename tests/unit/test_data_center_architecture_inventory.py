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


def test_inventory_projection_ignores_only_volatile_source_lines() -> None:
    """Moving unchanged references cannot churn governance; semantic changes still do."""

    module = _load_inventory_module()
    before = [
        {"path": "apps/example.py", "line": 10, "text": "latest_value"},
        {"path": "apps/example.py", "line": 12, "text": "latest_value"},
    ]
    moved = [
        {"path": "apps/example.py", "line": 110, "text": "latest_value"},
        {"path": "apps/example.py", "line": 112, "text": "latest_value"},
    ]
    changed = [
        {"path": "apps/example.py", "line": 110, "text": "current_value"},
        {"path": "apps/example.py", "line": 112, "text": "latest_value"},
    ]

    assert module._project_reference_rows(before) == module._project_reference_rows(moved)
    assert module._project_reference_rows(before) != module._project_reference_rows(changed)
    assert module._project_reference_rows(before) == [
        {"path": "apps/example.py", "text": "latest_value"},
        {"path": "apps/example.py", "text": "latest_value"},
    ]


def test_inventory_artifact_contains_no_volatile_line_locators() -> None:
    """Every governed reference row uses path and semantic content only."""

    payload = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "2.0"
    list_sections = (
        "provider_imports_outside_data_center",
        "direct_data_center_imports_outside_data_center",
        "external_http_imports_for_review",
        "approved_non_data_http_imports",
        "cross_app_orm_imports",
        "current_surface_references",
        "data_write_task_decorators",
    )
    for section in list_sections:
        assert all("line" not in row for row in payload[section])
    for rows in payload["legacy_fact_references"].values():
        assert all("line" not in row for row in rows)


def test_build_inventory_is_stable_across_nonsemantic_source_movement(
    tmp_path: Path, monkeypatch
) -> None:
    """The complete builder ignores line movement but retains semantic changes."""

    module = _load_inventory_module()
    source = tmp_path / "apps" / "example.py"
    source.parent.mkdir(parents=True)
    legacy_contract = tmp_path / "legacy.json"
    legacy_contract.write_text(
        json.dumps({"legacy_modules": {}, "allowed_path_patterns": []}),
        encoding="utf-8",
    )
    http_dispositions = tmp_path / "http.json"
    http_dispositions.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "owner": "data-center-architecture",
                "policy": "test-only empty disposition set",
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "LEGACY_ACCESS_CONTRACT", legacy_contract)
    monkeypatch.setattr(module, "EXTERNAL_HTTP_DISPOSITIONS", http_dispositions)
    monkeypatch.setattr(module, "_iter_python_files", lambda: [source])

    source.write_text(
        "import akshare\n\ncurrent_value = object()\n",
        encoding="utf-8",
    )
    baseline = module.build_inventory()
    source.write_text(
        "# an unrelated comment\n\nimport akshare\n\ncurrent_value = object()\n",
        encoding="utf-8",
    )
    moved = module.build_inventory()
    source.write_text(
        "# an unrelated comment\n\nimport tushare\n\ncurrent_value = object()\n",
        encoding="utf-8",
    )
    changed = module.build_inventory()

    assert moved == baseline
    assert changed != baseline
    assert changed["counts"] == baseline["counts"]


def test_inventory_separates_sdk_ownership_from_reviewed_non_data_http() -> None:
    """Provider SDKs stay centralized and each non-data HTTP caller has an owner."""

    module = _load_inventory_module()
    payload = module.build_inventory()
    assert payload["counts"]["provider_imports_outside_data_center"] == 0
    assert payload["counts"]["direct_data_center_imports_outside_data_center"] == 0
    assert payload["counts"]["external_http_imports_for_review"] == 0
    assert payload["counts"]["approved_non_data_http_imports"] == 5
    approved = payload["approved_non_data_http_imports"]
    assert {(item["path"], item["import"], item["owner"], item["scope"]) for item in approved} == {
        (
            "apps/dashboard/infrastructure/ai_insight_client.py",
            "requests",
            "ai-provider",
            "ai_inference",
        ),
        (
            "apps/terminal/infrastructure/http_client.py",
            "requests",
            "terminal",
            "internal_control_plane",
        ),
        (
            "apps/agent_runtime/infrastructure/terminal_runtime_staging_harness.py",
            "requests",
            "agent-runtime",
            "internal_control_plane",
        ),
        (
            "shared/infrastructure/alert_service.py",
            "requests",
            "task-monitor",
            "alert_delivery",
        ),
        (
            "shared/infrastructure/alerts.py",
            "requests",
            "platform-observability",
            "alert_delivery",
        ),
    }
    assert all(item["reason"].strip() for item in approved)
    assert "generated_at" not in payload

    artifact = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    for count_name in (
        "provider_imports_outside_data_center",
        "direct_data_center_imports_outside_data_center",
        "external_http_imports_for_review",
        "approved_non_data_http_imports",
    ):
        assert artifact["counts"][count_name] == payload["counts"][count_name]


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
