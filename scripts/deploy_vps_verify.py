#!/usr/bin/env python3
"""
Post-deploy verification helper for deploy-vps.ps1.

The health probe must validate the remote HTTP status instead of assuming
the endpoint always returns a non-empty body.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

HTTP_CODE_MARKER = "__AGOM_HTTP_CODE__="
DJANGO_DEPLOY_CHECK_TIMEOUT_SECONDS = 180


def _summarize(text: str, limit: int = 200) -> str:
    normalized = " ".join((text or "").split())
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."


def _ssh_connect(host: str, port: int, username: str, password: str, timeout: int):
    try:
        import paramiko  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency failure is environment-specific
        print(f"[WARN] Post-deploy verification skipped: paramiko unavailable ({exc})")
        raise SystemExit(0) from exc

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=username,
        password=password,
        look_for_keys=False,
        allow_agent=False,
        timeout=timeout,
        banner_timeout=timeout,
        auth_timeout=timeout,
    )
    return client


def _run(ssh, command: str, timeout: int) -> tuple[int, str, str]:
    _stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    channel = stdout.channel
    deadline = time.monotonic() + timeout
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()

    while True:
        drained = False
        while channel.recv_ready():
            stdout_buffer.extend(channel.recv(32768))
            drained = True
        while channel.recv_stderr_ready():
            stderr_buffer.extend(channel.recv_stderr(32768))
            drained = True

        if channel.exit_status_ready():
            exit_code = channel.recv_exit_status()
            break

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            channel.close()
            raise TimeoutError(f"remote command timed out after {timeout}s")
        if not drained:
            time.sleep(min(0.05, remaining))

    return (
        exit_code,
        stdout_buffer.decode("utf-8", errors="replace"),
        stderr_buffer.decode("utf-8", errors="replace"),
    )


def parse_caddy_site_address(first_line: str) -> str:
    stripped = (first_line or "").strip()
    if not stripped:
        return ":80"
    return stripped.split()[0].rstrip("{").strip()


@dataclass(frozen=True)
class HealthProbeTarget:
    url: str
    insecure_tls: bool
    resolve_host: str | None = None
    resolve_port: int | None = None


def build_health_probe_target(
    site_address: str,
    http_port: int,
    health_path: str = "/api/health/",
) -> HealthProbeTarget:
    normalized_path = health_path if health_path.startswith("/") else f"/{health_path}"
    site = (site_address or "").strip()

    if not site or site.startswith(":"):
        return HealthProbeTarget(
            url=f"http://127.0.0.1:{http_port}{normalized_path}",
            insecure_tls=False,
            resolve_host=None,
            resolve_port=None,
        )

    normalized_site = site if "://" in site else f"https://{site}"
    parsed = urlsplit(normalized_site)
    scheme = parsed.scheme or "https"
    hostname = parsed.hostname or ""
    if not hostname:
        return HealthProbeTarget(
            url=f"http://127.0.0.1:{http_port}{normalized_path}",
            insecure_tls=False,
            resolve_host=None,
            resolve_port=None,
        )

    if scheme == "http":
        port = parsed.port or http_port
    else:
        port = parsed.port or 443
    authority = hostname if parsed.port is None else f"{hostname}:{port}"

    return HealthProbeTarget(
        url=f"{scheme}://{authority}{normalized_path}",
        # A production verification must validate the certificate chain.  The
        # local --resolve mapping is still used so the probe reaches Caddy.
        insecure_tls=False,
        resolve_host=hostname,
        resolve_port=port,
    )


def build_health_probe_command(target: HealthProbeTarget) -> str:
    curl_args: list[str] = ["curl"]
    if target.insecure_tls:
        curl_args.append("-k")
    curl_args.extend(["-sS", "-L", "--max-time", "10"])
    if target.resolve_host and target.resolve_port:
        curl_args.extend(["--resolve", f"{target.resolve_host}:{target.resolve_port}:127.0.0.1"])
    curl_args.extend(["-o", "$tmp_body", "-w", "%{http_code}", target.url])

    shell_args: list[str] = []
    for arg in curl_args:
        if arg == "$tmp_body":
            shell_args.append('"$tmp_body"')
        else:
            shell_args.append(shlex.quote(arg))

    curl_command = " ".join(shell_args)
    return (
        "tmp_body=$(mktemp) && "
        f"http_code=$({curl_command}) && "
        f"printf '{HTTP_CODE_MARKER}%s\\n' \"$http_code\" && "
        'cat "$tmp_body" && '
        'rm -f "$tmp_body"'
    )


def parse_health_probe_output(stdout: str) -> tuple[str | None, str]:
    if not stdout:
        return None, ""

    marker_index = stdout.find(HTTP_CODE_MARKER)
    if marker_index == -1:
        return None, stdout.strip()

    remainder = stdout[marker_index + len(HTTP_CODE_MARKER) :]
    first_newline = remainder.find("\n")
    if first_newline == -1:
        return remainder.strip() or None, ""

    http_code = remainder[:first_newline].strip() or None
    body = remainder[first_newline + 1 :].strip()
    return http_code, body


def evaluate_health_probe_result(exit_code: int, stdout: str, stderr: str) -> tuple[bool, str]:
    if exit_code != 0:
        detail = _summarize(stderr or stdout or "health probe command failed")
        return False, detail

    http_code, body = parse_health_probe_output(stdout)
    if not http_code:
        return False, "missing HTTP status from health probe"

    body_summary = _summarize(body) if body else "(empty body)"
    if not http_code.startswith("2"):
        return False, f"HTTP {http_code} {body_summary}"

    return True, f"HTTP {http_code} {body_summary}"


def evaluate_runtime_command_result(
    exit_code: int,
    stdout: str,
    stderr: str,
) -> tuple[bool, str]:
    """Evaluate a runtime validation where empty successful output is valid."""

    if exit_code != 0:
        detail = _summarize(stderr or stdout or "command failed")
        return False, detail
    return True, _summarize(stdout or stderr) or "command completed successfully"


def evaluate_qlib_identity_result(
    exit_code: int,
    stdout: str,
    stderr: str,
) -> tuple[bool, str]:
    """Require pyqlib and reject the unrelated package named ``qlib``."""

    if exit_code != 0:
        detail = _summarize(stderr or stdout or "Qlib identity check failed")
        return False, detail

    values: dict[str, str] = {}
    for line in stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip()

    if not values.get("pyqlib"):
        return False, "pyqlib distribution is missing"
    if values.get("wrong_qlib") != "absent":
        return False, "wrong qlib distribution is installed"
    if not values.get("module"):
        return False, "qlib module path is missing"

    return True, _summarize(stdout)


def _parse_key_values(stdout: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip()
    return values


def evaluate_release_identity_result(
    exit_code: int,
    stdout: str,
    stderr: str,
    expected_commit: str | None = None,
) -> tuple[bool, str]:
    """Require the release Git SHA and image OCI revision label to agree."""

    if exit_code != 0:
        return False, _summarize(stderr or stdout or "release identity check failed")
    values = _parse_key_values(stdout)
    git_sha = values.get("git_sha", "")
    image_sha = values.get("image_sha", "")
    image_id = values.get("image_id", "")
    if not git_sha or not image_sha or not image_id:
        return False, "release identity output is incomplete"
    if git_sha != image_sha:
        return False, f"Git SHA {git_sha} does not match image label {image_sha}"
    if expected_commit and git_sha != expected_commit:
        return False, f"deployed SHA {git_sha} does not match expected {expected_commit}"
    return True, f"git_sha={git_sha} image_id={image_id}"


def evaluate_resource_result(
    exit_code: int,
    stdout: str,
    stderr: str,
) -> tuple[bool, str, list[str]]:
    """Fail on OOM/restarts/critical memory and warn above 80 percent."""

    if exit_code != 0:
        return False, _summarize(stderr or stdout or "resource check failed"), []
    try:
        rows = json.loads(stdout)
    except (TypeError, json.JSONDecodeError):
        return False, "invalid resource check output", []
    warnings: list[str] = []
    for row in rows:
        service = str(row.get("service", "unknown"))
        memory = float(row.get("memory_percent", 0))
        oom = bool(row.get("oom_killed"))
        restarts = int(row.get("restart_count", 0))
        if oom or restarts or memory > 95:
            return (
                False,
                f"{service}: memory={memory:.1f}% oom={oom} restarts={restarts}",
                warnings,
            )
        if memory > 80:
            warnings.append(f"{service}: memory={memory:.1f}%")
    return True, f"checked {len(rows)} containers", warnings


def _emit_command_result(label: str, exit_code: int, stdout: str, stderr: str) -> bool:
    if exit_code != 0:
        detail = _summarize(stderr or stdout or "command failed")
        print(f"[FAIL] {label}: {detail}")
        return False

    summary = _summarize(stdout)
    if not summary:
        print(f"[FAIL] {label}: empty response")
        return False

    print(f"[OK] {label}: {summary}")
    return True


def build_compose_command(target_dir: str, *args: str) -> str:
    """Build a remote docker compose command for the deployed release."""

    quoted_args = " ".join(shlex.quote(arg) for arg in args)
    return (
        f"cd {shlex.quote(target_dir)}/current && "
        "docker compose -p agomtradepro -f docker/docker-compose.vps.yml "
        f"--env-file deploy/.env {quoted_args}"
    )


def build_container_running_command(target_dir: str, service: str) -> str:
    """Build a command that prints whether a compose service container is running."""

    compose_ps = build_compose_command(target_dir, "ps", "-q", service)
    return (
        f"cid=$({compose_ps}) && "
        '[ -n "$cid" ] && '
        "docker inspect -f '{{.State.Running}}' \"$cid\""
    )


def build_celery_ping_command(target_dir: str) -> str:
    """Build a remote command that verifies Celery workers respond through Redis."""

    return build_compose_command(
        target_dir,
        "exec",
        "-T",
        "web",
        "celery",
        "-A",
        "core",
        "inspect",
        "ping",
        "--timeout=8",
    )


def build_django_deploy_check_command(target_dir: str) -> str:
    """Build an isolated Django production system-check command."""

    return build_compose_command(
        target_dir,
        "run",
        "--rm",
        "--no-deps",
        "web",
        "python",
        "manage.py",
        "check",
        "--deploy",
    )


def build_migration_check_command(target_dir: str) -> str:
    """Build a command that fails while migrations remain unapplied."""

    return build_compose_command(
        target_dir,
        "exec",
        "-T",
        "web",
        "python",
        "manage.py",
        "migrate",
        "--check",
        "--noinput",
    )


def build_canonical_schema_check_command(target_dir: str) -> str:
    """Build a command that rejects releases missing canonical control-plane tables.

    ``migrate --check`` can be green when an old image is self-consistent but
    does not contain the newest migration files.  The table contract closes
    that false-green deployment path for the Data Center cutover.
    """

    required_tables = (
        "data_center_canonical_publication",
        "data_center_publication_member",
        "data_center_sync_run",
        "data_center_sync_batch",
        "data_center_sync_checkpoint",
        "data_center_raw_landing",
        "data_center_schema_fingerprint",
        "data_center_reconciliation_evidence",
        "data_center_publication_rollback",
    )
    table_literal = repr(required_tables)
    python_code = (
        "from django.db import connection; "
        f"required=set({table_literal}); "
        "actual=set(connection.introspection.table_names()); "
        "missing=sorted(required-actual); "
        "print('canonical_control_plane_missing=' + ','.join(missing)); "
        "import sys; sys.exit(1 if missing else 0)"
    )
    return build_compose_command(
        target_dir,
        "exec",
        "-T",
        "web",
        "python",
        "-c",
        python_code,
    )


def build_tui_metadata_check_command(target_dir: str) -> str:
    """Require the active TUI registry to match the deployed release artifact."""

    return build_compose_command(
        target_dir,
        "exec",
        "-T",
        "web",
        "python",
        "tui-metadata-compiler/scripts/publish_tui_metadata.py",
        "config/tui/published/tui_operation_graph.published.json",
        "--check",
        "--registry-key",
        "default",
    )


def build_qlib_identity_command(target_dir: str) -> str:
    """Build a command that reports the installed Qlib distribution identity."""

    python_code = """from importlib import metadata
