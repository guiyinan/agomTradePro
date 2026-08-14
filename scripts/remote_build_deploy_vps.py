#!/usr/bin/env python3
"""
Upload a source bundle to a VPS, build the Docker image on the VPS, deploy it
in-place, optionally restore local SQLite, download a deployment report, and
clean up remote temporary files.
"""

from __future__ import annotations

import argparse
import getpass
import io
import ipaddress
import json
import os
import posixpath
import re
import secrets
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NoReturn


def _info(msg: str) -> None:
    print(f"[INFO] {msg}")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def _die(msg: str, code: int = 1) -> NoReturn:
    print(f"[ERROR] {msg}", file=sys.stderr)
    raise SystemExit(code)


def _prompt(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    value = input(f"{prompt}{suffix}: ").strip()
    if not value and default is not None:
        return default
    return value


def _prompt_bool(prompt: str, default: bool) -> bool:
    default_text = "Y/n" if default else "y/N"
    raw = input(f"{prompt} ({default_text}): ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes", "1", "true"}


def _optional_env_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        _die(f"{name} must be an integer, got {raw!r}. Error: {exc}")


def _normalize_domain(value: str) -> str:
    """Return a canonical DNS hostname and reject unsafe Caddy site addresses."""

    candidate = value.strip().rstrip(".")
    if not candidate:
        return ""
    if "://" in candidate or any(separator in candidate for separator in ("/", "\\", ":")):
        raise ValueError("DOMAIN must be a DNS hostname without a scheme, path, or port")
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        pass
    else:
        raise ValueError("DOMAIN must be a DNS hostname, not a bare IP address")

    try:
        ascii_domain = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("DOMAIN is not a valid DNS hostname") from exc
    if len(ascii_domain) > 253:
        raise ValueError("DOMAIN exceeds the 253-character DNS limit")
    labels = ascii_domain.split(".")
    if len(labels) < 2 or any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or re.fullmatch(r"[a-z0-9-]+", label) is None
        for label in labels
    ):
        raise ValueError("DOMAIN must be a valid fully qualified DNS hostname")
    return ascii_domain


def _normalize_source_commit(value: str) -> str:
    """Return an exact Git SHA-1 identity or reject the deployment source."""

    candidate = value.strip()
    if re.fullmatch(r"[0-9a-f]{40}", candidate) is None:
        raise ValueError("SOURCE_COMMIT must be an exact lowercase 40-hex Git commit")
    return candidate


def _latest_sqlite(project_root: Path) -> Path:
    db = project_root / "db.sqlite3"
    if not db.exists():
        _die(f"SQLite file not found: {db}")
    return db


def _read_env_value(path: Path, name: str) -> str:
    """Read one value from a simple KEY=VALUE environment file."""

    if not path.exists():
        return ""
    prefix = f"{name}="
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if line.startswith(prefix):
            return line[len(prefix) :].strip().strip("\"'")
    return ""


def _resolve_sqlite_encryption_key(project_root: Path, explicit_key: str) -> str:
    """Resolve the source key that must accompany a restored SQLite database."""

    candidates = (
        explicit_key,
        os.environ.get("AGOMTRADEPRO_ENCRYPTION_KEY", ""),
        _read_env_value(project_root / ".env", "AGOMTRADEPRO_ENCRYPTION_KEY"),
    )
    key = next((str(value).strip() for value in candidates if str(value).strip()), "")
    if not key:
        _die(
            "--include-sqlite requires the source AGOMTRADEPRO_ENCRYPTION_KEY; "
            "set it in the environment or project .env before restoring the database"
        )
    return key


def _ssh_connect(
    host: str,
    port: int,
    username: str,
    password: str,
    timeout: int,
) -> Any:
    try:
        import paramiko  # type: ignore
    except Exception as exc:
        _die(f"paramiko not available (pip install paramiko). Import error: {exc}")

    connection_timeout = min(timeout, 30)
    last_error: Exception | None = None
    for attempt in range(1, 5):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                look_for_keys=False,
                allow_agent=False,
                timeout=connection_timeout,
                banner_timeout=connection_timeout,
                auth_timeout=connection_timeout,
            )
            return client
        except (EOFError, OSError, paramiko.SSHException) as exc:
            client.close()
            last_error = exc
            if attempt < 4:
                delay = attempt * 2
                _warn(
                    f"SSH connection attempt {attempt}/4 failed "
                    f"({type(exc).__name__}); retrying in {delay}s"
                )
                time.sleep(delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError("SSH connection failed without an exception")


def _run(ssh: Any, cmd: str, timeout: int) -> tuple[int, str, str]:
    _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
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


def _validate_ssh_credentials(
    host: str, port: int, username: str, password: str, timeout: int
) -> None:
    ssh = _ssh_connect(host=host, port=port, username=username, password=password, timeout=timeout)
    try:
        code, _out, err = _run(ssh, "true", timeout=timeout)
        if code != 0:
            _die(f"SSH login succeeded but remote shell check failed. Stderr={err.strip()}")
    finally:
        ssh.close()


def _check_remote_dependencies(
    host: str, port: int, username: str, password: str, timeout: int
) -> None:
    """Check that all required tools are installed on the remote server."""
    required_tools = [
        ("docker", "docker --version"),
        (
            "docker compose",
            "docker compose version 2>/dev/null || docker-compose --version 2>/dev/null",
        ),
        ("tar", "tar --version"),
        ("python3", "python3 --version"),
        ("curl", "curl --version"),
        ("sed", "sed --version"),
    ]

    ssh = _ssh_connect(host=host, port=port, username=username, password=password, timeout=timeout)
    try:
        _info("Checking remote server dependencies...")
        missing: list[str] = []

        for name, cmd in required_tools:
            code, out, err = _run(
                ssh,
                f"command -v {name.split()[0]} >/dev/null 2>&1 && {cmd} || echo MISSING",
                timeout=timeout,
            )
            result = out.strip()
            if "MISSING" in result or code != 0:
                missing.append(name)
                _warn(f"Missing: {name}")
            else:
                # Extract version info (first line)
                version_info = result.split("\n")[0][:60]
                _info(f"Found: {name} - {version_info}")

        if missing:
            install_hint = """
Missing required tools on remote server. Install with:

  # Ubuntu/Debian
  apt update && apt install -y docker.io docker-compose python3 curl sed tar
  # Or use Docker's official install script:
  curl -fsSL https://get.docker.com | sh

  # CentOS/RHEL
  yum install -y docker docker-compose python3 curl sed tar
"""
            _die(f"Remote server missing required tools: {', '.join(missing)}{install_hint}")
    finally:
        ssh.close()


def _bool_env(value: bool) -> str:
    return "1" if value else "0"


def _make_source_bundle(
    project_root: Path,
    output_path: Path,
    include_sqlite: bool,
    sqlite_file: Path | None,
    include_wheelhouse: bool,
) -> None:
    top_name = output_path.stem.replace(".tar", "")
    excludes = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".claude",
        "node_modules",
        "dist",
        "htmlcov",
        "reports",
        "screenshots",
        "output",
        "media",
        "staticfiles",
        "venv",
        "env",
        "ENV",
        "agomtradepro",
    }
    skip_suffixes = {
        ".pyc",
        ".pyo",
        ".tmp",
        ".temp",
        ".tar.gz",
        ".sqlite3-journal",
        ".sqlite3-shm",
        ".sqlite3-wal",
    }
    wheelhouse_root = project_root / ".cache" / "pip-wheels" / "linux-py311"

    with tarfile.open(output_path, "w:gz") as tar:
        for path in _source_bundle_paths(
            project_root,
            wheelhouse_root=wheelhouse_root,
            include_wheelhouse=include_wheelhouse,
        ):
            rel = path.relative_to(project_root)
            parts = rel.parts
            if not parts:
                continue
            if parts[0] == ".cache":
                try:
                    path.relative_to(wheelhouse_root)
                except ValueError:
                    continue
                if not include_wheelhouse and path.name != ".keep":
                    continue
            if parts[0] in excludes:
                continue
            if any(part == "__pycache__" for part in parts):
                continue
            if path.name in {
                "db.sqlite3",
                "celerybeat-schedule",
                "celerybeat-schedule-shm",
                "celerybeat-schedule-wal",
            }:
                continue
            if path.is_file() and any(path.name.endswith(sfx) for sfx in skip_suffixes):
                continue

            arcname = posixpath.join(top_name, rel.as_posix())
            try:
                tar.add(path, arcname=arcname, recursive=False)
            except FileNotFoundError:
                continue

        if include_sqlite and sqlite_file is not None:
            db_arcname = posixpath.join(top_name, "backups", "db.sqlite3")
            tar.add(sqlite_file, arcname=db_arcname, recursive=False)


def _source_bundle_paths(
    project_root: Path,
    *,
    wheelhouse_root: Path,
    include_wheelhouse: bool,
) -> Iterable[Path]:
    """Yield tracked and relevant untracked paths without local runtime data."""

    try:
        raw_paths = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=project_root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        yield from project_root.rglob("*")
        return

    relative_paths = {
        Path(os.fsdecode(raw_path)) for raw_path in raw_paths.split(b"\0") if raw_path
    }
    if include_wheelhouse and wheelhouse_root.is_dir():
        relative_paths.update(
            path.relative_to(project_root)
            for path in wheelhouse_root.rglob("*")
            if path.is_file() or path.is_symlink()
        )
    for relative_path in sorted(relative_paths, key=lambda path: path.as_posix()):
        path = project_root / relative_path
        if path.is_file() or path.is_symlink():
            yield path


def _upload_sqlite_to_git_clone_release(
    *,
    ssh: Any,
    sqlite_file: Path,
    target_dir: str,
    release_tag: str,
    timeout: int,
) -> None:
    """Upload local SQLite into the git-cloned release backup slot."""

    release_dir = posixpath.join(target_dir.rstrip("/"), "releases", f"source-{release_tag}")
    remote_backups_dir = posixpath.join(release_dir, "backups")
    remote_db = posixpath.join(remote_backups_dir, "db.sqlite3")
    code, _out, err = _run(
        ssh,
        f"mkdir -p {shlex.quote(remote_backups_dir)}",
        timeout=timeout,
    )
    if code != 0:
        _die(f"Failed to create remote sqlite backup dir. Stderr={err.strip()}")

    tmp_remote = remote_db + f".uploading.{int(time.time())}"
    _info(f"Uploading local SQLite for git-clone deploy: {remote_db}")
    sftp = ssh.open_sftp()
    try:
        sftp.put(str(sqlite_file), tmp_remote)
        try:
            sftp.remove(remote_db)
        except OSError:
            pass
        sftp.rename(tmp_remote, remote_db)
    finally:
        sftp.close()

    validate_cmd = (
        f"REMOTE_DB={shlex.quote(remote_db)} python3 - <<'PY'\n"
        "import os\n"
        "import sqlite3\n"
        "path = os.environ['REMOTE_DB']\n"
        "conn = sqlite3.connect(path)\n"
        "try:\n"
        "    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]\n"
        "    table_count = conn.execute(\"select count(*) from sqlite_master where type='table'\").fetchone()[0]\n"
        "finally:\n"
        "    conn.close()\n"
        "print(f'integrity={integrity}')\n"
        "print(f'table_count={table_count}')\n"
        "print(f'db_size={os.path.getsize(path)}')\n"
        "raise SystemExit(0 if integrity == 'ok' else 3)\n"
        "PY"
    )
    code, out, err = _run(ssh, validate_cmd, timeout=timeout)
    if code != 0:
        _die(
            "Uploaded SQLite failed remote integrity check. "
            f"Stdout={out.strip()} Stderr={err.strip()}"
        )
    _info(out.strip())


def _render_local_env(env_example_text: str, image_tag: str) -> str:
    lines: list[str] = []
    for line in env_example_text.splitlines():
        if line.startswith("WEB_IMAGE="):
            lines.append(f"WEB_IMAGE={image_tag}")
        elif line.startswith("ALLOWED_HOSTS="):
            lines.append("ALLOWED_HOSTS=127.0.0.1,localhost")
        elif line.startswith("CORS_ALLOWED_ORIGINS="):
            lines.append("CORS_ALLOWED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000")
        elif line.startswith("CSRF_TRUSTED_ORIGINS="):
            lines.append("CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000")
        elif line.startswith("CADDY_HTTP_PORT="):
            lines.append("CADDY_HTTP_PORT=8000")
        elif line.startswith("CADDY_HTTPS_PORT="):
            lines.append("CADDY_HTTPS_PORT=8443")
        elif line.startswith("ENABLE_RSSHUB="):
            lines.append("ENABLE_RSSHUB=false")
        elif line.startswith("ENABLE_CELERY="):
            lines.append("ENABLE_CELERY=true")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def _render_local_caddy(template_text: str) -> str:
    return template_text.replace("__SITE_ADDRESS__", ":80")


