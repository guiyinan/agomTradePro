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
import json
import os
import posixpath
import secrets
import shlex
import sys
import tarfile
import tempfile
import time
from pathlib import Path


def _info(msg: str) -> None:
    print(f"[INFO] {msg}")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def _die(msg: str, code: int = 1) -> None:
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


def _latest_sqlite(project_root: Path) -> Path:
    db = project_root / "db.sqlite3"
    if not db.exists():
        _die(f"SQLite file not found: {db}")
    return db


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


def _bool_env(value: bool) -> str:
    return "1" if value else "0"


def _make_source_bundle(
    project_root: Path,
    output_path: Path,
    include_sqlite: bool,
    sqlite_file: Path | None,
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
        "agomsaaf",
    }
    skip_suffixes = {".pyc", ".pyo", ".tmp", ".temp", ".tar.gz"}
    wheelhouse_root = project_root / ".cache" / "pip-wheels" / "linux-py311"

    with tarfile.open(output_path, "w:gz") as tar:
        for path in project_root.rglob("*"):
            rel = path.relative_to(project_root)
            parts = rel.parts
            if not parts:
                continue
            if parts[0] == ".cache":
                try:
                    path.relative_to(wheelhouse_root)
                except ValueError:
                    continue
            if parts[0] in excludes:
                continue
            if any(part == "__pycache__" for part in parts):
                continue
            if path.name in {"db.sqlite3", "celerybeat-schedule", "celerybeat-schedule-shm", "celerybeat-schedule-wal"}:
                continue
            if path.is_file() and any(path.name.endswith(sfx) for sfx in skip_suffixes):
                continue

            arcname = posixpath.join(top_name, rel.as_posix())
            tar.add(path, arcname=arcname, recursive=False)

        if include_sqlite and sqlite_file is not None:
            db_arcname = posixpath.join(top_name, "backups", "db.sqlite3")
            tar.add(sqlite_file, arcname=db_arcname, recursive=False)


def _build_remote_build_script() -> str:
    return r"""set -eu

TARGET_DIR="${TARGET_DIR:-/opt/agomsaaf}"
REMOTE_TARBALL="${REMOTE_TARBALL:?missing REMOTE_TARBALL}"
RELEASE_TAG="${RELEASE_TAG:?missing RELEASE_TAG}"
KEEP_REMOTE_TEMP="${KEEP_REMOTE_TEMP:-0}"
EXPORT_IMAGE_TAR="${EXPORT_IMAGE_TAR:-1}"
REMOTE_IMAGE_TAR="${REMOTE_IMAGE_TAR:?missing REMOTE_IMAGE_TAR}"

command -v docker >/dev/null 2>&1 || { echo "[ERROR] docker is required" >&2; exit 1; }
command -v tar >/dev/null 2>&1 || { echo "[ERROR] tar is required" >&2; exit 1; }

REMOTE_BASE="$(dirname "$REMOTE_TARBALL")"
WORK_ROOT="$REMOTE_BASE/build-$RELEASE_TAG"
rm -rf "$WORK_ROOT"
mkdir -p "$WORK_ROOT"
tar -xzf "$REMOTE_TARBALL" -C "$WORK_ROOT"
SRC_DIR="$(find "$WORK_ROOT" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[ -n "$SRC_DIR" ] || { echo "[ERROR] extracted source directory not found" >&2; exit 1; }
cd "$SRC_DIR"

if [ -f docker/entrypoint.prod.sh ]; then sed -i 's/\r$//' docker/entrypoint.prod.sh || true; fi
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

if ! docker build --build-arg PIP_OFFLINE_ONLY=0 --build-arg BUILDKIT_INLINE_CACHE=1 -f docker/Dockerfile.prod -t "agomsaaf-web:$RELEASE_TAG" .; then
  DOCKER_BUILDKIT=0 docker build --build-arg PIP_OFFLINE_ONLY=0 -f docker/Dockerfile.prod -t "agomsaaf-web:$RELEASE_TAG" .
fi

if [ "$EXPORT_IMAGE_TAR" = "1" ]; then
  mkdir -p "$(dirname "$REMOTE_IMAGE_TAR")"
  rm -f "$REMOTE_IMAGE_TAR"
  docker save -o "$REMOTE_IMAGE_TAR" "agomsaaf-web:$RELEASE_TAG"
fi

python3 - <<'PY'
import json
import os
from pathlib import Path
report = {
    "release_tag": os.environ["RELEASE_TAG"],
    "release_dir": str(Path(".").resolve()),
    "target_dir": Path(".").resolve().parents[1].as_posix(),
    "image_tag": f"agomsaaf-web:{os.environ['RELEASE_TAG']}",
    "remote_image_tar": os.environ.get("REMOTE_IMAGE_TAR", ""),
    "deployed": False,
}
Path("/tmp/agomsaaf-build-report.json").write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
PY

if [ "$KEEP_REMOTE_TEMP" != "1" ]; then
  rm -rf "$WORK_ROOT" "$REMOTE_TARBALL"
fi

echo "BUILD_REPORT_PATH=/tmp/agomsaaf-build-report.json"
echo "REMOTE_IMAGE_TAR=$REMOTE_IMAGE_TAR"
"""


