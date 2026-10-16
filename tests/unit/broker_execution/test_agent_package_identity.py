"""Candidate identity and artifact consistency for the Windows QMT Agent."""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qmt_agent import __version__
from qmt_agent.executor import QmtAgentExecutor
from qmt_agent.state_store import AgentStateStore

ROOT = Path(__file__).resolve().parents[3]
BUILD_SCRIPT = ROOT / "scripts" / "build_qmt_agent_package.ps1"


class _HeartbeatApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((endpoint, payload))
        return payload


class _HeartbeatBroker:
    def health(self) -> dict[str, object]:
        return {"qmt_connected": True, "qmt_version": "fixture"}


def _powershell_executable() -> str:
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if executable is None:
        pytest.skip("PowerShell is required to verify the Windows package builder")
    return executable


def _build_package(
    output_root: Path, *, version: str | None = None, script_path: Path = BUILD_SCRIPT
) -> subprocess.CompletedProcess[bytes]:
    command = [
        _powershell_executable(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
    ]
    if version is not None:
        command.extend(["-Version", version])
    command.extend(["-OutputRoot", str(output_root)])
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        check=False,
        timeout=180,
    )


def test_agent_candidate_version_is_the_heartbeat_identity(tmp_path: Path) -> None:
    assert __version__ == "0.2.0"
    config = SimpleNamespace(
        kill_switch_file=tmp_path / "STOP",
        system_account_id=7,
        dry_run=True,
    )
    api = _HeartbeatApi()
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    executor = QmtAgentExecutor(
        config=config,
        api=api,
        broker=_HeartbeatBroker(),
        state=state,
    )
    try:
        executor.heartbeat()
    finally:
        state.close()

    endpoint, payload = api.calls[0]
    assert endpoint == "heartbeat/"
    assert payload["agent_version"] == __version__


def test_builder_rejects_a_mismatched_version_before_creating_output(tmp_path: Path) -> None:
    output_root = tmp_path / "must-not-exist"

    result = _build_package(output_root, version="9.9.9")

    assert result.returncode != 0
    assert not output_root.exists()
    assert b"does not match source version" in result.stderr


def test_default_package_version_matches_source_and_contains_no_credentials(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "candidate-package"

    result = _build_package(output_root)

    assert result.returncode == 0, result.stderr
    archive_path = output_root / f"agom-qmt-agent-windows-{__version__}.zip"
    assert archive_path.is_file()
    assert Path(f"{archive_path}.sha256").is_file()
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        package_init = archive.read("qmt_agent/__init__.py").decode("utf-8")
        package_executor = archive.read("qmt_agent/executor.py").decode("utf-8")

    assert manifest["version"] == __version__
    assert manifest["contains_secrets"] is False
    assert manifest["contains_qmt"] is False
    assert manifest["contains_xtquant_wheel"] is False
    assert f'__version__ = "{__version__}"' in package_init
    assert "from . import __version__" in package_executor
    assert '"agent_version": __version__' in package_executor
    assert not any(
        Path(name).name.lower() in {".env", "credentials.json", "token.json"}
        or name.lower().endswith((".pem", ".p12", ".pfx", ".whl"))
        for name in names
    )


def test_packaged_heartbeat_reads_the_package_version_source() -> None:
    executor_source = (ROOT / "qmt_agent" / "executor.py").read_text("utf-8")

    assert "from . import __version__" in executor_source
    assert '"agent_version": __version__' in executor_source


def test_package_excludes_runtime_credentials_and_state_in_an_isolated_source_tree(
    tmp_path: Path,
) -> None:
    fixture_root = tmp_path / "fixture-repo"
    copied_paths = [
        Path("scripts/build_qmt_agent_package.ps1"),
        Path("qmt_agent/__init__.py"),
        Path("qmt_agent/executor.py"),
        Path("qmt_agent/README.md"),
        Path("qmt_agent/xtquant-lock.json"),
        Path("qmt_agent/config.example.yaml"),
        Path("docs/operations/qmt-agent-local-install-package.md"),
        Path("docs/operations/qmt-agent-runbook.md"),
        Path("docs/operations/qmt-integrated-bridge.md"),
        *(path.relative_to(ROOT) for path in (ROOT / "qmt_agent/scripts").glob("*.ps1")),
        *(path.relative_to(ROOT) for path in (ROOT / "qmt_agent/package").glob("*.ps1")),
    ]
    for relative in copied_paths:
        destination = fixture_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    for name in (".env", "credentials.json", "token.json", "state/agent.sqlite3"):
        fixture_file = fixture_root / "qmt_agent" / name
        fixture_file.parent.mkdir(parents=True, exist_ok=True)
        fixture_file.write_text("TEST_FIXTURE_ONLY_NOT_A_SECRET", encoding="utf-8")
    output_root = tmp_path / "fixture-output"

    result = _build_package(
        output_root, script_path=fixture_root / "scripts/build_qmt_agent_package.ps1"
    )

    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(output_root / f"agom-qmt-agent-windows-{__version__}.zip") as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
    for forbidden in (".env", "credentials.json", "token.json", "agent.sqlite3"):
        assert not any(Path(name).name == forbidden for name in names)
        assert not any(Path(item["path"]).name == forbidden for item in manifest["files"])
    assert "qmt_agent/scripts/start-agent.ps1" in names
    assert "Install.ps1" in names
