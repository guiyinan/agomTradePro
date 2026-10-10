"""Contract checks for the plan-bound fresh S6 preparation wrapper."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = PROJECT_ROOT / "scripts" / "prepare_release_rehearsal_attempt.sh"
EXPORTER_ROLE_BOOTSTRAP = PROJECT_ROOT / "scripts" / "postgres_s6_exporter_role_bootstrap.sql"


def _wrapper_text() -> str:
    return WRAPPER.read_text(encoding="utf-8")


def test_wrapper_consumes_only_a_reserved_v2_plan_and_plan_bound_source() -> None:
    source = _wrapper_text()

    assert '"--plan-file"' in source
    assert "build_attempt_plan(" in source
    assert "from scripts.plan_release_rehearsal_attempt import build_attempt_plan" in source
    assert '"schema": "release.s6-attempt-plan.v1"' not in source
    assert "provider_settings_export_path" in source
    assert "provider_identities_export_path" in source
    assert "candidate_source_snapshot_path" in source
    assert "candidate_source_receipt_path" in source
    assert "--reserve" not in source
    assert "workspace:/candidate-src" not in source
    assert '"$candidate_source:/candidate-src:ro"' in source
    assert "prepare_s6_candidate_source_snapshot.py" in source
    assert "--verify-only" in source


def test_all_export_modes_reverify_the_sealed_snapshot_with_structured_docker_argv() -> None:
    source = _wrapper_text()

    assert "production|universe|contract" in source
    assert "--run-export" in source
    assert '--container-uid "$candidate_uid"' in source
    assert '--container-gid "$candidate_gid"' in source
    assert '--execution-image "$execution_image"' in source
    assert '--input-directory "$candidate_input_staging"' in source
    assert '--output-directory "$export_root"' in source
    assert '--execution-env-file "$inputs/prepare-export.env"' in source
    assert '--docker-network "$prepare_network"' in source
    assert "--tmpfs /tmp:rw,nosuid,nodev,mode=1777,size=2147483648" in source
    assert 'helper_argv+=("--docker-arg=$docker_argument")' in source
    assert '"$candidate_input_staging:/candidate-inputs:ro"' in source
    assert '"$export_root:/candidate-output:rw"' in source
    assert "/candidate-src/scripts/export_s6_rehearsal_inputs.py" in source
    assert "^sha256:[0-9a-f]{64}$" in source
    assert 's6_candidate_export_failure_code "$mode"' in source
    assert "$mode_FAILED" not in source


def test_prepare_reorders_to_isolated_snapshot_and_exporter_network() -> None:
    source = _wrapper_text()
    exporter_role_sql = EXPORTER_ROLE_BOOTSTRAP.read_text(encoding="utf-8")

    assert "--format=custom --no-owner --no-acl" in source
    assert '"SELECT current_database()"' in source
    assert 'test "$production_database_actual" = "$expected_production_database"' in source
    assert '-d "$1" --format=custom' in source
    assert "pg_restore" in source
    assert 'docker network create --internal "$prepare_network"' in source
    assert 'docker volume create "$volume"' in source
    assert 'docker run -d --name "$pg" --network "$net"' in source
    assert 'docker run -d --name "$redis" --network "$net"' in source
    assert source.index("phase=isolated_containers") < source.index("phase=production_snapshot")
    assert source.index("phase=production_snapshot") < source.index("phase=role_bootstrap")
    assert source.index("phase=role_bootstrap") < source.index("phase=prepare_network")
    assert source.index("phase=prepare_network") < source.index("phase=candidate_exports")
    assert 'docker network connect --alias "$prepare_alias" "$prepare_network" "$pg"' in source
    assert "prepare_network_members" in source
    assert '"$candidate_source/scripts/postgres_s6_exporter_role_bootstrap.sql"' in source
    assert "agomtradepro_s6_exporter" in exporter_role_sql
    assert "default_transaction_read_only = 'on'" in exporter_role_sql
    assert (
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO agomtradepro_s6_exporter"
        in exporter_role_sql
    )
    assert "NOBYPASSRLS" in exporter_role_sql
    assert "has_table_privilege" in exporter_role_sql
    assert "default_transaction_read_only=on -c transaction_read_only=on" in source
    assert '    --network "$prepare_network"' in source
    assert '    --env-file "$inputs/prepare-export.env"' in source
    assert "production_network" not in source
    assert (
        'docker network connect --alias "$prepare_alias" "$prepare_network" "$redis"' not in source
    )
    assert "provider_allowlist = {" in source
    assert '"REDIS_URL", "REDIS_HOST"' in source
    assert '"execution_image_id": sys.argv[8] or None' in source
    assert '"execution_image_id": image_id' in source
    assert '"prepare_network_removed": True' in source
    assert "S6_PREPARE_COMPLETE candidate=%s attempt=%s execution_image_id=%s" in source


def test_wrapper_does_not_reintroduce_fixed_ci_or_dynamic_mode_diagnostics() -> None:
    source = _wrapper_text()

    assert "options=34" not in source
    assert "transport_inputs=3" not in source
    assert "resume=0" not in source
    assert "candidate-exporter.py" not in source
    assert "S6_ATTEMPT_PLAN.v1" not in source
    assert "S6_CANDIDATE_EXPORT_$mode_FAILED" not in source


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        assert separator and key not in values
        values[key] = value
    return values


def test_filtered_and_exporter_environments_execute_with_secret_negative_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _wrapper_text()
    allowlist_start = source.index("provider_allowlist = {")
    capture_start = source.rfind("import json, os, re, subprocess, sys\n", 0, allowlist_start)
    capture_end = source.index('\nPY\nchmod 600 "$inputs/provider.env"', capture_start)
    capture_body = source[capture_start:capture_end]

    inputs = tmp_path / "inputs-private"
    inputs.mkdir()
    provider_path = inputs / "provider.env"
    encryption_path = inputs / ".production-encryption-key"
    docker_environment = [
        "DJANGO_SETTINGS_MODULE=not-trusted.settings",
        "TUSHARE_TOKEN=provider-token-test-only",
        "TUSHARE_HTTP_URL=https://provider.invalid",
        "TUSHARE_REQUEST_MODE=rest_path",
        "DATA_CENTER_DEPLOYMENT_REGION=overseas_vps",
        "HTTP_PROXY=http://proxy.invalid",
        "SECRET_KEY=production-secret-must-not-escape",
        "DATABASE_URL=postgresql://prod-user:prod-secret@prod-db/prod",
        "AGOMTRADEPRO_ENCRYPTION_KEY=production-encryption-key-test-only",
        "REDIS_URL=redis://prod-redis/0",
        "REDIS_HOST=prod-redis",
        "UNRECOGNIZED_API_TOKEN=must-not-escape",
    ]
    inspect_result = subprocess.CompletedProcess(
        args=["docker", "inspect"],
        returncode=0,
        stdout=json.dumps(docker_environment).encode("utf-8"),
    )
    with (
        patch("subprocess.run", return_value=inspect_result),
        patch.object(
            sys,
            "argv",
            ["wrapper-capture", "web-container", str(provider_path), str(encryption_path)],
        ),
    ):
        exec(compile(capture_body, "<provider-env-capture>", "exec"), {"__name__": "__main__"})

    provider = _read_env_file(provider_path)
    assert provider == {
        "DATA_CENTER_DEPLOYMENT_REGION": "overseas_vps",
        "DJANGO_SETTINGS_MODULE": "core.settings.production",
        "HTTP_PROXY": "http://proxy.invalid",
        "TUSHARE_HTTP_URL": "https://provider.invalid",
        "TUSHARE_REQUEST_MODE": "rest_path",
        "TUSHARE_TOKEN": "provider-token-test-only",
    }
    assert "SECRET_KEY" not in provider
    assert "AGOMTRADEPRO_ENCRYPTION_KEY" not in provider
    assert "DATABASE_URL" not in provider
    assert "REDIS_URL" not in provider and "REDIS_HOST" not in provider
    assert "UNRECOGNIZED_API_TOKEN" not in provider
    assert encryption_path.read_text(encoding="utf-8") == (
        "AGOMTRADEPRO_ENCRYPTION_KEY=production-encryption-key-test-only\n"
    )

    generator_marker = "root, database, postgres, redis, prepare_alias = Path(sys.argv[1])"
    generator_start = source.rfind("import os, re, sys\n", 0, source.index(generator_marker))
    generator_end = source.index("\nPY\nunset S6_PREPARE_ADMIN_PASSWORD", generator_start)
    generator_body = source[generator_start:generator_end]
    for name, value in {
        "S6_PREPARE_ADMIN_PASSWORD": "a" * 32,
        "S6_PREPARE_RUNTIME_PASSWORD": "b" * 32,
        "S6_PREPARE_MIGRATOR_PASSWORD": "c" * 32,
        "S6_PREPARE_EXPORTER_PASSWORD": "d" * 32,
        "S6_PREPARE_SECRET_KEY": "fresh-rehearsal-secret-key",
        "S6_PREPARE_EXPORT_ENCRYPTION_KEY": "generated-export-encryption-key",
    }.items():
        monkeypatch.setenv(name, value)
    with patch.object(
        sys,
        "argv",
        [
            "wrapper-env-builder",
            str(inputs),
            "s6_test_database",
            "s6_test_postgres",
            "s6_test_redis",
            "s6_test_postgres-prepare",
        ],
    ):
        exec(compile(generator_body, "<isolated-env-builder>", "exec"), {"__name__": "__main__"})

    export_environment = _read_env_file(inputs / "prepare-export.env")
    assert export_environment == {
        "AGOMTRADEPRO_ENCRYPTION_KEY": "generated-export-encryption-key",
        "DATABASE_URL": "postgresql://agomtradepro_s6_exporter:"
        + "d" * 32
        + "@s6_test_postgres-prepare:5432/s6_test_database",
        "DJANGO_SETTINGS_MODULE": "core.settings.production",
        "POSTGRES_DB": "s6_test_database",
        "POSTGRES_HOST": "s6_test_postgres-prepare",
        "POSTGRES_PASSWORD": "d" * 32,
        "POSTGRES_PORT": "5432",
        "POSTGRES_USER": "agomtradepro_s6_exporter",
        "SECRET_KEY": "fresh-rehearsal-secret-key",
    }
    assert "TUSHARE_TOKEN" not in export_environment
    assert "UNRECOGNIZED_API_TOKEN" not in export_environment
    assert not any(key.startswith("REDIS_") for key in export_environment)
    isolated = _read_env_file(inputs / "isolated-postgres.env")
    assert isolated["TUSHARE_TOKEN"] == "provider-token-test-only"
    assert isolated["AGOMTRADEPRO_ENCRYPTION_KEY"] == "production-encryption-key-test-only"
    assert isolated["REDIS_HOST"] == "s6_test_redis"
    assert isolated["SECRET_KEY"] == "fresh-rehearsal-secret-key"


@pytest.mark.skipif(os.name != "posix", reason="final validation requires POSIX file modes")
def test_final_validation_python_executes_against_a_private_attempt_tree(tmp_path: Path) -> None:
    source = _wrapper_text()
    validation_start = source.index("phase=final_validation\n")
    body_start = source.index(
        "import datetime, hashlib, json, os, re, stat, sys\n", validation_start
    )
    body_end = source.index("\nPY\n", body_start)
    body = source[body_start:body_end]

    inputs = tmp_path / "inputs-private"
    exports = tmp_path / "exports"
    inputs.mkdir(mode=0o700)
    exports.mkdir(mode=0o700)
    names = {
        "provider-settings.json": {"candidate_sha": "c" * 40},
        "provider-identities.json": [{"deployment_region": "test"}],
        "unit-contract.json": {"candidate_sha": "c" * 40},
        "provider-policy-preflight.json": {"outcome": "pass"},
        "universe-summary.json": {
            "target_trade_date": "2026-10-10",
            "universe_count": 1,
            "universe_sha256": "a" * 64,
        },
    }
    for name, payload in names.items():
        encoded = (json.dumps(payload, sort_keys=True) + "\n").encode()
        (exports / name).write_bytes(encoded)
        (exports / name).chmod(0o600)
        (inputs / name).write_bytes(encoded)
        (inputs / name).chmod(0o600)
    for name in ("runner.env", "vps-password.txt"):
        (inputs / name).write_text("test-only\n", encoding="utf-8")
        (inputs / name).chmod(0o600)
    (inputs / "provider.env").write_text(
        "DJANGO_SETTINGS_MODULE=core.settings.production\n", encoding="utf-8"
    )
    (inputs / "isolated-postgres.env").write_text(
        "POSTGRES_HOST=s6_test_postgres\nPOSTGRES_DB=s6_test_database\n"
        "REDIS_HOST=s6_test_redis\nREDIS_URL=redis://s6_test_redis:6379/0\n",
        encoding="utf-8",
    )
    (inputs / "isolated-migrator.env").write_text(
        "POSTGRES_HOST=s6_test_postgres\nPOSTGRES_DB=s6_test_database\n",
        encoding="utf-8",
    )
    for name in ("provider.env", "isolated-postgres.env", "isolated-migrator.env"):
        (inputs / name).chmod(0o600)
    inputs.chmod(0o700)
    exports.chmod(0o700)

    candidate_sha = "c" * 40
    source_receipt_path = tmp_path / "candidate-source-receipt.json"
    source_receipt_path.write_text(
        json.dumps(
            {
                "candidate_sha": candidate_sha,
                "container_gid": exports.stat().st_gid,
                "tree_sha256": "a" * 64,
                "receipt_sha256": "b" * 64,
            }
        ),
        encoding="utf-8",
    )
    runner_python = "/opt/runner/bin/python"
    requirements_sha = "e" * 64
    runner_receipt_path = tmp_path / "runner-runtime-receipt.json"
    runner_receipt_path.write_text(
        json.dumps(
            {
                "schema": "release.s6-runner-runtime.v1",
                "runner_python": runner_python,
                "requirements_ops_sha256": requirements_sha,
                "paramiko_version": "5.0.0",
                "paramiko_commit": "a4489456b6f65281e172380cc4826cee5e851dbb",
            }
        ),
        encoding="utf-8",
    )
    receipt_path = tmp_path / "prepare-receipt.json"
    owner = exports.stat()
    args = [
        str(inputs),
        str(exports),
        candidate_sha,
        "s6_test_database",
        "s6_test_network",
        "s6_test_postgres",
        "s6_test_redis",
        "s6_test_network-prepare",
        "s6_test_postgres-prepare",
        "s6_test_namespace",
        str(tmp_path / "evidence"),
        str(exports / "provider-settings.json"),
        str(exports / "provider-identities.json"),
        str(source_receipt_path),
        "sha256:" + "d" * 64,
        str(receipt_path),
        str(runner_receipt_path),
        runner_python,
        requirements_sha,
        str(owner.st_uid),
        str(owner.st_gid),
    ]

    result = subprocess.run(
        [sys.executable, "-", *args],
        input=body,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema"] == "release.s6-prepare-receipt.v2"
    assert receipt["execution_image_id"] == "sha256:" + "d" * 64
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash syntax check requires bash")
def test_wrapper_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        [
            shutil.which("bash") or "bash",
            "-n",
            WRAPPER.relative_to(PROJECT_ROOT).as_posix(),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