def _build_remote_deploy_script() -> str:
    return r"""set -eu

HOST="${HOST:-}"
PORT="${PORT:-8000}"
TARGET_DIR="${TARGET_DIR:-/opt/agomsaaf}"
RELEASE_TAG="${RELEASE_TAG:?missing RELEASE_TAG}"
ACTION="${ACTION:-fresh}"
DOMAIN="${DOMAIN:-}"
ALLOWED_HOSTS_INPUT="${ALLOWED_HOSTS_INPUT:-}"
WIPE_DOCKER="${WIPE_DOCKER:-0}"
INCLUDE_SQLITE="${INCLUDE_SQLITE:-0}"
ENABLE_RSSHUB="${ENABLE_RSSHUB:-1}"
ENABLE_CELERY="${ENABLE_CELERY:-0}"

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
cd "$RELEASE_DIR"

if [ "$WIPE_DOCKER" = "1" ]; then
  docker ps -aq | xargs -r docker rm -f || true
  docker system prune -af --volumes || true
  rm -rf "$TARGET_DIR/current" || true
fi

SECRET_KEY="$(grep '^SECRET_KEY=' deploy/.env | cut -d '=' -f2- || true)"
if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "change-this-to-a-strong-secret" ] || printf '%s' "$SECRET_KEY" | grep -qi 'django-insecure'; then
  SECRET_KEY="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(50))
PY
)"
fi

if grep -q '^SECRET_KEY=' deploy/.env; then
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|" deploy/.env
else
  printf '\nSECRET_KEY=%s\n' "$SECRET_KEY" >> deploy/.env
fi

AGOM_KEY="$(grep '^AGOMSAAF_ENCRYPTION_KEY=' deploy/.env | cut -d '=' -f2- || true)"
if [ -z "$AGOM_KEY" ]; then
  AGOM_KEY="$(python3 - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
)"
fi

if grep -q '^AGOMSAAF_ENCRYPTION_KEY=' deploy/.env; then
  sed -i "s|^AGOMSAAF_ENCRYPTION_KEY=.*|AGOMSAAF_ENCRYPTION_KEY=$AGOM_KEY|" deploy/.env
else
  printf '\nAGOMSAAF_ENCRYPTION_KEY=%s\n' "$AGOM_KEY" >> deploy/.env
fi

if [ -n "$DOMAIN" ]; then
  if grep -q '^DOMAIN=' deploy/.env; then
    sed -i "s|^DOMAIN=.*|DOMAIN=$DOMAIN|" deploy/.env
  else
    printf '\nDOMAIN=%s\n' "$DOMAIN" >> deploy/.env
  fi
  SITE_ADDR="$DOMAIN"
else
  SITE_ADDR=":80"
fi

if [ -z "$ALLOWED_HOSTS_INPUT" ]; then
  if [ -n "$DOMAIN" ]; then
    ALLOWED_HOSTS_INPUT="$DOMAIN,127.0.0.1,localhost,$HOST"
  else
    ALLOWED_HOSTS_INPUT="127.0.0.1,localhost,$HOST"
  fi
fi

if grep -q '^ALLOWED_HOSTS=' deploy/.env; then
  sed -i "s|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS=$ALLOWED_HOSTS_INPUT|" deploy/.env
else
  printf '\nALLOWED_HOSTS=%s\n' "$ALLOWED_HOSTS_INPUT" >> deploy/.env
fi

if grep -q '^WEB_IMAGE=' deploy/.env; then
  sed -i "s|^WEB_IMAGE=.*|WEB_IMAGE=agomsaaf-web:$RELEASE_TAG|" deploy/.env
else
  printf '\nWEB_IMAGE=agomsaaf-web:%s\n' "$RELEASE_TAG" >> deploy/.env
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

if grep -q '^CADDY_HTTP_PORT=' deploy/.env; then
  sed -i "s|^CADDY_HTTP_PORT=.*|CADDY_HTTP_PORT=$PORT|" deploy/.env
else
  printf '\nCADDY_HTTP_PORT=%s\n' "$PORT" >> deploy/.env
fi

CADDY_HTTPS_PORT="$(grep '^CADDY_HTTPS_PORT=' deploy/.env | cut -d '=' -f2- || true)"
if [ -z "$CADDY_HTTPS_PORT" ]; then
  CADDY_HTTPS_PORT="443"
fi

port_in_use() {
  port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(:|\\])${port}$"
    return $?
  fi
  return 1
}

if port_in_use "$CADDY_HTTPS_PORT"; then
  CADDY_HTTPS_PORT="8443"
fi

if grep -q '^CADDY_HTTPS_PORT=' deploy/.env; then
  sed -i "s|^CADDY_HTTPS_PORT=.*|CADDY_HTTPS_PORT=$CADDY_HTTPS_PORT|" deploy/.env
else
  printf '\nCADDY_HTTPS_PORT=%s\n' "$CADDY_HTTPS_PORT" >> deploy/.env
fi

sed "s|__SITE_ADDRESS__|$SITE_ADDR|g" docker/Caddyfile.template > docker/Caddyfile

compose() {
  $COMPOSE -p agomsaaf -f docker/docker-compose.vps.yml --env-file deploy/.env "$@"
}

grep '^SECRET_KEY=' deploy/.env >/dev/null 2>&1 || {
  echo "[ERROR] SECRET_KEY was not persisted to deploy/.env" >&2
  exit 1
}

if [ "$ACTION" = "fresh" ]; then
  compose down --remove-orphans || true
fi

compose up -d redis web

if [ "$INCLUDE_SQLITE" = "1" ] && [ -f backups/db.sqlite3 ]; then
  WEB_CID="$(compose ps -q web)"
  [ -n "$WEB_CID" ] || { echo "[ERROR] web container not found for SQLite restore" >&2; exit 1; }
  docker cp backups/db.sqlite3 "$WEB_CID:/app/data/db.sqlite3"
  compose restart web
fi

TRIES=0
until compose exec -T web python manage.py migrate --noinput; do
  TRIES=$((TRIES + 1))
  if [ "$TRIES" -ge 10 ]; then
    echo "[ERROR] migration failed after retries" >&2
    exit 1
  fi
  sleep 5
done

SERVICES="redis web caddy"
if [ "$ENABLE_RSSHUB" = "1" ]; then
  SERVICES="$SERVICES rsshub"
fi
if [ "$ENABLE_CELERY" = "1" ]; then
  SERVICES="$SERVICES celery_worker celery_beat"
fi

compose up -d $SERVICES

rm -rf "$TARGET_DIR/current"
ln -s "$RELEASE_DIR" "$TARGET_DIR/current"

TRIES=0
until curl -fsS --max-time 5 "http://127.0.0.1:$PORT/api/health/" >/tmp/agomsaaf-health.json 2>/dev/null; do
  TRIES=$((TRIES + 1))
  if [ "$TRIES" -ge 20 ]; then
    echo "[ERROR] health check failed after retries" >&2
    compose ps >&2 || true
    docker logs --tail 200 agomsaaf-web-1 >&2 || true
    exit 1
  fi
  sleep 5
done

compose ps > /tmp/agomsaaf-compose-ps.txt || true

python3 - <<'PY'
import json
from pathlib import Path
report = {
    "release_tag": Path(".").name.replace("source-", ""),
    "release_dir": str(Path(".").resolve()),
    "target_dir": Path(".").resolve().parents[1].as_posix(),
    "health_json": Path("/tmp/agomsaaf-health.json").read_text(encoding="utf-8"),
    "compose_ps": Path("/tmp/agomsaaf-compose-ps.txt").read_text(encoding="utf-8"),
    "deployed": True,
}
Path("/tmp/agomsaaf-deploy-report.json").write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
PY

echo "REPORT_PATH=/tmp/agomsaaf-deploy-report.json"
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload source to a VPS, build there, and deploy.")
    ap.add_argument("--host", default=os.environ.get("AGOM_VPS_HOST", "").strip() or None)
    ap.add_argument("--port", type=int, default=int(os.environ.get("AGOM_VPS_PORT", "22")))
    ap.add_argument("--user", default=os.environ.get("AGOM_VPS_USER", "").strip() or None)
    ap.add_argument("--password-file", default=os.environ.get("AGOM_VPS_PASS_FILE", "").strip() or None)
    ap.add_argument("--remote-dir", default=os.environ.get("AGOM_VPS_REMOTE_DIR", "/tmp/agomsaaf-source-upload"))
    ap.add_argument("--target-dir", default=os.environ.get("AGOM_VPS_TARGET_DIR", "/opt/agomsaaf"))
    ap.add_argument("--http-port", type=int, default=int(os.environ.get("AGOM_VPS_HTTP_PORT", "8000")))
    ap.add_argument("--domain", default=os.environ.get("AGOM_VPS_DOMAIN", "").strip())
    ap.add_argument("--allowed-hosts", default=os.environ.get("AGOM_VPS_ALLOWED_HOSTS", "").strip())
    ap.add_argument("--action", choices=["fresh", "upgrade"], default=os.environ.get("AGOM_VPS_ACTION", "fresh"))
    ap.add_argument("--include-sqlite", action="store_true", default=False)
    ap.add_argument("--wipe-docker", action="store_true", default=False)
    ap.add_argument("--keep-remote-temp", action="store_true", default=False)
    ap.add_argument("--download-report", action="store_true", default=True)
    ap.add_argument("--report-dir", default=os.environ.get("AGOM_VPS_REPORT_DIR", "dist/remote-build-reports"))
    ap.add_argument("--download-built-image", action="store_true", default=False)
    ap.add_argument("--built-image-dir", default=os.environ.get("AGOM_VPS_IMAGE_DIR", "dist/remote-built-images"))
    ap.add_argument("--skip-deploy-after-build", action="store_false", dest="deploy_after_build", default=True)
    ap.add_argument("--prompt-before-deploy", action="store_true", default=False)
    ap.add_argument("--timeout", type=int, default=int(os.environ.get("AGOM_VPS_TIMEOUT", "1800")))
    ap.add_argument("--enable-rsshub", action="store_true", default=True)
    ap.add_argument("--disable-rsshub", action="store_true", default=False)
    ap.add_argument("--enable-celery", action="store_true", default=False)
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parents[1]
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

    if args.host is None:
        include_sqlite = _prompt_bool("Include local SQLite database?", False)
        wipe_docker = _prompt_bool("Wipe existing Docker resources first?", False)
        action = _prompt("Deploy action", args.action)
        http_port = int(_prompt("Public HTTP port", str(args.http_port)))
        domain = _prompt("Domain (blank for HTTP-only)", args.domain)
        allowed_hosts = _prompt("ALLOWED_HOSTS (blank for auto)", args.allowed_hosts)
    else:
        include_sqlite = args.include_sqlite
        wipe_docker = args.wipe_docker
        action = args.action
        http_port = args.http_port
        domain = args.domain
        allowed_hosts = args.allowed_hosts

    enable_rsshub = False if args.disable_rsshub else True
    enable_celery = args.enable_celery

    tag = time.strftime("%Y%m%d%H%M%S")
    bundle_name = f"agomsaaf-source-deploy-{tag}.tar.gz"
    local_bundle = project_root / "dist" / bundle_name
    local_bundle.parent.mkdir(parents=True, exist_ok=True)
    local_image_path = (project_root / args.built_image_dir / f"agomsaaf-web-{tag}.tar").resolve()
    remote_image_tar = posixpath.join(args.remote_dir.rstrip("/"), f"agomsaaf-web-{tag}.tar")
    sqlite_file = _latest_sqlite(project_root) if include_sqlite else None

    _info(f"Creating source bundle: {local_bundle}")
    _make_source_bundle(
        project_root=project_root,
        output_path=local_bundle,
        include_sqlite=include_sqlite,
        sqlite_file=sqlite_file,
    )

    _info(f"Connecting to {user}@{host}:{args.port}")
    ssh = _ssh_connect(host=host, port=args.port, username=user, password=password, timeout=args.timeout)
    try:
        remote_dir = args.remote_dir.rstrip("/")
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
        }

        exports = " ".join(f"{key}={shlex.quote(value)}" for key, value in build_env.items())
        remote_cmd = f"{exports} bash -lc {shlex.quote(remote_build_script)}"

        _info("Running remote build")
        code, out, err = _run(ssh, remote_cmd, timeout=args.timeout)
        if code != 0:
            _warn(out.strip())
            _die(f"Remote build failed. Exit={code}. Stderr={err.strip()}")

        build_report_path = None
        report_path = None
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
            if not args.keep_remote_temp:
                _run(ssh, f"rm -f {shlex.quote(remote_image_tar)}", timeout=args.timeout)

        deploy_after_build = args.deploy_after_build
        if args.prompt_before_deploy:
            deploy_after_build = _prompt_bool("Remote build completed. Deploy to VPS now?", False)

        if deploy_after_build:
            remote_deploy_script = _build_remote_deploy_script()
            deploy_env = {
                "HOST": host,
                "PORT": str(http_port),
                "TARGET_DIR": args.target_dir,
                "RELEASE_TAG": tag,
                "ACTION": action,
                "DOMAIN": domain,
                "ALLOWED_HOSTS_INPUT": allowed_hosts,
                "WIPE_DOCKER": _bool_env(wipe_docker),
                "INCLUDE_SQLITE": _bool_env(include_sqlite),
                "ENABLE_RSSHUB": _bool_env(enable_rsshub),
                "ENABLE_CELERY": _bool_env(enable_celery),
            }
            deploy_exports = " ".join(f"{key}={shlex.quote(value)}" for key, value in deploy_env.items())
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
                sftp.get(build_report_path, str(local_report))
            finally:
                sftp.close()

        print(out.strip())
        return 0
    finally:
        ssh.close()


if __name__ == "__main__":
    raise SystemExit(main())
