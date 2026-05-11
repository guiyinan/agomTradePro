#!/usr/bin/env python3
"""
Post-deploy verification helper for deploy-vps.ps1.

The health probe must validate the remote HTTP status instead of assuming
the endpoint always returns a non-empty body.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

HTTP_CODE_MARKER = "__AGOM_HTTP_CODE__="


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
        raise SystemExit(0)

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
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), out, err


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
        insecure_tls=(scheme == "https"),
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
        "cat \"$tmp_body\" && "
        "rm -f \"$tmp_body\""
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify AgomTradePro VPS deployment.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password-file", required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--http-port", type=int, default=8000)
    parser.add_argument("--target-dir", default="/opt/agomtradepro")
    parser.add_argument("--health-path", default="/api/health/")
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

        containers_code, containers_out, containers_err = _run(
            ssh,
            'docker ps --format "table {{.Names}}\\t{{.Status}}"',
            timeout=args.timeout,
        )
        ok = _emit_command_result(
            "Containers", containers_code, containers_out, containers_err
        ) and ok
    finally:
        ssh.close()

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
