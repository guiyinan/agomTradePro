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
    assert "python manage.py verify_canonical_schema --json" in script
    assert script.index("verify_canonical_schema --json") < script.index(
        "python manage.py check --deploy"
    )


def test_remote_deploy_publishes_canonical_https_origin_and_validates_tls():
    script = remote_build_deploy_vps._build_remote_deploy_script()

    assert 'EFFECTIVE_APP_BASE_URL="https://$EFFECTIVE_DOMAIN"' in script
    assert 'set_env_kv "APP_BASE_URL" "$EFFECTIVE_APP_BASE_URL"' in script
    assert "redir https://$EFFECTIVE_DOMAIN{uri} permanent" in script
    assert 'HEALTH_URL="https://$EFFECTIVE_DOMAIN/api/health/"' in script
    assert 'HEALTH_RESOLVE="--resolve $EFFECTIVE_DOMAIN:443:127.0.0.1"' in script
    assert "curl -fsS --max-time 10 $HEALTH_RESOLVE" in script


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


def test_legacy_deploy_verifies_canonical_schema_after_migrations():
    script = (Path(__file__).resolve().parents[2] / "scripts" / "deploy-on-vps.sh").read_text(
        encoding="utf-8"
    )

    assert "python manage.py verify_canonical_schema --json" in script
    assert script.index("verify_canonical_schema --json") > script.index(
        "python manage.py migrate --noinput"
    )


def test_remote_deploy_synchronizes_mcp_catalog_before_release_publish():
    remote_script = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")
    legacy_script = (
        Path(__file__).resolve().parents[2] / "scripts" / "deploy-on-vps.sh"
    ).read_text(encoding="utf-8")
    sync_command = (
        "python manage.py sync_ai_capability_catalog --type incremental "
        "--source mcp_tool --fail-on-error"
    )

    assert sync_command in remote_script
    assert remote_script.index(sync_command) < remote_script.index(
        'sh scripts/publish-tui-release.sh "$RELEASE_TAG"'
    )
    assert sync_command in legacy_script
    assert legacy_script.index(sync_command) < legacy_script.index(
        'sh scripts/publish-tui-release.sh "$release_name"'
    )


def test_remote_deploy_removes_duplicate_backup_cron_and_keeps_beat_as_owner():
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    assert "BACKUP_CRON_JOB=" not in script
    assert 'grep -v "vps-backup.sh" | crontab -' in script
    assert "Django Beat is the daily owner" in script
    assert "--keep-days 14" not in script
    assert "--keep-days 1" in script
