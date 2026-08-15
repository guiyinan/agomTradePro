#!/usr/bin/env python3
"""Create, validate, and download an AgomTradePro VPS PostgreSQL backup."""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import sys
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

MARKER_PREFIX = "AGOM_BACKUP_"


def _info(message: str) -> None:
    print(f"[INFO] {message}")


def _error(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)


def _connect_ssh(
    host: str,
    port: int,
    user: str,
    password: str,
    timeout: int,
) -> Any:
    """Open an SSH connection without persisting credentials."""
    try:
        import paramiko  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "paramiko is required; install it with: python -m pip install paramiko"
        ) from exc

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=user,
        password=password,
        look_for_keys=False,
        allow_agent=False,
        timeout=timeout,
        banner_timeout=timeout,
        auth_timeout=timeout,
    )
    return client


def _run_remote(ssh: Any, command: str, timeout: int) -> tuple[int, str, str]:
    """Run one remote command and collect its exit status and output."""
    _stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), output, error


def _parse_markers(output: str) -> dict[str, str]:
    """Parse machine-readable backup markers from remote output."""
    markers: dict[str, str] = {}
    for line in output.splitlines():
        if not line.startswith(MARKER_PREFIX) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        markers[key.removeprefix(MARKER_PREFIX)] = value.strip()
    return markers


def _sha256_file(path: Path) -> str:
    """Return a lowercase SHA-256 digest for a local file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validated_archive_name(remote_path: str) -> str:
    """Return a safe archive basename or reject unexpected remote output."""
    name = PurePosixPath(remote_path).name
    if not name.startswith("postgres-") or not name.endswith(".dump"):
        raise ValueError(f"Unexpected remote backup filename: {name}")
    return name


def _remote_backup_script(
    remote_backup_dir: str,
    download_latest: bool,
    prune_older_than_days: int,
) -> str:
    """Build the guarded remote backup and validation script."""
    backup_dir = shlex.quote(remote_backup_dir)
    mode = "latest" if download_latest else "create"
    return f"""set -euo pipefail
umask 077
backup_root={backup_dir}
database_dir="$backup_root/database"
mkdir -p "$database_dir"
chmod 700 "$backup_root" "$database_dir"

postgres_cid=$(docker ps \\
  --filter label=com.docker.compose.project=agomtradepro \\
  --filter label=com.docker.compose.service=postgres \\
  --format '{{{{.ID}}}}' | head -n 1)
[ -n "$postgres_cid" ] || {{ echo 'PostgreSQL container is not running' >&2; exit 31; }}

mode={mode}
if [ "$mode" = "create" ]; then
  timestamp=$(date -u +%Y%m%dT%H%M%SZ)
  archive="$database_dir/postgres-$timestamp.dump"
  temporary="$database_dir/.postgres-$timestamp.dump.partial"
  trap 'rm -f "$temporary"' EXIT
  docker exec "$postgres_cid" sh -lc \
    'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=6 --no-owner --no-acl' \
    > "$temporary"
  [ -s "$temporary" ] || {{ echo 'PostgreSQL backup is empty' >&2; exit 32; }}
  docker exec -i "$postgres_cid" sh -lc 'exec pg_restore --list' \
    < "$temporary" > /dev/null
  mv "$temporary" "$archive"
  chmod 600 "$archive"
  trap - EXIT
else
  archive=$(find "$database_dir" -maxdepth 1 -type f -name 'postgres-*.dump' \
    -printf '%T@ %p\n' | sort -rn | head -n 1 | cut -d ' ' -f 2-)
  [ -n "$archive" ] || {{ echo 'No PostgreSQL backup was found' >&2; exit 33; }}
  docker exec -i "$postgres_cid" sh -lc 'exec pg_restore --list' \
    < "$archive" > /dev/null
fi

if [ {prune_older_than_days} -gt 0 ]; then
  find "$database_dir" -maxdepth 1 -type f -name 'postgres-*.dump' \
    -mtime +{prune_older_than_days} ! -path "$archive" -delete
fi

