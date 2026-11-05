"""Functional checks for the QMT built-in Python onboarding script."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "qmt_agent" / "scripts" / "setup-builtin-python.ps1"


def _powershell_executable() -> str:
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if executable is None:
        pytest.skip("PowerShell is required to verify the QMT onboarding script")
    return executable


def test_onboarding_script_preserves_config_and_enforces_dry_run(tmp_path: Path) -> None:
    config_path = tmp_path / "agent.json"
    config_path.write_text(
        json.dumps(
            {
                "agent_id": "fixture-agent",
                "server_url": "https://vps.example.com",
                "qmt_userdata_path": "D:/qmt/userdata",
                "broker_account_id": "fixture-account",
                "broker_account_type": "STOCK",
                "system_account_id": 7,
                "dry_run": False,
                "verify_tls": True,
            }
        ),
        encoding="utf-8",
    )
    qmt_root = tmp_path / "qmt"
    executable = qmt_root / "bin.x64" / "XtItClient.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"TEST_FIXTURE_ONLY")

    result = subprocess.run(
        [
            _powershell_executable(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-ConfigPath",
            str(config_path),
            "-QmtRoot",
            str(qmt_root),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated["qmt_trade_api"] == "builtin_python"
    assert updated["qmt_builtin_pipe_name"] == "agom_qmt_builtin_bridge"
    assert updated["qmt_builtin_bridge_timeout_seconds"] == 10
    assert updated["dry_run"] is True
    assert updated["verify_tls"] is True
    assert updated["agent_id"] == "fixture-agent"
    assert len(list(tmp_path.glob("agent.json.builtin-backup-*"))) == 1
    assert b"No order or cancel function is called" in result.stdout
