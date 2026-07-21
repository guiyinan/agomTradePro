from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    spec = importlib.util.spec_from_file_location("remote_build_deploy_vps", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


remote_build_deploy_vps = _load_module()


def test_run_drains_stdout_and_stderr_without_sequential_read_deadlock():
    class FakeChannel:
        def __init__(self):
            self.stdout_chunks = [b"stdout\n"]
            self.stderr_chunks = [b"stderr\n"]

        def recv_ready(self):
            return bool(self.stdout_chunks)

        def recv_stderr_ready(self):
            return bool(self.stderr_chunks)

        def recv(self, _size):
            return self.stdout_chunks.pop(0)

        def recv_stderr(self, _size):
            return self.stderr_chunks.pop(0)

        def exit_status_ready(self):
            return not self.stdout_chunks and not self.stderr_chunks

        def recv_exit_status(self):
            return 0

        def close(self):
            return None

    class FakeStream:
        def __init__(self, channel):
            self.channel = channel

        def read(self):
            raise AssertionError("sequential stream reads can deadlock")

    class FakeSSH:
        def exec_command(self, _command, timeout):
            assert timeout == 5
            channel = FakeChannel()
            return object(), FakeStream(channel), FakeStream(channel)

    exit_code, stdout, stderr = remote_build_deploy_vps._run(FakeSSH(), "check", timeout=5)

    assert exit_code == 0
    assert stdout == "stdout\n"
    assert stderr == "stderr\n"


@pytest.mark.parametrize(
    "value",
    [
        "62.171.144.39",
        "2001:db8::1",
        "https://demo.agomtrade.pro",
        "demo.agomtrade.pro/path",
        "demo.agomtrade.pro:443",
    ],
)
def test_normalize_domain_rejects_values_that_caddy_cannot_certify_safely(value: str):
    with pytest.raises(ValueError):
        remote_build_deploy_vps._normalize_domain(value)


def test_normalize_domain_accepts_and_canonicalizes_dns_hostname():
    assert (
        remote_build_deploy_vps._normalize_domain(" Demo.AgomTrade.Pro. ") == "demo.agomtrade.pro"
    )


def test_normalize_domain_keeps_blank_http_only_mode():
    assert remote_build_deploy_vps._normalize_domain("  ") == ""


def test_remote_deploy_blocks_release_on_macro_governance_drift():
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    assert "python manage.py init_macro_indicator_governance --check" in script
    assert "python manage.py normalize_macro_fact_units --check" in script
    assert "macro data-governance drift check failed" in script


def test_remote_deploy_publishes_and_verifies_tui_release_metadata():
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    assert 'sh scripts/publish-tui-release.sh "$RELEASE_TAG"' in script
    assert "TUI metadata publish or verification failed" in script
    assert 'rollback-$(basename "$PREVIOUS_RELEASE")' in script
    assert "Automatic rollback publish" in script
    assert "Previous release TUI registry restore failed" in script

    deploy_script = (
        Path(__file__).resolve().parents[2] / "scripts" / "deploy-on-vps.sh"
    ).read_text(encoding="utf-8")
    release_helper = (
        Path(__file__).resolve().parents[2] / "scripts" / "publish-tui-release.sh"
    ).read_text(encoding="utf-8")

    assert 'sh scripts/publish-tui-release.sh "$release_name"' in deploy_script
    assert "--approve" in release_helper
    assert "--check" in release_helper
    assert "reviewed TUI metadata is missing" in release_helper


def test_remote_deploy_installs_idempotent_daily_backup_cron():
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    assert (
        'BACKUP_CRON_JOB="0 18 * * * $TARGET_DIR/current/scripts/vps-backup.sh'
        ' --keep-days 14 >> /var/log/agomtradepro-backup.log 2>&1"' in script
    )
    assert 'grep -qF "vps-backup.sh"' in script
    assert "backup cron already installed; skipping" in script
