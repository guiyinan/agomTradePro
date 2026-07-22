"""Static guards for the distributable Windows QMT Agent package."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_xtquant_lock_uses_https_and_the_verified_release() -> None:
    lock = json.loads((ROOT / "qmt_agent" / "xtquant-lock.json").read_text("utf-8"))

    assert lock["version"] == "250807.1.2"
    assert lock["url"].startswith("https://files.pythonhosted.org/")
    assert lock["source"] == "https://pypi.org/project/xtquant/250807.1.2/"
    assert lock["sha256"] == "91f19ff9a92971c5abe64fbd077e5212e0418f0820aa3427aef3444230f72921"


def test_package_entrypoints_and_builder_exist() -> None:
    required = [
        ROOT / "qmt_agent" / "package" / "Install.ps1",
        ROOT / "qmt_agent" / "package" / "Set-AgentToken.ps1",
        ROOT / "qmt_agent" / "package" / "Test-Connection.ps1",
        ROOT / "qmt_agent" / "package" / "Uninstall.ps1",
        ROOT / "scripts" / "build_qmt_agent_package.ps1",
        ROOT / "docs" / "operations" / "qmt-agent-local-install-package.md",
    ]

    assert all(path.is_file() for path in required)


def test_installer_fails_safe_and_never_embeds_credentials() -> None:
    installer = (ROOT / "qmt_agent" / "scripts" / "install-agent.ps1").read_text("utf-8")
    token_script = (ROOT / "qmt_agent" / "scripts" / "set-agent-token.ps1").read_text("utf-8")

    assert 'dry_run = $true' in installer
    assert 'broker_account_type = "STOCK"' in installer
    assert "Get-FileHash" in installer
    assert "XtQuantWheelSha256 is required" in installer
    assert "Read-Host" in token_script and "-AsSecureString" in token_script
    assert "ConvertFrom-SecureString" in token_script
    assert "交易密码" not in installer
    assert "40151752" not in installer + token_script