checksum=$(sha256sum "$archive" | awk '{{print $1}}')
size=$(stat -c '%s' "$archive")
printf 'AGOM_BACKUP_PATH=%s\n' "$archive"
printf 'AGOM_BACKUP_SHA256=%s\n' "$checksum"
printf 'AGOM_BACKUP_SIZE=%s\n' "$size"
"""


def _download_verified(
    ssh: Any,
    remote_path: str,
    expected_hash: str,
    expected_size: int,
    output_dir: Path,
    *,
    max_attempts: int = 5,
    reconnect: Callable[[], Any] | None = None,
) -> Path:
    """Download an archive atomically, resuming bounded SFTP retries."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    archive_name = _validated_archive_name(remote_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / archive_name
    partial = destination.with_name(f".{destination.name}.partial")
    partial.unlink(missing_ok=True)

    last_percent = -10

    def progress(transferred: int, total: int) -> None:
        nonlocal last_percent
        if total <= 0:
            return
        percent = int(transferred * 100 / total)
        if percent >= last_percent + 10 or percent == 100:
            print(f"[INFO] Download progress: {percent}%")
            last_percent = percent

    active_ssh = ssh
    transferred = 0
    for attempt in range(1, max_attempts + 1):
        sftp: Any | None = None
        try:
            transferred = partial.stat().st_size if partial.exists() else 0
            if transferred > expected_size:
                partial.unlink(missing_ok=True)
                transferred = 0
            sftp = active_ssh.open_sftp()
            sftp.get_channel().settimeout(60)
            with sftp.open(remote_path, "rb") as remote_handle:
                remote_handle.seek(transferred)
                # Paramiko's default one-request-at-a-time reads are very
                # slow on high-latency VPS links. Prefetch only the first
                # stream; resumed streams use an explicit offset so the
                # partial file remains the source of truth.
                if transferred == 0:
                    try:
                        remote_handle.prefetch(
                            file_size=expected_size,
                            max_concurrent_requests=64,
                        )
                    except (AttributeError, OSError):
                        pass
                with partial.open("ab") as local_handle:
                    while transferred < expected_size:
                        block = remote_handle.read(min(1024 * 1024, expected_size - transferred))
                        if not block:
                            raise RuntimeError("SFTP stream ended before the expected archive size")
                        remaining = expected_size - transferred
                        if len(block) > remaining:
                            raise RuntimeError("SFTP stream exceeded the expected archive size")
                        local_handle.write(block)
                        transferred += len(block)
                        progress(transferred, expected_size)
            break
        except Exception as exc:
            if attempt >= max_attempts:
                partial.unlink(missing_ok=True)
                raise RuntimeError(f"SFTP download failed after {attempt} attempts: {exc}") from exc
            transferred = partial.stat().st_size if partial.exists() else 0
            _info(
                "SFTP download interrupted; "
                f"retrying ({attempt + 1}/{max_attempts}) from {transferred} bytes"
            )
            if reconnect is not None:
                try:
                    active_ssh = reconnect()
                except Exception as reconnect_error:
                    _info(
                        f"SFTP reconnect failed; retrying the current connection: {reconnect_error}"
                    )
        finally:
            if sftp is not None:
                sftp.close()

    try:
        actual_size = partial.stat().st_size
        if actual_size != expected_size:
            raise RuntimeError(
                f"Downloaded size mismatch: expected {expected_size}, got {actual_size}"
            )
        actual_hash = _sha256_file(partial)
        if actual_hash.lower() != expected_hash.lower():
            raise RuntimeError(f"SHA-256 mismatch: expected {expected_hash}, got {actual_hash}")
        partial.replace(destination)
        checksum_file = destination.with_suffix(destination.suffix + ".sha256")
        checksum_file.write_text(f"{actual_hash}  {destination.name}\n", encoding="ascii")
        return destination
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Create a verified PostgreSQL custom-format backup on the "
            "AgomTradePro VPS and download it locally."
        )
    )
    parser.add_argument("--host", default=os.environ.get("AGOM_VPS_HOST", ""))
    parser.add_argument("--user", default=os.environ.get("AGOM_VPS_USER", "root"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("AGOM_VPS_PORT", "22")))
    parser.add_argument("--output-dir", default="backups/vps-postgres")
    parser.add_argument("--remote-backup-dir", default="/opt/agomtradepro/backups")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--download-latest", action="store_true")
    parser.add_argument("--prune-remote-older-than-days", type=int, default=0)
    return parser


def main() -> int:
    """Run the backup, remote validation, download, and checksum verification."""
    args = _build_parser().parse_args()
    host = str(args.host).strip()
    user = str(args.user).strip() or "root"
    password = os.environ.get("AGOM_VPS_PASS", "")

    if not host:
        _error("AGOM_VPS_HOST is required")
        return 2
    if not password:
        _error("AGOM_VPS_PASS is required")
        return 2
    if args.prune_remote_older_than_days < 0:
        _error("--prune-remote-older-than-days cannot be negative")
        return 2
    if not str(args.remote_backup_dir).startswith("/"):
        _error("--remote-backup-dir must be an absolute path")
        return 2

    action = "Downloading latest verified backup" if args.download_latest else "Creating backup"
    _info(f"{action} on {user}@{host}:{args.port}")
    ssh = None
    try:
        ssh = _connect_ssh(
            host=host,
            port=args.port,
            user=user,
            password=password,
            timeout=args.timeout,
        )
        script = _remote_backup_script(
            remote_backup_dir=args.remote_backup_dir,
            download_latest=args.download_latest,
            prune_older_than_days=args.prune_remote_older_than_days,
        )
        command = "bash -lc " + shlex.quote(script)
        code, output, error = _run_remote(ssh, command, timeout=args.timeout)
        if code != 0:
            detail = error.strip() or output.strip() or f"exit code {code}"
            raise RuntimeError(f"Remote backup failed: {detail}")

        markers = _parse_markers(output)
        required = {"PATH", "SHA256", "SIZE"}
        missing = sorted(required.difference(markers))
        if missing:
            raise RuntimeError(f"Remote backup omitted markers: {', '.join(missing)}")

        remote_path = markers["PATH"]
        expected_hash = markers["SHA256"].lower()
        if len(expected_hash) != 64 or any(
            char not in "0123456789abcdef" for char in expected_hash
        ):
            raise RuntimeError("Remote backup returned an invalid SHA-256")
        expected_size = int(markers["SIZE"])
        if expected_size <= 0:
            raise RuntimeError("Remote backup returned an invalid size")

        _info(f"Remote archive validated: {remote_path} ({expected_size} bytes)")

        def reconnect() -> Any:
            nonlocal ssh
            if ssh is not None:
                ssh.close()
            ssh = _connect_ssh(
                host=host,
                port=args.port,
                user=user,
                password=password,
                timeout=args.timeout,
            )
            return ssh

        destination = _download_verified(
            ssh=ssh,
            remote_path=remote_path,
            expected_hash=expected_hash,
            expected_size=expected_size,
            output_dir=Path(args.output_dir).expanduser().resolve(),
            reconnect=reconnect,
        )
        _info(f"Local archive: {destination}")
        _info(f"SHA-256: {expected_hash}")
        _info("Backup and download completed successfully")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        _error(str(exc))
        return 1
    finally:
        if ssh is not None:
            ssh.close()


if __name__ == "__main__":
    raise SystemExit(main())
