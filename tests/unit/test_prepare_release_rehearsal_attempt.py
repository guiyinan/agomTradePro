"""Contract checks for the plan-bound fresh S6 preparation wrapper."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from scripts.plan_release_rehearsal_attempt import build_attempt_plan
from scripts.prepare_s6_candidate_source_snapshot import (
    CandidateSourceSnapshotError,
    _FinalPrepareValidation,
    _read_validation_json_list,
    validate_final_prepare_receipt,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = PROJECT_ROOT / "scripts" / "prepare_release_rehearsal_attempt.sh"
EXPORTER_ROLE_BOOTSTRAP = PROJECT_ROOT / "scripts" / "postgres_s6_exporter_role_bootstrap.sql"


def _wrapper_text() -> str:
    return WRAPPER.read_text(encoding="utf-8")


def test_final_validation_json_list_reader_preserves_identity_array(tmp_path: Path) -> None:
    """The provider identity boundary accepts arrays without coercing them to objects."""

    path = tmp_path / "provider-identities.json"
    payload: list[object] = [{"role": "quote"}, {"role": "valuation"}]
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert _read_validation_json_list(path, "S6_PROVIDER_IDENTITIES_INVALID") == payload


def test_final_validation_json_list_reader_rejects_object(tmp_path: Path) -> None:
    """The provider identity boundary fails closed when the JSON shape is not an array."""

    path = tmp_path / "provider-identities.json"
    path.write_text(json.dumps({"role": "quote"}), encoding="utf-8")

    with pytest.raises(CandidateSourceSnapshotError, match="S6_PROVIDER_IDENTITIES_INVALID"):
        _read_validation_json_list(path, "S6_PROVIDER_IDENTITIES_INVALID")


def test_wrapper_consumes_only_a_reserved_v3_plan_and_plan_bound_source() -> None:
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
    assert source.count('python3 -B "$candidate_source_helper"') == 4
    assert 'python3 "$candidate_source_helper"' not in source
    assert "--verify-only" in source
    assert 'advance_isolated_market_graph="${plan_values[14]}"' in source
    assert 'test "$advance_isolated_market_graph" = 1 || return 0' in source
    assert '--read-only --user "$candidate_uid:$candidate_gid"' in source
    assert '"$candidate_source:/candidate-src:ro"' in source
    assert '"$inputs/isolated-postgres.env"' in source
    assert 'install -m 400 "$export_root/current-market-graph-refresh.json"' in source


def test_python_heredoc_failure_branches_do_not_use_line_continuations() -> None:
    source = _wrapper_text()

    for line in source.splitlines():
        if "<<'PY'" in line:
            assert not line.rstrip().endswith("\\")

    assert "<<'PY' || fail S6_PROVIDER_ENV_CAPTURE_INVALID" in source
    assert "<<'PY' || fail S6_CANDIDATE_INPUT_TREE_INVALID" in source
    assert "--validate-final-receipt" in source
    assert "<<'PY' || fail S6_PREPARE_FINAL_VALIDATION_FAILED" not in source


def test_all_export_modes_reverify_the_sealed_snapshot_with_structured_docker_argv() -> None:
    source = _wrapper_text()
    helper = (PROJECT_ROOT / "scripts" / "prepare_s6_candidate_source_snapshot.py").read_text(
        encoding="utf-8"
    )

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
    assert 'python3 -B "$candidate_source_helper" "${helper_argv[@]}"' in source
    assert source.count("parse_complete_rehearsal_identities") == 2
    assert "parse_complete_rehearsal_identities" in helper
    assert 'row.get("deployment_region") for row in identities' not in source


def test_prepare_reorders_to_isolated_snapshot_and_exporter_network() -> None:
    source = _wrapper_text()
    helper = (PROJECT_ROOT / "scripts" / "prepare_s6_candidate_source_snapshot.py").read_text(
        encoding="utf-8"
    )
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
    assert 'REVOKE TEMPORARY ON DATABASE :"database" FROM PUBLIC' in exporter_role_sql
    assert exporter_role_sql.index(
        'REVOKE TEMPORARY ON DATABASE :"database" FROM PUBLIC'
    ) < exporter_role_sql.index("has_database_privilege")
    assert "current_database(), 'TEMP'" in exporter_role_sql
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
    assert "provider_allowlist = {" in helper
    assert '"REDIS_URL"' in helper and '"REDIS_HOST"' in helper
    assert '"execution_image_id": context.execution_image_id' in helper
    assert '"prepare_network_removed": True' in helper
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


@pytest.mark.parametrize(("financial_region", "expected_code"), [("unknown", 0), (None, 1)])
def test_production_export_validation_uses_complete_identity_contract(
    tmp_path: Path,
    financial_region: str | None,
    expected_code: int,
) -> None:
    source = _wrapper_text()
    validation_start = source.index("run_candidate_export production")
    body_start = source.index("import json, sys\n", validation_start)
    body_end = source.index("\nPY\n", body_start)
    body = source[body_start:body_end]
    candidate_sha = "c" * 40
    settings_path = tmp_path / "provider-settings.json"
    identities_path = tmp_path / "provider-identities.json"
    unit_path = tmp_path / "unit-contract.json"
    settings_path.write_text(json.dumps({"provider": "test"}), encoding="utf-8")
    identities_path.write_text(
        json.dumps(
            [
                {
                    "role": "quote",
                    "provider_id": 2,
                    "source": "tushare",
                    "version": "v1",
                    "endpoint_id": "quote-endpoint",
                    "deployment_region": None,
                },
                {
                    "role": "valuation",
                    "provider_id": 3,
                    "source": "tencent",
                    "version": "v1",
                    "endpoint_id": "valuation-endpoint",
                    "deployment_region": None,
                },
                {
                    "role": "akshare_financial_route:3",
                    "provider_id": 3,
                    "source": "akshare_financial",
                    "version": "v1",
                    "endpoint_id": "financial-endpoint",
                    "deployment_region": financial_region,
                },
            ]
        ),
        encoding="utf-8",
    )
    unit_path.write_text(
        json.dumps(
            {
                "schema": "release.provider-unit-contract.v1",
                "candidate_sha": candidate_sha,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-",
            str(settings_path),
            str(identities_path),
            str(unit_path),
            candidate_sha,
            str(PROJECT_ROOT),
        ],
        input=body,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == expected_code
    if expected_code:
        assert "S6_PROVIDER_IDENTITIES_INVALID" in result.stderr


def _final_validation_context(
    tmp_path: Path,
    *,
    advance_graph: bool = False,
    task_result_run_id: str | None = None,
) -> _FinalPrepareValidation:
    """Create one canonical private S6 attempt tree for helper-level validation."""

    candidate_sha = "c" * 40
    plan = build_attempt_plan(
        candidate_sha=candidate_sha,
        attempt_id=uuid4().hex,
        attempts_dir=tmp_path / "attempts",
        advance_isolated_market_graph=advance_graph,
    )
    attempt_root = Path(plan["root"])
    attempt_root.mkdir(parents=True)
    plan_bytes = (json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )
    plan_path = attempt_root / "attempt-plan.json"
    plan_path.write_bytes(plan_bytes)
    plan_path.chmod(0o400)
    inputs = attempt_root / "inputs-private"
    exports = Path(plan["provider_settings_export_path"]).parent
    inputs.mkdir(mode=0o700)
    exports.mkdir(parents=True, mode=0o700)
    names = {
        "provider-settings.json": {"candidate_sha": candidate_sha},
        "provider-identities.json": [
            {
                "role": "quote",
                "provider_id": 2,
                "source": "tushare",
                "version": "v1",
                "endpoint_id": "quote-endpoint",
                "deployment_region": None,
            },
            {
                "role": "valuation",
                "provider_id": 3,
                "source": "tencent",
                "version": "v1",
                "endpoint_id": "valuation-endpoint",
                "deployment_region": None,
            },
            {
                "role": "akshare_financial_route:3",
                "provider_id": 3,
                "source": "akshare_financial",
                "version": "v1",
                "endpoint_id": "financial-endpoint",
                "deployment_region": "unknown",
            },
        ],
        "unit-contract.json": {"candidate_sha": candidate_sha},
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
        f"POSTGRES_HOST={plan['postgres_container']}\nPOSTGRES_DB={plan['database']}\n"
        f"REDIS_HOST={plan['redis_container']}\n"
        f"REDIS_URL=redis://{plan['redis_container']}:6379/0\n",
        encoding="utf-8",
    )
    (inputs / "isolated-migrator.env").write_text(
        f"POSTGRES_HOST={plan['postgres_container']}\nPOSTGRES_DB={plan['database']}\n",
        encoding="utf-8",
    )
    for name in ("provider.env", "isolated-postgres.env", "isolated-migrator.env"):
        (inputs / name).chmod(0o600)
    inputs.chmod(0o700)
    exports.chmod(0o700)

    source_directory = Path(plan["candidate_source_snapshot_path"])
    source_directory.mkdir()
    source_receipt_path = Path(plan["candidate_source_receipt_path"])
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
    runner_python_path = attempt_root / "runner-venv" / "bin" / "python"
    runner_python_path.parent.mkdir(parents=True)
    runner_python_path.write_text("test-only\n", encoding="utf-8")
    runner_python_path.chmod(0o700)
    runner_python = str(runner_python_path)
    requirements_sha = "e" * 64
    runner_receipt_path = attempt_root / "runner-runtime-receipt.json"
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
    owner = exports.stat()
    context = _FinalPrepareValidation(
        candidate_sha=candidate_sha,
        source_directory=source_directory,
        source_receipt=source_receipt_path,
        container_uid=owner.st_uid,
        container_gid=owner.st_gid,
        execution_image_id="sha256:" + "d" * 64,
        inputs=inputs,
        exports=exports,
        runner_python=runner_python,
        requirements_sha256=requirements_sha,
        postgres_container_id="1" * 64,
        redis_container_id="2" * 64,
        network_id="3" * 64,
    )
    if advance_graph:
        run_id = "11111111-1111-4111-8111-111111111111"
        result_run_id = task_result_run_id or run_id
        activation_id = "22222222-2222-4222-8222-222222222222"
        datasets = (
            "equity.price.bar",
            "equity.quote.snapshot",
            "equity.valuation.fact",
        )
        pointers: list[dict[str, object]] = []
        publications: list[dict[str, object]] = []
        member_hashes = dict.fromkeys(datasets, "4" * 64)
        fact_hashes = dict.fromkeys(datasets, "5" * 64)
        for index, dataset in enumerate(datasets, start=1):
            publication_id = f"00000000-0000-4000-8000-{index:012d}"
            publication_hash = str(index) * 64
            pointers.append(
                {
                    "dataset_key": dataset,
                    "publication_id": publication_id,
                    "publication_hash": publication_hash,
                    "activation_id": activation_id,
                }
            )
            publications.append(
                {
                    "dataset_key": dataset,
                    "publication_id": publication_id,
                    "publication_hash": publication_hash,
                    "member_manifest_hash": member_hashes[dataset],
                    "run_id": run_id,
                    "state": "published",
                    "must_not_use_for_decision": False,
                    "coverage_requested_count": 3,
                    "coverage_eligible_count": 1,
                    "coverage_selected_count": 1,
                    "coverage_missing_count": 2,
                    "scope_blocks": [{"reason": "bounded_evidence_gap", "count": 2}],
                }
            )
        graph_receipt: dict[str, object] = {
            "schema": "release.s6-isolated-market-graph-refresh.v1",
            "outcome": "success",
            "candidate_sha": candidate_sha,
            "attempt_id": plan["attempt_id"],
            "attempt_plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
            "database": plan["database"],
            "postgres_container": plan["postgres_container"],
            "redis_container": plan["redis_container"],
            "postgres_container_id": context.postgres_container_id,
            "redis_container_id": context.redis_container_id,
            "network": plan["network"],
            "network_id": context.network_id,
            "execution_image_id": context.execution_image_id,
            "task_name": "data_center.refresh_full_market_publications",
            "task_id": f"s6-market-refresh-{plan['attempt_id']}",
            "task_attempt_id": "6" * 32,
            "task_result_sha256": "7" * 64,
            "task_result": {
                "outcome": "success",
                "requested": 3,
                "succeeded": 3,
                "failed": 0,
                "stored": 9,
                "publication_run_id": result_run_id,
            },
            "run_id": run_id,
            "activation_id": activation_id,
            "target_trade_date": "2026-10-10",
            "source_time_min": "2026-10-09T08:00:00+00:00",
            "source_time_max": "2026-10-10T08:00:00+00:00",
            "pointers": pointers,
            "publications": publications,
            "member_hashes": member_hashes,
            "fact_hashes": fact_hashes,
        }
        unsigned = (
            json.dumps(
                graph_receipt,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        graph_receipt["receipt_sha256"] = hashlib.sha256(unsigned).hexdigest()
        graph_encoded = (
            json.dumps(
                graph_receipt,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        graph_output = exports / "current-market-graph-refresh.json"
        graph_output.write_bytes(graph_encoded)
        graph_output.chmod(0o600)
        graph_input = inputs / graph_output.name
        graph_input.write_bytes(graph_encoded)
        graph_input.chmod(0o400)
    return context


@pytest.mark.skipif(os.name != "posix", reason="final validation requires POSIX file modes")
def test_final_validation_helper_writes_plan_bound_v3_receipt(tmp_path: Path) -> None:
    """The Python helper validates the attempt tree and records the opt-in graph."""

    from scripts import prepare_s6_candidate_source_snapshot as snapshot_helper

    context = _final_validation_context(tmp_path, advance_graph=True)
    try:
        result = snapshot_helper.main(
            [
                "--candidate-sha",
                context.candidate_sha,
                "--destination",
                str(context.source_directory),
                "--receipt",
                str(context.source_receipt),
                "--container-gid",
                str(context.container_gid),
                "--container-uid",
                str(context.container_uid),
                "--execution-image",
                context.execution_image_id,
                "--input-directory",
                str(context.inputs),
                "--output-directory",
                str(context.exports),
                "--validate-final-receipt",
                "--runner-python",
                context.runner_python,
                "--requirements-sha256",
                context.requirements_sha256,
                "--postgres-container-id",
                context.postgres_container_id,
                "--redis-container-id",
                context.redis_container_id,
                "--network-id",
                context.network_id,
            ]
        )
        assert result == 0
        receipt_path = context.inputs.parent / "prepare-receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["schema"] == "release.s6-prepare-receipt.v3"
        assert receipt["advance_isolated_market_graph"] is True
        assert (
            receipt["current_market_graph_refresh_run_id"] == "11111111-1111-4111-8111-111111111111"
        )
        assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt
        assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    finally:
        shutil.rmtree(context.exports, ignore_errors=True)


@pytest.mark.skipif(os.name != "posix", reason="final validation requires POSIX file modes")
def test_final_validation_helper_rejects_result_run_drift_without_receipt(
    tmp_path: Path,
) -> None:
    """A success receipt cannot be written when Task result and graph run differ."""

    context = _final_validation_context(
        tmp_path,
        advance_graph=True,
        task_result_run_id="33333333-3333-4333-8333-333333333333",
    )
    try:
        with pytest.raises(
            CandidateSourceSnapshotError, match="S6_GRAPH_REFRESH_TASK_RESULT_INVALID"
        ):
            validate_final_prepare_receipt(context)
        assert not (context.inputs.parent / "prepare-receipt.json").exists()
    finally:
        shutil.rmtree(context.exports, ignore_errors=True)


@pytest.mark.skipif(os.name != "posix", reason="final validation requires POSIX file modes")
def test_final_validation_helper_rejects_unexpected_export_without_receipt(
    tmp_path: Path,
) -> None:
    """Unexpected export files block preparation before receipt creation."""

    context = _final_validation_context(tmp_path)
    try:
        unexpected = context.exports / "unexpected.json"
        unexpected.write_text("{}\n", encoding="utf-8")
        unexpected.chmod(0o600)
        with pytest.raises(CandidateSourceSnapshotError, match="S6_EXPORT_FILE_SET_INVALID"):
            validate_final_prepare_receipt(context)
        assert not (context.inputs.parent / "prepare-receipt.json").exists()
    finally:
        shutil.rmtree(context.exports, ignore_errors=True)


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


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash success-tail check requires bash")
def test_wrapper_success_tail_sets_complete_and_reports_completion() -> None:
    """The final marker runs only after the phase is set to complete."""

    source = _wrapper_text()
    phase_marker = "\nphase=complete\nprintf 'S6_PREPARE_COMPLETE candidate=%s attempt=%s execution_image_id=%s\\n'"
    assert phase_marker in source
    assert "phase=completeprintf" not in source

    completion_tail = source[source.rindex("\nphase=complete") + 1 :]
    variable_arguments = '  "$sha" "$attempt_id" "$execution_image"'
    assert variable_arguments in completion_tail
    completion_tail = completion_tail.replace(
        variable_arguments,
        f"  candidate-test-sha attempt-test-id sha256:{'a' * 64}",
        1,
    )
    result = subprocess.run(
        [shutil.which("bash") or "bash", "-c", completion_tail],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "S6_PREPARE_COMPLETE candidate=candidate-test-sha attempt=attempt-test-id "
        f"execution_image_id=sha256:{'a' * 64}\n"
    )
