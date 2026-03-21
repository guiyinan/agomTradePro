#!/usr/bin/env python3
"""
Fetch critical secrets from a VPS deployment env file and back them up locally.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shlex
import sys
import time
from pathlib import Path


def _info(msg: str) -> None:
    print(f"[INFO] {msg}")


def _die(msg: str, code: int = 1) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    raise SystemExit(code)


def _prompt(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    value = input(f"{prompt}{suffix}: ").strip()
    if not value and default is not None:
        return default
    return value


def _ssh_connect(host: str, port: int, username: str, password: str, timeout: int):
    try:
        import paramiko  # type: ignore
    except Exception as exc:
        _die(f"paramiko not available (pip install paramiko). Import error: {exc}")

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


def _run(ssh, cmd: str, timeout: int) -> tuple[int, str, str]:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), out, err


def main() -> int:
    ap = argparse.ArgumentParser(description="Backup critical VPS secrets to a local ignored file.")
    ap.add_argument("--host", default=os.environ.get("AGOM_VPS_HOST", "").strip() or None)
    ap.add_argument("--port", type=int, default=int(os.environ.get("AGOM_VPS_PORT", "22")))
    ap.add_argument("--user", default=os.environ.get("AGOM_VPS_USER", "").strip() or None)
    ap.add_argument("--password-file", default=os.environ.get("AGOM_VPS_PASS_FILE", "").strip() or None)
    ap.add_argument("--remote-env", default=os.environ.get("AGOM_VPS_REMOTE_ENV", "/opt/agomtradepro/current/deploy/.env"))
    ap.add_argument("--output-dir", default=os.environ.get("AGOM_VPS_SECRET_BACKUP_DIR", "backups/vps-secrets"))
    ap.add_argument("--timeout", type=int, default=int(os.environ.get("AGOM_VPS_TIMEOUT", "60")))
    args = ap.parse_args()

    host = args.host or _prompt("VPS host/IP")
    if not host:
        _die("Missing VPS host")

    user = args.user or _prompt("SSH username", "root")
    password = (os.environ.get("AGOM_VPS_PASS") or "").strip()
    if not password and args.password_file:
        password = Path(args.password_file).expanduser().read_text(encoding="utf-8").strip()
    if not password:
        password = getpass.getpass("SSH password: ")
    if not password:
        _die("Empty password")

    ssh = _ssh_connect(host=host, port=args.port, username=user, password=password, timeout=args.timeout)
    try:
        remote_cmd = (
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            f"p = Path({args.remote_env!r})\n"
            "if not p.exists():\n"
            "    raise SystemExit('REMOTE_ENV_MISSING')\n"
            "wanted = {'SECRET_KEY', 'AGOMTRADEPRO_ENCRYPTION_KEY'}\n"
            "for line in p.read_text(encoding='utf-8').splitlines():\n"
            "    if '=' not in line or line.lstrip().startswith('#'):\n"
            "        continue\n"
            "    key, value = line.split('=', 1)\n"
            "    if key in wanted:\n"
            "        print(f'{key}={value}')\n"
            "PY"
        )
        code, out, err = _run(ssh, "bash -lc " + shlex.quote(remote_cmd), timeout=args.timeout)
        if code != 0:
            _die(f"Failed to read remote env. Stderr={err.strip() or out.strip()}")

        values: dict[str, str] = {}
        for line in out.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()

        if "SECRET_KEY" not in values or "AGOMTRADEPRO_ENCRYPTION_KEY" not in values:
            _die("Remote env did not return both SECRET_KEY and AGOMTRADEPRO_ENCRYPTION_KEY")

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d%H%M%S")
        safe_host = host.replace(":", "_")
        output_path = output_dir / f"{safe_host}-{timestamp}.env"
        content = [
            f"# Backup from {host}:{args.port}",
            f"# Remote env: {args.remote_env}",
            f"# Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"SECRET_KEY={values['SECRET_KEY']}",
            f"AGOMTRADEPRO_ENCRYPTION_KEY={values['AGOMTRADEPRO_ENCRYPTION_KEY']}",
            "",
        ]
        output_path.write_text("\n".join(content), encoding="utf-8")
        _info(f"Secrets backup written: {output_path}")
        return 0
    finally:
        ssh.close()


if __name__ == "__main__":
    raise SystemExit(main())
