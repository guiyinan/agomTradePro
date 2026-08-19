"""Contract tests for isolated PostgreSQL backup/restore evidence."""

from __future__ import annotations

import importlib.util
import json
import subprocess
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


def test_restore_uses_parallel_fail_closed_client_without_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    dump = tmp_path / "postgres-current.dump"
    target = module.parse_postgres_target("postgresql://agom:secret@localhost/agom_ci")
    observed: list[str] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        observed.extend(command)
        assert kwargs["check"] is True
        return SimpleNamespace()

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module.restore_dump(dump, target, "agom_ci_restore_verify_deadbeef")

    assert "--jobs=4" in observed
    assert "--exit-on-error" in observed
    assert "secret" not in observed


def test_container_restore_client_keeps_password_out_of_docker_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    dump = tmp_path / "postgres-current.dump"
    dump.write_bytes(b"custom-dump")
    target = module.parse_postgres_target("postgresql://agom:secret@localhost:5544/agom_ci")
    observed: list[str] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        observed.extend(command)
        assert kwargs["check"] is True
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert "PGPASSWORD" not in environment
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module.restore_dump(
        dump,
        target,
        "agom_ci_restore_verify_deadbeef",
        container_image="postgres:18.4",
    )

    assert observed[:4] == ["docker", "run", "--rm", "--volume"]
    assert "postgres:18.4" in observed
    assert "host.docker.internal" in observed
    joined = " ".join(observed)
    assert "chmod 600 /tmp/agom-postgres-restore.pgpass" in joined
    assert "PGPASSFILE=/tmp/agom-postgres-restore.pgpass" in joined
    assert "/run/secrets/agom-postgres-restore.pgpass" in joined
    assert "secret" not in observed


