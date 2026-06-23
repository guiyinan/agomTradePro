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
