from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_production_dockerfile_installs_pyqlib_distribution() -> None:
    dockerfile = (REPO_ROOT / "docker" / "Dockerfile.prod").read_text(encoding="utf-8")

    assert "ARG PYQLIB_VERSION=0.9.7" in dockerfile
    assert '"pyqlib==${PYQLIB_VERSION}"' in dockerfile
    assert "metadata.distribution('pyqlib')" in dockerfile
    assert "import qlib.data" in dockerfile
    assert "libgomp1" in dockerfile
    assert " qlib>=0.9.0" not in dockerfile


def test_mirror_dockerfile_installs_pyqlib_distribution() -> None:
    dockerfile = (REPO_ROOT / "docker" / "Dockerfile.prod.mirror").read_text(encoding="utf-8")

    assert "ARG PYQLIB_VERSION=0.9.7" in dockerfile
    assert '"pyqlib==${PYQLIB_VERSION}"' in dockerfile
    assert "metadata.distribution('pyqlib')" in dockerfile
    assert "import qlib.data" in dockerfile
    assert "libgomp1" in dockerfile
    assert " qlib>=0.9.0" not in dockerfile


def test_qlib_train_image_uses_supported_python_and_pyqlib_distribution() -> None:
    dockerfile = (REPO_ROOT / "docker" / "Dockerfile.qlib-train").read_text(encoding="utf-8")

    assert dockerfile.startswith("FROM python:3.11-slim\n")
    assert "python -m pip install pyqlib lightgbm scipy" in dockerfile
    assert "libgomp1" in dockerfile
    assert "python -m pip install qlib " not in dockerfile


def test_production_images_include_postgresql_backup_client() -> None:
    for relative_path in ("docker/Dockerfile.prod", "docker/Dockerfile.prod.mirror"):
        dockerfile = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        instructions = "\n".join(
            line for line in dockerfile.splitlines() if not line.lstrip().startswith("#")
        )
        assert "ARG POSTGRESQL_CLIENT_MAJOR=16" in instructions, relative_path
        assert '"postgresql-client-${POSTGRESQL_CLIENT_MAJOR}"' in instructions, relative_path
        assert "pg_dump --version" in instructions, relative_path
        assert "postgresql-client \\" not in instructions, relative_path


def test_production_image_includes_tui_release_publisher() -> None:
    """The deploy-time TUI publisher must survive Docker context filtering."""

    dockerignore_lines = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    shell_script_exclusion = dockerignore_lines.index("scripts/*.sh")
    publisher_inclusion = dockerignore_lines.index("!scripts/publish-tui-release.sh")

    assert publisher_inclusion > shell_script_exclusion
    assert (REPO_ROOT / "scripts" / "publish-tui-release.sh").is_file()
    for relative_path in ("docker/Dockerfile.prod", "docker/Dockerfile.prod.mirror"):
        dockerfile = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "COPY . /app" in dockerfile, relative_path


def test_linux_wheelhouse_directory_is_preserved_for_docker_copy() -> None:
    assert (REPO_ROOT / ".cache" / "pip-wheels" / "linux-py311" / ".keep").exists()
    deploy_script = (REPO_ROOT / "scripts" / "remote_build_deploy_vps.py").read_text(
        encoding="utf-8"
    )
    assert 'os.environ.get("AGOM_VPS_INCLUDE_WHEELHOUSE", "")' in deploy_script
    assert 'if not include_wheelhouse and path.name != ".keep":' in deploy_script
    assert '"git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"' in (
        deploy_script
    )
    assert "SSH connection attempt {attempt}/4 failed" in deploy_script
    assert "find . -type f -name '*.sh' -exec sed -i 's/\\r$//' {} +" in deploy_script


def test_docker_context_excludes_codex_runtime_temporaries() -> None:
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert ".codex_tmp/" in dockerignore
    assert ".codex-test-deps/" in dockerignore


def test_vps_compose_worker_consumes_qlib_queues() -> None:
    compose = (REPO_ROOT / "docker" / "docker-compose.vps.yml").read_text(encoding="utf-8")
    healthcheck = (REPO_ROOT / "docker" / "healthcheck-web.sh").read_text(encoding="utf-8")

    assert "CELERY_WORKER_QUEUES:-celery,qlib_infer,qlib_train" in compose
    assert "healthcheck:\n      disable: true" in compose
    assert '"$curl_bin" -fsS --connect-timeout 2 --max-time 5' in healthcheck
    assert "curl -sS -o /dev/null -w '%{http_code}'" not in compose