import qlib
import qlib.data

print(f"pyqlib={metadata.version('pyqlib')}")
try:
    metadata.version("qlib")
except metadata.PackageNotFoundError:
    print("wrong_qlib=absent")
else:
    print("wrong_qlib=present")
print(f"module={qlib.__file__}")
"""
    return build_compose_command(
        target_dir,
        "exec",
        "-T",
        "web",
        "python",
        "-c",
        python_code,
    )


def build_release_identity_command(target_dir: str) -> str:
    """Report source identity from the release and running web image."""

    compose_ps = build_compose_command(target_dir, "ps", "-q", "web")
    return (
        f"cd {shlex.quote(target_dir)}/current && "
        "git_sha=$(git rev-parse HEAD) && "
        f"cid=$({compose_ps}) && "
        "image_id=$(docker inspect -f '{{.Image}}' \"$cid\") && "
        'image_sha=$(docker image inspect -f \'{{index .Config.Labels "org.opencontainers.image.revision"}}\' "$image_id") && '
        'printf "git_sha=%s\\nimage_sha=%s\\nimage_id=%s\\n" "$git_sha" "$image_sha" "$image_id"'
    )


def build_security_backup_command(target_dir: str) -> str:
    """Validate secret permissions and a fresh, readable persistent backup."""

    quoted = shlex.quote(target_dir)
    return (
        f"target={quoted}; "
        'test "$(stat -c %a "$target")" = 700; '
        'test "$(stat -c %a "$target/secrets.env")" = 600; '
        'test "$(stat -c %a "$target/current/deploy/.env")" = 600; '
        'test "$(stat -c %a "$target/backups")" = 700; '
        'backup=$(find "$target/backups/database" -type f '
        '\\( -name "*.dump" -o -name "*.gz" \\) -mmin -1560 '
        '-printf "%T@ %p\\n" | sort -nr | head -1 | cut -d" " -f2-); '
        'test -n "$backup"; '
        'case "$backup" in *.gz) gzip -t "$backup" ;; '
        '*.dump) head -c 5 "$backup" | grep -q PGDMP ;; esac; '
        'test "$(stat -c %a "$backup")" = 600; '
        'printf "backup=%s\\n" "$backup"'
    )


def build_resource_command(target_dir: str) -> str:
    """Return resource and restart state as JSON for web and Celery Beat."""

    python_code = """import json, subprocess
