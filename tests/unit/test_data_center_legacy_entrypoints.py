from __future__ import annotations

import json
from pathlib import Path

from scripts.check_data_center_legacy_entrypoints import validate


def _write_manifest(path: Path, *, entrypoints: list[dict], wrappers: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "owner": "data_center",
                "entrypoints": entrypoints,
                "wrappers": wrappers,
            }
        ),
        encoding="utf-8",
    )


def test_repository_legacy_entrypoint_inventory_is_exact() -> None:
    assert validate() == []


def test_guard_rejects_stale_direct_entry(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "clean.py").write_text("VALUE = 1\n", encoding="utf-8")
    manifest = tmp_path / "governance" / "entrypoints.json"
    _write_manifest(
        manifest,
        entrypoints=[
            {
                "path": "scripts/clean.py",
                "replacement": "public port",
                "status": "compatibility_owner",
            }
        ],
        wrappers=[],
    )

    assert validate(
        manifest_path=manifest,
        scripts_root=scripts,
        repository_root=tmp_path,
    ) == ["stale_script_entrypoint:scripts/clean.py"]


def test_guard_requires_exact_wrapper_inventory_and_status(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    wrapper = scripts / "wrapper.py"
    wrapper.write_text('LEGACY_DATA_CENTER_WRAPPER = "sync_macro_data"\n', encoding="utf-8")
    manifest = tmp_path / "governance" / "entrypoints.json"
    _write_manifest(manifest, entrypoints=[], wrappers=[])

    assert validate(
        manifest_path=manifest,
        scripts_root=scripts,
        repository_root=tmp_path,
    ) == ["unregistered_compatibility_wrapper:scripts/wrapper.py"]

    _write_manifest(
        manifest,
        entrypoints=[],
        wrappers=[
            {
                "path": "scripts/wrapper.py",
                "replacement": "python manage.py sync_macro_data",
                "status": "retirement_pending",
            }
        ],
    )
    assert validate(
        manifest_path=manifest,
        scripts_root=scripts,
        repository_root=tmp_path,
    ) == ["wrapper_status_invalid:scripts/wrapper.py:retirement_pending"]


def test_guard_uses_operational_governance_for_canonical_scripts(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    canonical = scripts / "canonical.py"
    canonical.write_text(
        "from apps.data_center.infrastructure.models import CanonicalFactModel\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "governance" / "entrypoints.json"
    _write_manifest(manifest, entrypoints=[], wrappers=[])
    operational = tmp_path / "governance" / "data_center_operational_entrypoints.json"
    operational.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "category": ["operational_script", "operational_dispatch_edge"],
                        "path": "scripts/canonical.py",
                        "status": "active_public",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert validate(
        manifest_path=manifest,
        scripts_root=scripts,
        repository_root=tmp_path,
    ) == []