def test_vps_compose_freezes_terminal_queue_migration_flags() -> None:
    """Queue flags require an explicit reviewed runtime authorization."""

    compose = (REPO_ROOT / "docker" / "docker-compose.vps.yml").read_text(encoding="utf-8")
    expected = {
        "TERMINAL_QUEUED_INTAKE_ENABLED: ${TERMINAL_QUEUED_INTAKE_ENABLED:-false}",
        "TERMINAL_QUEUED_WORKER_ENABLED: ${TERMINAL_QUEUED_WORKER_ENABLED:-false}",
        "TERMINAL_RUNTIME_AUTHORIZED: ${TERMINAL_RUNTIME_AUTHORIZED:-false}",
        "TERMINAL_LEGACY_INLINE_ENABLED: ${TERMINAL_LEGACY_INLINE_ENABLED:-true}",
        "TERMINAL_EMERGENCY_STOP: ${TERMINAL_EMERGENCY_STOP:-false}",
        "TERMINAL_PER_USER_QUEUED_LIMIT: ${TERMINAL_PER_USER_QUEUED_LIMIT:-4}",
        "TERMINAL_GLOBAL_QUEUED_LIMIT: ${TERMINAL_GLOBAL_QUEUED_LIMIT:-40}",
        "TERMINAL_PER_USER_ACTIVE_LIMIT: ${TERMINAL_PER_USER_ACTIVE_LIMIT:-1}",
        "TERMINAL_GLOBAL_ACTIVE_LIMIT: ${TERMINAL_GLOBAL_ACTIVE_LIMIT:-4}",
        "TERMINAL_LEGACY_INLINE_CONCURRENCY: ${TERMINAL_LEGACY_INLINE_CONCURRENCY:-1}",
        "TERMINAL_LEGACY_INLINE_TIMEOUT_SECONDS: ${TERMINAL_LEGACY_INLINE_TIMEOUT_SECONDS:-60}",
    }
    assert all(item in compose for item in expected)


def test_production_settings_require_explicit_terminal_runtime_authorization() -> None:
    """Production queue flags are jointly gated by the runtime authorization switch."""

    production = (REPO_ROOT / "core" / "settings" / "production.py").read_text(encoding="utf-8")
    assert (
        '_TERMINAL_RUNTIME_AUTHORIZED = env.bool("TERMINAL_RUNTIME_AUTHORIZED", default=False)'
        in production
    )
    assert (
        "TERMINAL_QUEUED_INTAKE_ENABLED = _TERMINAL_RUNTIME_AUTHORIZED and env.bool(" in production
    )
    assert (
        "TERMINAL_QUEUED_WORKER_ENABLED = _TERMINAL_RUNTIME_AUTHORIZED and env.bool(" in production
    )
    assert "TERMINAL_LEGACY_INLINE_ENABLED = True" in production
    assert "TERMINAL_LEGACY_INLINE_CONCURRENCY = 1" in production
    assert "TERMINAL_LEGACY_INLINE_TIMEOUT_SECONDS = 60" in production


def test_vps_compose_declares_dedicated_terminal_agent_worker() -> None:
    """The queued route has a separate queue and bounded worker process."""

    compose = (REPO_ROOT / "docker" / "docker-compose.vps.yml").read_text(encoding="utf-8")
    assert "terminal_agent_worker:" in compose
    assert "- terminal_agent" in compose
    assert "TERMINAL_RUNTIME_ROLE: queued_worker" in compose
    assert "--prefetch-multiplier" in compose


def test_vps_compose_uses_neutral_pid_namespace_service() -> None:
    compose = (REPO_ROOT / "docker" / "docker-compose.vps.yml").read_text(encoding="utf-8")

    assert "runtime_ns:" in compose
    assert 'pid: "service:runtime_ns"' in compose
    assert 'pid: "service:web"' not in compose


def test_production_runtime_mounts_and_embeds_release_identity() -> None:
    compose = (REPO_ROOT / "docker" / "docker-compose.vps.yml").read_text(encoding="utf-8")

    assert (
        compose.count("../.agom-release-manifest.json:/run/agomtradepro/release-manifest.json:ro")
        == 3
    )
    assert compose.count("AGOM_RELEASE_MANIFEST_PATH: /run/agomtradepro/release-manifest.json") == 3
    for relative_path in ("docker/Dockerfile.prod", "docker/Dockerfile.prod.mirror"):
        dockerfile = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "/app/.agom-build-identity.json" in dockerfile, relative_path
        assert "'schema_version': 1" in dockerfile, relative_path
        assert "'source_commit': os.environ['SOURCE_COMMIT']" in dockerfile, relative_path


