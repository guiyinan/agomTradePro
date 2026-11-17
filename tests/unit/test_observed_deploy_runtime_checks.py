"""Check effective infrastructure drift without Docker or database access."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import observed_deploy_runtime_checks as checks


def _running_container(tmp_path: Path) -> dict[str, object]:
    config = tmp_path / "Caddyfile"
    config.write_text("served config", encoding="utf-8")
    return {
        "Id": "a" * 64,
        "Image": "sha256:" + "b" * 64,
        "Config": {"Env": ["SECRET=never-retain-this"], "Cmd": ["serve"]},
        "HostConfig": {"RestartPolicy": "unless-stopped"},
        "State": {
            "Running": True,
            "Paused": False,
            "Restarting": False,
            "StartedAt": "2026-11-17T00:00:00Z",
        },
        "NetworkSettings": {"Networks": {"production": {"NetworkID": "c" * 64}}},
        "Mounts": [
            {
                "Source": str(config),
                "Destination": "/etc/caddy/Caddyfile",
                "Type": "bind",
                "RW": False,
            }
        ],
    }


def test_infrastructure_receipt_keeps_secrets_out_and_rejects_effective_config_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _running_container(tmp_path)
    monkeypatch.setattr(checks, "_container", lambda *args, **kwargs: container)
    baseline = checks.infrastructure_snapshot()
    assert "never-retain-this" not in json.dumps(baseline)
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(baseline), encoding="utf-8")
    checks.compare_infrastructure(path)
    changed = copy.deepcopy(container)
    changed["Config"]["Cmd"] = ["different-behavior"]
    monkeypatch.setattr(checks, "_container", lambda *args, **kwargs: changed)
    with pytest.raises(checks.LegacyBaselineBlocked, match="OBSERVED_INFRASTRUCTURE_DRIFT"):
        checks.compare_infrastructure(path)


def test_infrastructure_mounted_config_content_is_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _running_container(tmp_path)
    monkeypatch.setattr(checks, "_container", lambda *args, **kwargs: container)
    before = checks.infrastructure_snapshot()
    (tmp_path / "Caddyfile").write_text("different route", encoding="utf-8")
    assert checks.infrastructure_snapshot() != before


def test_invalid_candidate_phase_fails_before_docker_or_filesystem_access(tmp_path: Path) -> None:
    with pytest.raises(checks.LegacyBaselineBlocked, match="OBSERVED_CANDIDATE_PHASE_INVALID"):
        checks.check_candidate_apps(
            tmp_path / "missing", phase="invalid", image_id="x", candidate_sha="y"
        )


def test_candidate_beat_cannot_pass_with_a_worker_command() -> None:
    image: dict[str, object] = {
        "Cmd": ["web"],
        "Entrypoint": ["/entrypoint.sh"],
        "WorkingDir": "/app",
        "User": "1000",
        "Env": ["PATH=/bin"],
    }
    expected: dict[str, object] = {
        "command": ["celery", "beat"],
        "environment": {"ROLE": "beat"},
        "pid": "service:runtime_ns",
        "restart": "unless-stopped",
        "networks": {"default": {}},
    }
    actual: dict[str, object] = {
        "Config": {
            "Cmd": ["celery", "beat"],
            "Entrypoint": ["/entrypoint.sh"],
            "WorkingDir": "/app",
            "User": "1000",
            "Env": ["PATH=/bin", "ROLE=beat"],
        },
        "HostConfig": {
            "PidMode": "container:namespace",
            "RestartPolicy": {"Name": "unless-stopped"},
            "ReadonlyRootfs": False,
            "Privileged": False,
        },
        "NetworkSettings": {"Networks": {"production": {}}},
    }
    checks.check_service_role(
        actual,
        expected,
        image,
        phase="b",
        network_names={"production"},
        namespace_container_id="namespace",
    )
    changed = copy.deepcopy(actual)
    changed["Config"]["Cmd"] = ["celery", "worker", "-Q", "other"]
    with pytest.raises(checks.LegacyBaselineBlocked, match="OBSERVED_APP_SERVICE_ROLE_MISMATCH"):
        checks.check_service_role(
            changed,
            expected,
            image,
            phase="b",
            network_names={"production"},
            namespace_container_id="namespace",
        )
