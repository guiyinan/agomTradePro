from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_checker():
    module_path = ROOT / "scripts" / "check_postgres_role_contract.py"
    spec = importlib.util.spec_from_file_location("check_postgres_role_contract", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _load_role_env_helper():
    module_path = ROOT / "scripts" / "ensure_vps_postgres_role_env.py"
    spec = importlib.util.spec_from_file_location("ensure_vps_postgres_role_env", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


role_env_helper = _load_role_env_helper()


def test_role_contract_evaluator_fails_closed_on_missing_or_false_checks() -> None:
    accepted = dict.fromkeys(checker.ROLE_CONTRACT_CHECKS, True)
    assert checker.evaluate_role_contract(accepted) == ()
    accepted["runtime_can_execute_fence_lock"] = False
    assert checker.evaluate_role_contract(accepted) == ("runtime_can_execute_fence_lock",)
    assert checker.evaluate_role_contract({}) == checker.ROLE_CONTRACT_CHECKS


def test_runtime_check_reuses_exact_authority_coverage_and_acl_verifiers() -> None:
    source = (ROOT / "scripts" / "check_postgres_role_contract.py").read_text(encoding="utf-8")
    assert "verify_account_authority_generation_coverage()" in source
    assert "verify_account_authority_generation_runtime_acl()" in source
    assert "source_relations AS" not in checker.ROLE_CONTRACT_SQL
    assert "search_path=pg_catalog" in checker.ROLE_CONTRACT_SQL
    assert "pg_temp" not in checker.ROLE_CONTRACT_SQL
    assert "'TRUNCATE'" in checker.ROLE_CONTRACT_SQL
    assert "'TRIGGER'" in checker.ROLE_CONTRACT_SQL


def test_bootstrap_requires_distinct_long_url_safe_role_passwords() -> None:
    bootstrap = (ROOT / "scripts" / "postgres_role_bootstrap.sql").read_text(encoding="utf-8")
    bootstrap_helper = (ROOT / "scripts" / "bootstrap_vps_postgres_roles.sh").read_text(
        encoding="utf-8"
    )
    assert "length(:'admin_password') >= 32" in bootstrap
    assert "length(:'runtime_password') >= 32" in bootstrap
    assert "length(:'migrator_password') >= 32" in bootstrap
    assert "public.account_authority_generation_lock()" in bootstrap
    assert "account_authority_generation_fence_lock" not in bootstrap
    assert "public.account_authority_generation_lock()" in checker.ROLE_CONTRACT_SQL
    assert "account_authority_generation_fence_lock" not in checker.ROLE_CONTRACT_SQL
    assert "AS collation" not in bootstrap
    assert "AS collation" not in checker.ROLE_CONTRACT_SQL
    assert ":'admin_password' <> :'runtime_password'" in bootstrap
    assert ":'admin_password' <> :'migrator_password'" in bootstrap
    assert ":'runtime_password' <> :'migrator_password'" in bootstrap
    assert "!~ '[^A-Za-z0-9_-]'" in bootstrap
    assert "WITH INHERIT FALSE, SET TRUE, ADMIN FALSE" in bootstrap
    assert "migrator must be the only member able to SET ROLE owner" in bootstrap
    assert "^(replace-with|change-this|your-password|password|secret)" in bootstrap
    assert "runtime still owns a public database object" in bootstrap
    assert re.search(
        r"IF EXISTS \(\s*SELECT 1\s*FROM \(\s*SELECT relation\.relowner AS owner_oid"
        r".*?\) AS public_object_owners\s*WHERE public_object_owners\.owner_oid"
        r" = 'agomtradepro_runtime'::pg_catalog\.regrole\s*\) THEN",
        bootstrap,
        flags=re.DOTALL,
    )
    assert "replace-with-url-safe-secret" not in bootstrap
    assert "postgresql://" not in bootstrap
    assert r"\getenv admin_password AGOMTRADEPRO_ADMIN_PASSWORD" in bootstrap
    assert "ALTER ROLE %I PASSWORD %L" in bootstrap
    assert "current_setting('log_statement') = 'none'" in bootstrap
    assert "current_setting('log_min_duration_statement') = '-1'" in bootstrap
    assert "current_setting('log_min_duration_sample') = '-1'" in bootstrap
    assert "current_setting('log_statement_sample_rate') = '0'" in bootstrap
    assert "current_setting('log_transaction_sample_rate') = '0'" in bootstrap
    assert "current_setting('log_min_error_statement') = 'panic'" in bootstrap
    assert "current_setting('log_parameter_max_length') = '0'" in bootstrap
    assert "current_setting('log_parameter_max_length_on_error') = '0'" in bootstrap
    assert "maintenance connection statement logging must be disabled" in bootstrap
    assert "maintenance_statement_logging_guard_failed" in bootstrap
    assert "role_password_contract_guard_failed" in bootstrap
    assert r"\quit" not in bootstrap
    assert bootstrap.index("maintenance_statement_logging_disabled") < bootstrap.index(
        "length(:'admin_password')"
    )
    assert bootstrap.index("BEGIN;") < bootstrap.index("ALTER ROLE %I PASSWORD %L")
    assert (
        'AGOMTRADEPRO_ADMIN_PASSWORD="$(get_env_kv POSTGRES_PASSWORD "$ENV_FILE")"'
        in bootstrap_helper
    )
    assert "-e AGOMTRADEPRO_ADMIN_PASSWORD" in bootstrap_helper
    assert '-e PGOPTIONS="$MAINTENANCE_PGOPTIONS"' in bootstrap_helper
    assert "log_statement=none" in bootstrap_helper
    assert "log_min_duration_statement=-1" in bootstrap_helper
    assert "log_min_duration_sample=-1" in bootstrap_helper
    assert "log_statement_sample_rate=0" in bootstrap_helper
    assert "log_transaction_sample_rate=0" in bootstrap_helper
    assert "log_min_error_statement=panic" in bootstrap_helper
    assert "log_parameter_max_length=0" in bootstrap_helper
    assert "log_parameter_max_length_on_error=0" in bootstrap_helper


def test_role_env_helper_generates_and_reuses_distinct_runtime_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / "deploy" / ".env"
    secrets_path = tmp_path / "secrets.env"
    env_path.parent.mkdir()
    env_path.write_text(
        "POSTGRES_DB=sample_db\nPOSTGRES_USER=admin\n"
        f"POSTGRES_PASSWORD={'P' * 36}\n"
        "DATABASE_URL=postgresql://admin:admin-password@postgres:5432/sample_db\n"
        "AGOMTRADEPRO_RUNTIME_PASSWORD=replace-with-url-safe-secret\n"
        "AGOMTRADEPRO_MIGRATOR_PASSWORD=replace-with-url-safe-secret\n",
        encoding="utf-8",
    )
    passwords = iter(("R" * 36, "M" * 36))
    monkeypatch.setattr(role_env_helper.secrets, "token_urlsafe", lambda _size: next(passwords))

    role_env_helper.ensure_vps_postgres_role_env(env_path, secrets_path)
    env = role_env_helper._read_env_file(env_path)
    persisted = role_env_helper._read_env_file(secrets_path)
    runtime_url = urlsplit(env["DATABASE_URL"])
    migrator_url = urlsplit(env["MIGRATOR_DATABASE_URL"])
    assert runtime_url.username == "agomtradepro_runtime"
    assert runtime_url.password == "R" * 36
    assert migrator_url.username == "agomtradepro_migrator"
    assert migrator_url.password == "M" * 36
    assert runtime_url.password != migrator_url.password
    assert env["POSTGRES_PASSWORD"] not in {
        runtime_url.password,
        migrator_url.password,
    }
    assert runtime_url.hostname == migrator_url.hostname == "postgres"
    assert runtime_url.path == migrator_url.path == "/sample_db"
    assert env["POSTGRES_USER"] == "admin"
    assert env["POSTGRES_PASSWORD"] == "P" * 36
    assert persisted["DATABASE_URL"] == env["DATABASE_URL"]
    assert persisted["MIGRATOR_DATABASE_URL"] == env["MIGRATOR_DATABASE_URL"]
    assert persisted["POSTGRES_PASSWORD"] == "P" * 36

    monkeypatch.setattr(
        role_env_helper.secrets,
        "token_urlsafe",
        lambda _size: pytest.fail("existing valid role passwords must be reused"),
    )
    role_env_helper.ensure_vps_postgres_role_env(env_path, secrets_path)
    assert role_env_helper._read_env_file(env_path)["DATABASE_URL"] == env["DATABASE_URL"]


def test_role_env_helper_rotates_placeholder_admin_password_and_persists_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / "deploy" / ".env"
    secrets_path = tmp_path / "secrets.env"
    env_path.parent.mkdir()
    env_path.write_text(
        "POSTGRES_DB=sample_db\nPOSTGRES_PASSWORD=change-this-admin\n",
        encoding="utf-8",
    )
    secrets_path.write_text("POSTGRES_PASSWORD=placeholder\n", encoding="utf-8")
    generated_passwords = iter(("A" * 36, "R" * 36, "M" * 36))
    monkeypatch.setattr(
        role_env_helper.secrets,
        "token_urlsafe",
        lambda _size: next(generated_passwords),
    )

    role_env_helper.ensure_vps_postgres_role_env(env_path, secrets_path)

    env = role_env_helper._read_env_file(env_path)
    persisted = role_env_helper._read_env_file(secrets_path)
    assert env["POSTGRES_PASSWORD"] == "A" * 36
    assert persisted["POSTGRES_PASSWORD"] == env["POSTGRES_PASSWORD"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{36,}", env["POSTGRES_PASSWORD"])


def test_role_env_helper_replaces_env_files_atomically_with_private_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / "deploy" / ".env"
    secrets_path = tmp_path / "secrets.env"
    env_path.parent.mkdir()
    env_path.write_text("POSTGRES_DB=sample_db\n", encoding="utf-8")
    original_replace = role_env_helper.os.replace
    replacements: list[tuple[Path, Path]] = []
    chmod_calls: list[tuple[Path, int]] = []
    original_chmod = role_env_helper.os.chmod

    def inspect_chmod(path: Path, mode: int) -> None:
        chmod_calls.append((path, mode))
        original_chmod(path, mode)

    def inspect_replace(source: Path, destination: Path) -> None:
        if destination == env_path:
            assert destination.read_text(encoding="utf-8") == "POSTGRES_DB=sample_db\n"
        else:
            assert not destination.exists()
        assert source.parent == destination.parent
        assert chmod_calls[-1] == (source, 0o600)
        replacements.append((source, destination))
        original_replace(source, destination)

    generated_passwords = iter(("A" * 36, "R" * 36, "M" * 36))
    monkeypatch.setattr(
        role_env_helper.secrets,
        "token_urlsafe",
        lambda _size: next(generated_passwords),
    )
    monkeypatch.setattr(role_env_helper.os, "chmod", inspect_chmod)
    monkeypatch.setattr(role_env_helper.os, "replace", inspect_replace)
    role_env_helper.ensure_vps_postgres_role_env(env_path, secrets_path)

    assert [destination for _, destination in replacements] == [env_path, secrets_path]
    assert not any(source.exists() for source, _ in replacements)


def test_runtime_compose_services_do_not_receive_migrator_url() -> None:
    compose = (ROOT / "docker" / "docker-compose.vps.yml").read_text(encoding="utf-8")

    def service_block(name: str) -> str:
        match = re.search(
            rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:|\Z)",
            compose,
        )
        assert match is not None
        return match.group(1)

    migrator = service_block("migrator")
    web = service_block("web")
    worker = service_block("celery_worker")
    beat = service_block("celery_beat")
    assert len(re.findall(r"\$\{MIGRATOR_DATABASE_URL:", compose)) == 1
    assert "MIGRATOR_DATABASE_URL" in migrator
    assert (
        'command: ["python", "-m", "scripts.manage_vps_migrations", '
        '"migrate", "--noinput"]' in migrator
    )
    assert "python scripts/manage_vps_migrations.py" not in compose
    migration_runner = (ROOT / "scripts" / "manage_vps_migrations.py").read_text(encoding="utf-8")
    assert '_ALLOWED_COMMANDS = frozenset({"migrate", "flush", "loaddata"})' in migration_runner
    for service in (web, worker, beat):
        assert "DATABASE_URL: ${DATABASE_URL:?DATABASE_URL is required}" in service
        assert "AGOMTRADEPRO_DATABASE_ROLE: runtime" in service
        assert "MIGRATOR_DATABASE_URL" not in service


def test_remote_deploy_uses_migration_helper_as_the_only_bootstrap_gate() -> None:
    remote = (ROOT / "scripts" / "remote_build_deploy_vps.py").read_text(encoding="utf-8")
    helper = (ROOT / "scripts" / "migrate-vps-sqlite-to-postgres.sh").read_text(encoding="utf-8")
    logging_window = (ROOT / "scripts" / "postgres_statement_logging_window.sh").read_text(
        encoding="utf-8"
    )

    assert "compose up -d runtime_ns redis postgres" in remote
    assert (
        'COMPOSE_PROJECT_NAME=agomtradepro sh scripts/migrate-vps-sqlite-to-postgres.sh "$TARGET_DIR" "$RELEASE_DIR"'
        in remote
    )
    assert "python3 scripts/ensure_vps_postgres_role_env.py" in remote
    assert remote.index('set_env_kv "POSTGRES_PASSWORD" "$POSTGRES_PASSWORD_VALUE"') < remote.index(
        "python3 scripts/ensure_vps_postgres_role_env.py"
    )
    assert "bootstrap_vps_postgres_roles.sh" not in remote
    assert (
        "for runtime_service in web celery_worker celery_qlib_worker celery_beat terminal_agent_worker; do"
        in remote
    )
    assert 'compose stop "$runtime_service"' in remote
    assert (
        remote.index('compose stop "$runtime_service"')
        < remote.index("compose up -d runtime_ns redis postgres")
        < remote.index(
            'if ! COMPOSE_PROJECT_NAME=agomtradepro sh scripts/migrate-vps-sqlite-to-postgres.sh "$TARGET_DIR" "$RELEASE_DIR"; then'
        )
        < remote.index("compose up -d $SERVICES")
    )
    ready_check_position = helper.index('if [ "$POSTGRES_READY" != "1" ]')
    logging_window_call = helper.index("enter_statement_logging_window\n", ready_check_position)
    assert (
        helper.index("POSTGRES_READY=1")
        < ready_check_position
        < logging_window_call
        < helper.index('bash "$RELEASE_DIR/scripts/bootstrap_vps_postgres_roles.sh"')
    )
    assert '. "$RELEASE_DIR/scripts/postgres_statement_logging_window.sh"' in helper
    assert "ALTER SYSTEM SET log_statement = 'none'" in logging_window
    assert "ALTER SYSTEM SET log_min_duration_sample = '-1'" in logging_window
    assert "ALTER SYSTEM SET log_statement_sample_rate = '0'" in logging_window
    assert "ALTER SYSTEM SET log_transaction_sample_rate = '0'" in logging_window
    assert "ALTER SYSTEM SET log_parameter_max_length_on_error = '0'" in logging_window
    assert "ALTER SYSTEM RESET log_statement" in logging_window
    assert "ALTER SYSTEM RESET log_min_duration_sample" in logging_window
    assert "PostgreSQL statement logging settings were not restored" in logging_window
    assert "[0-9]+(us|ms|s|min|h|d)?" in logging_window
    assert helper.index("restore_statement_logging\n  trap - EXIT") < helper.index(
        "printf 'initialized_without_legacy_sqlite="
    )
    assert helper.index("restore_statement_logging\ntrap - EXIT") < helper.index(
        "printf 'migrated_from_sqlite="
    )

    bootstrap_calls = re.findall(
        r'^[ \t]*bash "\$RELEASE_DIR/scripts/bootstrap_vps_postgres_roles\.sh".*$',
        helper,
        flags=re.MULTILINE,
    )
    migrate_calls = re.findall(
        r"^[ \t]*compose run --rm --no-deps migrator python -m scripts\.manage_vps_migrations migrate --noinput$",
        helper,
        flags=re.MULTILINE,
    )
    assert len(bootstrap_calls) == 6
    assert len(migrate_calls) == 3
    bootstrap_positions = [
        match.start() for match in re.finditer(re.escape(bootstrap_calls[0]), helper)
    ]
    migrate_positions = [
        match.start() for match in re.finditer(re.escape(migrate_calls[0]), helper)
    ]
    assert all(
        before < migrate < after
        for before, migrate, after in zip(
            bootstrap_positions[::2],
            migrate_positions,
            bootstrap_positions[1::2],
            strict=True,
        )
    )


def test_vps_deploy_bootstraps_roles_after_readiness_before_migrator() -> None:
    deploy = (ROOT / "scripts" / "deploy-on-vps.sh").read_text(encoding="utf-8")
    bootstrap_helper = (ROOT / "scripts" / "bootstrap_vps_postgres_roles.sh").read_text(
        encoding="utf-8"
    )
    migration_helper = (ROOT / "scripts" / "migrate-vps-sqlite-to-postgres.sh").read_text(
        encoding="utf-8"
    )
    ready_check = 'if [ "$POSTGRES_READY" != "1" ]'
    runtime_stop = "for runtime_service in web celery_worker celery_qlib_worker celery_beat terminal_agent_worker; do"
    runtime_stop_command = 'compose_vps stop "$runtime_service"'
    migrate_helper_call = 'COMPOSE_PROJECT_NAME="$PROJECT_NAME" sh scripts/migrate-vps-sqlite-to-postgres.sh "$TARGET_DIR" "$release_dir"'
    migrate = "compose run --rm --no-deps migrator python -m scripts.manage_vps_migrations migrate --noinput"

    assert (
        deploy.index("ensure_database_role_env\n\ncore_services")
        < deploy.index(runtime_stop)
        < deploy.index(runtime_stop_command)
        < deploy.index(migrate_helper_call)
    )
    assert "bootstrap_vps_postgres_roles.sh" not in deploy
    assert 'bash "$RELEASE_DIR/scripts/bootstrap_vps_postgres_roles.sh"' in migration_helper
    assert migration_helper.index("POSTGRES_READY=1") < migration_helper.index(ready_check)
    assert (
        migration_helper.index(ready_check)
        < migration_helper.index('bash "$RELEASE_DIR/scripts/bootstrap_vps_postgres_roles.sh"')
        < migration_helper.index(migrate)
    )
    assert 'extra_services="$extra_services terminal_agent_worker"' in deploy
    assert "env_value TERMINAL_RUNTIME_AUTHORIZED deploy/.env" in deploy
    assert "env_value TERMINAL_QUEUED_INTAKE_ENABLED deploy/.env" in deploy
    assert "env_value TERMINAL_QUEUED_WORKER_ENABLED deploy/.env" in deploy
    assert "compose_vps up -d web caddy $extra_services" in deploy
    assert 'RELEASE_DIR="${3:-$TARGET_DIR/current}"' in bootstrap_helper
    assert 'COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-agomtradepro}"' in bootstrap_helper
    assert 'COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-agomtradepro}"' in migration_helper
    assert "Runtime service $runtime_service is still running" in migration_helper
    assert migration_helper.index(
        "Runtime service $runtime_service is still running"
    ) < migration_helper.index("compose up -d runtime_ns redis postgres")
    assert (
        'bash "$RELEASE_DIR/scripts/bootstrap_vps_postgres_roles.sh" "$TARGET_DIR" --apply "$RELEASE_DIR"'
        in migration_helper
    )
    assert 'rm -f "$TARGET_DIR/.postgres-migration-complete"' in deploy
    assert deploy.index('mkdir -p "$TARGET_DIR/releases"') > deploy.index(
        'if [ "$ACTION" = "logs" ]; then'
    )
    assert '"${PROJECT_NAME}_sqlite_data:/dest"' in deploy
    status_block = deploy.split('if [ "$ACTION" = "status" ]; then', 1)[1].split("fi", 1)[0]
    logs_block = deploy.split('if [ "$ACTION" = "logs" ]; then', 1)[1].split("fi", 1)[0]
    assert "ensure_database_role_env" not in status_block
    assert "ensure_database_role_env" not in logs_block
    assert (
        'bash scripts/migrate-vps-sqlite-to-postgres.sh "$TARGET_DIR" "$release_dir"' not in deploy
    )
    assert "python manage.py migrate --noinput" not in deploy
    assert '"${COMPOSE_PROJECT_NAME}_sqlite_data:/source:ro"' in migration_helper
    assert 'COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-agomtradepro}"' in migration_helper


def test_runtime_role_passwords_are_persisted_as_distinct_split_urls() -> None:
    remote = (ROOT / "scripts" / "remote_build_deploy_vps.py").read_text(encoding="utf-8")
    role_env = (ROOT / "scripts" / "ensure_vps_postgres_role_env.py").read_text(encoding="utf-8")

    assert "secrets.token_urlsafe(36)" in role_env
    assert "len(value) < 32" in role_env
    assert "migrator_password in {" in role_env
    assert "admin_password," in role_env
    assert "runtime_password," in role_env
    assert "postgresql://agomtradepro_runtime:{runtime_password}" in role_env
    assert "postgresql://agomtradepro_migrator:{migrator_password}" in role_env
    assert '"DATABASE_URL": runtime_url' in role_env
    assert '"MIGRATOR_DATABASE_URL": migrator_url' in role_env
    assert "python3 scripts/ensure_vps_postgres_role_env.py" in remote
    assert "generate_role_password" not in remote
    assert "postgresql://${POSTGRES_USER_VALUE}:${POSTGRES_PASSWORD_VALUE}@postgres:" not in remote


def test_runtime_entrypoint_runs_role_check_before_startup_commands() -> None:
    entrypoint = (ROOT / "docker" / "entrypoint.prod.sh").read_text(encoding="utf-8")
    assert 'if [ "$database_role" = "runtime" ]; then' in entrypoint
    assert "python -m scripts.check_postgres_role_contract" in entrypoint
    assert entrypoint.index("python -m scripts.check_postgres_role_contract") < entrypoint.index(
        'if [ "$is_web_command" = "1" ]'
    )
    migration_helper = (ROOT / "scripts" / "migrate-vps-sqlite-to-postgres.sh").read_text(
        encoding="utf-8"
    )
    assert "web python -m scripts.sqlite_snapshot_contract capture" in migration_helper
    assert re.search(r"\bpython scripts/[A-Za-z0-9_./-]+\.py", entrypoint) is None
    assert re.search(r"\bpython scripts/[A-Za-z0-9_./-]+\.py", migration_helper) is None
