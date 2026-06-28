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


def test_vps_remote_deploy_verifies_celery_when_enabled() -> None:
    script = (REPO_ROOT / "scripts" / "remote_build_deploy_vps.py").read_text(encoding="utf-8")

    assert 'if [ "$ENABLE_CELERY" = "1" ]; then' in script
    assert "celery_worker celery_beat" in script
    assert "celery -A core inspect ping --timeout=8" in script


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
    assert "AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START: ${AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START:-0}" in compose
    assert "AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START=0" in env_example
    assert "AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START=1" not in env_example
    assert '${AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START:-0}' in entrypoint
    assert '${AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START:-1}' not in entrypoint
