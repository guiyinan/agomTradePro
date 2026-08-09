"""Fail-closed contracts for canonical runtime-definition governance."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.check_runtime_config_coverage import (
    MANIFEST,
    ROOT,
    validate_runtime_definition_contracts,
)


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _canonical_definition(manifest: dict[str, object]) -> dict[str, object]:
    definitions = manifest["definitions"]
    assert isinstance(definitions, list)
    definition = next(
        item
        for item in definitions
        if isinstance(item, dict) and item.get("config_key") == "alpha.qlib.enabled"
    )
    return definition


def test_canonical_runtime_definition_contract_accepts_repository_manifest() -> None:
    report = validate_runtime_definition_contracts(_manifest())

    assert report["canonical_definition_count"] >= 11
    assert report["locator_count"] > 0


def test_canonical_runtime_definition_requires_blocked_fallback() -> None:
    manifest = copy.deepcopy(_manifest())
    definition = _canonical_definition(manifest)
    definition["fallback"] = "system_settings_compatibility"

    with pytest.raises(ValueError, match="canonical_fallback_not_blocked:alpha.qlib.enabled"):
        validate_runtime_definition_contracts(manifest)


def test_materialization_required_definition_requires_existing_migration() -> None:
    manifest = copy.deepcopy(_manifest())
    definition = _canonical_definition(manifest)
    definition["materialization_required"] = True
    definition["materialization_migration"] = (
        "apps/config_center/migrations/9999_missing_materialization.py"
    )

    with pytest.raises(ValueError, match="materialization_migration_invalid"):
        validate_runtime_definition_contracts(manifest)


def test_materialization_required_definition_rejects_missing_migration() -> None:
    manifest = copy.deepcopy(_manifest())
    definition = _canonical_definition(manifest)
    definition["materialization_required"] = True
    definition.pop("materialization_migration", None)

    with pytest.raises(ValueError, match="materialization_migration_missing"):
        validate_runtime_definition_contracts(manifest)


@pytest.mark.parametrize("field_name", ["consumers", "tests"])
def test_canonical_runtime_definition_requires_locator_evidence(field_name: str) -> None:
    manifest = copy.deepcopy(_manifest())
    definition = _canonical_definition(manifest)
    definition[field_name] = []

    with pytest.raises(ValueError, match=f"canonical_{field_name}_missing"):
        validate_runtime_definition_contracts(manifest)


def test_canonical_runtime_definition_rejects_missing_locator_symbol(tmp_path: Path) -> None:
    manifest = copy.deepcopy(_manifest())
    definition = _canonical_definition(manifest)
    test_file = tmp_path / "tests" / "unit" / "test_runtime.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_present() -> None:\n    pass\n", encoding="utf-8")
    definition["consumers"] = ["tests/unit/test_runtime.py::missing_consumer"]
    definition["tests"] = ["tests/unit/test_runtime.py::test_missing"]
    definition["materialization_required"] = False
    definition.pop("materialization_migration", None)

    with pytest.raises(ValueError, match="symbol_missing"):
        validate_runtime_definition_contracts(manifest, repo_root=tmp_path)


def test_canonical_runtime_definition_rejects_duplicate_keys() -> None:
    manifest = copy.deepcopy(_manifest())
    definitions = manifest["definitions"]
    assert isinstance(definitions, list)
    definitions.append(copy.deepcopy(_canonical_definition(manifest)))

    with pytest.raises(ValueError, match="definition_key_duplicate:alpha.qlib.enabled"):
        validate_runtime_definition_contracts(manifest, repo_root=ROOT)