def _local_start_ps1(image_filename: str, include_sqlite: bool) -> str:
    sqlite_block = ""
    if include_sqlite:
        sqlite_block = r"""
if (Test-Path ".\data\db.sqlite3") {
    $webCid = docker compose ps -q web
    if ($webCid) {
        $dbExists = docker exec $webCid sh -lc "test -s /app/data/db.sqlite3"
        if ($LASTEXITCODE -ne 0) {
            docker exec -u root $webCid sh -lc "mkdir -p /app/data && chown -R appuser:appuser /app/data" | Out-Null
            docker cp ".\data\db.sqlite3" "$webCid`:/app/data/db.sqlite3" | Out-Null
            docker exec -u root $webCid chown -R appuser:appuser /app/data | Out-Null
            docker compose restart web | Out-Null
        }
    }
}
"""
    return rf"""$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot\..
$env:COMPOSE_PROJECT_NAME = 'agomtradeprolocal'

if (-not (Test-Path '.env')) {{
    Copy-Item '.env.example' '.env'
}}

$envText = Get-Content '.env' -Raw
if ($envText -match 'SECRET_KEY=change-this-to-a-strong-secret') {{
    $secret = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([guid]::NewGuid().ToString() + [guid]::NewGuid().ToString()))
    $envText = $envText -replace 'SECRET_KEY=change-this-to-a-strong-secret', ('SECRET_KEY=' + $secret)
}}
if ($envText -match 'AGOMTRADEPRO_ENCRYPTION_KEY=$') {{
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $key = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
    $envText = $envText -replace 'AGOMTRADEPRO_ENCRYPTION_KEY=$', ('AGOMTRADEPRO_ENCRYPTION_KEY=' + $key)
}}
Set-Content '.env' $envText -Encoding UTF8

docker load -i ".\images\{image_filename}"
docker compose up -d redis web caddy
{sqlite_block}
Write-Host 'Started: http://127.0.0.1:8000/' -ForegroundColor Green
"""


def _local_start_sh(image_filename: str, include_sqlite: bool) -> str:
    sqlite_block = ""
    if include_sqlite:
        sqlite_block = """
if [ -f ./data/db.sqlite3 ]; then
  web_cid="$(docker compose ps -q web)"
  if [ -n "$web_cid" ]; then
    if ! docker exec "$web_cid" sh -lc 'test -s /app/data/db.sqlite3'; then
      docker exec -u root "$web_cid" sh -lc 'mkdir -p /app/data && chown -R appuser:appuser /app/data'
      docker cp ./data/db.sqlite3 "$web_cid:/app/data/db.sqlite3"
      docker exec -u root "$web_cid" chown -R appuser:appuser /app/data
      docker compose restart web
    fi
  fi
fi
"""
    return f"""#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
export COMPOSE_PROJECT_NAME=agomtradeprolocal

if [ ! -f .env ]; then
  cp .env.example .env
fi

if grep -q '^SECRET_KEY=change-this-to-a-strong-secret' .env; then
  secret="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(50))
PY
)"
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$secret|" .env
fi

if grep -q '^AGOMTRADEPRO_ENCRYPTION_KEY=$' .env; then
  key="$(python3 - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
)"
  sed -i "s|^AGOMTRADEPRO_ENCRYPTION_KEY=$|AGOMTRADEPRO_ENCRYPTION_KEY=$key|" .env
fi

docker load -i "./images/{image_filename}"
docker compose up -d redis web caddy
{sqlite_block}
echo "Started: http://127.0.0.1:8000/"
"""


def _local_stop_ps1() -> str:
    return """$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot\\..
$env:COMPOSE_PROJECT_NAME = 'agomtradeprolocal'
docker compose down
"""


def _redact_sensitive_text(text: str) -> str:
    text = re.sub(r"(Authorization:\s*Token\s+)[A-Za-z0-9]+", r"\1<REDACTED_TOKEN>", text)
    text = re.sub(
        r"(AGOMTRADEPRO_API_TOKEN[\"']?\s*[:=]\s*[\"'])[A-Za-z0-9]+([\"'])",
        r"\1<REDACTED_TOKEN>\2",
        text,
    )
    text = re.sub(
        r"(token[\"']?\s*[:=]\s*[\"'])[A-Za-z0-9]{20,}([\"'])",
        r"\1<REDACTED_TOKEN>\2",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(API Token\**:\s*`?)[A-Za-z0-9]{20,}(`?)",
        r"\1<REDACTED_TOKEN>\2",
        text,
        flags=re.IGNORECASE,
    )
    return text


def _add_runtime_docs(zf: zipfile.ZipFile, bundle_root_name: str, project_root: Path) -> None:
    doc_paths = [
        project_root / "docs" / "mcp" / "mcp-deployment.md",
        project_root / "docs" / "mcp" / "mcp_guide.md",
        project_root / "docs" / "development" / "startup-scripts.md",
        project_root / "docs" / "deployment" / "DOCKER_DEPLOYMENT.md",
    ]

    for path in doc_paths:
        if path.exists():
            rel_name = path.relative_to(project_root).as_posix()
            zf.writestr(f"{bundle_root_name}/{rel_name}", path.read_text(encoding="utf-8"))

    skill_src = project_root / ".agents" / "skills" / "mcp-remote-agomtradepro" / "SKILL.md"
    if skill_src.exists():
        skill_text = _redact_sensitive_text(skill_src.read_text(encoding="utf-8"))
        zf.writestr(
            f"{bundle_root_name}/skills/mcp-remote-agomtradepro/SKILL.redacted.md", skill_text
        )