rows = []
for service in ("web", "celery_beat"):
    cid = subprocess.check_output(["docker", "compose", "-p", "agomtradepro", "-f", "docker/docker-compose.vps.yml", "--env-file", "deploy/.env", "ps", "-q", service], text=True).strip()
    info = json.loads(subprocess.check_output(["docker", "inspect", cid], text=True))[0]
    state = info["State"]
    raw = subprocess.check_output(["docker", "stats", "--no-stream", "--format", "{{.MemPerc}}", cid], text=True).strip().rstrip("%").replace(",", ".")
    rows.append({"service": service, "memory_percent": float(raw), "oom_killed": state.get("OOMKilled", False), "restart_count": info.get("RestartCount", 0)})
print(json.dumps(rows))
"""
    return f"cd {shlex.quote(target_dir)}/current && python3 -c {shlex.quote(python_code)}"


def build_data_freshness_command(target_dir: str) -> str:
    """Use model metadata instead of stale hard-coded database table names."""

    python_code = """from datetime import timedelta
from django.utils import timezone
from apps.data_center.infrastructure.models import QuoteSnapshotModel
from apps.task_monitor.infrastructure.models import TaskExecutionModel
quote = QuoteSnapshotModel._default_manager.order_by('-snapshot_at').values_list('snapshot_at', flat=True).first()
task = TaskExecutionModel._default_manager.order_by('-updated_at').values_list('updated_at', flat=True).first()
print(f'quote_table={QuoteSnapshotModel._meta.db_table} quote_latest={quote}')
print(f'task_table={TaskExecutionModel._meta.db_table} task_latest={task}')
if not quote: raise SystemExit('quote data is missing')
if not task: raise SystemExit('task history is missing')
if quote and quote < timezone.now() - timedelta(days=4): raise SystemExit('quote data is stale')
if task and task < timezone.now() - timedelta(hours=26): raise SystemExit('task history is stale')
"""
    return build_compose_command(
        target_dir, "exec", "-T", "web", "python", "manage.py", "shell", "-c", python_code
    )


def build_certificate_expiry_command(site_address: str) -> str | None:
    """Require an HTTPS certificate that remains valid for at least 21 days."""

    site = site_address if "://" in site_address else f"https://{site_address}"
    parsed = urlsplit(site)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    host = parsed.hostname
    port = parsed.port or 443
    destination = shlex.quote(f"{host}:{port}")
    server_name = shlex.quote(host)
    return (
        f"echo | openssl s_client -connect {destination} -servername {server_name} 2>/dev/null "
        "| openssl x509 -checkend 1814400 -noout"
    )


def build_rollback_command(target_dir: str, http_port: int, expect_celery: bool) -> str:
    """Atomically restore the release recorded before the current deployment."""

    target = shlex.quote(target_dir)
    celery_check = ""
    if expect_celery:
        celery_check = (
            "for celery_attempt in $(seq 1 12); do "
            "$compose exec -T web celery -A core inspect ping --timeout=8 >/dev/null && break; "
            'test "$celery_attempt" -lt 12; sleep 3; done; '
        )
    return (
        f'target={target}; previous=$(readlink -f "$target/previous"); '
        'test -n "$previous"; test -d "$previous"; '
        'current=$(readlink -f "$target/current"); test "$previous" != "$current"; '
        'cd "$current"; compose="docker compose -p agomtradepro -f '
        'docker/docker-compose.vps.yml --env-file deploy/.env"; '
        '$compose down --remove-orphans; cd "$previous"; $compose up -d; '
        "if test -f scripts/publish-tui-release.sh; then "
        '$compose run --rm --no-deps web sh scripts/publish-tui-release.sh "rollback-$(basename "$previous")"; '
        "else test -f config/tui/published/tui_operation_graph.published.json; "
        "$compose run --rm --no-deps web python tui-metadata-compiler/scripts/publish_tui_metadata.py "
        "config/tui/published/tui_operation_graph.published.json --approve "
        '--generation-source mixed --backend-version "rollback-$(basename "$previous")" '
        '--review-note "Automatic rollback publish $(basename "$previous")"; fi; '
        'rm -f "$target/.current-rollback"; '
        'ln -s "$previous" "$target/.current-rollback"; '
        'mv -Tf "$target/.current-rollback" "$target/current"; '
        f"for attempt in $(seq 1 20); do curl -fsS --max-time 10 http://127.0.0.1:{http_port}/api/health/ >/dev/null && break; "
        'test "$attempt" -lt 20; sleep 3; done; '
        f"{celery_check}printf 'restored=%s\\n' \"$previous\""
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify AgomTradePro VPS deployment.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password-file", required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--http-port", type=int, default=8000)
    parser.add_argument("--target-dir", default="/opt/agomtradepro")
    parser.add_argument("--health-path", default="/api/health/")
    parser.add_argument("--expect-celery", action="store_true", default=False)
    parser.add_argument("--expected-commit")
    parser.add_argument("--auto-rollback", action="store_true", default=False)
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()

    password = Path(args.password_file).read_text(encoding="utf-8").strip()
    ssh = _ssh_connect(
        host=args.host,
        port=args.port,
        username=args.user,
        password=password,
        timeout=args.timeout,
    )

    ok = True
    try:
        caddy_code, caddy_out, caddy_err = _run(
            ssh,
            f"head -1 {shlex.quote(args.target_dir)}/current/docker/Caddyfile",
            timeout=args.timeout,
        )
        ok = _emit_command_result("Caddyfile", caddy_code, caddy_out, caddy_err) and ok

        site_address = parse_caddy_site_address(caddy_out)
        if site_address.startswith(":"):
            print("[WARN] Caddyfile is :80 - DOMAIN not configured, HTTPS will not work")

        health_target = build_health_probe_target(
            site_address=site_address,
            http_port=args.http_port,
            health_path=args.health_path,
        )
        health_code, health_out, health_err = _run(
            ssh,
            build_health_probe_command(health_target),
            timeout=args.timeout,
        )
        health_ok, health_summary = evaluate_health_probe_result(
            exit_code=health_code,
            stdout=health_out,
            stderr=health_err,
        )
        if health_ok:
            print(f"[OK] Health: {health_summary}")
        else:
            print(f"[FAIL] Health: {health_summary}")
            ok = False

        certificate_command = build_certificate_expiry_command(site_address)
        if certificate_command:
            cert_code, cert_out, cert_err = _run(
                ssh, certificate_command, timeout=max(args.timeout, 30)
            )
            cert_ok, cert_summary = evaluate_runtime_command_result(cert_code, cert_out, cert_err)
            print(f"[{'OK' if cert_ok else 'FAIL'}] TLS expiry: {cert_summary}")
            ok = cert_ok and ok

        containers_code, containers_out, containers_err = _run(
            ssh,
            'docker ps --format "table {{.Names}}\\t{{.Status}}"',
            timeout=args.timeout,
        )
        ok = (
            _emit_command_result("Containers", containers_code, containers_out, containers_err)
            and ok
        )

        runtime_checks = (
            (
                "Django deploy check",
                build_django_deploy_check_command(args.target_dir),
                max(args.timeout, DJANGO_DEPLOY_CHECK_TIMEOUT_SECONDS),
            ),
            (
                "Migrations",
                build_migration_check_command(args.target_dir),
                max(args.timeout, 30),
            ),
            (
                "Canonical Data Center schema",
                build_canonical_schema_check_command(args.target_dir),
                max(args.timeout, 60),
            ),
            (
                "TUI metadata registry",
                build_tui_metadata_check_command(args.target_dir),
                max(args.timeout, 30),
            ),
        )
        for label, command, command_timeout in runtime_checks:
            command_code, command_out, command_err = _run(
                ssh,
                command,
                timeout=command_timeout,
            )
            command_ok, command_summary = evaluate_runtime_command_result(
                command_code,
                command_out,
                command_err,
            )
            print(f"[{'OK' if command_ok else 'FAIL'}] {label}: {command_summary}")
            ok = command_ok and ok

        qlib_code, qlib_out, qlib_err = _run(
            ssh,
            build_qlib_identity_command(args.target_dir),
            timeout=max(args.timeout, 30),
        )
        qlib_ok, qlib_summary = evaluate_qlib_identity_result(
            qlib_code,
            qlib_out,
            qlib_err,
        )
        print(f"[{'OK' if qlib_ok else 'FAIL'}] Qlib identity: {qlib_summary}")
        ok = qlib_ok and ok

        identity_code, identity_out, identity_err = _run(
            ssh,
            build_release_identity_command(args.target_dir),
            timeout=max(args.timeout, 30),
        )
        identity_ok, identity_summary = evaluate_release_identity_result(
            identity_code,
            identity_out,
            identity_err,
            expected_commit=args.expected_commit,
        )
        print(f"[{'OK' if identity_ok else 'FAIL'}] Release identity: {identity_summary}")
        ok = identity_ok and ok

        security_code, security_out, security_err = _run(
            ssh,
            build_security_backup_command(args.target_dir),
            timeout=max(args.timeout, 30),
        )
        security_ok, security_summary = evaluate_runtime_command_result(
            security_code, security_out, security_err
        )
        print(f"[{'OK' if security_ok else 'FAIL'}] Secrets and backup: {security_summary}")
        ok = security_ok and ok

        resource_code, resource_out, resource_err = _run(
            ssh,
            build_resource_command(args.target_dir),
            timeout=max(args.timeout, 30),
        )
        resource_ok, resource_summary, resource_warnings = evaluate_resource_result(
            resource_code, resource_out, resource_err
        )
        print(f"[{'OK' if resource_ok else 'FAIL'}] Resources: {resource_summary}")
        for warning in resource_warnings:
            print(f"[WARN] Resources: {warning}")
        ok = resource_ok and ok

        freshness_code, freshness_out, freshness_err = _run(
            ssh,
            build_data_freshness_command(args.target_dir),
            timeout=max(args.timeout, 30),
        )
        freshness_ok, freshness_summary = evaluate_runtime_command_result(
            freshness_code, freshness_out, freshness_err
        )
        print(f"[{'OK' if freshness_ok else 'FAIL'}] Data freshness: {freshness_summary}")
        ok = freshness_ok and ok

        if args.expect_celery:
            for service in ("celery_worker", "celery_beat"):
                service_code, service_out, service_err = _run(
                    ssh,
                    build_container_running_command(args.target_dir, service),
                    timeout=args.timeout,
                )
                running_ok = service_code == 0 and service_out.strip() == "true"
                if running_ok:
                    print(f"[OK] {service}: running")
                else:
                    detail = _summarize(service_err or service_out or "not running")
                    print(f"[FAIL] {service}: {detail}")
                    ok = False

            celery_code, celery_out, celery_err = _run(
                ssh,
                build_celery_ping_command(args.target_dir),
                timeout=max(args.timeout, 30),
            )
            ok = _emit_command_result("Celery ping", celery_code, celery_out, celery_err) and ok
        if not ok and args.auto_rollback:
            print("[WARN] Mandatory verification failed; restoring previous release")
            rollback_code, rollback_out, rollback_err = _run(
                ssh,
                build_rollback_command(args.target_dir, args.http_port, args.expect_celery),
                timeout=max(args.timeout, 180),
            )
            rollback_ok, rollback_summary = evaluate_runtime_command_result(
                rollback_code, rollback_out, rollback_err
            )
            print(f"[{'OK' if rollback_ok else 'FAIL'}] Automatic rollback: {rollback_summary}")
    finally:
        ssh.close()

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
