"""Static regression tests for production Web liveness recovery."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_vps_compose_uses_self_recovering_web_healthcheck():
    compose = (REPO_ROOT / "docker" / "docker-compose.vps.yml").read_text(encoding="utf-8")

    assert "sh docker/healthcheck-web.sh" in compose
    assert "WEB_HEALTH_SELF_TERMINATE_AFTER_FAILURES" in compose


def test_healthcheck_only_terminates_daphne_after_repeated_failures():
    script = (REPO_ROOT / "docker" / "healthcheck-web.sh").read_text(encoding="utf-8")

    assert "WEB_HEALTH_SELF_TERMINATE_AFTER_FAILURES" in script
    assert "core.asgi:application" in script
    assert "kill -TERM" in script
    assert '"$curl_bin" -fsS' in script


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


def _run_healthcheck(
    *,
    tmp_path: Path,
    probe_result: str,
) -> subprocess.CompletedProcess[str]:
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("POSIX shell is unavailable")
    fake_curl = tmp_path / "fake-curl.sh"
    if not fake_curl.exists():
        fake_curl.write_text(
            '#!/bin/sh\n[ "${FAKE_HEALTH_RESULT:-failure}" = "success" ]\n',
            encoding="utf-8",
            newline="\n",
        )
        fake_curl.chmod(0o755)
    environment = {
        **os.environ,
        "FAKE_HEALTH_RESULT": probe_result,
        "WEB_HEALTH_CURL_BIN": _shell_path(fake_curl),
        "WEB_HEALTH_FAILURE_FILE": _shell_path(tmp_path / "failure-count"),
        "WEB_HEALTH_PROC_ROOT": _shell_path(tmp_path / "proc"),
        "WEB_HEALTH_SELF_TERMINATE_AFTER_FAILURES": "3",
    }
    return subprocess.run(
        [shell, str(REPO_ROOT / "docker" / "healthcheck-web.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_healthcheck_counts_consecutive_failures_and_resets_after_success(tmp_path):
    process_dir = tmp_path / "proc" / "999999"
    process_dir.mkdir(parents=True)
    (process_dir / "cmdline").write_bytes(
        b"/usr/local/bin/daphne\0-b\00.0.0.0\0core.asgi:application\0"
    )
    failure_file = tmp_path / "failure-count"

    first = _run_healthcheck(tmp_path=tmp_path, probe_result="failure")
    second = _run_healthcheck(tmp_path=tmp_path, probe_result="failure")
    third = _run_healthcheck(tmp_path=tmp_path, probe_result="failure")

    assert (first.returncode, second.returncode, third.returncode) == (1, 1, 1)
    assert "terminating Daphne" not in first.stderr
    assert "terminating Daphne" not in second.stderr
    assert "terminating Daphne PID 999999" in third.stderr
    assert failure_file.read_text(encoding="utf-8").strip() == "3"

    recovered = _run_healthcheck(tmp_path=tmp_path, probe_result="success")

    assert recovered.returncode == 0
    assert not failure_file.exists()
