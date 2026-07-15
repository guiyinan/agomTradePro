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
    assert target.insecure_tls is True
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


def test_build_django_deploy_check_command_uses_running_web_container():
    command = deploy_vps_verify.build_django_deploy_check_command("/opt/agomtradepro")

    assert "exec -T web python manage.py check --deploy" in command


def test_build_migration_check_command_rejects_unapplied_migrations():
    command = deploy_vps_verify.build_migration_check_command("/opt/agomtradepro")

    assert "exec -T web python manage.py migrate --check --noinput" in command


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
