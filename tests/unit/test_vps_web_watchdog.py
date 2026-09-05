"""Behavioral contract tests for the host-level Web recovery watchdog."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _shell_path(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("POSIX shell is unavailable")
    converted = subprocess.run(
        [shell, "-lc", f'cygpath -u "{path}"'],
        check=True,
        capture_output=True,
        text=True,
    )
    return converted.stdout.strip()


def _write_fake_docker(tmp_path: Path) -> tuple[Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake_docker = tmp_path / "fake-docker.sh"
    status_file = tmp_path / "health-status"
    restart_file = tmp_path / "restart-commands"
    fake_docker.write_text(
        """#!/bin/sh
status_file="${FAKE_DOCKER_STATUS_FILE:?}"
restart_file="${FAKE_DOCKER_RESTART_FILE:?}"

if [ "${1:-}" = "compose" ]; then
    action=""
    for arg in "$@"; do
        case "$arg" in
            ps|restart) action="$arg" ;;
        esac
    done
    if [ "$action" = "ps" ]; then
        printf 'web-container\\n'
        exit 0
    fi
    if [ "$action" = "restart" ]; then
        printf '%s\\n' "$*" >>"$restart_file"
        if [ "${FAKE_DOCKER_RECOVER_ON_RESTART:-0}" = "1" ]; then
            printf 'healthy\\n' >"$status_file"
        fi
        exit 0
    fi
    exit 64
fi

if [ "${1:-}" = "inspect" ]; then
    cat "$status_file"
    exit 0
fi