def test_vps_remote_deploy_defaults_and_celery_runtime_checks() -> None:
    script = (REPO_ROOT / "scripts" / "remote_build_deploy_vps.py").read_text(encoding="utf-8")
    one_click_script = (REPO_ROOT / "scripts" / "deploy-vps.ps1").read_text(encoding="utf-8")
    compose = (REPO_ROOT / "docker" / "docker-compose.vps.yml").read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "docker" / "Dockerfile.prod").read_text(encoding="utf-8")
    backup = (REPO_ROOT / "scripts" / "vps-backup.sh").read_text(encoding="utf-8")
    restore = (REPO_ROOT / "scripts" / "vps-restore.sh").read_text(encoding="utf-8")
    migration = (REPO_ROOT / "scripts" / "migrate-vps-sqlite-to-postgres.sh").read_text(
        encoding="utf-8"
    )
    entrypoint = (REPO_ROOT / "docker" / "entrypoint.prod.sh").read_text(encoding="utf-8")
    production_settings = (REPO_ROOT / "core" / "settings" / "production.py").read_text(
        encoding="utf-8"
    )
    caddyfile = (REPO_ROOT / "docker" / "Caddyfile.template").read_text(encoding="utf-8")

    assert 'os.environ.get("AGOM_VPS_TIMEOUT", "3600")' in script
    assert "[int]$BuildTimeoutSeconds = 3600" in one_click_script
    assert "'--timeout', \"$BuildTimeoutSeconds\"" in one_click_script
    assert "'--timeout', '120'" in one_click_script
    assert "compose up -d runtime_ns redis postgres" in script
    assert 'SERVICES="runtime_ns redis postgres web caddy"' in script
    assert 'if [ "$ENABLE_CELERY" = "1" ]; then' in script
    assert "celery_worker celery_beat" in script
    assert "env_value()" in script
    assert "TERMINAL_WORKER_ENABLED=0" in script
    assert "compose rm -sf terminal_agent_worker" in script
    assert 'EXPECTED_RUNTIME_IMAGE="agomtradepro-web:$RELEASE_TAG"' in script
    assert "terminal_agent_worker image does not match release" in script
    assert "celery -A core inspect ping --timeout=8" in script
    assert "for attempt in $(seq 1 12)" in script
    assert "Celery worker did not respond to inspect ping after retries" in script
    assert "SKIP_PREDEPLOY_BACKUP" in script
    assert "AUTO_ROLLBACK" in script
    assert "rollback_deployment" in script
    assert 'bash "$RELEASE_DIR/scripts/vps-backup.sh"' in script
    assert "chmod 600" in script
    assert "if ($GlobalDockerCleanup)" in one_click_script
    assert "npm run check:tui" in one_click_script
    assert "--expected-commit" in one_click_script
    assert "org.opencontainers.image.revision=$SOURCE_COMMIT" in dockerfile
    assert "python manage.py show_release_identity" in script
    assert '--expected-commit "$SOURCE_COMMIT" --json' in script
    assert '"build_started_at"' in script
    assert '"build_finished_at"' in script
    assert 'release_tag = os.environ["RELEASE_TAG"]' in script
    assert 'image_ref = f"agomtradepro-web:{release_tag}"' in script
    assert 'Path(".").name.replace("source-", "")' not in script
    assert "-m compileall -q /app" in script
    assert "WEB_MEMORY_LIMIT:-1g" in compose
    assert "CELERY_BEAT_MEMORY_LIMIT:-512m" in compose
    assert "/app/backups/database" in compose
    assert "source.backup(destination)" in backup
    assert "PRAGMA integrity_check" in backup
    assert "pg_dump" in backup
    assert "pg_restore --list" in backup
    assert "pg_restore" in restore
    assert "dropdb --force --if-exists" in restore
    assert "postgres:16-alpine" in compose
    assert "postgres_data:/var/lib/postgresql/data" in compose
    assert "POSTGRES_PASSWORD is required" in compose
    assert "DATABASE_URL is required" in compose
    assert "REALTIME_WEBSOCKET_ENABLED:-True" in compose
    assert "SECURE_SSL_REDIRECT:-False" in compose
    assert 'set_env_kv "SECURE_SSL_REDIRECT" "True"' not in script
    assert (
        'MIDDLEWARE.index("django.middleware.security.SecurityMiddleware")' in production_settings
    )
    assert 'SILENCED_SYSTEM_CHECKS = ["security.W008"]' in production_settings
    assert 'Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"' in caddyfile
    assert 'X-Content-Type-Options "nosniff"' in caddyfile
    assert 'Referrer-Policy "strict-origin-when-cross-origin"' in caddyfile
    assert "?Strict-Transport-Security" not in caddyfile
    assert 'CMD ["daphne"]' in dockerfile
    assert "core.asgi:application" in entrypoint
    assert "core.wsgi:application" not in entrypoint
    assert "sqlite-to-postgres.jsonl" in migration
    assert "--format jsonl" in migration
    assert "PYTHONUTF8=1" in migration
    assert "manage.py flush --noinput" in migration
    assert "AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS=1" in migration
    assert "pg_isready" in migration
    assert "PostgreSQL did not become ready within 120 seconds" in migration
    assert "dropdb --force --if-exists" in migration
    assert "Critical table count mismatch" in migration
    assert "for model in apps.get_models()" in migration
    assert '"auth.permission"' in migration
    assert ".postgres-migration-complete" in migration
    assert "check_encryption_readiness --json" in migration


