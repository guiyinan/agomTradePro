"""Verify the observer hashes real scoped bytes and keeps Docker secrets private."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import capture_legacy_observed_runtime as observer


def _code_observation(root: Path) -> subprocess.CompletedProcess[str]:
    program = observer._CONTAINER_OBSERVATION_PROGRAM.replace(
        "root = Path('/app')", f"root = Path({str(root)!r})"
    )
    return subprocess.run(
        [sys.executable, "-c", program, '["code.py"]', "[]"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_scoped_code_digest_detects_application_changes_and_ignores_runtime_output(
    tmp_path: Path,
) -> None:
    (tmp_path / "code.py").write_bytes(b"immutable app code\n")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/request.log").write_bytes(b"runtime log changes")
    (tmp_path / ".env").write_bytes(b"SECRET=sensitive-never-in-result")
    first = _code_observation(tmp_path)
    assert first.returncode == 0, first.stderr
    initial = json.loads(first.stdout)
    assert initial["code_file_count"] == 1
    assert "sensitive-never-in-result" not in first.stdout
    expected = hashlib.sha256(b"agomtradepro-app-runtime-code.v1\0code.py\0immutable app code\n\0")
    assert initial["runtime_code_sha256"] == expected.hexdigest()
    (tmp_path / "logs/request.log").write_bytes(b"new runtime logs")
    (tmp_path / ".env").write_bytes(b"SECRET=rotated")
    assert json.loads(_code_observation(tmp_path).stdout) == initial
    (tmp_path / "code.py").write_bytes(b"modified app code\n")
    assert (
        json.loads(_code_observation(tmp_path).stdout)["runtime_code_sha256"]
        != expected.hexdigest()
    )


def test_readonly_docker_failure_never_exposes_raw_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["docker"], 1, "SECRET=private", "token=private")

    monkeypatch.setattr(observer.subprocess, "run", fail)
    with pytest.raises(
        observer.LegacyBaselineBlocked, match="^LEGACY_RUNTIME_OBSERVATION_COMMAND_FAILED$"
    ):
        observer._command(("docker", "inspect", "container"))


def test_ambiguous_service_is_blocked_before_any_container_exec() -> None:
    calls: list[tuple[str, ...]] = []

    def command(arguments: tuple[str, ...]) -> str:
        calls.append(arguments)
        return "container-one\ncontainer-two"

    with pytest.raises(observer.LegacyBaselineBlocked, match="LEGACY_RUNTIME_SERVICE_NOT_UNIQUE"):
        observer._service("web", ("code.py",), command)
    assert len(calls) == 1
    assert calls[0][:2] == ("docker", "ps")


def test_compare_rejects_digest_mismatch_before_live_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_bytes(b"private invalid evidence")

    def forbidden() -> None:
        pytest.fail("invalid pinned bytes must be rejected before any Docker access")

    monkeypatch.setattr(observer, "observe_legacy_runtime", forbidden)
    assert (
        observer.main(["compare", "--baseline-json", str(baseline), "--baseline-sha256", "a" * 64])
        == 2
    )
    output = capsys.readouterr()
    assert output.err.strip() == (
        "LEGACY_OBSERVED_RUNTIME_BLOCKED code=LEGACY_BASELINE_DIGEST_MISMATCH"
    )
    assert "private invalid evidence" not in output.err + output.out


@pytest.mark.parametrize("value", [True, False, -1, "7", None])
def test_docker_stat_integer_boundary_rejects_nonintegers(value: object) -> None:
    with pytest.raises(observer.LegacyBaselineBlocked):
        observer._integer(value)


def test_nested_application_data_is_part_of_the_code_digest(tmp_path: Path) -> None:
    (tmp_path / "code.py").write_bytes(b"code")
    nested = tmp_path / "apps/research/data"
    nested.mkdir(parents=True)
    (nested / "catalog.json").write_bytes(b"version one")
    first = json.loads(_code_observation(tmp_path).stdout)
    assert first["code_file_count"] == 2
    (nested / "catalog.json").write_bytes(b"version two")
    assert (
        json.loads(_code_observation(tmp_path).stdout)["runtime_code_sha256"]
        != first["runtime_code_sha256"]
    )


def test_runtime_walk_errors_cannot_silently_omit_source(tmp_path: Path) -> None:
    program = observer._CONTAINER_OBSERVATION_PROGRAM.replace(
        "root = Path('/app')", f"root = Path({str(tmp_path)!r})"
    )
    injected = (
        "def denied_walk(*args, **kwargs):\n"
        "    handler = kwargs.get('onerror')\n"
        "    if handler: handler(PermissionError('sensitive path'))\n"
        "    return iter(())\n"
        "os.walk = denied_walk\n"
    )
    program = program.replace("count = 0\n", "count = 0\n" + injected)
    (tmp_path / "code.py").write_bytes(b"code")
    result = subprocess.run(
        [sys.executable, "-c", program, '["code.py"]', "[]"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "LEGACY_RUNTIME_CODE_READ_FAILED" in result.stderr
    assert "sensitive path" not in result.stderr


def test_effective_process_digest_detects_command_and_network_drift() -> None:
    container: dict[str, object] = {
        "Config": {
            "Cmd": ["celery", "worker", "-Q", "financial"],
            "Entrypoint": ["/entrypoint.sh"],
            "WorkingDir": "/app",
            "User": "1000",
            "Env": ["SECRET=never-printed"],
            "Hostname": "old-docker-id",
            "Labels": {"com.docker.compose.version": "old"},
        },
        "HostConfig": {
            "RestartPolicy": {"Name": "unless-stopped"},
            "PidMode": "container:infra",
            "NetworkMode": "project_default",
            "PortBindings": {},
            "Binds": ["alias:/run/manifest:ro"],
        },
        "NetworkSettings": {
            "Networks": {"project_default": {"NetworkID": "a" * 64, "IPAddress": "172.20.0.5"}}
        },
    }
    initial = observer.process_configuration_digest(container)
    ephemeral = copy.deepcopy(container)
    ephemeral["Config"]["Hostname"] = "new-docker-id"
    ephemeral["HostConfig"]["Binds"] = ["realpath:/run/manifest:ro"]
    ephemeral["NetworkSettings"]["Networks"]["project_default"]["IPAddress"] = "172.20.0.6"
    assert observer.process_configuration_digest(ephemeral) == initial
    ephemeral["Config"]["Cmd"] = ["celery", "worker", "-Q", "different-task-queue"]
    assert observer.process_configuration_digest(ephemeral) != initial
    network = copy.deepcopy(container)
    network["NetworkSettings"]["Networks"]["project_default"]["NetworkID"] = "b" * 64
    assert observer.process_configuration_digest(network) != initial
