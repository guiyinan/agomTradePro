from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    spec = importlib.util.spec_from_file_location("remote_build_deploy_vps", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


remote_build_deploy_vps = _load_module()


def test_run_drains_stdout_and_stderr_without_sequential_read_deadlock() -> None:
    class FakeChannel:
        def __init__(self) -> None:
            self.stdout_chunks = [b"stdout\n"]
            self.stderr_chunks = [b"stderr\n"]

        def recv_ready(self) -> bool:
            return bool(self.stdout_chunks)

        def recv_stderr_ready(self) -> bool:
            return bool(self.stderr_chunks)

        def recv(self, _size: int) -> bytes:
            return self.stdout_chunks.pop(0)

        def recv_stderr(self, _size: int) -> bytes:
            return self.stderr_chunks.pop(0)

        def exit_status_ready(self) -> bool:
            return not self.stdout_chunks and not self.stderr_chunks

        def recv_exit_status(self) -> int:
            return 0

        def close(self) -> None:
            return None

    class FakeStream:
        def __init__(self, channel: FakeChannel) -> None:
            self.channel = channel

        def read(self) -> bytes:
            raise AssertionError("sequential stream reads can deadlock")

    class FakeSSH:
        def exec_command(
            self, _command: str, timeout: int
        ) -> tuple[object, FakeStream, FakeStream]:
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
def test_normalize_domain_rejects_values_that_caddy_cannot_certify_safely(
    value: str,
) -> None:
    with pytest.raises(ValueError):
        remote_build_deploy_vps._normalize_domain(value)


def test_normalize_domain_accepts_and_canonicalizes_dns_hostname() -> None:
    assert (
        remote_build_deploy_vps._normalize_domain(" Demo.AgomTrade.Pro. ") == "demo.agomtrade.pro"
    )


def test_normalize_domain_keeps_blank_http_only_mode() -> None:
    assert remote_build_deploy_vps._normalize_domain("  ") == ""


@pytest.mark.parametrize(
    "value",
    [
        "",
        "unknown",
        "A" * 40,
        "a" * 39,
        "a" * 41,
        "g" * 40,
    ],
)
def test_normalize_source_commit_rejects_noncanonical_identity(value: str) -> None:
    with pytest.raises(ValueError, match="lowercase 40-hex"):
        remote_build_deploy_vps._normalize_source_commit(value)


def test_normalize_source_commit_accepts_exact_lowercase_sha1() -> None:
    source_commit = "0123456789abcdef0123456789abcdef01234567"

    assert remote_build_deploy_vps._normalize_source_commit(source_commit) == source_commit


@pytest.mark.parametrize(
    ("builder_name", "source_mode"),
    [
        ("_build_remote_build_script", "source-upload"),
        ("_build_remote_git_clone_build_script", "git-clone"),
    ],
)
def test_remote_builds_fail_closed_and_write_immutable_release_manifest(
    builder_name: str,
    source_mode: str,
) -> None:
    script = getattr(remote_build_deploy_vps, builder_name)()

    assert "unknown" not in script
    assert 're.fullmatch(r"[0-9a-f]{40}", source_commit)' in script
    assert "org.opencontainers.image.revision" in script
    assert 'if [ "$IMAGE_REVISION" != "$SOURCE_COMMIT" ]; then' in script
    assert "image OCI revision does not match source commit" in script
    assert 'MANIFEST_PATH=".agom-release-manifest.json"' in script
    assert 'manifest_path.open("x", encoding="utf-8", newline="\\n")' in script
    assert "manifest_path.chmod(0o444)" in script
    assert '"version": 1' in script
    assert '"release_tag": release_tag' in script
    assert '"source_commit": source_commit' in script
    assert '"image_tag": image_tag' in script
    assert '"image_id": image_id' in script
    assert '"build_started_at": build_started_at' in script
    assert '"build_finished_at": build_finished_at' in script
    assert f'"source_mode": "{source_mode}"' in script
    assert "sort_keys=True" in script
    assert script.index('re.fullmatch(r"[0-9a-f]{40}", source_commit)') < script.index(
        "docker build"
    )
    assert script.index("org.opencontainers.image.revision") < script.index(
        'manifest_path.open("x"'
    )


def test_upload_mode_passes_exact_local_source_commit_without_unknown_fallback() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    assert 'source_commit = "unknown"' not in source
    assert '"SOURCE_COMMIT": source_commit' in source
    upload_branch = source.split("else:\n            remote_bundle =", 1)[1]
    upload_build_env = upload_branch.split("exports =", 1)[0]
    assert '"SOURCE_COMMIT": source_commit' in upload_build_env


def test_upload_mode_rejects_tracked_or_untracked_worktree_changes_before_bundle_or_ssh() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    status_command = '["git", "status", "--porcelain", "--untracked-files=all"]'
    dirty_error = "Source-upload mode requires a clean Git worktree"
    bundle_start = '_info(f"Creating source bundle: {local_bundle}")'
    ssh_start = '_info(f"Connecting to {user}@{host}:{args.port}")'

    assert status_command in source
    assert dirty_error in source
    assert source.index(status_command) < source.index(bundle_start)
    assert source.index(status_command) < source.index(ssh_start)


def test_git_clone_mode_pins_remote_clone_to_requested_local_candidate() -> None:
    script = remote_build_deploy_vps._build_remote_git_clone_build_script()

    expected_assignment = 'EXPECTED_SOURCE_COMMIT="${SOURCE_COMMIT:?missing SOURCE_COMMIT}"'
    cloned_assignment = 'CLONED_SOURCE_COMMIT="$(git rev-parse --verify HEAD)"'
    comparison = 'if [ "$CLONED_SOURCE_COMMIT" != "$EXPECTED_SOURCE_COMMIT" ]; then'

    assert expected_assignment in script
    assert cloned_assignment in script
    assert comparison in script
    assert "cloned source commit does not match requested candidate" in script
    assert script.index(expected_assignment) < script.index("git clone")
    assert script.index(cloned_assignment) < script.index(comparison)
    assert script.index(comparison) < script.index("docker build")


def test_remote_deploy_validates_manifest_and_image_before_any_start_or_switch() -> None:
    script = remote_build_deploy_vps._build_remote_deploy_script()

    validation = 'MANIFEST_PATH="$RELEASE_DIR/.agom-release-manifest.json"'
    first_start = "compose up -d runtime_ns redis postgres"
    final_start = "compose up -d $SERVICES"
    current_switch = 'mv -Tf "$TARGET_DIR/.current-next" "$TARGET_DIR/current"'

    assert validation in script
    assert "release manifest must contain exactly" in script
    assert "expected_keys = {" in script
    assert 'manifest["release_tag"] != release_tag' in script
    assert 'manifest["image_tag"] != expected_image_tag' in script
    assert 'image_id != manifest["image_id"]' in script
    assert 'image_revision != manifest["source_commit"]' in script
    assert "release manifest must be read-only (0444)" in script
    assert script.index(validation) < script.index(first_start)
    assert script.index(validation) < script.index(final_start)
    assert script.index(validation) < script.index(current_switch)


def test_remote_deploy_rejects_persistent_asgi_database_connections_before_shutdown() -> None:
    script = remote_build_deploy_vps._build_remote_deploy_script()

    policy_error = "ASGI database policy requires CONN_MAX_AGE=0"
    shutdown = 'if [ "$ACTION" = "fresh" ]; then'

    assert "CONN_MAX_AGE" in script
    assert "docker run --rm --env-file deploy/.env --entrypoint python" in script
    assert policy_error in script
    assert script.index(policy_error) < script.index(shutdown)


def test_deployment_report_retains_validated_release_identity() -> None:
    script = remote_build_deploy_vps._build_remote_deploy_script()

    assert 'release_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))' in script
    assert '"release_manifest": release_manifest' in script
    assert '"version": release_manifest["version"]' in script
    assert '"image_tag": release_manifest["image_tag"]' in script
    assert '"source_mode": release_manifest["source_mode"]' in script


def test_remote_deploy_blocks_release_on_macro_governance_drift() -> None:
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


def test_remote_deploy_publishes_canonical_https_origin_and_validates_tls() -> None:
    script = remote_build_deploy_vps._build_remote_deploy_script()

    assert 'EFFECTIVE_APP_BASE_URL="https://$EFFECTIVE_DOMAIN"' in script
    assert 'set_env_kv "APP_BASE_URL" "$EFFECTIVE_APP_BASE_URL"' in script
    assert "redir https://$EFFECTIVE_DOMAIN{uri} permanent" in script
    assert 'HEALTH_URL="https://$EFFECTIVE_DOMAIN/api/health/"' in script
    assert 'HEALTH_RESOLVE="--resolve $EFFECTIVE_DOMAIN:443:127.0.0.1"' in script
    assert "curl -fsS --max-time 10 $HEALTH_RESOLVE" in script


def test_remote_deploy_publishes_and_verifies_tui_release_metadata() -> None:
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


def test_legacy_deploy_verifies_canonical_schema_after_migrations() -> None:
    script = (Path(__file__).resolve().parents[2] / "scripts" / "deploy-on-vps.sh").read_text(
        encoding="utf-8"
    )

    assert "python manage.py verify_canonical_schema --json" in script
    assert script.index("verify_canonical_schema --json") > script.index(
        "python manage.py migrate --noinput"
    )


def test_remote_deploy_synchronizes_mcp_catalog_before_release_publish() -> None:
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


def test_remote_deploy_removes_duplicate_backup_cron_and_keeps_beat_as_owner() -> None:
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    ).read_text(encoding="utf-8")

    assert "BACKUP_CRON_JOB=" not in script
    assert 'grep -v "vps-backup.sh" | crontab -' in script
    assert "Django Beat is the daily owner" in script
    assert "--keep-days 14" not in script
    assert "--keep-days 1" in script