def test_apps_with_infrastructure_models_have_django_discovery_bridge() -> None:
    """Every infrastructure model module must be discoverable by Django commands."""

    missing = []
    for infrastructure_model in sorted((REPO_ROOT / "apps").glob("*/infrastructure/models.py")):
        bridge = infrastructure_model.parents[1] / "models.py"
        if not bridge.exists():
            missing.append(str(bridge.relative_to(REPO_ROOT)))

    assert missing == []


def test_git_clone_include_sqlite_uploads_local_db_before_deploy() -> None:
    script = (REPO_ROOT / "scripts" / "remote_build_deploy_vps.py").read_text(encoding="utf-8")

    assert "def _upload_sqlite_to_git_clone_release" in script
    assert "Uploading local SQLite for git-clone deploy" in script
    assert "PRAGMA integrity_check" in script
    assert "_upload_sqlite_to_git_clone_release(" in script


def test_remote_deploy_passes_source_commit_to_release_identity_gate() -> None:
    """The deploy phase must receive the same immutable commit as the image."""

    script = (REPO_ROOT / "scripts" / "remote_build_deploy_vps.py").read_text(encoding="utf-8")

    assert '"SOURCE_COMMIT": source_commit' in script
    assert '"RELEASE_TAG": tag' in script
    assert '--expected-commit "$SOURCE_COMMIT" --json' in script


def test_include_sqlite_fails_when_release_db_is_missing() -> None:
    script = (REPO_ROOT / "scripts" / "remote_build_deploy_vps.py").read_text(encoding="utf-8")

    assert 'if [ "$INCLUDE_SQLITE" = "1" ]; then' in script
    assert "INCLUDE_SQLITE=1 but backups/db.sqlite3 is missing in release" in script
    assert "exit 1" in script


def test_sqlite_restore_carries_source_encryption_key_and_checks_readiness() -> None:
    script = (REPO_ROOT / "scripts" / "remote_build_deploy_vps.py").read_text(encoding="utf-8")
    one_click_script = (REPO_ROOT / "scripts" / "deploy-vps.ps1").read_text(encoding="utf-8")

    assert "def _resolve_sqlite_encryption_key" in script
    assert "--include-sqlite requires the source AGOMTRADEPRO_ENCRYPTION_KEY" in script
    assert "SQLite restore will use the source database encryption key" in script
    assert "check_encryption_readiness --json" in script
    assert "encrypted production data is not readable with the deployed key" in script
    assert "overwrite DB and use source encryption key" in one_click_script


def test_windows_start_dev_uses_python_module_celery_and_all_queues() -> None:
    script = (REPO_ROOT / "scripts" / "start-dev.ps1").read_text(encoding="utf-8")

    assert "-m celery -A core worker" in script
    assert "-Q celery,qlib_infer,qlib_train" in script
    assert "start_celery_worker.bat" not in script
    assert "start_celery_beat.bat" not in script