def test_restore_failure_reports_bounded_redacted_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    dump = tmp_path / "postgres-current.dump"
    target = module.parse_postgres_target("postgresql://agom:secret@localhost/agom_ci")

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        raise subprocess.CalledProcessError(
            returncode=7,
            cmd=command,
            stderr=f"{'x' * 5000} secret final database error",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        module.restore_dump(dump, target, "agom_ci_restore_verify_deadbeef")

    message = str(exc_info.value)
    assert "pg_restore_failed(returncode=7" in message
    assert "final database error" in message
    assert "secret" not in message
    assert "[redacted]" in message
    assert len(message) < 4100


def test_container_dump_validation_preserves_exact_list_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    dump = tmp_path / "postgres-current.dump"
    dump.write_bytes(b"custom-dump")
    target = module.parse_postgres_target("postgresql://agom:secret@db.internal/agom_ci")
    observed: list[str] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        observed.extend(command)
        assert kwargs["check"] is True
        return SimpleNamespace(stdout="; header\n1; TABLE DATA public sample agom\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.validate_custom_dump(dump, target, container_image="postgres:18.4") == 1
    assert observed[:3] == ["docker", "run", "--rm"]
    assert observed[-2:] == ["--list", "/tmp/agom-postgres-restore.dump"]
    assert "secret" not in observed


def test_pgpass_value_escapes_delimiters_and_rejects_line_breaks() -> None:
    module = _load_script()

    assert module._pgpass_value(r"p:a\\ss") == r"p\:a\\\\ss"
    with pytest.raises(ValueError, match="line breaks"):
        module._pgpass_value("bad\npassword")


def test_constraint_normalization_collapses_postgres_dump_reparse_casts() -> None:
    module = _load_script()
    source = (
        "CHECK (status::text = ANY "
        "(ARRAY['ready'::character varying, 'blocked'::character varying]::text[]))"
    )
    restored = (
        "CHECK (status::text = ANY "
        "(ARRAY['ready'::character varying::text, "
        "'blocked'::character varying::text]))"
    )

    assert module._normalize_constraint_definition(source) == (
        module._normalize_constraint_definition(restored)
    )


def test_main_writes_success_evidence_after_exact_restore_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    dump = tmp_path / "postgres-current.dump"
    dump.write_bytes(b"verified-custom-dump")
    report_path = tmp_path / "evidence.json"
    snapshot = {
        "tables": {"django_migrations": {"rows": 1, "content_sha256": "abc"}},
        "data_center_migrations": ["0065_widen_retention_member_digests"],
        "schema_sha256": "schema-hash",
        "sequences": {"sample_id_seq": {"last_value": 7, "is_called": True}},
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
    assert evidence["snapshot_difference"] == {
        "changed_sequences": {},
        "changed_tables": {},
        "extra_migrations": [],
        "extra_sequences": [],
        "extra_tables": [],
        "missing_migrations": [],
        "missing_sequences": [],
        "missing_tables": [],
        "schema_sha256": None,
    }
    assert len(evidence["dump_sha256"]) == 64
    assert evidence["dump_sha256_before"] == evidence["dump_sha256_after"]
    assert not report_path.with_suffix(".json.partial").exists()


def test_main_rejects_dump_replacement_during_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restore evidence must fail if the input archive changes mid-run."""

    module = _load_script()
    dump = tmp_path / "postgres-current.dump"
    dump.write_bytes(b"verified-custom-dump")
    report_path = tmp_path / "changed-evidence.json"
    snapshot = {
        "tables": {"sample": {"rows": 1, "content_sha256": "same"}},
        "data_center_migrations": [],
        "schema_sha256": "schema-hash",
        "sequences": {},
    }
    monkeypatch.setattr(module, "validate_custom_dump", lambda *_args: 1)
    monkeypatch.setattr(module, "snapshot_database", lambda _url: snapshot)
    monkeypatch.setattr(module, "recreate_restore_database", lambda *_args: None)

    def mutate_dump(path: Path, *_args: object) -> None:
        path.write_bytes(b"replacement-archive")

    monkeypatch.setattr(module, "restore_dump", mutate_dump)
    monkeypatch.setattr(module, "drop_restore_database", lambda *_args: None)

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

    assert exit_code == 1
    assert evidence["error"] == "RuntimeError: postgres_backup_changed_during_restore"
    assert evidence["dump_sha256_before"] != evidence["dump_sha256_after"]
    assert evidence["dump_sha256"] == evidence["dump_sha256_after"]


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


def test_main_persists_component_differences_on_snapshot_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    dump = tmp_path / "postgres-current.dump"
    dump.write_bytes(b"verified-custom-dump")
    report_path = tmp_path / "mismatch-evidence.json"
    source = {
        "tables": {"sample": {"rows": 2, "content_sha256": "source-data"}},
        "data_center_migrations": ["0065_widen_retention_member_digests"],
        "schema_sha256": "source-schema",
        "sequences": {"sample_id_seq": {"last_value": 2, "is_called": True}},
    }
    restored = {
        "tables": {"sample": {"rows": 1, "content_sha256": "restored-data"}},
        "data_center_migrations": [],
        "schema_sha256": "restored-schema",
        "sequences": {"sample_id_seq": {"last_value": 1, "is_called": True}},
    }
    snapshots = iter([source, restored])
    monkeypatch.setattr(module, "validate_custom_dump", lambda *_args: 7)
    monkeypatch.setattr(module, "snapshot_database", lambda _url: next(snapshots))
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

    assert exit_code == 1
    assert evidence["error"] == "RuntimeError: postgres_restore_snapshot_mismatch"
    assert evidence["source_snapshot"] == source
    assert evidence["restored_snapshot"] == restored
    assert evidence["snapshot_difference"]["changed_tables"]["sample"] == {
        "source": source["tables"]["sample"],
        "restored": restored["tables"]["sample"],
    }
    assert evidence["snapshot_difference"]["missing_migrations"] == [
        "0065_widen_retention_member_digests"
    ]
    assert evidence["snapshot_difference"]["changed_sequences"] == {
        "sample_id_seq": {
            "source": source["sequences"]["sample_id_seq"],
            "restored": restored["sequences"]["sample_id_seq"],
        }
    }
    assert evidence["snapshot_difference"]["schema_sha256"] == {
        "source": "source-schema",
        "restored": "restored-schema",
    }
