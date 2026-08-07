"""Semantic coverage for the retired fact-access guard."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_data_center_legacy_fact_access.py"


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("legacy_fact_guard_semantics", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("legacy fact guard cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def guard_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, dict]:
    """Return a guard module rooted at an isolated production tree."""

    guard = _load_guard()
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    contract = {
        "legacy_modules": {
            "apps.equity.infrastructure.models": ["StockDailyModel"],
            "apps.equity.models": ["StockDailyModel"],
        },
        "legacy_tables": ["equity_stock_daily"],
        "allowed_path_patterns": [],
    }
    return guard, contract


@pytest.mark.parametrize(
    "source,expected_kind",
    [
        (
            "from apps.equity.models import StockDailyModel\nvalue = StockDailyModel\n",
            "legacy_model_import",
        ),
        (
            "import apps.equity.infrastructure.models as legacy\nvalue = legacy.StockDailyModel\n",
            "legacy_module_attribute_reference",
        ),
        (
            "from django.apps import apps\nvalue = apps.get_model('equity', 'StockDailyModel')\n",
            "legacy_dynamic_model_reference",
        ),
        (
            "import importlib\nvalue = importlib.import_module('apps.equity.models')\n",
            "legacy_dynamic_module_import",
        ),
        (
            "sql = 'DELETE FROM equity_stock_daily WHERE bar_date < %s'\n",
            "legacy_table_sql_reference",
        ),
        (
            "tables = ['equity_stock_daily']\nsql = f'SELECT * FROM {tables[0]}'\n",
            "legacy_table_dynamic_reference",
        ),
    ],
)
def test_guard_detects_semantic_and_raw_sql_bypasses(
    guard_repo: tuple[ModuleType, dict],
    source: str,
    expected_kind: str,
) -> None:
    guard, contract = guard_repo
    path = guard.ROOT / "apps" / "consumer" / "service.py"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")

    violations = guard._scan_file(path, contract)

    assert expected_kind in {item["kind"] for item in violations}


def test_guard_scans_executable_sql_files(
    guard_repo: tuple[ModuleType, dict],
) -> None:
    guard, contract = guard_repo
    path = guard.ROOT / "scripts" / "migration" / "legacy.sql"
    path.parent.mkdir(parents=True)
    path.write_text("INSERT INTO equity_stock_daily (id) VALUES (1);", encoding="utf-8")

    violations = guard._scan_executable_text(path, contract)

    assert violations == [
        {
            "path": "scripts/migration/legacy.sql",
            "line": 1,
            "symbol": "equity_stock_daily",
            "kind": "legacy_table_sql_reference",
        }
    ]