def test_web_startup_does_not_run_alpha_bootstrap_by_default() -> None:
    compose = (REPO_ROOT / "docker" / "docker-compose.vps.yml").read_text(encoding="utf-8")
    entrypoint = (REPO_ROOT / "docker" / "entrypoint.prod.sh").read_text(encoding="utf-8")
    deploy_script = (REPO_ROOT / "scripts" / "remote_build_deploy_vps.py").read_text(
        encoding="utf-8"
    )
    env_example = (REPO_ROOT / "deploy" / ".env.vps.example").read_text(encoding="utf-8")

    assert "AGOMTRADEPRO_CHECK_DEPLOY_ON_START: ${AGOMTRADEPRO_CHECK_DEPLOY_ON_START:-0}" in compose
    assert "AGOMTRADEPRO_AUTO_MIGRATE_ON_START: ${AGOMTRADEPRO_AUTO_MIGRATE_ON_START:-0}" in compose
    assert "AGOMTRADEPRO_BOOTSTRAP_ON_START: ${AGOMTRADEPRO_BOOTSTRAP_ON_START:-0}" in compose
    assert (
        "AGOMTRADEPRO_COLLECTSTATIC_ON_START: ${AGOMTRADEPRO_COLLECTSTATIC_ON_START:-0}" in compose
    )
    assert (
        "AGOMTRADEPRO_SETUP_SCHEDULE_ON_START: ${AGOMTRADEPRO_SETUP_SCHEDULE_ON_START:-0}"
        in compose
    )
    assert (
        "AGOMTRADEPRO_ENSURE_SUPERUSER_ON_START: ${AGOMTRADEPRO_ENSURE_SUPERUSER_ON_START:-0}"
        in compose
    )
    assert (
        "AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START: ${AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START:-0}"
        in compose
    )
    assert "AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START=0" in env_example
    assert "AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START=1" not in env_example
    assert "${AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START:-0}" in entrypoint
    assert "${AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START:-1}" not in entrypoint
    assert 'set_env_kv "AGOMTRADEPRO_CHECK_DEPLOY_ON_START" "0"' in deploy_script
    assert 'set_env_kv "AGOMTRADEPRO_AUTO_MIGRATE_ON_START" "0"' in deploy_script
    assert 'set_env_kv "AGOMTRADEPRO_BOOTSTRAP_ON_START" "0"' in deploy_script
    assert 'set_env_kv "AGOMTRADEPRO_COLLECTSTATIC_ON_START" "0"' in deploy_script
    assert 'set_env_kv "AGOMTRADEPRO_SETUP_SCHEDULE_ON_START" "0"' in deploy_script
    assert 'set_env_kv "AGOMTRADEPRO_ENSURE_SUPERUSER_ON_START" "0"' in deploy_script
    assert "${AGOMTRADEPRO_AUTO_MIGRATE_ON_START:-0}" in entrypoint
    assert "${AGOMTRADEPRO_CHECK_DEPLOY_ON_START:-0}" in entrypoint
    assert "${AGOMTRADEPRO_BOOTSTRAP_ON_START:-0}" in entrypoint
    assert "${AGOMTRADEPRO_COLLECTSTATIC_ON_START:-0}" in entrypoint
    assert "${AGOMTRADEPRO_SETUP_SCHEDULE_ON_START:-0}" in entrypoint
    assert "${AGOMTRADEPRO_ENSURE_SUPERUSER_ON_START:-0}" in entrypoint
    assert "-e AGOMTRADEPRO_ENSURE_SUPERUSER_ON_START=1" in deploy_script
    assert "compose run --rm --no-deps web python manage.py check --deploy" in deploy_script
    assert (
        "compose run --rm --no-deps web python manage.py collectstatic --noinput" in deploy_script
    )


def test_config_center_initial_migration_uses_portable_boolean_default() -> None:
    migration = (REPO_ROOT / "apps" / "config_center" / "migrations" / "0001_initial.py").read_text(
        encoding="utf-8"
    )

    assert "bool NOT NULL DEFAULT FALSE" in migration
    assert "bool NOT NULL DEFAULT 0" not in migration


def test_macro_source_field_accepts_existing_production_provenance() -> None:
    model = (REPO_ROOT / "apps" / "macro" / "infrastructure" / "models.py").read_text(
        encoding="utf-8"
    )
    migration = (
        REPO_ROOT / "apps" / "macro" / "migrations" / "0019_expand_macro_indicator_source.py"
    ).read_text(encoding="utf-8")

    assert 'source = models.CharField(max_length=50, help_text="数据源")' in model
    assert "max_length=50" in migration
