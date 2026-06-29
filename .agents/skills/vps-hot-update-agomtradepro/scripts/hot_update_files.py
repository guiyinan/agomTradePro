#!/usr/bin/env python
"""Hot update selected AgomTradePro files on a VPS.

This script intentionally updates only selected code/static files. It does not
rebuild Docker images, run migrations, or touch the SQLite data volume.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import posixpath
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import paramiko
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit("paramiko is required for VPS hot updates") from exc


@dataclass(frozen=True)
class RemoteConfig:
    host: str
    user: str
    password: str
    port: int
    target_dir: str
    container: str
    project: str
    compose_file: str
    env_file: str
    static_volume: str
    domain: str
    health_path: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help="Repo-relative files to hot update")
    parser.add_argument("--target-dir", default=os.environ.get("AGOM_VPS_TARGET_DIR") or "/opt/agomtradepro")
    parser.add_argument("--container", default="agomtradepro-web-1")
    parser.add_argument("--project", default="agomtradepro")
    parser.add_argument("--compose-file", default="docker/docker-compose.vps.yml")
    parser.add_argument("--env-file", default="deploy/.env")
    parser.add_argument(
        "--static-volume",
        default="/var/lib/docker/volumes/agomtradepro_static_data/_data",
        help="Remote collected static volume root",
    )
    parser.add_argument("--domain", default=os.environ.get("AGOM_VPS_DOMAIN") or "demo.agomtrade.pro")
    parser.add_argument("--health-path", default="/api/health/")
    parser.add_argument("--no-restart-web", action="store_true", help="Do not restart the web service")
    parser.add_argument(
        "--expect-substring",
        action="append",
        default=[],
        metavar="PATH::TEXT",
        help="Assert a marker exists in local and remote copies",
    )
    return parser.parse_args()


def require_config(args: argparse.Namespace) -> RemoteConfig:
    host = os.environ.get("AGOM_VPS_HOST")
    password = os.environ.get("AGOM_VPS_PASS")
    if not host:
        raise SystemExit("AGOM_VPS_HOST is required")
    if not password:
        raise SystemExit("AGOM_VPS_PASS is required")
    return RemoteConfig(
        host=host,
        user=os.environ.get("AGOM_VPS_USER") or "root",
        password=password,
        port=int(os.environ.get("AGOM_VPS_PORT") or 22),
        target_dir=args.target_dir.rstrip("/"),
        container=args.container,
        project=args.project,
        compose_file=args.compose_file,
        env_file=args.env_file,
        static_volume=args.static_volume.rstrip("/"),
        domain=args.domain,
        health_path=args.health_path,
    )


def normalize_repo_file(repo_root: Path, value: str) -> tuple[str, Path]:
    rel = value.replace("\\", "/").strip("/")
    if not rel or rel.startswith("../") or "/../" in rel:
        raise SystemExit(f"unsafe relative file path: {value}")
    path = (repo_root / rel).resolve()
    try:
        path.relative_to(repo_root)
    except ValueError as exc:
        raise SystemExit(f"file is outside repo root: {value}") from exc
    if not path.is_file():
        raise SystemExit(f"file does not exist: {rel}")
    return rel, path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_expectations(values: list[str]) -> dict[str, list[str]]:
    expectations: dict[str, list[str]] = {}
    for value in values:
        if "::" not in value:
            raise SystemExit(f"--expect-substring must use PATH::TEXT: {value}")
        rel, marker = value.split("::", 1)
        rel = rel.replace("\\", "/").strip("/")
        if not rel or not marker:
            raise SystemExit(f"invalid --expect-substring: {value}")
        expectations.setdefault(rel, []).append(marker)
    return expectations


def q(value: str) -> str:
    return shlex.quote(value)


class Remote:
    def __init__(self, config: RemoteConfig) -> None:
        self.config = config
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def __enter__(self) -> "Remote":
        self.client.connect(
            hostname=self.config.host,
            port=self.config.port,
            username=self.config.user,
            password=self.config.password,
            timeout=20,
        )
        return self

    def __exit__(self, *_exc: object) -> None:
        self.client.close()

    def run(self, command: str, timeout: int = 240) -> str:
        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        if code != 0:
            raise RuntimeError(f"remote command failed ({code})\n{command}\nSTDOUT:\n{out}\nSTDERR:\n{err}")
        if err:
            sys.stderr.write(err)
        return out

    def mkdir_p(self, remote_dir: str) -> None:
        self.run(f"mkdir -p {q(remote_dir)}")

    def put(self, local_path: Path, remote_path: str) -> None:
        sftp = self.client.open_sftp()
        try:
            self.mkdir_p(posixpath.dirname(remote_path))
            sftp.put(str(local_path), remote_path)
        finally:
            sftp.close()


def static_volume_path(config: RemoteConfig, rel: str) -> str | None:
    if not rel.startswith("static/"):
        return None
    return posixpath.join(config.static_volume, rel[len("static/") :])


def build_remote_update_command(
    config: RemoteConfig,
    rel_files: list[str],
    expectations: dict[str, list[str]],
    backup_dir: str,
    restart_web: bool,
) -> str:
    current = posixpath.join(config.target_dir, "current")
    lines = [
        "set -eu",
        f"cd {q(current)}",
    ]

    for rel in rel_files:
        lines.append(f"docker cp {q(rel)} {q(config.container + ':/app/' + rel)}")
        static_path = static_volume_path(config, rel)
        if static_path:
            lines.extend(
                [
                    f"mkdir -p {q(posixpath.dirname(static_path))}",
                    f"cp -a {q(rel)} {q(static_path)}",
                ]
            )

    if restart_web:
        lines.append(
            f"docker compose -p {q(config.project)} -f {q(config.compose_file)} --env-file {q(config.env_file)} restart web"
        )
        lines.extend(
            [
                "for i in $(seq 1 30); do",
                f"  if docker exec {q(config.container)} curl -fsS http://127.0.0.1:8000{q(config.health_path)} >/tmp/agom_web_health.out 2>/tmp/agom_web_health.err; then break; fi",
                "  sleep 2",
                "done",
            ]
        )

    lines.append(f"printf 'backup_dir=%s\\n' {q(backup_dir)}")
    for rel in rel_files:
        lines.append(f"printf 'release_sha {rel} '; sha256sum {q(rel)} | awk '{{print $1}}'")
        lines.append(
            f"printf 'container_exists {rel} '; docker exec {q(config.container)} test -f {q('/app/' + rel)} && echo yes"
        )
        static_path = static_volume_path(config, rel)
        if static_path:
            lines.append(f"printf 'static_exists {rel} '; test -f {q(static_path)} && echo yes")

    for rel, markers in expectations.items():
        for marker in markers:
            lines.append(f"grep -Fq {q(marker)} {q(rel)}")
            lines.append(f"docker exec {q(config.container)} grep -Fq {q(marker)} {q('/app/' + rel)}")
            static_path = static_volume_path(config, rel)
            if static_path:
                lines.append(f"grep -Fq {q(marker)} {q(static_path)}")
            lines.append(f"printf 'marker_ok {rel} %s\\n' {q(marker)}")

    lines.extend(
        [
            f"printf 'https_health_status='; curl -fsSk -o /dev/null -w '%{{http_code}}' https://{q(config.domain)}{q(config.health_path)}; printf '\\n'",
            "printf 'containers\\n'",
            f"docker compose -p {q(config.project)} -f {q(config.compose_file)} --env-file {q(config.env_file)} ps --format 'table {{{{.Name}}}}\\t{{{{.Service}}}}\\t{{{{.State}}}}'",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    config = require_config(args)
    repo_root = Path.cwd().resolve()
    files = [normalize_repo_file(repo_root, value) for value in args.files]
    rel_files = [rel for rel, _path in files]
    expectations = parse_expectations(args.expect_substring)

    missing_expectation_files = sorted(set(expectations) - set(rel_files))
    if missing_expectation_files:
        raise SystemExit(f"expectations refer to files not being uploaded: {missing_expectation_files}")

    for rel, markers in expectations.items():
        text = (repo_root / rel).read_text(encoding="utf-8")
        for marker in markers:
            if marker not in text:
                raise SystemExit(f"local marker not found in {rel}: {marker}")

    print("mode=hot-update code-only")
    print(f"host={config.host}")
    print(f"target_dir={config.target_dir}")
    for rel, path in files:
        print(f"local_sha {rel} {file_sha256(path)}")

    timestamp = time.strftime("%Y%m%d%H%M%S")
    backup_dir = f"{config.target_dir}/manual-file-backups/{timestamp}"
    current = posixpath.join(config.target_dir, "current")

    with Remote(config) as remote:
        remote.run(f"test -d {q(current)}")
        backup_lines = ["set -eu", f"cd {q(current)}", f"mkdir -p {q(backup_dir)}"]
        for rel, _path in files:
            backup_lines.extend(
                [
                    f"mkdir -p {q(posixpath.join(backup_dir, posixpath.dirname(rel)))}",
                    f"cp -a {q(rel)} {q(posixpath.join(backup_dir, rel))}",
                ]
            )
        remote.run("\n".join(backup_lines))
        for rel, path in files:
            remote.put(path, posixpath.join(current, rel))
        command = build_remote_update_command(
            config=config,
            rel_files=rel_files,
            expectations=expectations,
            backup_dir=backup_dir,
            restart_web=not args.no_restart_web,
        )
        print(remote.run(command, timeout=360))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