exit 64
""",
        encoding="utf-8",
        newline="\n",
    )
    fake_docker.chmod(0o755)
    status_file.write_text("unhealthy\n", encoding="utf-8", newline="\n")
    return fake_docker, status_file, restart_file


def _watchdog_env(
    *,
    target_dir: Path,
    state_dir: Path,
    fake_docker: Path,
    status_file: Path,
    restart_file: Path,
    **overrides: str,
) -> dict[str, str]:
    values = {
        "AGOMTRADEPRO_WATCHDOG_DOCKER_BIN": _shell_path(fake_docker),
        "AGOMTRADEPRO_WATCHDOG_TARGET_DIR": _shell_path(target_dir),
        "AGOMTRADEPRO_WATCHDOG_COMPOSE_FILE": _shell_path(
            target_dir / "docker" / "docker-compose.vps.yml"
        ),
        "AGOMTRADEPRO_WATCHDOG_ENV_FILE": _shell_path(target_dir / "deploy" / ".env"),
        "AGOMTRADEPRO_WATCHDOG_STATE_DIR": _shell_path(state_dir),
        "AGOMTRADEPRO_WATCHDOG_FAILURE_THRESHOLD": "2",
        "AGOMTRADEPRO_WATCHDOG_RESTART_COOLDOWN_SECONDS": "0",
        "AGOMTRADEPRO_WATCHDOG_RESTART_WINDOW_SECONDS": "3600",
        "AGOMTRADEPRO_WATCHDOG_MAX_RESTARTS": "2",
        "AGOMTRADEPRO_WATCHDOG_RECOVERY_TIMEOUT_SECONDS": "2",
        "AGOMTRADEPRO_WATCHDOG_RECOVERY_POLL_SECONDS": "1",
        "FAKE_DOCKER_STATUS_FILE": _shell_path(status_file),
        "FAKE_DOCKER_RESTART_FILE": _shell_path(restart_file),
        **overrides,
    }
    return {**os.environ, **values}


def _run_watchdog(
    tmp_path: Path,
    *,
    recover_on_restart: bool = False,
    **overrides: str,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    target_dir = tmp_path / "target"
    (target_dir / "docker").mkdir(parents=True, exist_ok=True)
    (target_dir / "deploy").mkdir(exist_ok=True)
    (target_dir / "docker" / "docker-compose.vps.yml").write_text("services:\n", encoding="utf-8")
    (target_dir / "deploy" / ".env").write_text("WEB_IMAGE=test\n", encoding="utf-8")
    state_dir = tmp_path / "state"
    fake_docker, status_file, restart_file = _write_fake_docker(tmp_path)
    env = _watchdog_env(
        target_dir=target_dir,
        state_dir=state_dir,
        fake_docker=fake_docker,
        status_file=status_file,
        restart_file=restart_file,
        FAKE_DOCKER_RECOVER_ON_RESTART="1" if recover_on_restart else "0",
        **overrides,
    )
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("POSIX shell is unavailable")
    process = subprocess.run(
        [shell, str(REPO_ROOT / "scripts" / "vps-web-watchdog.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    return process, state_dir, restart_file


def test_watchdog_waits_for_threshold_then_restarts_only_web_and_confirms_recovery(
    tmp_path: Path,
) -> None:
    first, state_dir, restart_file = _run_watchdog(tmp_path)
    assert first.returncode == 1
    assert "waiting before recovery" in first.stdout
    assert not restart_file.exists()

    second, _, _ = _run_watchdog(tmp_path, recover_on_restart=True)
    assert second.returncode == 0
    assert "restarting only the web service" in second.stdout
    assert "Web recovered" in second.stdout
    assert len(restart_file.read_text(encoding="utf-8").splitlines()) == 1
    assert not (state_dir / "consecutive-unhealthy").exists()


def test_watchdog_cooldown_prevents_restart_storm(tmp_path: Path) -> None:
    first, _, restart_file = _run_watchdog(
        tmp_path,
        recover_on_restart=False,
        AGOMTRADEPRO_WATCHDOG_FAILURE_THRESHOLD="1",
        AGOMTRADEPRO_WATCHDOG_RESTART_COOLDOWN_SECONDS="999999",
        AGOMTRADEPRO_WATCHDOG_RECOVERY_TIMEOUT_SECONDS="1",
    )
    assert first.returncode == 1
    assert len(restart_file.read_text(encoding="utf-8").splitlines()) == 1

    second, _, _ = _run_watchdog(
        tmp_path,
        AGOMTRADEPRO_WATCHDOG_FAILURE_THRESHOLD="1",
        AGOMTRADEPRO_WATCHDOG_RESTART_COOLDOWN_SECONDS="999999",
    )
    assert second.returncode == 1
    assert "cooldown" in second.stdout
    assert len(restart_file.read_text(encoding="utf-8").splitlines()) == 1


def test_watchdog_enforces_restart_budget_in_rolling_window(tmp_path: Path) -> None:
    first, _, restart_file = _run_watchdog(
        tmp_path,
        AGOMTRADEPRO_WATCHDOG_FAILURE_THRESHOLD="1",
        AGOMTRADEPRO_WATCHDOG_MAX_RESTARTS="1",
    )
    assert first.returncode == 1
    assert len(restart_file.read_text(encoding="utf-8").splitlines()) == 1

    process, _, _ = _run_watchdog(
        tmp_path,
        AGOMTRADEPRO_WATCHDOG_FAILURE_THRESHOLD="1",
        AGOMTRADEPRO_WATCHDOG_MAX_RESTARTS="1",
    )
    assert process.returncode == 1
    assert "recovery budget exhausted" in process.stdout
    assert len(restart_file.read_text(encoding="utf-8").splitlines()) == 1

    # The fake command is not invoked for any sibling service.  This static
    # assertion protects the intended runtime boundary in addition to the
    # command-log assertions above.
    source = (REPO_ROOT / "scripts" / "vps-web-watchdog.sh").read_text(encoding="utf-8")
    assert "compose restart web" in source
    assert "compose restart runtime_ns" not in source
    assert "compose restart celery_worker" not in source


def test_watchdog_healthy_status_clears_stale_failure_without_restart(tmp_path: Path) -> None:
    process, state_dir, restart_file = _run_watchdog(tmp_path)
    assert process.returncode == 1
    (state_dir / "consecutive-unhealthy").write_text("7\n", encoding="utf-8")

    # A new fake stack starts unhealthy by default; make the probe healthy
    # before invoking the watchdog to model recovery between timer ticks.
    target_dir = tmp_path / "target"
    fake_docker = tmp_path / "fake-docker.sh"
    status_file = tmp_path / "health-status"
    env = _watchdog_env(
        target_dir=target_dir,
        state_dir=state_dir,
        fake_docker=fake_docker,
        status_file=status_file,
        restart_file=restart_file,
    )
    status_file.write_text("healthy\n", encoding="utf-8")
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("POSIX shell is unavailable")
    healthy = subprocess.run(
        [shell, str(REPO_ROOT / "scripts" / "vps-web-watchdog.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert healthy.returncode == 0
    assert not (state_dir / "consecutive-unhealthy").exists()
    assert not restart_file.exists()


def test_watchdog_installation_is_explicit_and_packaged_without_docker_sidecar() -> None:
    script = (REPO_ROOT / "scripts" / "vps-web-watchdog.sh").read_text(encoding="utf-8")
    service = (REPO_ROOT / "deploy" / "agomtradepro-web-watchdog.service").read_text(
        encoding="utf-8"
    )
    timer = (REPO_ROOT / "deploy" / "agomtradepro-web-watchdog.timer").read_text(encoding="utf-8")
    packaging = (REPO_ROOT / "scripts" / "package-for-vps.ps1").read_text(encoding="utf-8")
    verifier = (REPO_ROOT / "scripts" / "verify-vps-bundle.ps1").read_text(encoding="utf-8")

    assert '"$docker_bin" compose' in script
    assert "docker.sock" not in script
    assert "ExecStart=/bin/sh /opt/agomtradepro/current/scripts/vps-web-watchdog.sh" in service
    assert "TimeoutStartSec=150s" in service
    assert "OnUnitActiveSec=1min" in timer
    assert "Copy-Item scripts/vps-web-watchdog.sh" in packaging
    assert "Copy-Item deploy/agomtradepro-web-watchdog.service" in packaging
    assert "Copy-Item deploy/agomtradepro-web-watchdog.timer" in packaging
    assert '"deploy/agomtradepro-web-watchdog.service"' in verifier
    assert '"deploy/agomtradepro-web-watchdog.timer"' in verifier
    assert '"scripts/vps-web-watchdog.sh"' in verifier
