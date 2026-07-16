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


def test_linux_wheelhouse_directory_is_preserved_for_docker_copy() -> None:
    assert (REPO_ROOT / ".cache" / "pip-wheels" / "linux-py311" / ".keep").exists()


def test_vps_compose_worker_consumes_qlib_queues() -> None:
    compose = (REPO_ROOT / "docker" / "docker-compose.vps.yml").read_text(encoding="utf-8")

    assert "CELERY_WORKER_QUEUES:-celery,qlib_infer,qlib_train" in compose
    assert "healthcheck:\n      disable: true" in compose


def test_vps_compose_uses_neutral_pid_namespace_service() -> None:
    compose = (REPO_ROOT / "docker" / "docker-compose.vps.yml").read_text(encoding="utf-8")

    assert "runtime_ns:" in compose
    assert 'pid: "service:runtime_ns"' in compose
    assert 'pid: "service:web"' not in compose


def test_vps_remote_deploy_defaults_and_celery_runtime_checks() -> None:
    script = (REPO_ROOT / "scripts" / "remote_build_deploy_vps.py").read_text(encoding="utf-8")
    one_click_script = (REPO_ROOT / "scripts" / "deploy-vps.ps1").read_text(encoding="utf-8")
    compose = (REPO_ROOT / "docker" / "docker-compose.vps.yml").read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "docker" / "Dockerfile.prod").read_text(encoding="utf-8")
    backup = (REPO_ROOT / "scripts" / "vps-backup.sh").read_text(encoding="utf-8")
    restore = (REPO_ROOT / "scripts" / "vps-restore.sh").read_text(encoding="utf-8")
    migration = (
        REPO_ROOT / "scripts" / "migrate-vps-sqlite-to-postgres.sh"
    ).read_text(encoding="utf-8")
    entrypoint = (REPO_ROOT / "docker" / "entrypoint.prod.sh").read_text(
        encoding="utf-8"
    )

    assert 'os.environ.get("AGOM_VPS_TIMEOUT", "3600")' in script
    assert "[int]$BuildTimeoutSeconds = 3600" in one_click_script
    assert "'--timeout', \"$BuildTimeoutSeconds\"" in one_click_script
    assert "'--timeout', '15'" in one_click_script
    assert "compose up -d runtime_ns redis postgres" in script
    assert 'SERVICES="runtime_ns redis postgres web caddy"' in script
    assert 'if [ "$ENABLE_CELERY" = "1" ]; then' in script
    assert "celery_worker celery_beat" in script
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
    assert ".postgres-migration-complete" in migration
    assert "check_encryption_readiness --json" in migration


def test_git_clone_include_sqlite_uploads_local_db_before_deploy() -> None:
    script = (REPO_ROOT / "scripts" / "remote_build_deploy_vps.py").read_text(encoding="utf-8")

    assert "def _upload_sqlite_to_git_clone_release" in script
    assert "Uploading local SQLite for git-clone deploy" in script
    assert "PRAGMA integrity_check" in script
    assert "_upload_sqlite_to_git_clone_release(" in script


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
    env_example = (REPO_ROOT / "deploy" / ".env.vps.example").read_text(encoding="utf-8")

    assert "AGOMTRADEPRO_BOOTSTRAP_ON_START: ${AGOMTRADEPRO_BOOTSTRAP_ON_START:-1}" in compose
    assert (
        "AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START: ${AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START:-0}"
        in compose
    )
    assert "AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START=0" in env_example
    assert "AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START=1" not in env_example
    assert "${AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START:-0}" in entrypoint
    assert "${AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START:-1}" not in entrypoint


def test_config_center_initial_migration_uses_portable_boolean_default() -> None:
    migration = (
        REPO_ROOT / "apps" / "config_center" / "migrations" / "0001_initial.py"
    ).read_text(encoding="utf-8")

    assert "bool NOT NULL DEFAULT FALSE" in migration
    assert "bool NOT NULL DEFAULT 0" not in migration


def test_macro_source_field_accepts_existing_production_provenance() -> None:
    model = (
        REPO_ROOT / "apps" / "macro" / "infrastructure" / "models.py"
    ).read_text(encoding="utf-8")
    migration = (
        REPO_ROOT / "apps" / "macro" / "migrations" / "0019_expand_macro_indicator_source.py"
    ).read_text(encoding="utf-8")

    assert 'source = models.CharField(max_length=50, help_text="数据源")' in model
    assert "max_length=50" in migration
