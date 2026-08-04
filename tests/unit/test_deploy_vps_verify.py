from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "deploy_vps_verify.py"
    spec = importlib.util.spec_from_file_location("deploy_vps_verify", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


deploy_vps_verify = _load_module()


def test_run_drains_stdout_and_stderr_without_file_read_deadlock():
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

    exit_code, stdout, stderr = deploy_vps_verify._run(FakeSSH(), "check", timeout=5)

    assert exit_code == 0
    assert stdout == "stdout\n"
    assert stderr == "stderr\n"


def test_parse_caddy_site_address_handles_domain_line():
    assert (
        deploy_vps_verify.parse_caddy_site_address("demo.agomtrade.pro {") == "demo.agomtrade.pro"
    )


def test_parse_caddy_site_address_handles_http_listener():
    assert deploy_vps_verify.parse_caddy_site_address(":80 {") == ":80"


def test_build_health_probe_target_uses_http_port_for_http_only_site():
    target = deploy_vps_verify.build_health_probe_target(":80", http_port=8000)

    assert target.url == "http://127.0.0.1:8000/api/health/"
    assert target.insecure_tls is False
    assert target.resolve_host is None
    assert target.resolve_port is None


def test_build_health_probe_target_uses_local_tls_with_host_header_for_domain():
    target = deploy_vps_verify.build_health_probe_target("demo.agomtrade.pro", http_port=8000)

    assert target.url == "https://demo.agomtrade.pro/api/health/"
    assert target.insecure_tls is False
    assert target.resolve_host == "demo.agomtrade.pro"
    assert target.resolve_port == 443


def test_parse_health_probe_output_extracts_status_and_body():
    http_code, body = deploy_vps_verify.parse_health_probe_output(
        '__AGOM_HTTP_CODE__=200\n{"status":"ok"}'
    )

    assert http_code == "200"
    assert body == '{"status":"ok"}'


def test_evaluate_health_probe_result_accepts_empty_body_for_success():
    ok, summary = deploy_vps_verify.evaluate_health_probe_result(
        exit_code=0,
        stdout="__AGOM_HTTP_CODE__=204\n",
        stderr="",
    )

    assert ok is True
    assert summary == "HTTP 204 (empty body)"


def test_evaluate_health_probe_result_rejects_non_2xx_status():
    ok, summary = deploy_vps_verify.evaluate_health_probe_result(
        exit_code=0,
        stdout='__AGOM_HTTP_CODE__=503\n{"status":"error"}',
        stderr="",
    )

    assert ok is False
    assert summary == 'HTTP 503 {"status":"error"}'


def test_build_compose_command_uses_vps_compose_file_and_env():
    command = deploy_vps_verify.build_compose_command(
        "/opt/agomtradepro", "ps", "-q", "celery_worker"
    )

    assert "cd /opt/agomtradepro/current" in command
    assert "docker compose -p agomtradepro" in command
    assert "-f docker/docker-compose.vps.yml" in command
    assert "--env-file deploy/.env" in command
    assert "ps -q celery_worker" in command


def test_build_celery_ping_command_checks_workers_from_web_container():
    command = deploy_vps_verify.build_celery_ping_command("/opt/agomtradepro")

    assert "exec -T web celery -A core inspect ping --timeout=8" in command


def test_build_django_deploy_check_command_uses_isolated_web_container():
    command = deploy_vps_verify.build_django_deploy_check_command("/opt/agomtradepro")

    assert "run --rm --no-deps web python manage.py check --deploy" in command
    assert deploy_vps_verify.DJANGO_DEPLOY_CHECK_TIMEOUT_SECONDS == 180


def test_build_migration_check_command_rejects_unapplied_migrations():
    command = deploy_vps_verify.build_migration_check_command("/opt/agomtradepro")

    assert "exec -T web python manage.py migrate --check --noinput" in command


def test_build_canonical_schema_check_command_rejects_old_data_center_schema():
    command = deploy_vps_verify.build_canonical_schema_check_command("/opt/agomtradepro")

    assert "exec -T web python -c" in command
    assert "data_center_sync_run" in command
    assert "data_center_sync_checkpoint" in command
    assert "data_center_raw_payload" in command
    assert "data_center_dataset_contract" in command
    assert "data_center_retention_run" in command
    assert "data_center_publication_rollback" in command
    assert "canonical_control_plane_missing" in command


def test_build_tui_metadata_check_command_compares_registry_with_release():
    command = deploy_vps_verify.build_tui_metadata_check_command("/opt/agomtradepro")

    assert "publish_tui_metadata.py" in command
    assert "tui_operation_graph.published.json" in command
    assert "--check --registry-key default" in command


def test_evaluate_runtime_command_result_accepts_empty_success_output():
    ok, summary = deploy_vps_verify.evaluate_runtime_command_result(
        exit_code=0,
        stdout="",
        stderr="",
    )

    assert ok is True
    assert summary == "command completed successfully"


def test_build_qlib_identity_command_checks_distribution_and_module():
    command = deploy_vps_verify.build_qlib_identity_command("/opt/agomtradepro")

    assert "exec -T web python -c" in command
    assert "metadata.version" in command
    assert "pyqlib" in command
    assert "wrong_qlib" in command
    assert "import qlib.data" in command
    assert "qlib.__file__" in command


def test_evaluate_qlib_identity_result_accepts_canonical_runtime():
    ok, summary = deploy_vps_verify.evaluate_qlib_identity_result(
        exit_code=0,
        stdout=(
            "pyqlib=0.9.7\n"
            "wrong_qlib=absent\n"
            "module=/usr/local/lib/python3.11/site-packages/qlib/__init__.py\n"
        ),
        stderr="",
    )

    assert ok is True
    assert "pyqlib=0.9.7" in summary


def test_evaluate_qlib_identity_result_rejects_wrong_distribution():
    ok, summary = deploy_vps_verify.evaluate_qlib_identity_result(
        exit_code=0,
        stdout=(
            "pyqlib=0.9.7\n"
            "wrong_qlib=present\n"
            "module=/usr/local/lib/python3.11/site-packages/qlib/__init__.py\n"
        ),
        stderr="",
    )

    assert ok is False
    assert "wrong qlib distribution is installed" in summary


def test_release_identity_requires_git_image_and_expected_sha_to_match():
    sha = "a" * 40
    ok, summary = deploy_vps_verify.evaluate_release_identity_result(
        0,
        f"git_sha={sha}\nimage_sha={sha}\nimage_id=sha256:123\n",
        "",
        expected_commit=sha,
    )

    assert ok is True
    assert "image_id=sha256:123" in summary

    mismatch, mismatch_summary = deploy_vps_verify.evaluate_release_identity_result(
        0,
        f"git_sha={sha}\nimage_sha={'b' * 40}\nimage_id=sha256:123\n",
        "",
    )
    assert mismatch is False
    assert "does not match image label" in mismatch_summary


def test_resource_result_warns_at_80_and_fails_at_95_or_restart():
    ok, summary, warnings = deploy_vps_verify.evaluate_resource_result(
        0,
        '[{"service":"web","memory_percent":81,"oom_killed":false,"restart_count":0}]',
        "",
    )
    assert ok is True
    assert summary == "checked 1 containers"
    assert warnings == ["web: memory=81.0%"]

    failed, failure, _warnings = deploy_vps_verify.evaluate_resource_result(
        0,
        '[{"service":"web","memory_percent":50,"oom_killed":false,"restart_count":1}]',
        "",
    )
    assert failed is False
    assert "restarts=1" in failure


def test_verification_commands_cover_identity_backup_resources_and_model_metadata():
    identity = deploy_vps_verify.build_release_identity_command("/opt/agomtradepro")
    backup = deploy_vps_verify.build_security_backup_command("/opt/agomtradepro")
    resources = deploy_vps_verify.build_resource_command("/opt/agomtradepro")
    freshness = deploy_vps_verify.build_data_freshness_command("/opt/agomtradepro")
    certificate = deploy_vps_verify.build_certificate_expiry_command("demo.agomtrade.pro")
    rollback = deploy_vps_verify.build_rollback_command(
        "/opt/agomtradepro", 8000, expect_celery=True
    )

    assert "org.opencontainers.image.revision" in identity
    assert "-mmin -1560" in backup
    assert '-name "*.dump"' in backup
    assert "gzip -t" in backup
    assert "PGDMP" in backup
    assert "OOMKilled" in resources
    assert "_meta.db_table" in freshness
    assert "-checkend 1814400" in certificate
    assert 'readlink -f "$target/previous"' in rollback
    assert "mv -Tf" in rollback
    assert "celery -A core inspect ping" in rollback
    assert "publish-tui-release.sh" in rollback
    assert "Automatic rollback publish" in rollback
