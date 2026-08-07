"""Contract tests for isolated PostgreSQL backup/restore evidence."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_postgres_backup_restore.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_postgres_backup_restore", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("restore verification script cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_target_keeps_password_out_of_client_arguments() -> None:
    module = _load_script()

    target = module.parse_postgres_target("postgresql://agom:secret-value@db.internal:5544/agom_ci")

    assert target.database == "agom_ci"
    assert target.client_environment()["PGPASSWORD"] == "secret-value"
    assert "secret-value" not in " ".join(target.client_connection_args())
    assert target.url_for_database("agom_restore").endswith("/agom_restore")


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///local.sqlite3",
        "postgresql://user@localhost/invalid-name",
        "postgresql://localhost/database",
    ],
)
def test_parse_target_rejects_unsafe_or_incomplete_urls(database_url: str) -> None:
    module = _load_script()

    with pytest.raises(ValueError):
        module.parse_postgres_target(database_url)


def test_custom_dump_validation_uses_pg_restore_list_without_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    dump = tmp_path / "postgres-current.dump"
    dump.write_bytes(b"custom-dump")
    target = module.parse_postgres_target("postgresql://agom:secret@localhost/agom_ci")
    observed: list[str] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        observed.extend(command)
        assert kwargs["check"] is True
        return SimpleNamespace(stdout="; header\n1; TABLE DATA public sample agom\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.validate_custom_dump(dump, target) == 1
    assert observed[:2] == ["pg_restore", "--list"]
    assert "secret" not in observed


def test_main_writes_success_evidence_after_exact_restore_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    dump = tmp_path / "postgres-current.dump"
    dump.write_bytes(b"verified-custom-dump")
    report_path = tmp_path / "evidence.json"
    snapshot = {
        "tables": {"django_migrations": {"rows": 1, "content_sha256": "abc"}},
        "data_center_migrations": ["0064_retention_exact_plan_members"],
        "schema_sha256": "schema-hash",
    }
    monkeypatch.setattr(module, "validate_custom_dump", lambda *_args: 7)
    monkeypatch.setattr(module, "snapshot_database", lambda _url: snapshot)
    monkeypatch.setattr(module, "recreate_restore_database", lambda *_args: None)
    monkeypatch.setattr(module, "restore_dump", lambda *_args: None)
    monkeypatch.setattr(module, "drop_restore_database", lambda *_args: None)
    monkeypatch.setattr(
        module,
        "build_canonical_schema_report",
        lambda *_args: {"missing_tables": [], "missing_migrations": []},
    )

    exit_code = module.main(
        [
            "--database-url",
            "postgresql://agom:secret@localhost/agom_ci",
            "--dump-path",
            str(dump),
            "--report-path",
            str(report_path),
        ]
    )
    evidence = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert evidence["outcome"] == "success"
    assert evidence["restore_entries"] == 7
    assert evidence["source_snapshot"] == evidence["restored_snapshot"]
    assert len(evidence["dump_sha256"]) == 64
    assert not report_path.with_suffix(".json.partial").exists()


def test_main_rejects_uncontrolled_restore_database_without_dropping_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    dump = tmp_path / "postgres-current.dump"
    dump.write_bytes(b"verified-custom-dump")
    report_path = tmp_path / "failed-evidence.json"
    dropped: list[str] = []
    monkeypatch.setattr(
        module,
        "drop_restore_database",
        lambda _target, database: dropped.append(database),
    )

    exit_code = module.main(
        [
            "--database-url",
            "postgresql://agom:secret@localhost/agom_ci",
            "--dump-path",
            str(dump),
            "--report-path",
            str(report_path),
            "--restore-database",
            "unrelated_database",
        ]
    )
    evidence = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert evidence["outcome"] == "failed"
    assert "controlled verification prefix" in evidence["error"]
    assert dropped == []