def _create_local_runtime_bundle(
    project_root: Path,
    dist_dir: Path,
    tag: str,
    image_tag: str,
    local_image_path: Path,
    include_sqlite: bool,
    sqlite_file: Path | None,
) -> Path:
    bundle_root_name = f"agomtradepro-local-runtime-{tag}"
    bundle_zip_path = dist_dir / f"{bundle_root_name}.zip"
    compose_src = project_root / "docker" / "docker-compose.vps.yml"
    env_src = project_root / "deploy" / ".env.vps.example"
    caddy_src = project_root / "docker" / "Caddyfile.template"

    if not compose_src.exists() or not env_src.exists() or not caddy_src.exists():
        _die("Missing local runtime bundle source files (compose/env/caddy template)")

    env_text = _render_local_env(env_src.read_text(encoding="utf-8"), image_tag=image_tag)
    caddy_text = _render_local_caddy(caddy_src.read_text(encoding="utf-8"))
    image_filename = local_image_path.name

    with zipfile.ZipFile(bundle_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(local_image_path, arcname=f"{bundle_root_name}/images/{image_filename}")
        zf.writestr(
            f"{bundle_root_name}/docker-compose.yml", compose_src.read_text(encoding="utf-8")
        )
        zf.writestr(f"{bundle_root_name}/.env.example", env_text)
        zf.writestr(f"{bundle_root_name}/Caddyfile", caddy_text)
        zf.writestr(
            f"{bundle_root_name}/scripts/start-local.ps1",
            _local_start_ps1(image_filename, include_sqlite),
        )
        zf.writestr(
            f"{bundle_root_name}/scripts/start-local.sh",
            _local_start_sh(image_filename, include_sqlite),
        )
        zf.writestr(f"{bundle_root_name}/scripts/stop-local.ps1", _local_stop_ps1())
        _add_runtime_docs(zf, bundle_root_name, project_root)
        zf.writestr(
            f"{bundle_root_name}/README.txt",
            "\n".join(
                [
                    "AgomTradePro local runtime bundle",
                    "",
                    "What is included:",
                    "- web image tar",
                    "- docker-compose.yml",
                    "- .env.example",
                    "- Caddyfile",
                    "- start/stop scripts",
                    "- selected MCP/deployment docs",
                    "- redacted MCP skill reference",
                    "",
                    "What is not included:",
                    "- redis/caddy images (docker compose will pull them automatically)",
                    "- full source tree",
                    "",
                    "Quick start on another machine:",
                    "1. unzip this bundle",
                    "2. open the extracted folder",
                    "3. run scripts/start-local.ps1",
                    "",
                    "Persistence:",
                    "- sqlite data is stored in the docker named volume sqlite_data",
                    "- bundled data/db.sqlite3 is only seeded on first start when the volume is empty",
                    "- scripts/stop-local.ps1 uses docker compose down and does not remove volumes",
                    "",
                    "Default URL:",
                    "- http://127.0.0.1:8000/",
                ]
            )
            + "\n",
        )
        if include_sqlite and sqlite_file is not None and sqlite_file.exists():
            zf.write(sqlite_file, arcname=f"{bundle_root_name}/data/db.sqlite3")

    return bundle_zip_path


def _build_remote_build_script() -> str:
    return r"""set -eu

TARGET_DIR="${TARGET_DIR:-/opt/agomtradepro}"
REMOTE_TARBALL="${REMOTE_TARBALL:?missing REMOTE_TARBALL}"
RELEASE_TAG="${RELEASE_TAG:?missing RELEASE_TAG}"
KEEP_REMOTE_TEMP="${KEEP_REMOTE_TEMP:-0}"
EXPORT_IMAGE_TAR="${EXPORT_IMAGE_TAR:-1}"
REMOTE_IMAGE_TAR="${REMOTE_IMAGE_TAR:?missing REMOTE_IMAGE_TAR}"
DEPLOY_AFTER_BUILD="${DEPLOY_AFTER_BUILD:-1}"
SOURCE_COMMIT="${SOURCE_COMMIT:?missing SOURCE_COMMIT}"
export SOURCE_COMMIT
BUILD_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export BUILD_STARTED_AT

command -v docker >/dev/null 2>&1 || { echo "[ERROR] docker is required" >&2; exit 1; }
command -v tar >/dev/null 2>&1 || { echo "[ERROR] tar is required" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "[ERROR] python3 is required" >&2; exit 1; }

python3 - "$SOURCE_COMMIT" <<'PY'
import re
import sys

source_commit = sys.argv[1]
if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
    raise SystemExit("[ERROR] SOURCE_COMMIT must be an exact lowercase 40-hex Git commit")
PY

REMOTE_BASE="$(dirname "$REMOTE_TARBALL")"
WORK_ROOT="$REMOTE_BASE/build-$RELEASE_TAG"
rm -rf "$WORK_ROOT"
mkdir -p "$WORK_ROOT"
tar -xzf "$REMOTE_TARBALL" -C "$WORK_ROOT"
SRC_DIR="$(find "$WORK_ROOT" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[ -n "$SRC_DIR" ] || { echo "[ERROR] extracted source directory not found" >&2; exit 1; }
cd "$SRC_DIR"

find . -type f -name '*.sh' -exec sed -i 's/\r$//' {} +
if [ -f deploy/.env.vps.example ]; then sed -i 's/\r$//' deploy/.env.vps.example || true; fi

mkdir -p "$TARGET_DIR/releases"
RELEASE_DIR="$TARGET_DIR/releases/source-$RELEASE_TAG"
rm -rf "$RELEASE_DIR"
mkdir -p "$(dirname "$RELEASE_DIR")"
cp -a "$SRC_DIR" "$RELEASE_DIR"
cd "$RELEASE_DIR"

if [ ! -f deploy/.env ]; then
  cp deploy/.env.vps.example deploy/.env
fi

AVAILABLE_CPUS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 1)"
case "$AVAILABLE_CPUS" in
  ''|*[!0-9]*)
    AVAILABLE_CPUS=1
    ;;
esac
if [ "$AVAILABLE_CPUS" -le 1 ]; then
  sed -i 's/cpus: 1.5/cpus: 1.0/g' docker/docker-compose.vps.yml
fi

if ! docker build --build-arg PIP_OFFLINE_ONLY=0 --build-arg BUILDKIT_INLINE_CACHE=1 --build-arg "SOURCE_COMMIT=$SOURCE_COMMIT" -f docker/Dockerfile.prod -t "agomtradepro-web:$RELEASE_TAG" .; then
  DOCKER_BUILDKIT=0 docker build --build-arg PIP_OFFLINE_ONLY=0 --build-arg "SOURCE_COMMIT=$SOURCE_COMMIT" -f docker/Dockerfile.prod -t "agomtradepro-web:$RELEASE_TAG" .
fi
docker run --rm --entrypoint python "agomtradepro-web:$RELEASE_TAG" -m compileall -q /app
IMAGE_TAG="agomtradepro-web:$RELEASE_TAG"
IMAGE_ID="$(docker image inspect "$IMAGE_TAG" --format '{{.Id}}')"
IMAGE_REVISION="$(docker image inspect "$IMAGE_TAG" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
if [ "$IMAGE_REVISION" != "$SOURCE_COMMIT" ]; then
  echo "[ERROR] image OCI revision does not match source commit: image=$IMAGE_REVISION source=$SOURCE_COMMIT" >&2
  exit 1
fi
export IMAGE_TAG IMAGE_ID IMAGE_REVISION
BUILD_FINISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export BUILD_FINISHED_AT

MANIFEST_PATH=".agom-release-manifest.json"
export MANIFEST_PATH
python3 - <<'PY'
import json
import os
import re
from datetime import datetime
from pathlib import Path

release_tag = os.environ["RELEASE_TAG"]
source_commit = os.environ["SOURCE_COMMIT"]
image_tag = os.environ["IMAGE_TAG"]
image_id = os.environ["IMAGE_ID"]
build_started_at = os.environ["BUILD_STARTED_AT"]
build_finished_at = os.environ["BUILD_FINISHED_AT"]

if re.fullmatch(r"[0-9]{14}", release_tag) is None:
    raise SystemExit("[ERROR] RELEASE_TAG must be an exact 14-digit UTC deployment tag")
if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
    raise SystemExit("[ERROR] SOURCE_COMMIT must be an exact lowercase 40-hex Git commit")
if image_tag != f"agomtradepro-web:{release_tag}":
    raise SystemExit("[ERROR] image tag does not match release tag")
if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
    raise SystemExit("[ERROR] Docker image ID is not an exact sha256 identity")
timestamp_format = "%Y-%m-%dT%H:%M:%SZ"
started = datetime.strptime(build_started_at, timestamp_format)
finished = datetime.strptime(build_finished_at, timestamp_format)
if finished < started:
    raise SystemExit("[ERROR] build finish timestamp precedes build start timestamp")

manifest = {
    "version": 1,
    "release_tag": release_tag,
    "source_commit": source_commit,
    "image_tag": image_tag,
    "image_id": image_id,
    "build_started_at": build_started_at,
    "build_finished_at": build_finished_at,
    "source_mode": "source-upload",
}
manifest_path = Path(os.environ["MANIFEST_PATH"])
with manifest_path.open("x", encoding="utf-8", newline="\n") as handle:
    json.dump(manifest, handle, ensure_ascii=True, indent=2, sort_keys=True)
    handle.write("\n")
manifest_path.chmod(0o444)
PY

if [ "$EXPORT_IMAGE_TAR" = "1" ]; then
  IMAGE_BYTES="$(docker image inspect "agomtradepro-web:$RELEASE_TAG" --format '{{.Size}}' 2>/dev/null || echo 0)"
  AVAIL_BYTES="$(df -Pk "$(dirname "$REMOTE_IMAGE_TAR")" | awk 'NR==2 {print $4 * 1024}')"
  HEADROOM_BYTES=$((2 * 1024 * 1024 * 1024))
  REQUIRED_BYTES=$((IMAGE_BYTES + HEADROOM_BYTES))
  if [ "$AVAIL_BYTES" -lt "$REQUIRED_BYTES" ]; then
    echo "[ERROR] insufficient disk space for docker save. available=${AVAIL_BYTES} required=${REQUIRED_BYTES}" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$REMOTE_IMAGE_TAR")"
  rm -f "$REMOTE_IMAGE_TAR"
  docker save -o "$REMOTE_IMAGE_TAR" "agomtradepro-web:$RELEASE_TAG"
fi

python3 - <<'PY'
import json
import os
from pathlib import Path

manifest_path = Path(os.environ["MANIFEST_PATH"])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
report = {
    **manifest,
    "release_dir": str(Path(".").resolve()),
    "target_dir": Path(".").resolve().parents[1].as_posix(),
    "remote_image_tar": os.environ.get("REMOTE_IMAGE_TAR", ""),
    "deployed": False,
    "deploy_after_build": os.environ.get("DEPLOY_AFTER_BUILD", "1") == "1",
}
Path("/tmp/agomtradepro-build-report.json").write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
PY

if [ "$DEPLOY_AFTER_BUILD" != "1" ] && [ "$KEEP_REMOTE_TEMP" != "1" ]; then
  rm -rf "$RELEASE_DIR"
fi

if [ "$KEEP_REMOTE_TEMP" != "1" ]; then
  rm -rf "$WORK_ROOT" "$REMOTE_TARBALL"
fi

echo "BUILD_REPORT_PATH=/tmp/agomtradepro-build-report.json"
echo "REMOTE_IMAGE_TAR=$REMOTE_IMAGE_TAR"
"""


def _cleanup_remote_build_artifacts(
    ssh: Any,
    *,
    tag: str,
    remote_image_tar: str | None,
    remote_dir: str,
    target_dir: str,
    timeout: int,
) -> None:
    cleanup_lines = [
        "set -eu",
    ]

    if remote_image_tar:
        cleanup_lines.append(f"rm -f {shlex.quote(remote_image_tar)} 2>/dev/null || true")

    cleanup_lines.extend(
        [
            "rm -f /tmp/agomtradepro-build-report.json /tmp/agomtradepro-deploy-report.json /tmp/agomtradepro-health.json /tmp/agomtradepro-compose-ps.txt 2>/dev/null || true",
            f"docker image rm -f {shlex.quote(f'agomtradepro-web:{tag}')} 2>/dev/null || true",
            "dangling=$(docker images -f dangling=true -q 2>/dev/null || true)",
            'if [ -n "$dangling" ]; then docker rmi -f $dangling 2>/dev/null || true; fi',
            f"rmdir {shlex.quote(remote_dir)} 2>/dev/null || true",
            f'if [ -d {shlex.quote(target_dir)} ] && [ -z "$(find {shlex.quote(target_dir)} -mindepth 1 -maxdepth 1 2>/dev/null)" ]; then rmdir {shlex.quote(target_dir)} 2>/dev/null || true; fi',
        ]
    )

    _run(ssh, "bash -lc " + shlex.quote("\n".join(cleanup_lines)), timeout=timeout)


def _build_remote_git_clone_build_script() -> str:
    return r"""set -eu

TARGET_DIR="${TARGET_DIR:-/opt/agomtradepro}"
RELEASE_TAG="${RELEASE_TAG:?missing RELEASE_TAG}"
GIT_REPO="${GIT_REPO:?missing GIT_REPO}"
GIT_BRANCH="${GIT_BRANCH:-main}"
KEEP_REMOTE_TEMP="${KEEP_REMOTE_TEMP:-0}"
EXPORT_IMAGE_TAR="${EXPORT_IMAGE_TAR:-1}"
REMOTE_IMAGE_TAR="${REMOTE_IMAGE_TAR:?missing REMOTE_IMAGE_TAR}"
DEPLOY_AFTER_BUILD="${DEPLOY_AFTER_BUILD:-1}"
EXPECTED_SOURCE_COMMIT="${SOURCE_COMMIT:?missing SOURCE_COMMIT}"
export EXPECTED_SOURCE_COMMIT
BUILD_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export BUILD_STARTED_AT

command -v docker >/dev/null 2>&1 || { echo "[ERROR] docker is required" >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "[ERROR] git is required" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "[ERROR] python3 is required" >&2; exit 1; }

python3 - "$EXPECTED_SOURCE_COMMIT" <<'PY'
import re
import sys

source_commit = sys.argv[1]
if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
    raise SystemExit("[ERROR] SOURCE_COMMIT must be an exact lowercase 40-hex Git commit")
PY

RELEASE_DIR="$TARGET_DIR/releases/source-$RELEASE_TAG"
rm -rf "$RELEASE_DIR"
mkdir -p "$(dirname "$RELEASE_DIR")"

echo "[INFO] Cloning $GIT_REPO branch=$GIT_BRANCH into $RELEASE_DIR"
git clone --depth 1 --branch "$GIT_BRANCH" "$GIT_REPO" "$RELEASE_DIR"
cd "$RELEASE_DIR"
CLONED_SOURCE_COMMIT="$(git rev-parse --verify HEAD)"
python3 - "$CLONED_SOURCE_COMMIT" <<'PY'
import re
import sys

source_commit = sys.argv[1]
if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
    raise SystemExit("[ERROR] SOURCE_COMMIT must be an exact lowercase 40-hex Git commit")
PY
if [ "$CLONED_SOURCE_COMMIT" != "$EXPECTED_SOURCE_COMMIT" ]; then
  echo "[ERROR] cloned source commit does not match requested candidate: cloned=$CLONED_SOURCE_COMMIT expected=$EXPECTED_SOURCE_COMMIT" >&2
  exit 1
fi
SOURCE_COMMIT="$CLONED_SOURCE_COMMIT"
export SOURCE_COMMIT

if [ -f docker/entrypoint.prod.sh ]; then sed -i 's/\r$//' docker/entrypoint.prod.sh || true; fi
if [ -f deploy/.env.vps.example ]; then sed -i 's/\r$//' deploy/.env.vps.example || true; fi

if [ ! -f deploy/.env ]; then
  cp deploy/.env.vps.example deploy/.env
fi

AVAILABLE_CPUS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 1)"
case "$AVAILABLE_CPUS" in
  ''|*[!0-9]*)
    AVAILABLE_CPUS=1
    ;;
esac
if [ "$AVAILABLE_CPUS" -le 1 ]; then
  sed -i 's/cpus: 1.5/cpus: 1.0/g' docker/docker-compose.vps.yml
fi

echo "[INFO] Building Docker image agomtradepro-web:$RELEASE_TAG"
if ! docker build --build-arg PIP_OFFLINE_ONLY=0 --build-arg BUILDKIT_INLINE_CACHE=1 --build-arg "SOURCE_COMMIT=$SOURCE_COMMIT" -f docker/Dockerfile.prod -t "agomtradepro-web:$RELEASE_TAG" .; then
  DOCKER_BUILDKIT=0 docker build --build-arg PIP_OFFLINE_ONLY=0 --build-arg "SOURCE_COMMIT=$SOURCE_COMMIT" -f docker/Dockerfile.prod -t "agomtradepro-web:$RELEASE_TAG" .
fi
docker run --rm --entrypoint python "agomtradepro-web:$RELEASE_TAG" -m compileall -q /app
IMAGE_TAG="agomtradepro-web:$RELEASE_TAG"
IMAGE_ID="$(docker image inspect "$IMAGE_TAG" --format '{{.Id}}')"
IMAGE_REVISION="$(docker image inspect "$IMAGE_TAG" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
if [ "$IMAGE_REVISION" != "$SOURCE_COMMIT" ]; then
  echo "[ERROR] image OCI revision does not match source commit: image=$IMAGE_REVISION source=$SOURCE_COMMIT" >&2
  exit 1
fi
export IMAGE_TAG IMAGE_ID IMAGE_REVISION
BUILD_FINISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export BUILD_FINISHED_AT

MANIFEST_PATH=".agom-release-manifest.json"
export MANIFEST_PATH
python3 - <<'PY'
import json
import os
import re
from datetime import datetime
from pathlib import Path

release_tag = os.environ["RELEASE_TAG"]
source_commit = os.environ["SOURCE_COMMIT"]
image_tag = os.environ["IMAGE_TAG"]
image_id = os.environ["IMAGE_ID"]
build_started_at = os.environ["BUILD_STARTED_AT"]
build_finished_at = os.environ["BUILD_FINISHED_AT"]

if re.fullmatch(r"[0-9]{14}", release_tag) is None:
    raise SystemExit("[ERROR] RELEASE_TAG must be an exact 14-digit UTC deployment tag")
if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
    raise SystemExit("[ERROR] SOURCE_COMMIT must be an exact lowercase 40-hex Git commit")
if image_tag != f"agomtradepro-web:{release_tag}":
    raise SystemExit("[ERROR] image tag does not match release tag")
if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
    raise SystemExit("[ERROR] Docker image ID is not an exact sha256 identity")
timestamp_format = "%Y-%m-%dT%H:%M:%SZ"
started = datetime.strptime(build_started_at, timestamp_format)
finished = datetime.strptime(build_finished_at, timestamp_format)
if finished < started:
    raise SystemExit("[ERROR] build finish timestamp precedes build start timestamp")

manifest = {
    "version": 1,
    "release_tag": release_tag,
    "source_commit": source_commit,
    "image_tag": image_tag,
    "image_id": image_id,
    "build_started_at": build_started_at,
    "build_finished_at": build_finished_at,
    "source_mode": "git-clone",
}
manifest_path = Path(os.environ["MANIFEST_PATH"])
with manifest_path.open("x", encoding="utf-8", newline="\n") as handle:
    json.dump(manifest, handle, ensure_ascii=True, indent=2, sort_keys=True)
    handle.write("\n")
manifest_path.chmod(0o444)
PY

if [ "$EXPORT_IMAGE_TAR" = "1" ]; then
  IMAGE_BYTES="$(docker image inspect "agomtradepro-web:$RELEASE_TAG" --format '{{.Size}}' 2>/dev/null || echo 0)"
  AVAIL_BYTES="$(df -Pk "$(dirname "$REMOTE_IMAGE_TAR")" | awk 'NR==2 {print $4 * 1024}')"
  HEADROOM_BYTES=$((2 * 1024 * 1024 * 1024))
  REQUIRED_BYTES=$((IMAGE_BYTES + HEADROOM_BYTES))
  if [ "$AVAIL_BYTES" -lt "$REQUIRED_BYTES" ]; then
    echo "[ERROR] insufficient disk space for docker save. available=${AVAIL_BYTES} required=${REQUIRED_BYTES}" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$REMOTE_IMAGE_TAR")"
  rm -f "$REMOTE_IMAGE_TAR"
  docker save -o "$REMOTE_IMAGE_TAR" "agomtradepro-web:$RELEASE_TAG"
fi

python3 - <<'PY'
import json
import os
from pathlib import Path

manifest_path = Path(os.environ["MANIFEST_PATH"])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
report = {
    **manifest,
    "release_dir": str(Path(".").resolve()),
    "target_dir": Path(".").resolve().parents[1].as_posix(),
    "remote_image_tar": os.environ.get("REMOTE_IMAGE_TAR", ""),
    "deployed": False,
    "deploy_after_build": os.environ.get("DEPLOY_AFTER_BUILD", "1") == "1",
    "git_repo": os.environ.get("GIT_REPO", ""),
    "git_branch": os.environ.get("GIT_BRANCH", "main"),
}
Path("/tmp/agomtradepro-build-report.json").write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
PY

echo "BUILD_REPORT_PATH=/tmp/agomtradepro-build-report.json"
echo "REMOTE_IMAGE_TAR=$REMOTE_IMAGE_TAR"
"""


def _build_remote_deploy_script() -> str:
    return r"""set -eu

HOST="${HOST:-}"
PORT="${PORT:-}"
TARGET_DIR="${TARGET_DIR:-/opt/agomtradepro}"
RELEASE_TAG="${RELEASE_TAG:?missing RELEASE_TAG}"
ACTION="${ACTION:-fresh}"
DOMAIN="${DOMAIN:-}"
ALLOWED_HOSTS_INPUT="${ALLOWED_HOSTS_INPUT:-}"
WIPE_DOCKER="${WIPE_DOCKER:-0}"
WIPE_VOLUMES="${WIPE_VOLUMES:-0}"
INCLUDE_SQLITE="${INCLUDE_SQLITE:-0}"
ENABLE_RSSHUB="${ENABLE_RSSHUB:-1}"
ENABLE_CELERY="${ENABLE_CELERY:-0}"
SKIP_PREDEPLOY_BACKUP="${SKIP_PREDEPLOY_BACKUP:-0}"
AUTO_ROLLBACK="${AUTO_ROLLBACK:-1}"

command -v docker >/dev/null 2>&1 || { echo "[ERROR] docker is required" >&2; exit 1; }
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "[ERROR] docker compose is required" >&2
  exit 1
fi

RELEASE_DIR="$TARGET_DIR/releases/source-$RELEASE_TAG"
[ -d "$RELEASE_DIR" ] || { echo "[ERROR] release dir not found: $RELEASE_DIR" >&2; exit 1; }
MANIFEST_PATH="$RELEASE_DIR/.agom-release-manifest.json"
echo "[INFO] Validating immutable release provenance"
if ! python3 - "$MANIFEST_PATH" "$RELEASE_TAG" <<'PY'
import json
import re
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path

manifest_path = Path(sys.argv[1])
release_tag = sys.argv[2]
if manifest_path.is_symlink() or not manifest_path.is_file():
    raise SystemExit("release manifest must be a regular file")
if stat.S_IMODE(manifest_path.stat().st_mode) != 0o444:
    raise SystemExit("release manifest must be read-only (0444)")
try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"release manifest is unreadable: {exc}") from exc
if not isinstance(manifest, dict):
    raise SystemExit("release manifest must be a JSON object")
expected_keys = {
    "version",
    "release_tag",
    "source_commit",
    "image_tag",
    "image_id",
    "build_started_at",
    "build_finished_at",
    "source_mode",
}
if set(manifest) != expected_keys:
    raise SystemExit(f"release manifest must contain exactly {sorted(expected_keys)}")
if type(manifest["version"]) is not int or manifest["version"] != 1:
    raise SystemExit("release manifest version must be integer 1")
string_keys = expected_keys - {"version"}
if any(type(manifest[key]) is not str or not manifest[key] for key in string_keys):
    raise SystemExit("release manifest identity fields must be non-empty strings")
if re.fullmatch(r"[0-9]{14}", release_tag) is None:
    raise SystemExit("release tag must be an exact 14-digit UTC deployment tag")
if manifest["release_tag"] != release_tag:
    raise SystemExit("release manifest tag does not match requested release")
if re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"]) is None:
    raise SystemExit("release manifest source commit must be exact lowercase 40-hex")
expected_image_tag = f"agomtradepro-web:{release_tag}"
if manifest["image_tag"] != expected_image_tag:
    raise SystemExit("release manifest image tag does not match requested release")
if re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["image_id"]) is None:
    raise SystemExit("release manifest image ID must be an exact sha256 identity")
if manifest["source_mode"] not in {"source-upload", "git-clone"}:
    raise SystemExit("release manifest source mode is unsupported")
timestamp_format = "%Y-%m-%dT%H:%M:%SZ"
for key in ("build_started_at", "build_finished_at"):
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", manifest[key]) is None:
        raise SystemExit(f"release manifest {key} is not an exact UTC timestamp")
started = datetime.strptime(manifest["build_started_at"], timestamp_format)
finished = datetime.strptime(manifest["build_finished_at"], timestamp_format)
if finished < started:
    raise SystemExit("release manifest build timestamps are not monotonic")

image_id = subprocess.check_output(
    ["docker", "image", "inspect", expected_image_tag, "--format", "{{.Id}}"],
    text=True,
).strip()
image_revision = subprocess.check_output(
    [
        "docker",
        "image",
        "inspect",
        expected_image_tag,
        "--format",
        '{{index .Config.Labels "org.opencontainers.image.revision"}}',
    ],
    text=True,
).strip()
if image_id != manifest["image_id"]:
    raise SystemExit("release image ID does not match immutable manifest")
if image_revision != manifest["source_commit"]:
    raise SystemExit("release image OCI revision does not match immutable manifest")
PY
then
  echo "[ERROR] release provenance validation failed before deployment mutation" >&2
  exit 1
fi
PREVIOUS_RELEASE="$(readlink -f "$TARGET_DIR/current" 2>/dev/null || true)"
PREVIOUS_IMAGE=""
if [ -n "$PREVIOUS_RELEASE" ] && [ -f "$PREVIOUS_RELEASE/deploy/.env" ]; then
  PREVIOUS_IMAGE="$(grep '^WEB_IMAGE=' "$PREVIOUS_RELEASE/deploy/.env" | tail -n 1 | cut -d '=' -f2- || true)"
fi
ROLLBACK_READY=0
DEPLOY_SUCCEEDED=0
OLD_IMAGE_ARCHIVE=""

rollback_deployment() {
  exit_code="$?"
  trap - EXIT
  if [ "$exit_code" -ne 0 ] && [ "$DEPLOY_SUCCEEDED" != "1" ] && [ "$AUTO_ROLLBACK" = "1" ] && [ "$ROLLBACK_READY" = "1" ] && [ -n "$PREVIOUS_RELEASE" ] && [ -d "$PREVIOUS_RELEASE" ]; then
    echo "[WARN] Deployment failed; restoring previous release $PREVIOUS_RELEASE" >&2
    if [ -n "$OLD_IMAGE_ARCHIVE" ] && [ -f "$OLD_IMAGE_ARCHIVE" ]; then
      docker load -i "$OLD_IMAGE_ARCHIVE" >/dev/null 2>&1 || true
    fi
    cd "$PREVIOUS_RELEASE"
    $COMPOSE -p agomtradepro -f docker/docker-compose.vps.yml --env-file deploy/.env down --remove-orphans >/dev/null 2>&1 || true
    $COMPOSE -p agomtradepro -f docker/docker-compose.vps.yml --env-file deploy/.env up -d >/dev/null 2>&1 || true
    if [ -f scripts/publish-tui-release.sh ]; then
      if ! $COMPOSE -p agomtradepro -f docker/docker-compose.vps.yml --env-file deploy/.env run --rm --no-deps web sh scripts/publish-tui-release.sh "rollback-$(basename "$PREVIOUS_RELEASE")"; then
        echo "[ERROR] Previous release TUI registry restore failed" >&2
      fi
    elif [ -f config/tui/published/tui_operation_graph.published.json ]; then
      if ! $COMPOSE -p agomtradepro -f docker/docker-compose.vps.yml --env-file deploy/.env run --rm --no-deps web python tui-metadata-compiler/scripts/publish_tui_metadata.py config/tui/published/tui_operation_graph.published.json --approve --generation-source mixed --backend-version "rollback-$(basename "$PREVIOUS_RELEASE")" --review-note "Automatic rollback publish $(basename "$PREVIOUS_RELEASE")"; then
        echo "[ERROR] Previous release TUI registry restore failed" >&2
      fi
    else
      echo "[ERROR] Previous release has no reviewed TUI metadata artifact" >&2
    fi
    rm -f "$TARGET_DIR/.current-rollback"
    ln -s "$PREVIOUS_RELEASE" "$TARGET_DIR/.current-rollback"
    mv -Tf "$TARGET_DIR/.current-rollback" "$TARGET_DIR/current"
    echo "[WARN] Previous release restore attempted" >&2
  fi
  [ -z "$OLD_IMAGE_ARCHIVE" ] || rm -f "$OLD_IMAGE_ARCHIVE" 2>/dev/null || true
  exit "$exit_code"
}
trap rollback_deployment EXIT
cd "$RELEASE_DIR"

get_env_kv() {
  key="$1"
  file="$2"
  [ -f "$file" ] || return 0
  grep "^${key}=" "$file" | tail -n 1 | cut -d '=' -f2- || true
}

remove_env_kv() {
  key="$1"
  if [ -f deploy/.env ]; then
    sed -i "/^${key}=.*/d" deploy/.env
  fi
}

csv_merge_unique() {
  python3 - "$@" <<'PY'
import sys

seen = []
for value in sys.argv[1:]:
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item or "your-vps-ip" in item:
            continue
        if item not in seen:
            seen.append(item)
print(",".join(seen))
PY
}

origin_list_is_stale() {
  value="$1"
  python3 - "$value" "$HOST" <<'PY'
import sys

value = (sys.argv[1] or "").strip()
host = (sys.argv[2] or "").strip()
items = [item.strip() for item in value.split(",") if item.strip()]
if not items:
    raise SystemExit(0)
if any("your-vps-ip" in item for item in items):
    raise SystemExit(0)
baseline = {
    "http://127.0.0.1:8000",
    "http://localhost:8000",
}
if host:
    baseline.add(f"http://{host}:8000")
if set(items).issubset(baseline):
    raise SystemExit(0)
raise SystemExit(1)
PY
}

# Preserve keys from previous deployment before wiping
OLD_SECRET_KEY=""
OLD_ENCRYPTION_KEY=""
OLD_DOMAIN=""
OLD_ALLOWED_HOSTS=""
OLD_SECURE_SSL_REDIRECT_EXEMPT_HOSTS=""
OLD_CORS_ALLOWED_ORIGINS=""
OLD_CSRF_TRUSTED_ORIGINS=""
OLD_CADDY_HTTP_PORT=""
OLD_CADDY_HTTPS_PORT=""
OLD_APP_BASE_URL=""
OLD_AGOMTRADEPRO_BASE_URL=""
OLD_AGOMTRADEPRO_API_TOKEN=""
OLD_AGOMTRADEPRO_USERNAME=""
OLD_AGOMTRADEPRO_PASSWORD=""
OLD_POSTGRES_DB=""
OLD_POSTGRES_USER=""
OLD_POSTGRES_PASSWORD=""
OLD_DATABASE_URL=""
SECRETS_FILE="$TARGET_DIR/secrets.env"
mkdir -p "$TARGET_DIR" "$TARGET_DIR/backups"
chmod 700 "$TARGET_DIR" "$TARGET_DIR/backups"
touch "$SECRETS_FILE"
chmod 600 "$SECRETS_FILE"
_read_old_keys() {
  _src="$1"
  if [ ! -f "$_src" ]; then return; fi
  [ -z "$OLD_SECRET_KEY" ] && OLD_SECRET_KEY="$(get_env_kv SECRET_KEY "$_src")"
  [ -z "$OLD_ENCRYPTION_KEY" ] && OLD_ENCRYPTION_KEY="$(get_env_kv AGOMTRADEPRO_ENCRYPTION_KEY "$_src")"
  [ -z "$OLD_DOMAIN" ] && OLD_DOMAIN="$(get_env_kv DOMAIN "$_src")"
  [ -z "$OLD_ALLOWED_HOSTS" ] && OLD_ALLOWED_HOSTS="$(get_env_kv ALLOWED_HOSTS "$_src")"
  [ -z "$OLD_SECURE_SSL_REDIRECT_EXEMPT_HOSTS" ] && OLD_SECURE_SSL_REDIRECT_EXEMPT_HOSTS="$(get_env_kv SECURE_SSL_REDIRECT_EXEMPT_HOSTS "$_src")"
  [ -z "$OLD_CORS_ALLOWED_ORIGINS" ] && OLD_CORS_ALLOWED_ORIGINS="$(get_env_kv CORS_ALLOWED_ORIGINS "$_src")"
  [ -z "$OLD_CSRF_TRUSTED_ORIGINS" ] && OLD_CSRF_TRUSTED_ORIGINS="$(get_env_kv CSRF_TRUSTED_ORIGINS "$_src")"
  [ -z "$OLD_CADDY_HTTP_PORT" ] && OLD_CADDY_HTTP_PORT="$(get_env_kv CADDY_HTTP_PORT "$_src")"
  [ -z "$OLD_CADDY_HTTPS_PORT" ] && OLD_CADDY_HTTPS_PORT="$(get_env_kv CADDY_HTTPS_PORT "$_src")"
  [ -z "$OLD_APP_BASE_URL" ] && OLD_APP_BASE_URL="$(get_env_kv APP_BASE_URL "$_src")"
  [ -z "$OLD_AGOMTRADEPRO_BASE_URL" ] && OLD_AGOMTRADEPRO_BASE_URL="$(get_env_kv AGOMTRADEPRO_BASE_URL "$_src")"
  [ -z "$OLD_AGOMTRADEPRO_API_TOKEN" ] && OLD_AGOMTRADEPRO_API_TOKEN="$(get_env_kv AGOMTRADEPRO_API_TOKEN "$_src")"
  [ -z "$OLD_AGOMTRADEPRO_USERNAME" ] && OLD_AGOMTRADEPRO_USERNAME="$(get_env_kv AGOMTRADEPRO_USERNAME "$_src")"
  [ -z "$OLD_AGOMTRADEPRO_PASSWORD" ] && OLD_AGOMTRADEPRO_PASSWORD="$(get_env_kv AGOMTRADEPRO_PASSWORD "$_src")"
  [ -z "$OLD_POSTGRES_DB" ] && OLD_POSTGRES_DB="$(get_env_kv POSTGRES_DB "$_src")"
  [ -z "$OLD_POSTGRES_USER" ] && OLD_POSTGRES_USER="$(get_env_kv POSTGRES_USER "$_src")"
  [ -z "$OLD_POSTGRES_PASSWORD" ] && OLD_POSTGRES_PASSWORD="$(get_env_kv POSTGRES_PASSWORD "$_src")"
  [ -z "$OLD_DATABASE_URL" ] && OLD_DATABASE_URL="$(get_env_kv DATABASE_URL "$_src")"
  return 0
}
_read_old_keys "$SECRETS_FILE"
_read_old_keys "$TARGET_DIR/current/deploy/.env"
if [ -n "$OLD_ENCRYPTION_KEY" ]; then
  echo "[INFO] Found existing AGOMTRADEPRO_ENCRYPTION_KEY, will reuse"
fi

if [ -n "$PREVIOUS_RELEASE" ] && [ -d "$PREVIOUS_RELEASE" ]; then
  rm -f "$TARGET_DIR/.previous-next"
  ln -s "$PREVIOUS_RELEASE" "$TARGET_DIR/.previous-next"
  mv -Tf "$TARGET_DIR/.previous-next" "$TARGET_DIR/previous"
  if [ "$SKIP_PREDEPLOY_BACKUP" = "1" ]; then
    echo "[WARN] Pre-deploy backup skipped by explicit emergency option" >&2
  else
    echo "[INFO] Creating verified pre-deploy backup"
    bash "$RELEASE_DIR/scripts/vps-backup.sh" \
      --target-dir "$PREVIOUS_RELEASE" \
      --backup-dir "$TARGET_DIR/backups" \
      --keep-days 1
  fi
  ROLLBACK_READY=1
fi

if [ "$WIPE_DOCKER" = "1" ]; then
  SAVED_IMAGE=""
  if docker image inspect "agomtradepro-web:$RELEASE_TAG" >/dev/null 2>&1; then
    SAVED_IMAGE="/tmp/agomtradepro-web-saved-$RELEASE_TAG.tar"
    docker save -o "$SAVED_IMAGE" "agomtradepro-web:$RELEASE_TAG"
  fi
  if [ -n "$PREVIOUS_IMAGE" ] && docker image inspect "$PREVIOUS_IMAGE" >/dev/null 2>&1; then
    OLD_IMAGE_ARCHIVE="/tmp/agomtradepro-previous-image-$RELEASE_TAG.tar"
    docker save -o "$OLD_IMAGE_ARCHIVE" "$PREVIOUS_IMAGE"
  fi
  docker ps -aq | xargs -r docker rm -f || true
  if [ "$WIPE_VOLUMES" = "1" ]; then
    echo "[INFO] Wiping all Docker resources including volumes (DATA WILL BE LOST)"
    docker system prune -af --volumes || true
  else
    echo "[INFO] Wiping containers and images (preserving data volumes)"
    docker system prune -af || true
  fi
  rm -rf "$TARGET_DIR/current" || true
  if [ -n "$SAVED_IMAGE" ] && [ -f "$SAVED_IMAGE" ]; then
    docker load -i "$SAVED_IMAGE"
    rm -f "$SAVED_IMAGE"
  fi
fi

SECRET_KEY="$(grep '^SECRET_KEY=' deploy/.env | cut -d '=' -f2- || true)"
if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "change-this-to-a-strong-secret" ] || printf '%s' "$SECRET_KEY" | grep -qi 'django-insecure'; then
  if [ -n "$OLD_SECRET_KEY" ]; then
    SECRET_KEY="$OLD_SECRET_KEY"
  else
    SECRET_KEY="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(50))
PY
)"
  fi
fi

if grep -q '^SECRET_KEY=' deploy/.env; then
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|" deploy/.env
else
  printf '\nSECRET_KEY=%s\n' "$SECRET_KEY" >> deploy/.env
fi

if [ -n "$PRESET_ENCRYPTION_KEY" ]; then
  AGOM_KEY="$PRESET_ENCRYPTION_KEY"
else
  AGOM_KEY="$(grep '^AGOMTRADEPRO_ENCRYPTION_KEY=' deploy/.env | cut -d '=' -f2- || true)"
  if [ -z "$AGOM_KEY" ] && [ -n "$OLD_ENCRYPTION_KEY" ]; then
    AGOM_KEY="$OLD_ENCRYPTION_KEY"
    echo "[INFO] Reused AGOMTRADEPRO_ENCRYPTION_KEY from previous deployment"
  fi
  if [ -z "$AGOM_KEY" ]; then
    AGOM_KEY="$(python3 - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
)"
    echo "[INFO] Auto-generated new AGOMTRADEPRO_ENCRYPTION_KEY (no previous key found)"
    echo "[WARN] Save this key! You will need it to decrypt existing API keys."
  fi
fi

if grep -q '^AGOMTRADEPRO_ENCRYPTION_KEY=' deploy/.env; then
  sed -i "s|^AGOMTRADEPRO_ENCRYPTION_KEY=.*|AGOMTRADEPRO_ENCRYPTION_KEY=$AGOM_KEY|" deploy/.env
else
  printf '\nAGOMTRADEPRO_ENCRYPTION_KEY=%s\n' "$AGOM_KEY" >> deploy/.env
fi

_persist_secrets_env() {
  key="$1"
  value="$2"
  if grep -q "^${key}=" "$SECRETS_FILE" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$SECRETS_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$SECRETS_FILE"
  fi
  chmod 600 "$SECRETS_FILE"
}
_persist_secrets_env "SECRET_KEY" "$SECRET_KEY"
_persist_secrets_env "AGOMTRADEPRO_ENCRYPTION_KEY" "$AGOM_KEY"

set_env_kv() {
  key="$1"
  value="$2"
  if grep -q "^${key}=" deploy/.env; then
    sed -i "s|^${key}=.*|${key}=${value}|" deploy/.env
  else
    printf '\n%s=%s\n' "$key" "$value" >> deploy/.env
  fi
}

POSTGRES_DB_VALUE="$(get_env_kv POSTGRES_DB deploy/.env)"
POSTGRES_USER_VALUE="$(get_env_kv POSTGRES_USER deploy/.env)"
POSTGRES_PASSWORD_VALUE="$(get_env_kv POSTGRES_PASSWORD deploy/.env)"
[ -n "$OLD_POSTGRES_DB" ] && POSTGRES_DB_VALUE="$OLD_POSTGRES_DB"
[ -n "$OLD_POSTGRES_USER" ] && POSTGRES_USER_VALUE="$OLD_POSTGRES_USER"
[ -n "$OLD_POSTGRES_PASSWORD" ] && POSTGRES_PASSWORD_VALUE="$OLD_POSTGRES_PASSWORD"
[ -n "$POSTGRES_DB_VALUE" ] || POSTGRES_DB_VALUE="agomtradepro"
[ -n "$POSTGRES_USER_VALUE" ] || POSTGRES_USER_VALUE="agomtradepro"
case "$POSTGRES_PASSWORD_VALUE" in
  ""|change-this-*|changeme|example|placeholder)
    POSTGRES_PASSWORD_VALUE="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
    ;;
esac
DATABASE_URL_VALUE="postgresql://${POSTGRES_USER_VALUE}:${POSTGRES_PASSWORD_VALUE}@postgres:5432/${POSTGRES_DB_VALUE}"
set_env_kv "POSTGRES_DB" "$POSTGRES_DB_VALUE"
set_env_kv "POSTGRES_USER" "$POSTGRES_USER_VALUE"
set_env_kv "POSTGRES_PASSWORD" "$POSTGRES_PASSWORD_VALUE"
set_env_kv "DATABASE_URL" "$DATABASE_URL_VALUE"
# Deployment-only checks and mutations run explicitly below. Persist zeroes so
# a routine web-container restart stays fast and never repeats them because an
# older release left opt-in flags enabled in deploy/.env.
set_env_kv "AGOMTRADEPRO_CHECK_DEPLOY_ON_START" "0"
set_env_kv "AGOMTRADEPRO_AUTO_MIGRATE_ON_START" "0"
set_env_kv "AGOMTRADEPRO_BOOTSTRAP_ON_START" "0"
set_env_kv "AGOMTRADEPRO_COLLECTSTATIC_ON_START" "0"
set_env_kv "AGOMTRADEPRO_SETUP_SCHEDULE_ON_START" "0"
set_env_kv "AGOMTRADEPRO_ENSURE_SUPERUSER_ON_START" "0"
_persist_secrets_env "POSTGRES_DB" "$POSTGRES_DB_VALUE"
_persist_secrets_env "POSTGRES_USER" "$POSTGRES_USER_VALUE"
_persist_secrets_env "POSTGRES_PASSWORD" "$POSTGRES_PASSWORD_VALUE"
_persist_secrets_env "DATABASE_URL" "$DATABASE_URL_VALUE"

EFFECTIVE_DOMAIN="$DOMAIN"
if [ -z "$EFFECTIVE_DOMAIN" ] && [ -n "$OLD_DOMAIN" ]; then
  EFFECTIVE_DOMAIN="$OLD_DOMAIN"
fi

if [ -n "$EFFECTIVE_DOMAIN" ]; then
  set_env_kv "DOMAIN" "$EFFECTIVE_DOMAIN"
  _persist_secrets_env "DOMAIN" "$EFFECTIVE_DOMAIN"
  SITE_ADDR="$EFFECTIVE_DOMAIN"
else
  remove_env_kv "DOMAIN"
  SITE_ADDR=":80"
fi

if [ -n "$EFFECTIVE_DOMAIN" ]; then
  # Caddy owns the edge redirect. Keeping Django redirect disabled preserves
  # internal service-to-service HTTP while SECURE_PROXY_SSL_HEADER still lets
  # SecurityMiddleware publish HSTS and related headers on public HTTPS.
  set_env_kv "SECURE_SSL_REDIRECT" "False"
  set_env_kv "SESSION_COOKIE_SECURE" "True"
  set_env_kv "CSRF_COOKIE_SECURE" "True"
  set_env_kv "SECURE_HSTS_SECONDS" "31536000"
  set_env_kv "SECURE_HSTS_INCLUDE_SUBDOMAINS" "True"
  set_env_kv "SECURE_HSTS_PRELOAD" "True"
  set_env_kv "CORS_ALLOW_ALL_ORIGINS" "False"
else
  set_env_kv "SECURE_SSL_REDIRECT" "False"
  set_env_kv "SESSION_COOKIE_SECURE" "False"
  set_env_kv "CSRF_COOKIE_SECURE" "False"
  set_env_kv "SECURE_HSTS_SECONDS" "0"
  set_env_kv "SECURE_HSTS_INCLUDE_SUBDOMAINS" "False"
  set_env_kv "SECURE_HSTS_PRELOAD" "False"
fi

if [ -n "$EFFECTIVE_DOMAIN" ]; then
  AUTO_ALLOWED_HOSTS="$EFFECTIVE_DOMAIN,127.0.0.1,localhost,$HOST,web"
else
  AUTO_ALLOWED_HOSTS="127.0.0.1,localhost,$HOST,web"
fi

if [ -n "$ALLOWED_HOSTS_INPUT" ]; then
  EFFECTIVE_ALLOWED_HOSTS="$(csv_merge_unique "$ALLOWED_HOSTS_INPUT" "$AUTO_ALLOWED_HOSTS")"
elif [ -n "$OLD_ALLOWED_HOSTS" ]; then
  EFFECTIVE_ALLOWED_HOSTS="$(csv_merge_unique "$OLD_ALLOWED_HOSTS" "$AUTO_ALLOWED_HOSTS")"
else
  EFFECTIVE_ALLOWED_HOSTS="$AUTO_ALLOWED_HOSTS"
fi

set_env_kv "ALLOWED_HOSTS" "$EFFECTIVE_ALLOWED_HOSTS"

AUTO_SECURE_SSL_REDIRECT_EXEMPT_HOSTS="127.0.0.1,localhost,web"
if [ -n "$OLD_SECURE_SSL_REDIRECT_EXEMPT_HOSTS" ]; then
  EFFECTIVE_SECURE_SSL_REDIRECT_EXEMPT_HOSTS="$(
    csv_merge_unique "$OLD_SECURE_SSL_REDIRECT_EXEMPT_HOSTS" "$AUTO_SECURE_SSL_REDIRECT_EXEMPT_HOSTS"
  )"
else
  EFFECTIVE_SECURE_SSL_REDIRECT_EXEMPT_HOSTS="$AUTO_SECURE_SSL_REDIRECT_EXEMPT_HOSTS"
fi
set_env_kv "SECURE_SSL_REDIRECT_EXEMPT_HOSTS" "$EFFECTIVE_SECURE_SSL_REDIRECT_EXEMPT_HOSTS"

EFFECTIVE_AGOMTRADEPRO_BASE_URL="${AGOMTRADEPRO_BASE_URL:-}"
if [ -z "$EFFECTIVE_AGOMTRADEPRO_BASE_URL" ] && [ -n "$OLD_AGOMTRADEPRO_BASE_URL" ]; then
  EFFECTIVE_AGOMTRADEPRO_BASE_URL="$OLD_AGOMTRADEPRO_BASE_URL"
fi
if [ -z "$EFFECTIVE_AGOMTRADEPRO_BASE_URL" ]; then
  EFFECTIVE_AGOMTRADEPRO_BASE_URL="http://web:8000"
fi
set_env_kv "AGOMTRADEPRO_BASE_URL" "$EFFECTIVE_AGOMTRADEPRO_BASE_URL"
_persist_secrets_env "AGOMTRADEPRO_BASE_URL" "$EFFECTIVE_AGOMTRADEPRO_BASE_URL"

EFFECTIVE_AGOMTRADEPRO_API_TOKEN="${AGOMTRADEPRO_API_TOKEN:-}"
if [ -z "${AGOMTRADEPRO_API_TOKEN+x}" ] && [ -n "$OLD_AGOMTRADEPRO_API_TOKEN" ]; then
  EFFECTIVE_AGOMTRADEPRO_API_TOKEN="$OLD_AGOMTRADEPRO_API_TOKEN"
fi
set_env_kv "AGOMTRADEPRO_API_TOKEN" "$EFFECTIVE_AGOMTRADEPRO_API_TOKEN"
_persist_secrets_env "AGOMTRADEPRO_API_TOKEN" "$EFFECTIVE_AGOMTRADEPRO_API_TOKEN"

EFFECTIVE_AGOMTRADEPRO_USERNAME="${AGOMTRADEPRO_USERNAME:-}"
if [ -z "${AGOMTRADEPRO_USERNAME+x}" ] && [ -n "$OLD_AGOMTRADEPRO_USERNAME" ]; then
  EFFECTIVE_AGOMTRADEPRO_USERNAME="$OLD_AGOMTRADEPRO_USERNAME"
fi
set_env_kv "AGOMTRADEPRO_USERNAME" "$EFFECTIVE_AGOMTRADEPRO_USERNAME"
_persist_secrets_env "AGOMTRADEPRO_USERNAME" "$EFFECTIVE_AGOMTRADEPRO_USERNAME"

EFFECTIVE_AGOMTRADEPRO_PASSWORD="${AGOMTRADEPRO_PASSWORD:-}"
if [ -z "${AGOMTRADEPRO_PASSWORD+x}" ] && [ -n "$OLD_AGOMTRADEPRO_PASSWORD" ]; then
  EFFECTIVE_AGOMTRADEPRO_PASSWORD="$OLD_AGOMTRADEPRO_PASSWORD"
fi
set_env_kv "AGOMTRADEPRO_PASSWORD" "$EFFECTIVE_AGOMTRADEPRO_PASSWORD"
_persist_secrets_env "AGOMTRADEPRO_PASSWORD" "$EFFECTIVE_AGOMTRADEPRO_PASSWORD"

if grep -q '^WEB_IMAGE=' deploy/.env; then
  sed -i "s|^WEB_IMAGE=.*|WEB_IMAGE=agomtradepro-web:$RELEASE_TAG|" deploy/.env
else
  printf '\nWEB_IMAGE=agomtradepro-web:%s\n' "$RELEASE_TAG" >> deploy/.env
fi

if grep -q '^ENABLE_RSSHUB=' deploy/.env; then
  sed -i "s|^ENABLE_RSSHUB=.*|ENABLE_RSSHUB=$ENABLE_RSSHUB|" deploy/.env
else
  printf '\nENABLE_RSSHUB=%s\n' "$ENABLE_RSSHUB" >> deploy/.env
fi

if grep -q '^ENABLE_CELERY=' deploy/.env; then
  sed -i "s|^ENABLE_CELERY=.*|ENABLE_CELERY=$ENABLE_CELERY|" deploy/.env
else
  printf '\nENABLE_CELERY=%s\n' "$ENABLE_CELERY" >> deploy/.env
fi

if [ -n "$PORT" ]; then
  EFFECTIVE_HTTP_PORT="$PORT"
elif [ -n "$EFFECTIVE_DOMAIN" ]; then
  EFFECTIVE_HTTP_PORT="80"
elif [ -n "$OLD_CADDY_HTTP_PORT" ]; then
  EFFECTIVE_HTTP_PORT="$OLD_CADDY_HTTP_PORT"
else
  EFFECTIVE_HTTP_PORT="8000"
fi

set_env_kv "CADDY_HTTP_PORT" "$EFFECTIVE_HTTP_PORT"

if [ -n "$OLD_CADDY_HTTPS_PORT" ]; then
  EFFECTIVE_HTTPS_PORT="$OLD_CADDY_HTTPS_PORT"
else
  EFFECTIVE_HTTPS_PORT="443"
fi

if [ -n "$EFFECTIVE_DOMAIN" ]; then
  EFFECTIVE_HTTPS_PORT="443"
fi

set_env_kv "CADDY_HTTPS_PORT" "$EFFECTIVE_HTTPS_PORT"

if [ -n "$EFFECTIVE_DOMAIN" ]; then
  EFFECTIVE_APP_BASE_URL="https://$EFFECTIVE_DOMAIN"
elif [ -n "$OLD_APP_BASE_URL" ]; then
  EFFECTIVE_APP_BASE_URL="$OLD_APP_BASE_URL"
elif [ "$EFFECTIVE_HTTP_PORT" = "80" ]; then
  EFFECTIVE_APP_BASE_URL="http://$HOST"
else
  EFFECTIVE_APP_BASE_URL="http://$HOST:$EFFECTIVE_HTTP_PORT"
fi
set_env_kv "APP_BASE_URL" "$EFFECTIVE_APP_BASE_URL"
_persist_secrets_env "APP_BASE_URL" "$EFFECTIVE_APP_BASE_URL"

set_env_kv "AGOM_BACKUP_DIR" "$TARGET_DIR/backups/database"
mkdir -p "$TARGET_DIR/backups/database"
chown 1000:1000 "$TARGET_DIR/backups/database"
chmod 700 "$TARGET_DIR/backups/database"

CURRENT_CORS_ALLOWED_ORIGINS="$(get_env_kv CORS_ALLOWED_ORIGINS deploy/.env)"
if origin_list_is_stale "$CURRENT_CORS_ALLOWED_ORIGINS"; then
  remove_env_kv "CORS_ALLOWED_ORIGINS"
fi

CURRENT_CSRF_TRUSTED_ORIGINS="$(get_env_kv CSRF_TRUSTED_ORIGINS deploy/.env)"
if origin_list_is_stale "$CURRENT_CSRF_TRUSTED_ORIGINS"; then
  remove_env_kv "CSRF_TRUSTED_ORIGINS"
fi

if [ -n "$EFFECTIVE_DOMAIN" ]; then
  EFFECTIVE_CORS_ALLOWED_ORIGINS="https://$EFFECTIVE_DOMAIN"
  EFFECTIVE_CSRF_TRUSTED_ORIGINS="https://$EFFECTIVE_DOMAIN"
  if [ -n "$OLD_CORS_ALLOWED_ORIGINS" ] && ! origin_list_is_stale "$OLD_CORS_ALLOWED_ORIGINS"; then
    EFFECTIVE_CORS_ALLOWED_ORIGINS="$(csv_merge_unique "$OLD_CORS_ALLOWED_ORIGINS" "$EFFECTIVE_CORS_ALLOWED_ORIGINS")"
  fi
  if [ -n "$OLD_CSRF_TRUSTED_ORIGINS" ] && ! origin_list_is_stale "$OLD_CSRF_TRUSTED_ORIGINS"; then
    EFFECTIVE_CSRF_TRUSTED_ORIGINS="$(csv_merge_unique "$OLD_CSRF_TRUSTED_ORIGINS" "$EFFECTIVE_CSRF_TRUSTED_ORIGINS")"
  fi
  set_env_kv "CORS_ALLOWED_ORIGINS" "$EFFECTIVE_CORS_ALLOWED_ORIGINS"
  set_env_kv "CSRF_TRUSTED_ORIGINS" "$EFFECTIVE_CSRF_TRUSTED_ORIGINS"
else
  remove_env_kv "CORS_ALLOWED_ORIGINS"
  remove_env_kv "CSRF_TRUSTED_ORIGINS"
fi

sed "s|__SITE_ADDRESS__|$SITE_ADDR|g" docker/Caddyfile.template > docker/Caddyfile
if [ -n "$EFFECTIVE_DOMAIN" ] && [ -n "$HOST" ]; then
  HTTP_REDIRECT_HOST="$HOST"
  case "$HTTP_REDIRECT_HOST" in
    *:*) HTTP_REDIRECT_HOST="[$HTTP_REDIRECT_HOST]" ;;
  esac
  cat >> docker/Caddyfile <<EOF

http://$HTTP_REDIRECT_HOST {
    redir https://$EFFECTIVE_DOMAIN{uri} permanent
}
EOF
fi
chmod 600 deploy/.env "$SECRETS_FILE"

compose() {
  $COMPOSE -p agomtradepro -f docker/docker-compose.vps.yml --env-file deploy/.env "$@"
}

grep '^SECRET_KEY=' deploy/.env >/dev/null 2>&1 || {
  echo "[ERROR] SECRET_KEY was not persisted to deploy/.env" >&2
  exit 1
}

if [ "$ACTION" = "fresh" ]; then
  compose down --remove-orphans || true
fi

compose up -d runtime_ns redis postgres

if [ "$INCLUDE_SQLITE" = "1" ]; then
  if [ ! -f backups/db.sqlite3 ]; then
    echo "[ERROR] INCLUDE_SQLITE=1 but backups/db.sqlite3 is missing in release" >&2
    exit 1
  fi
  docker volume create agomtradepro_sqlite_data >/dev/null
  docker run --rm \
    -v agomtradepro_sqlite_data:/dest \
    -v "$RELEASE_DIR/backups:/src:ro" \
    alpine:3.20 \
    sh -lc 'cp /src/db.sqlite3 /dest/db.sqlite3 && chown 1000:1000 /dest /dest/db.sqlite3 && chmod 664 /dest/db.sqlite3'
fi

if ! bash scripts/migrate-vps-sqlite-to-postgres.sh "$TARGET_DIR"; then
  echo "[ERROR] PostgreSQL initialization or SQLite migration failed" >&2
  exit 1
fi

if ! compose run --rm --no-deps web python manage.py verify_canonical_schema --json; then
  echo "[ERROR] canonical Data Center schema or migration marker is incomplete" >&2
  exit 1
fi

if ! compose run --rm --no-deps web python manage.py initialize_data_center_catalog; then
  echo "[ERROR] Data Center runtime catalog synchronization failed" >&2
  exit 1
fi

if ! compose run --rm --no-deps web python manage.py check --deploy; then
  echo "[ERROR] Django production deployment checks failed" >&2
  exit 1
fi

if ! compose run --rm --no-deps web python manage.py collectstatic --noinput; then
  echo "[ERROR] static asset collection failed" >&2
  exit 1
fi

if ! compose run --rm --no-deps web python manage.py sync_ai_capability_catalog --type incremental --source mcp_tool --fail-on-error; then
  echo "[ERROR] MCP capability catalog synchronization failed" >&2
  exit 1
fi

if ! compose run --rm --no-deps web sh scripts/publish-tui-release.sh "$RELEASE_TAG"; then
  echo "[ERROR] TUI metadata publish or verification failed" >&2
  exit 1
fi

BOOTSTRAP_ALPHA="${AGOMTRADEPRO_BOOTSTRAP_WITH_ALPHA:-0}"
BOOTSTRAP_DECISION_REPAIR="${AGOMTRADEPRO_BOOTSTRAP_WITH_DECISION_REPAIR:-0}"
BOOTSTRAP_CMD="python manage.py bootstrap_cold_start"
if [ "$BOOTSTRAP_ALPHA" = "1" ]; then
  BOOTSTRAP_CMD="$BOOTSTRAP_CMD --with-alpha --alpha-universes ${AGOMTRADEPRO_BOOTSTRAP_ALPHA_UNIVERSES:-csi300} --alpha-top-n ${AGOMTRADEPRO_BOOTSTRAP_ALPHA_TOP_N:-30}"
fi
if [ "$BOOTSTRAP_DECISION_REPAIR" = "1" ]; then
  BOOTSTRAP_CMD="$BOOTSTRAP_CMD --with-decision-repair --decision-quote-max-age-hours ${AGOMTRADEPRO_DECISION_QUOTE_MAX_AGE_HOURS:-4}"
  if [ -n "${AGOMTRADEPRO_DECISION_ASSET_CODES:-}" ]; then
    BOOTSTRAP_CMD="$BOOTSTRAP_CMD --decision-asset-codes ${AGOMTRADEPRO_DECISION_ASSET_CODES}"
  fi
  if [ "${AGOMTRADEPRO_DECISION_REPAIR_SKIP_PULSE:-0}" = "1" ]; then
    BOOTSTRAP_CMD="$BOOTSTRAP_CMD --skip-pulse"
  fi
  if [ "${AGOMTRADEPRO_DECISION_REPAIR_SKIP_ALPHA:-0}" = "1" ]; then
    BOOTSTRAP_CMD="$BOOTSTRAP_CMD --skip-alpha"
  fi
fi

if ! compose run --rm --no-deps web sh -lc "$BOOTSTRAP_CMD"; then
  echo "[ERROR] cold-start bootstrap failed" >&2
  exit 1
fi

if ! compose run --rm --no-deps web sh -lc "python manage.py init_macro_indicator_governance --check && python manage.py normalize_macro_fact_units --check"; then
  echo "[ERROR] macro data-governance drift check failed" >&2
  exit 1
fi

if ! compose run --rm --no-deps web python manage.py setup_macro_daily_sync --hour "${MACRO_SYNC_HOUR:-8}" --minute "${MACRO_SYNC_MINUTE:-5}"; then
  echo "[WARN] failed to configure macro periodic tasks automatically" >&2
fi

# Superuser reconciliation is a deployment transaction, not a web-process
# startup responsibility. The entrypoint only performs it for this explicit run.
compose run --rm --no-deps \
  -e AGOMTRADEPRO_ENSURE_SUPERUSER_ON_START=1 \
  web true

SERVICES="runtime_ns redis postgres web caddy"
if [ "$ENABLE_RSSHUB" = "1" ]; then
  SERVICES="$SERVICES rsshub"
fi
if [ "$ENABLE_CELERY" = "1" ]; then
  SERVICES="$SERVICES celery_worker celery_beat"
fi

compose up -d $SERVICES

rm -f "$TARGET_DIR/.current-next"
ln -s "$RELEASE_DIR" "$TARGET_DIR/.current-next"
mv -Tf "$TARGET_DIR/.current-next" "$TARGET_DIR/current"

if [ -n "$EFFECTIVE_DOMAIN" ]; then
  HEALTH_URL="https://$EFFECTIVE_DOMAIN/api/health/"
  HEALTH_RESOLVE="--resolve $EFFECTIVE_DOMAIN:443:127.0.0.1"
else
  HEALTH_URL="http://127.0.0.1:$EFFECTIVE_HTTP_PORT/api/health/"
  HEALTH_RESOLVE=""
fi

TRIES=0
until curl -fsS --max-time 10 $HEALTH_RESOLVE "$HEALTH_URL" >/tmp/agomtradepro-health.json 2>/dev/null; do
  TRIES=$((TRIES + 1))
  if [ "$TRIES" -ge 20 ]; then
    echo "[ERROR] public health/TLS check failed after retries: $HEALTH_URL" >&2
    compose ps >&2 || true
    docker logs --tail 200 agomtradepro-caddy-1 >&2 || true
    docker logs --tail 200 agomtradepro-web-1 >&2 || true
    exit 1
  fi
  sleep 5
done

if ! compose exec -T web python manage.py check_encryption_readiness --json \
  >/tmp/agomtradepro-encryption-readiness.json 2>&1; then
  echo "[ERROR] encrypted production data is not readable with the deployed key" >&2
  cat /tmp/agomtradepro-encryption-readiness.json >&2 || true
  exit 1
fi
cat /tmp/agomtradepro-encryption-readiness.json

if [ "$ENABLE_CELERY" = "1" ]; then
  for service in celery_worker celery_beat; do
    cid="$(compose ps -q "$service" || true)"
    if [ -z "$cid" ]; then
      echo "[ERROR] $service container was not created" >&2
      compose ps >&2 || true
      exit 1
    fi
    running="$(docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null || echo false)"
    if [ "$running" != "true" ]; then
      echo "[ERROR] $service is not running" >&2
      docker logs --tail 200 "$cid" >&2 || true
      exit 1
    fi
  done

  CELERY_PING_OK=0
  for attempt in $(seq 1 12); do
    if compose exec -T web celery -A core inspect ping --timeout=8 >/tmp/agomtradepro-celery-ping.txt 2>&1; then
      CELERY_PING_OK=1
      break
    fi
    worker_cid="$(compose ps -q celery_worker || true)"
    worker_running="$(docker inspect -f '{{.State.Running}}' "$worker_cid" 2>/dev/null || echo false)"
    if [ "$worker_running" != "true" ]; then
      echo "[ERROR] celery_worker exited before inspect ping succeeded" >&2
      docker logs --tail 200 "$worker_cid" >&2 || true
      exit 1
    fi
    sleep 5
  done
  if [ "$CELERY_PING_OK" != "1" ]; then
    echo "[ERROR] Celery worker did not respond to inspect ping after retries" >&2
    cat /tmp/agomtradepro-celery-ping.txt >&2 || true
    compose ps >&2 || true
    exit 1
  fi
fi

compose ps > /tmp/agomtradepro-compose-ps.txt || true

python3 - <<'PY'
import json
import os
import subprocess
from pathlib import Path
release_tag = os.environ["RELEASE_TAG"]
manifest_path = Path(".agom-release-manifest.json")
release_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
image_ref = f"agomtradepro-web:{release_tag}"
if image_ref != release_manifest["image_tag"]:
    raise SystemExit("release manifest image tag changed during deployment")
image_id = subprocess.check_output(
    ["docker", "inspect", image_ref, "--format", "{{.Id}}"],
    text=True,
).strip()
source_commit = subprocess.check_output(
    ["docker", "inspect", image_ref, "--format", "{{index .Config.Labels \"org.opencontainers.image.revision\"}}"],
    text=True,
).strip()
if release_manifest["release_tag"] != release_tag:
    raise SystemExit("release manifest tag changed during deployment")
if image_id != release_manifest["image_id"]:
    raise SystemExit("release image ID changed during deployment")
if source_commit != release_manifest["source_commit"]:
    raise SystemExit("release image OCI revision changed during deployment")
report = {
    "version": release_manifest["version"],
    "release_tag": release_tag,
    "release_dir": str(Path(".").resolve()),
    "target_dir": Path(".").resolve().parents[1].as_posix(),
    "health_json": Path("/tmp/agomtradepro-health.json").read_text(encoding="utf-8"),
    "compose_ps": Path("/tmp/agomtradepro-compose-ps.txt").read_text(encoding="utf-8"),
    "image_tag": release_manifest["image_tag"],
    "image_id": release_manifest["image_id"],
    "source_commit": release_manifest["source_commit"],
    "build_started_at": release_manifest["build_started_at"],
    "build_finished_at": release_manifest["build_finished_at"],
    "source_mode": release_manifest["source_mode"],
    "release_manifest": release_manifest,
    "deployed": True,
}
Path("/tmp/agomtradepro-deploy-report.json").write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
PY

# Daily database backups are owned by Django Beat.  This deploy path only
# creates the explicit, verified pre-deploy recovery point above.
if crontab -l 2>/dev/null | grep -v "vps-backup.sh" | crontab -; then
  echo "[INFO] removed legacy duplicate vps-backup cron; Django Beat is the daily owner"
else
  echo "[WARN] unable to remove legacy duplicate vps-backup cron" >&2
fi

DEPLOY_SUCCEEDED=1
[ -z "$OLD_IMAGE_ARCHIVE" ] || rm -f "$OLD_IMAGE_ARCHIVE" 2>/dev/null || true
echo "REPORT_PATH=/tmp/agomtradepro-deploy-report.json"
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload source to a VPS, build there, and deploy.")
    ap.add_argument("--host", default=os.environ.get("AGOM_VPS_HOST", "").strip() or None)
    ap.add_argument("--port", type=int, default=int(os.environ.get("AGOM_VPS_PORT", "22")))
    ap.add_argument("--user", default=os.environ.get("AGOM_VPS_USER", "").strip() or None)
    ap.add_argument(
        "--password-file", default=os.environ.get("AGOM_VPS_PASS_FILE", "").strip() or None
    )
    ap.add_argument(
        "--remote-dir",
        default=os.environ.get("AGOM_VPS_REMOTE_DIR", "/tmp/agomtradepro-source-upload"),
    )
    ap.add_argument(
        "--target-dir", default=os.environ.get("AGOM_VPS_TARGET_DIR", "/opt/agomtradepro")
    )
    ap.add_argument("--http-port", type=int, default=None)
    ap.add_argument("--domain", default=os.environ.get("AGOM_VPS_DOMAIN", "").strip())
    ap.add_argument("--allowed-hosts", default=os.environ.get("AGOM_VPS_ALLOWED_HOSTS", "").strip())
    ap.add_argument(
        "--action", choices=["fresh", "upgrade"], default=os.environ.get("AGOM_VPS_ACTION", "fresh")
    )
    ap.add_argument("--include-sqlite", action="store_true", default=False)
    ap.add_argument("--wipe-docker", action="store_true", default=False)
    ap.add_argument("--wipe-volumes", action="store_true", default=False)
    ap.add_argument("--skip-predeploy-backup", action="store_true", default=False)
    ap.add_argument("--disable-auto-rollback", action="store_true", default=False)
    ap.add_argument("--keep-remote-temp", action="store_true", default=False)
    ap.add_argument("--download-report", action="store_true", default=True)
    ap.add_argument(
        "--report-dir", default=os.environ.get("AGOM_VPS_REPORT_DIR", "dist/remote-build-reports")
    )
    ap.add_argument("--download-built-image", action="store_true", default=False)
    ap.add_argument("--built-image-dir", default=os.environ.get("AGOM_VPS_IMAGE_DIR", "dist"))
    ap.add_argument(
        "--skip-deploy-after-build", action="store_false", dest="deploy_after_build", default=True
    )
    ap.add_argument("--prompt-before-deploy", action="store_true", default=False)
    ap.add_argument("--timeout", type=int, default=int(os.environ.get("AGOM_VPS_TIMEOUT", "3600")))
    ap.add_argument("--enable-rsshub", action="store_true", default=True)
    ap.add_argument("--disable-rsshub", action="store_true", default=False)
    ap.add_argument("--enable-celery", action="store_true", default=False)
    ap.add_argument("--disable-celery", action="store_true", default=False)
    ap.add_argument("--bootstrap-decision-repair", action="store_true", default=False)
    ap.add_argument("--decision-asset-codes", default="")
    ap.add_argument("--decision-quote-max-age-hours", default="4")
    ap.add_argument("--decision-repair-skip-pulse", action="store_true", default=False)
    ap.add_argument("--decision-repair-skip-alpha", action="store_true", default=False)
    ap.add_argument(
        "--encryption-key",
        default="",
        help="AGOMTRADEPRO_ENCRYPTION_KEY to set on VPS (blank = keep existing)",
    )
    ap.add_argument(
        "--git-clone",
        action="store_true",
        default=False,
        help="Clone from GitHub on VPS instead of uploading local source (much faster)",
    )
    ap.add_argument(
        "--git-repo",
        default=os.environ.get("AGOM_VPS_GIT_REPO", "https://github.com/guiyinan/agomTradePro.git"),
        help="Git repo URL for --git-clone mode",
    )
    ap.add_argument(
        "--git-branch",
        default=os.environ.get("AGOM_VPS_GIT_BRANCH", "main"),
        help="Git branch/tag for --git-clone mode",
    )
    args = ap.parse_args()
    if args.http_port is None:
        args.http_port = _optional_env_int("AGOM_VPS_HTTP_PORT")

    project_root = Path(__file__).resolve().parents[1]
    try:
        raw_source_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        _die(f"Unable to resolve the local source commit: {exc}")
    try:
        source_commit = _normalize_source_commit(raw_source_commit)
    except ValueError as exc:
        _die(str(exc))
    if not args.git_clone:
        try:
            worktree_status = subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=project_root,
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            _die(f"Unable to verify the source-upload worktree: {exc}")
        dirty_paths = len(worktree_status.splitlines())
        if dirty_paths:
            _die(
                "Source-upload mode requires a clean Git worktree; "
                f"found {dirty_paths} tracked or untracked path(s)"
            )
    host = args.host or _prompt("VPS host/IP")
    if not host:
        _die("Missing VPS host")

    user = args.user or _prompt("SSH username", "root")
    password = os.environ.get("AGOM_VPS_PASS", "").strip()
    if not password and args.password_file:
        password = Path(args.password_file).expanduser().read_text(encoding="utf-8").strip()
    if not password:
        password = getpass.getpass("SSH password: ")
    if not password:
        _die("Empty password")

    _info(f"Validating SSH credentials for {user}@{host}:{args.port}")
    _validate_ssh_credentials(
        host=host, port=args.port, username=user, password=password, timeout=min(args.timeout, 30)
    )
    _info("SSH credentials validated")

    _check_remote_dependencies(
        host=host, port=args.port, username=user, password=password, timeout=min(args.timeout, 60)
    )

    deploy_after_build = args.deploy_after_build
    cleanup_build_only_after_download = False
    sdk_base_url = os.environ.get("AGOMTRADEPRO_BASE_URL", "").strip()
    sdk_api_token = os.environ.get("AGOMTRADEPRO_API_TOKEN", "").strip()
    sdk_username = os.environ.get("AGOMTRADEPRO_USERNAME", "").strip()
    sdk_password = os.environ.get("AGOMTRADEPRO_PASSWORD", "").strip()
    if args.host is None:
        include_sqlite = _prompt_bool("Include local SQLite database?", False)
        deploy_after_build = _prompt_bool("Deploy to VPS after remote build?", False)
        if deploy_after_build:
            wipe_docker = _prompt_bool("Wipe existing Docker resources first?", False)
            if wipe_docker:
                print("  WARNING: This will stop all containers and remove unused images.")
                wipe_volumes = _prompt_bool(
                    "  Also DELETE all data volumes (SQLite DB, Redis, Media)?", False
                )
                if wipe_volumes:
                    print("  >>> ALL DATA WILL BE LOST! Only proceed if you want a fresh start.")
                else:
                    print("  >>> Data volumes (SQLite, Redis, Media) will be preserved.")
            else:
                wipe_volumes = False
            print("  Deploy action:")
            print("    fresh   - Stop and recreate containers (default, safer)")
            print("    upgrade - Rolling update without full restart")
            action_input = _prompt("Action", args.action)
            if action_input not in ("fresh", "upgrade"):
                print(f"  Invalid action '{action_input}', using 'fresh'")
                action = "fresh"
            else:
                action = action_input
            default_http_port = str(args.http_port) if args.http_port is not None else ""
            http_port_input = _prompt(
                "Public HTTP port (blank = keep existing/auto)",
                default_http_port,
            )
            http_port = int(http_port_input) if http_port_input else None
            domain = _prompt("Domain (blank for HTTP-only)", args.domain)
            allowed_hosts = _prompt("ALLOWED_HOSTS (blank for auto)", args.allowed_hosts)
            # Encryption key for AI provider API keys
            _info("AGOMTRADEPRO_ENCRYPTION_KEY is used to encrypt AI provider API keys.")
            _info("If the VPS already has a key, press Enter to keep it.")
            gen_key = _prompt_bool("Generate a new encryption key?", False)
            if gen_key:
                from cryptography.fernet import Fernet

                encryption_key = Fernet.generate_key().decode()
                _info(f"Generated encryption key: {encryption_key}")
                _info("Save this key! You will need it if you redeploy from scratch.")
            else:
                encryption_key = _prompt("Encryption key (blank = keep existing on VPS)", "")

        else:
            wipe_docker = False
            wipe_volumes = False
            action = args.action
            http_port = args.http_port
            domain = args.domain
            allowed_hosts = args.allowed_hosts
            encryption_key = ""
    else:
        include_sqlite = args.include_sqlite
        wipe_docker = args.wipe_docker
        wipe_volumes = args.wipe_volumes
        action = args.action
        http_port = args.http_port
        domain = args.domain
        allowed_hosts = args.allowed_hosts
        encryption_key = getattr(args, "encryption_key", "") or ""

    try:
        domain = _normalize_domain(domain)
    except ValueError as exc:
        _die(str(exc))

    if include_sqlite:
        encryption_key = _resolve_sqlite_encryption_key(project_root, encryption_key)
        _info("SQLite restore will use the source database encryption key")

    enable_rsshub = False if args.disable_rsshub else True
    enable_celery = False if args.disable_celery else True

    tag = time.strftime("%Y%m%d%H%M%S")
    bundle_name = f"agomtradepro-source-deploy-{tag}.tar.gz"
    local_bundle = project_root / "dist" / bundle_name
    local_image_path = (
        project_root / args.built_image_dir / f"agomtradepro-web-{tag}.tar"
    ).resolve()
    remote_dir = args.remote_dir.rstrip("/")
    remote_image_tar = posixpath.join(remote_dir, f"agomtradepro-web-{tag}.tar")
    sqlite_file = _latest_sqlite(project_root) if include_sqlite else None
    include_wheelhouse = os.environ.get("AGOM_VPS_INCLUDE_WHEELHOUSE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if not args.git_clone:
        _info(f"Creating source bundle: {local_bundle}")
        local_bundle.parent.mkdir(parents=True, exist_ok=True)
        _make_source_bundle(
            project_root=project_root,
            output_path=local_bundle,
            include_sqlite=include_sqlite,
            sqlite_file=sqlite_file,
            include_wheelhouse=include_wheelhouse,
        )
    else:
        _info("Skipping local source bundle (git-clone mode)")
        local_bundle.parent.mkdir(parents=True, exist_ok=True)

    _info(f"Connecting to {user}@{host}:{args.port}")
    ssh = _ssh_connect(
        host=host, port=args.port, username=user, password=password, timeout=args.timeout
    )
    try:
        remote_dir = args.remote_dir.rstrip("/")
        remote_image_tar = posixpath.join(remote_dir, f"agomtradepro-web-{tag}.tar")
        build_report_path = None
        report_path = None

        if args.git_clone:
            _info(f"Using git-clone mode: repo={args.git_repo} branch={args.git_branch}")
            remote_build_script = _build_remote_git_clone_build_script()
            build_env = {
                "TARGET_DIR": args.target_dir,
                "RELEASE_TAG": tag,
                "GIT_REPO": args.git_repo,
                "GIT_BRANCH": args.git_branch,
                "KEEP_REMOTE_TEMP": _bool_env(args.keep_remote_temp),
                "EXPORT_IMAGE_TAR": _bool_env(False),
                "REMOTE_IMAGE_TAR": remote_image_tar,
                "DEPLOY_AFTER_BUILD": _bool_env(deploy_after_build),
                "SOURCE_COMMIT": source_commit,
            }
            exports = " ".join(f"{key}={shlex.quote(value)}" for key, value in build_env.items())
            remote_cmd = f"{exports} bash -lc {shlex.quote(remote_build_script)}"

            _info("Running remote git-clone + build")
            code, out, err = _run(ssh, remote_cmd, timeout=args.timeout)
            if code != 0:
                _warn(out.strip())
                _die(f"Remote git-clone build failed. Exit={code}. Stderr={err.strip()}")
            if include_sqlite:
                if sqlite_file is None:
                    _die("--include-sqlite was requested but local db.sqlite3 was not resolved")
                _upload_sqlite_to_git_clone_release(
                    ssh=ssh,
                    sqlite_file=sqlite_file,
                    target_dir=args.target_dir,
                    release_tag=tag,
                    timeout=args.timeout,
                )
        else:
            remote_bundle = posixpath.join(remote_dir, bundle_name)
            _info(f"Ensuring remote upload dir: {remote_dir}")
            code, _out, err = _run(ssh, f"mkdir -p {shlex.quote(remote_dir)}", timeout=args.timeout)
            if code != 0:
                _die(f"Failed to create remote dir. Stderr={err.strip()}")

            _info(f"Uploading source bundle: {remote_bundle}")
            sftp = ssh.open_sftp()
            try:
                tmp_remote = remote_bundle + f".uploading.{int(time.time())}"
                sftp.put(str(local_bundle), tmp_remote)
                try:
                    sftp.remove(remote_bundle)
                except OSError:
                    pass
                sftp.rename(tmp_remote, remote_bundle)
            finally:
                sftp.close()

            remote_build_script = _build_remote_build_script()
            build_env = {
                "TARGET_DIR": args.target_dir,
                "REMOTE_TARBALL": remote_bundle,
                "RELEASE_TAG": tag,
                "KEEP_REMOTE_TEMP": _bool_env(args.keep_remote_temp),
                "EXPORT_IMAGE_TAR": _bool_env(True),
                "REMOTE_IMAGE_TAR": remote_image_tar,
                "DEPLOY_AFTER_BUILD": _bool_env(deploy_after_build),
                "SOURCE_COMMIT": source_commit,
            }

            exports = " ".join(f"{key}={shlex.quote(value)}" for key, value in build_env.items())
            remote_cmd = f"{exports} bash -lc {shlex.quote(remote_build_script)}"

            _info("Running remote build")
            code, out, err = _run(ssh, remote_cmd, timeout=args.timeout)
            if code != 0:
                _warn(out.strip())
                _die(f"Remote build failed. Exit={code}. Stderr={err.strip()}")

        for line in out.splitlines():
            if line.startswith("BUILD_REPORT_PATH="):
                build_report_path = line.split("=", 1)[1].strip()
            if line.startswith("REPORT_PATH="):
                report_path = line.split("=", 1)[1].strip()
            if line.startswith("REMOTE_IMAGE_TAR="):
                remote_image_tar = line.split("=", 1)[1].strip()

        if args.download_built_image and remote_image_tar:
            local_image_path.parent.mkdir(parents=True, exist_ok=True)
            _info(f"Downloading built image tar: {local_image_path}")
            sftp = ssh.open_sftp()
            try:
                sftp.get(remote_image_tar, str(local_image_path))
            finally:
                sftp.close()
            runtime_bundle_path = _create_local_runtime_bundle(
                project_root=project_root,
                dist_dir=local_image_path.parent,
                tag=tag,
                image_tag=f"agomtradepro-web:{tag}",
                local_image_path=local_image_path,
                include_sqlite=include_sqlite,
                sqlite_file=sqlite_file,
            )
            _info(f"Created local runtime bundle: {runtime_bundle_path}")
            if (not deploy_after_build) and (not args.keep_remote_temp):
                cleanup_build_only_after_download = True
            elif not args.keep_remote_temp:
                _run(ssh, f"rm -f {shlex.quote(remote_image_tar)}", timeout=args.timeout)

        if args.prompt_before_deploy:
            deploy_after_build = _prompt_bool("Remote build completed. Deploy to VPS now?", False)

        if deploy_after_build:
            remote_deploy_script = _build_remote_deploy_script()
            deploy_env = {
                "HOST": host,
                "PORT": "" if http_port is None else str(http_port),
                "TARGET_DIR": args.target_dir,
                "RELEASE_TAG": tag,
                "ACTION": action,
                "DOMAIN": domain,
                "ALLOWED_HOSTS_INPUT": allowed_hosts,
                "WIPE_DOCKER": _bool_env(wipe_docker),
                "WIPE_VOLUMES": _bool_env(wipe_volumes),
                "INCLUDE_SQLITE": _bool_env(include_sqlite),
                "ENABLE_RSSHUB": _bool_env(enable_rsshub),
                "ENABLE_CELERY": _bool_env(enable_celery),
                "SKIP_PREDEPLOY_BACKUP": _bool_env(args.skip_predeploy_backup),
                "AUTO_ROLLBACK": _bool_env(not args.disable_auto_rollback),
                "AGOMTRADEPRO_BOOTSTRAP_WITH_DECISION_REPAIR": _bool_env(
                    args.bootstrap_decision_repair
                ),
                "AGOMTRADEPRO_DECISION_ASSET_CODES": args.decision_asset_codes,
                "AGOMTRADEPRO_DECISION_QUOTE_MAX_AGE_HOURS": args.decision_quote_max_age_hours,
                "AGOMTRADEPRO_DECISION_REPAIR_SKIP_PULSE": _bool_env(
                    args.decision_repair_skip_pulse
                ),
                "AGOMTRADEPRO_DECISION_REPAIR_SKIP_ALPHA": _bool_env(
                    args.decision_repair_skip_alpha
                ),
                "PRESET_ENCRYPTION_KEY": encryption_key,
                "AGOMTRADEPRO_BASE_URL": sdk_base_url,
                "AGOMTRADEPRO_API_TOKEN": sdk_api_token,
                "AGOMTRADEPRO_USERNAME": sdk_username,
                "AGOMTRADEPRO_PASSWORD": sdk_password,
            }
            deploy_exports = " ".join(
                f"{key}={shlex.quote(value)}" for key, value in deploy_env.items()
            )
            deploy_cmd = f"{deploy_exports} bash -lc {shlex.quote(remote_deploy_script)}"
            _info("Running remote deploy")
            code, deploy_out, deploy_err = _run(ssh, deploy_cmd, timeout=args.timeout)
            if code != 0:
                _warn(deploy_out.strip())
                _die(f"Remote deploy failed. Exit={code}. Stderr={deploy_err.strip()}")
            out = f"{out.rstrip()}\n{deploy_out.strip()}".strip()
            for line in deploy_out.splitlines():
                if line.startswith("REPORT_PATH="):
                    report_path = line.split("=", 1)[1].strip()

        if args.download_report and report_path:
            report_dir = (project_root / args.report_dir).resolve()
            report_dir.mkdir(parents=True, exist_ok=True)
            local_report = report_dir / f"remote-build-report-{tag}.json"
            _info(f"Downloading deployment report: {local_report}")
            sftp = ssh.open_sftp()
            try:
                sftp.get(report_path, str(local_report))
            finally:
                sftp.close()
        elif args.download_report and build_report_path:
            report_dir = (project_root / args.report_dir).resolve()
            report_dir.mkdir(parents=True, exist_ok=True)
            local_report = report_dir / f"remote-build-report-{tag}.json"
            _info(f"Downloading build-only report: {local_report}")
            sftp = ssh.open_sftp()
            try:
                try:
                    sftp.get(build_report_path, str(local_report))
                except FileNotFoundError:
                    _warn(f"Remote build report missing, skipped download: {build_report_path}")
            finally:
                sftp.close()

        if cleanup_build_only_after_download:
            _info("Cleaning remote build-only artifacts")
            _cleanup_remote_build_artifacts(
                ssh,
                tag=tag,
                remote_image_tar=remote_image_tar,
                remote_dir=remote_dir,
                target_dir=args.target_dir,
                timeout=args.timeout,
            )

        print(out.strip())
        return 0
    finally:
        ssh.close()


if __name__ == "__main__":
    raise SystemExit(main())
