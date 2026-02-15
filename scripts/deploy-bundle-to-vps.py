#!/usr/bin/env python3
"""
Upload a bundle tar.gz to a VPS over SSH and run the in-bundle deploy script.

Design goals:
- Interactive by default (prompt for missing values).
- Non-destructive defaults (does not print passwords).
- Works from Windows/macOS/Linux as long as Python + paramiko are available.
"""

from __future__ import annotations

import argparse
import getpass
import os
import posixpath
import shlex
import sys
import time
from pathlib import Path


def _die(msg: str, code: int = 1) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    raise SystemExit(code)


def _info(msg: str) -> None:
    print(f"[INFO] {msg}")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def _latest_bundle(dist_dir: Path) -> Path | None:
    bundles = sorted(dist_dir.glob("agomsaaf-vps-bundle-*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    return bundles[0] if bundles else None


def _ssh_connect(host: str, port: int, username: str, password: str, timeout: int):
    try:
        import paramiko  # type: ignore
    except Exception as e:
        _die(f"paramiko not available (pip install paramiko). Import error: {e}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Avoid agent/key surprises. This is a password-first deploy script.
    try:
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
    except paramiko.ssh_exception.AuthenticationException:
        # Probe allowed auth methods; some servers use keyboard-interactive (PAM) even for passwords.
        import socket

        sock = socket.create_connection((host, port), timeout=timeout)
        transport = paramiko.Transport(sock)
        transport.banner_timeout = timeout
        transport.auth_timeout = timeout
        transport.start_client(timeout=timeout)
        allowed: str = ""
        try:
            # Paramiko 4 removed Transport.get_allowed_auths; use auth_none to discover allowed types.
            transport.auth_none(username)
        except paramiko.ssh_exception.BadAuthenticationType as e:
            allowed = ",".join(getattr(e, "allowed_types", []) or [])
        except Exception:
            allowed = ""

        # Try keyboard-interactive as a fallback using the same password.
        if "keyboard-interactive" in allowed.split(","):
            def handler(title, instructions, prompts):
                answers = []
                for prompt, _echo in prompts:
                    # Most PAM prompts are "Password:"; respond with the provided password.
                    if "password" in prompt.lower():
                        answers.append(password)
                    else:
                        answers.append("")
                return answers

            transport.auth_interactive(username, handler)

            if transport.is_authenticated():
                ki_client = paramiko.SSHClient()
                ki_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                # Reuse the authenticated transport.
                ki_client._transport = transport  # type: ignore[attr-defined]
                return ki_client

        # Nothing worked; include allowed methods for debugging (no secrets).
        msg = f"Authentication failed for {username}@{host}:{port}."
        if allowed:
            msg += f" Allowed auths: {allowed}"
        raise paramiko.ssh_exception.AuthenticationException(msg)


def _run(ssh, cmd: str, timeout: int) -> tuple[int, str, str]:
    stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=False, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), out, err


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload and deploy an AgomSAAF VPS bundle.")
    ap.add_argument("--host", default=os.environ.get("AGOM_VPS_HOST", "").strip() or None)
    ap.add_argument("--port", type=int, default=int(os.environ.get("AGOM_VPS_PORT", "22")))
    ap.add_argument("--user", default=os.environ.get("AGOM_VPS_USER", "").strip() or None)
    ap.add_argument("--bundle", default=os.environ.get("AGOM_VPS_BUNDLE", "").strip() or None)
    ap.add_argument("--password-file", default=os.environ.get("AGOM_VPS_PASS_FILE", "").strip() or None)
    ap.add_argument("--remote-dir", default=os.environ.get("AGOM_VPS_REMOTE_DIR", "/tmp/agomsaaf-upload"))
    ap.add_argument("--action", choices=["fresh", "upgrade", "restore-only"], default=os.environ.get("AGOM_VPS_ACTION", "fresh"))
    ap.add_argument("--target-dir", default=os.environ.get("AGOM_VPS_TARGET_DIR", "/opt/agomsaaf"))
    ap.add_argument("--timeout", type=int, default=int(os.environ.get("AGOM_VPS_TIMEOUT", "60")))
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    dist_dir = project_root / "dist"

    host = args.host or input("VPS host/IP: ").strip()
    if not host:
        _die("Missing --host")

    user = args.user or input("SSH username [root]: ").strip() or "root"

    bundle_path: Path
    if args.bundle:
        bundle_path = Path(args.bundle).expanduser().resolve()
    else:
        latest = _latest_bundle(dist_dir)
        if not latest:
            _die(f"No bundle found in {dist_dir}")
        default = str(latest)
        raw = input(f"Bundle tar.gz path [{default}]: ").strip()
        bundle_path = Path(raw or default).expanduser().resolve()

    if not bundle_path.exists():
        _die(f"Bundle not found: {bundle_path}")

    password = (os.environ.get("AGOM_VPS_PASS") or "").strip()
    if not password and args.password_file:
        try:
            password = Path(args.password_file).expanduser().read_text(encoding="utf-8").strip()
        except Exception as e:
            _die(f"Failed to read --password-file: {args.password_file}. Error: {e}")
    if not password:
        password = getpass.getpass("SSH password: ")
    if not password:
        _die("Empty password")

    remote_dir = args.remote_dir.rstrip("/")
    remote_bundle = posixpath.join(remote_dir, bundle_path.name)
    remote_deploy = posixpath.join(remote_dir, "deploy-on-vps.fixed.sh")

    _info(f"Connecting to {user}@{host}:{args.port}")
    ssh = _ssh_connect(host=host, port=args.port, username=user, password=password, timeout=args.timeout)
    try:
        _info(f"Ensuring remote dir: {remote_dir}")
        code, out, err = _run(ssh, f"mkdir -p {remote_dir}", timeout=args.timeout)
        if code != 0:
            _die(f"Failed to create remote dir. Exit={code}. Stderr={err.strip()}")

        # Cleanup leftovers from previous interrupted uploads.
        _run(ssh, f"rm -f {remote_bundle}.uploading.* 2>/dev/null || true", timeout=args.timeout)

        local_size = bundle_path.stat().st_size
        code, out, err = _run(ssh, f"stat -c %s {remote_bundle} 2>/dev/null || true", timeout=args.timeout)
        remote_size = int(out.strip()) if out.strip().isdigit() else -1
        if remote_size == local_size:
            _info(f"Remote bundle already present with matching size ({local_size} bytes), skipping upload")
        else:
            _info(f"Uploading bundle to: {remote_bundle}")
            sftp = ssh.open_sftp()
            try:
                # Upload with a temp name, then rename into place.
                tmp_remote = remote_bundle + f".uploading.{int(time.time())}"
                sftp.put(str(bundle_path), tmp_remote)
                # Some SFTP servers don't allow overwrite via rename.
                try:
                    sftp.remove(remote_bundle)
                except OSError:
                    pass
                sftp.rename(tmp_remote, remote_bundle)
            finally:
                sftp.close()

        # Upload a known-good deploy script (handles CRLF manifest parsing, port auto-fallback, etc.)
        deploy_local = project_root / "scripts" / "deploy-on-vps.sh"
        _info(f"Uploading deploy helper: {remote_deploy}")
        sftp = ssh.open_sftp()
        try:
            sftp.put(str(deploy_local), remote_deploy)
        finally:
            sftp.close()

        _info("Bootstrapping deploy script from bundle (non-interactive)")
        ts = int(time.time())
        bootstrap_dir = f"/tmp/agomsaaf-bootstrap-{ts}"

        # Use non-interactive defaults inside deploy-on-vps.sh:
        # - DOMAIN stays empty => HTTP only (Caddy internal :80, host port comes from deploy/.env)
        # - SECRET_KEY autogenerated
        # - ALLOWED_HOSTS auto includes public IP (api.ipify.org) + localhost
        cmd = (
            "set -eu; "
            f"rm -rf {bootstrap_dir}; mkdir -p {bootstrap_dir}; "
            f"tar -xzf {remote_bundle} -C {bootstrap_dir}; "
            f"rel=$(ls -d {bootstrap_dir}/agomsaaf-vps-bundle-* | head -n 1); "
            "cd \"$rel\"; "
            # Windows-produced bundles may contain CRLF scripts which break /bin/sh parsing on Linux.
            "if command -v sed >/dev/null 2>&1; then "
            "  find scripts -maxdepth 1 -type f -name '*.sh' -print0 | xargs -0 sed -i 's/\\r$//'; "
            "  find docker -maxdepth 1 -type f -name '*.sh' -print0 | xargs -0 sed -i 's/\\r$//'; "
            "  [ -f deploy/manifest.json ] && sed -i 's/\\r$//' deploy/manifest.json; "
            "  find deploy -maxdepth 1 -type f -name '.env*' -print0 2>/dev/null | xargs -0 sed -i 's/\\r$//' || true; "
            f"  sed -i 's/\\r$//' {remote_deploy} || true; "
            "fi; "
            f"sh {remote_deploy} --bundle {remote_bundle} --target-dir {args.target_dir} --action {args.action}"
        )
        code, out, err = _run(ssh, f"bash -lc {shlex.quote(cmd)}", timeout=max(args.timeout, 300))
        if code != 0:
            _warn(out.strip())
            _die(f"Remote deploy failed. Exit={code}. Stderr={err.strip()}")

        _info("Remote deploy completed")
        if out.strip():
            print(out.strip())
        if err.strip():
            print(err.strip(), file=sys.stderr)

        _info("Checking health endpoint")
        # Host ports are controlled by deploy/.env on VPS (CADDY_HTTP_PORT). Default is 8000.
        http_port = "8000"
        code, out, err = _run(
            ssh,
            f"grep '^CADDY_HTTP_PORT=' {shlex.quote(args.target_dir)}/current/deploy/.env 2>/dev/null | tail -n 1 | cut -d '=' -f2- || true",
            timeout=args.timeout,
        )
        if out.strip().isdigit():
            http_port = out.strip()
        code, out, err = _run(ssh, f"curl -fsS --max-time 5 http://127.0.0.1:{http_port}/health/ || true", timeout=args.timeout)
        if out.strip():
            _info(f"Health: {out.strip()}")
        else:
            _warn("Health check returned empty response (maybe port differs, or curl missing).")

        return 0
    finally:
        ssh.close()


if __name__ == "__main__":
    raise SystemExit(main())
