#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

phase=arguments
failure_code=""
root=""
network_created=0
prepare_network_created=0
volume_created=0
postgres_created=0
redis_created=0
snapshot=""
bootstrap=""
status=""
execution_image=""

fail() {
  failure_code="$1"
  printf 'S6_PREPARE_BLOCKED code=%s\n' "$failure_code" >&2
  exit 60
}

if [[ $# -ne 2 || "$1" != "--plan-file" || -z "$2" ]]; then
  fail S6_PREPARE_PLAN_FILE_REQUIRED
fi
script_directory="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)" \
  || fail S6_PREPARE_WORKSPACE_UNAVAILABLE
workspace="$(git -C "$script_directory" rev-parse --show-toplevel 2>/dev/null)" \
  || fail S6_PREPARE_WORKSPACE_UNAVAILABLE
plan_payload="$(python3 - "$2" "$workspace" <<'PY'
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

def blocked(code):
    print(f"S6_PREPARE_BLOCKED code={code}", file=sys.stderr)
    raise SystemExit(2)

try:
    workspace = Path(sys.argv[2]).resolve(strict=True)
    if str(workspace) not in sys.path:
        sys.path.insert(0, str(workspace))
    plan_path = Path(os.path.abspath(sys.argv[1]))
    info = plan_path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o222:
        blocked("S6_ATTEMPT_PLAN_INVALID")
    raw = plan_path.read_bytes()
    plan = json.loads(raw.decode("utf-8"))
    if not isinstance(plan, dict):
        blocked("S6_ATTEMPT_PLAN_INVALID")
    from scripts.plan_release_rehearsal_attempt import build_attempt_plan
    candidate = plan.get("candidate_sha")
    attempt = plan.get("attempt_id")
    advance = plan.get("advance_isolated_market_graph")
    root_text = plan.get("root")
    if not isinstance(candidate, str) or not isinstance(attempt, str) or type(advance) is not bool:
        blocked("S6_ATTEMPT_PLAN_INVALID")
    if not isinstance(root_text, str) or not Path(root_text).is_absolute():
        blocked("S6_ATTEMPT_PLAN_INVALID")
    planned_root = Path(root_text)
    expected = build_attempt_plan(
        candidate_sha=candidate,
        attempt_id=attempt,
        attempts_dir=planned_root.parent,
        advance_isolated_market_graph=advance,
    )
    canonical = (json.dumps(expected, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if plan != expected or raw != canonical:
        blocked("S6_ATTEMPT_PLAN_BINDING_MISMATCH")
    if plan_path != planned_root / "attempt-plan.json":
        blocked("S6_ATTEMPT_PLAN_PATH_MISMATCH")
    if planned_root.is_symlink() or not planned_root.is_dir() or planned_root.resolve(strict=True) != planned_root:
        blocked("S6_ATTEMPT_ROOT_INVALID")
    head = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "--verify", "HEAD^{commit}"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
    )
    if head.returncode != 0:
        blocked("S6_CANDIDATE_HEAD_UNAVAILABLE")
    if head.stdout.decode("ascii", errors="replace").strip() != candidate:
        blocked("S6_CANDIDATE_HEAD_MISMATCH")
    clean = subprocess.run(
        ["git", "-C", str(workspace), "status", "--porcelain=v1",
         "--untracked-files=all", "--ignore-submodules=none"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
    )
    if clean.returncode != 0:
        blocked("S6_CANDIDATE_STATUS_UNAVAILABLE")
    if clean.stdout:
        blocked("S6_CANDIDATE_WORKSPACE_DIRTY")
    keys = (
        "candidate_sha", "attempt_id", "namespace", "root", "evidence_dir", "network",
        "postgres_container", "redis_container", "postgres_volume", "database",
        "provider_settings_export_path", "provider_identities_export_path",
        "candidate_source_snapshot_path", "candidate_source_receipt_path",
    )
    values = [expected[key] for key in keys]
    if any(not isinstance(value, str) or not value or any(c in value for c in "\r\n\x00") for value in values):
        blocked("S6_ATTEMPT_PLAN_INVALID")
    print("\n".join(values))
    print("1" if expected["advance_isolated_market_graph"] else "0")
except SystemExit:
    raise
except Exception:
    blocked("S6_ATTEMPT_PLAN_INVALID")
PY
)" || exit 60
plan_values=()
mapfile -t plan_values <<< "$plan_payload"
test "${#plan_values[@]}" -eq 15 || fail S6_ATTEMPT_PLAN_INVALID
sha="${plan_values[0]}"
attempt_id="${plan_values[1]}"
namespace="${plan_values[2]}"
root="${plan_values[3]}"
evidence_dir="${plan_values[4]}"
net="${plan_values[5]}"
pg="${plan_values[6]}"
redis="${plan_values[7]}"
volume="${plan_values[8]}"
db="${plan_values[9]}"
prepare_network="${net}-prepare"
prepare_alias="${pg}-prepare"
provider_settings_export_path="${plan_values[10]}"
provider_identities_export_path="${plan_values[11]}"
candidate_source="${plan_values[12]}"
candidate_source_receipt="${plan_values[13]}"
advance_isolated_market_graph="${plan_values[14]}"
attempt_plan_sha256="$(sha256sum -- "$2" 2>/dev/null | cut -d ' ' -f 1)"
[[ "$attempt_plan_sha256" =~ ^[0-9a-f]{64}$ ]] || fail S6_ATTEMPT_PLAN_INVALID
[[ "$advance_isolated_market_graph" == 0 || "$advance_isolated_market_graph" == 1 ]] \
  || fail S6_ATTEMPT_PLAN_INVALID
inputs="$root/inputs-private"
candidate_input_staging="$root/candidate-input-staging"
export_root="$(dirname -- "$provider_settings_export_path")"
candidate_source_helper="$candidate_source/scripts/prepare_s6_candidate_source_snapshot.py"
failure_helper="$workspace/scripts/shared/s6_candidate_export_failure.sh"
snapshot="$root/.fresh-production-snapshot.dump"
bootstrap="$inputs/postgres-role-bootstrap.sql"
exporter_role_bootstrap="$inputs/exporter-role-bootstrap.sql"
status="$root/prepare-status.json"
prepare_receipt="$root/prepare-receipt.json"
runner_venv="$root/runner-venv"
runner_python="$runner_venv/bin/python"
runner_receipt="$root/runner-runtime-receipt.json"
runner_create_log="$root/runner-venv-create.log"
runner_install_log="$root/runner-venv-install.log"
requirements_file="$workspace/requirements-ops.txt"
requirements_sha256=c31a7e1d69b84a2be0423913e439b42de5ad0542d8498a77ce1c2cce0c492743
candidate_uid=""
candidate_gid=""
web_container=""
web_container_id=""
isolated_pg_id=""
isolated_redis_id=""
isolated_network_id=""
production_postgres=""
expected_production_database=""
source "$failure_helper" 2>/dev/null || fail S6_CANDIDATE_EXPORT_FAILURE_HELPER_INVALID

finish() {
  local exit_code="$?"
  trap - EXIT
  set +e
  [[ -z "$snapshot" ]] || rm -f -- "$snapshot"
  [[ -z "$bootstrap" ]] || rm -f -- "$bootstrap"
  if [[ "$exit_code" -ne 0 ]]; then
    if [[ -d "$inputs" && ! -L "$inputs" ]]; then
      rm -f -- "$inputs/prepare-export.env" "$inputs/.production-encryption-key" \
        "$inputs/postgres-superuser.env" "$inputs/bootstrap-secrets.env" \
        "$inputs/postgres-role-bootstrap.sql" "$inputs/exporter-role-bootstrap.sql"
    fi
  else
    rm -f -- "$inputs/postgres-superuser.env" "$inputs/bootstrap-secrets.env" \
      "$inputs/postgres-role-bootstrap.sql" "$inputs/exporter-role-bootstrap.sql" \
      "$inputs/prepare-export.env" "$inputs/.production-encryption-key"
  fi
  local state=failed
  [[ "$exit_code" -ne 0 ]] || state=complete
  if [[ -n "$status" && -d "$root" && ! -L "$root" ]]; then
    python3 - "$status" "$state" "$phase" "$exit_code" "$failure_code" \
      "$sha" "$attempt_id" "$execution_image" <<'PY' >/dev/null 2>&1
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
target = Path(sys.argv[1])
temporary = target.with_name("." + target.name + "." + str(os.getpid()) + ".tmp")
payload = {
    "schema": "release.s6-prepare-status.v2",
    "state": sys.argv[2],
    "phase": sys.argv[3],
    "exit_code": int(sys.argv[4]),
    "error_code": sys.argv[5] or None,
    "candidate_sha": sys.argv[6],
    "attempt_id": sys.argv[7],
    "execution_image_id": sys.argv[8] or None,
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
    stream.write(json.dumps(payload, sort_keys=True) + "\n")
    stream.flush()
    os.fsync(stream.fileno())
os.replace(temporary, target)
PY
  fi
  exit "$exit_code"
}
trap finish EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

phase=preflight
test "$(id -u 2>/dev/null)" = 0 || fail S6_PREPARE_ROOT_REQUIRED
test -d "$root" && test ! -L "$root" || fail S6_ATTEMPT_ROOT_INVALID
chmod 700 "$root" 2>/dev/null || fail S6_ATTEMPT_ROOT_MODE_INVALID
test "$(stat -c '%a' "$root" 2>/dev/null)" = 700 || fail S6_ATTEMPT_ROOT_MODE_INVALID
test ! -e "$status" && test ! -L "$status" || fail S6_PREPARE_STATUS_ALREADY_EXISTS
test ! -e "$prepare_receipt" && test ! -L "$prepare_receipt" || fail S6_PREPARE_RECEIPT_ALREADY_EXISTS
test ! -e "$runner_venv" && test ! -L "$runner_venv" || fail S6_RUNNER_VENV_REUSE_REJECTED
test ! -e "$runner_receipt" && test ! -L "$runner_receipt" || fail S6_RUNNER_VENV_REUSE_REJECTED
test ! -e "$runner_create_log" && test ! -L "$runner_create_log" || fail S6_RUNNER_VENV_REUSE_REJECTED
test ! -e "$runner_install_log" && test ! -L "$runner_install_log" || fail S6_RUNNER_VENV_REUSE_REJECTED
test ! -e "$evidence_dir" && test ! -L "$evidence_dir" || fail S6_EVIDENCE_RECEIPT_REUSE_REJECTED
test ! -e "$export_root" && test ! -L "$export_root" || fail S6_PROVIDER_EXPORT_REUSE_REJECTED
test ! -e "$candidate_input_staging" && test ! -L "$candidate_input_staging" \
  || fail S6_CANDIDATE_INPUT_STAGING_REUSE_REJECTED
test -d "$candidate_source" && test ! -L "$candidate_source" || fail S6_CANDIDATE_SOURCE_SNAPSHOT_INVALID
test -f "$candidate_source_receipt" && test ! -L "$candidate_source_receipt" \
  || fail S6_CANDIDATE_SOURCE_RECEIPT_INVALID
test -f "$candidate_source_helper" && test ! -L "$candidate_source_helper" \
  || fail S6_CANDIDATE_SOURCE_HELPER_INVALID
test -f "$failure_helper" && test ! -L "$failure_helper" || fail S6_CANDIDATE_EXPORT_FAILURE_HELPER_INVALID

python3 - "$root" "$inputs" <<'PY' || fail S6_FRESH_ATTEMPT_CONTENTS_INVALID
import os, stat, sys
from pathlib import Path
root, inputs = Path(sys.argv[1]), Path(sys.argv[2])
allowed = {"attempt-plan.json", "candidate-source", "candidate-source-receipt.json",
           "inputs-private", "prepare.log", "prepare.pid"}
try:
    if not {item.name for item in os.scandir(root)}.issubset(allowed):
        raise ValueError
    info = inputs.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError
    files = {}
    for item in os.scandir(inputs):
        entry = item.stat(follow_symlinks=False)
        if not stat.S_ISREG(entry.st_mode):
            raise ValueError
        files[item.name] = stat.S_IMODE(entry.st_mode)
    if files != {"runner.env": 0o600, "vps-password.txt": 0o600}:
        raise ValueError
    for name in files:
        raw = (inputs / name).read_bytes()
        if not raw or b"\x00" in raw or b"\r" in raw or raw.startswith(b"\xef\xbb\xbf"):
            raise ValueError
except (OSError, ValueError):
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_FRESH_BOOTSTRAP_INPUTS_INVALID")
PY
if pgrep -af '[s]cripts/run_release_rehearsal.py' >/dev/null 2>&1; then fail S6_RUNNER_PROCESS_ALREADY_PRESENT; fi
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -Eq '^agom-s6-stage-'; then
  fail S6_STAGE_CONTAINER_ALREADY_PRESENT
fi
for name in "$pg" "$redis"; do
  if docker inspect "$name" >/dev/null 2>&1; then fail S6_ISOLATED_CONTAINER_ALREADY_PRESENT; fi
done
if docker network inspect "$net" >/dev/null 2>&1; then fail S6_ISOLATED_NETWORK_ALREADY_PRESENT; fi
if docker volume inspect "$volume" >/dev/null 2>&1; then fail S6_ISOLATED_VOLUME_ALREADY_PRESENT; fi

verify_log="$root/candidate-source-verify.log"
test ! -e "$verify_log" && test ! -L "$verify_log" || fail S6_CANDIDATE_SOURCE_LOG_REUSE_REJECTED
candidate_gid_from_receipt="$(python3 - "$candidate_source_receipt" <<'PY'
import json, sys
from pathlib import Path
try:
    value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    gid = value.get("container_gid")
    if isinstance(gid, bool) or not isinstance(gid, int) or gid < 0:
        raise ValueError
    print(gid)
except (OSError, ValueError, json.JSONDecodeError):
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_CANDIDATE_SOURCE_RECEIPT_INVALID")
PY
)" || fail S6_CANDIDATE_SOURCE_RECEIPT_INVALID
python3 -B "$candidate_source_helper" --candidate-sha "$sha" --destination "$candidate_source" \
  --receipt "$candidate_source_receipt" --container-gid "$candidate_gid_from_receipt" \
  --verify-only > "$verify_log" 2>&1 || fail S6_CANDIDATE_SOURCE_VERIFY_FAILED
chmod 600 "$verify_log"

docker_root="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null)" || fail S6_DOCKER_DAEMON_UNAVAILABLE
test -n "$docker_root" && test -d "$docker_root" || fail S6_DOCKER_ROOT_INVALID
disk_free="$(df -B1 --output=avail "$docker_root" 2>/dev/null | tail -n 1 | tr -d ' ')" \
  || fail S6_DOCKER_DISK_PROBE_INVALID
case "$disk_free" in *[!0-9]*|'') fail S6_DOCKER_DISK_PROBE_INVALID ;; esac
test "$disk_free" -ge 25769803776 || fail S6_DOCKER_DISK_HEADROOM_INSUFFICIENT
test -f "$requirements_file" && test ! -L "$requirements_file" || fail S6_RUNNER_REQUIREMENTS_INVALID
test "$(sha256sum "$requirements_file" 2>/dev/null | cut -d ' ' -f 1)" = "$requirements_sha256" \
  || fail S6_RUNNER_REQUIREMENTS_HASH_MISMATCH

phase=runner_venv
python3 -m venv "$runner_venv" > "$runner_create_log" 2>&1 || fail S6_RUNNER_VENV_CREATE_FAILED
chmod 600 "$runner_create_log"
"$runner_python" -m pip install --disable-pip-version-check --no-cache-dir --no-input \
  -r "$requirements_file" > "$runner_install_log" 2>&1 || fail S6_RUNNER_VENV_INSTALL_FAILED
chmod 600 "$runner_install_log"
"$runner_python" - "$runner_python" "$requirements_file" "$requirements_sha256" \
  "$runner_install_log" "$runner_receipt" <<'PY' || fail S6_RUNNER_RUNTIME_RECEIPT_INVALID
import hashlib, importlib.metadata, json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
runner_python, requirements, expected, install_log, receipt_path = sys.argv[1:]
if hashlib.sha256(Path(requirements).read_bytes()).hexdigest() != expected:
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_RUNNER_REQUIREMENTS_HASH_MISMATCH")
check = subprocess.run([runner_python, "-c", "import importlib.metadata as m; print(m.version('paramiko'))"],
                       check=False, capture_output=True, text=True)
if check.returncode or check.stdout.strip() != "5.0.0":
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_RUNNER_PARAMIKO_VERSION_MISMATCH")
dist = importlib.metadata.distribution("paramiko")
try:
    direct = json.loads(dist.read_text("direct_url.json") or "{}")
except (TypeError, json.JSONDecodeError):
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_RUNNER_PARAMIKO_PROVENANCE_INVALID")
commit = direct.get("vcs_info", {}).get("commit_id")
if commit != "a4489456b6f65281e172380cc4826cee5e851dbb":
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_RUNNER_PARAMIKO_COMMIT_MISMATCH")
log = Path(install_log)
if log.is_symlink() or not log.is_file() or log.stat().st_mode & 0o077:
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_RUNNER_VENV_LOG_INVALID")
payload = {
    "schema": "release.s6-runner-runtime.v1",
    "requirements_ops_sha256": expected,
    "runner_python": runner_python,
    "paramiko_version": "5.0.0",
    "paramiko_commit": commit,
    "install_log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
    "verified_at": datetime.now(timezone.utc).isoformat(),
}
target = Path(receipt_path)
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
    stream.write(json.dumps(payload, sort_keys=True) + "\n")
    stream.flush()
    os.fsync(stream.fileno())
PY
chmod 600 "$runner_receipt"

phase=production_inputs
web_list="$(docker ps --filter label=com.docker.compose.project=agomtradepro \
  --filter label=com.docker.compose.service=web --format '{{.ID}}' 2>/dev/null)" \
  || fail S6_PRODUCTION_WEB_UNAVAILABLE
web_matches=()
if [[ -n "$web_list" ]]; then mapfile -t web_matches <<< "$web_list"; fi
test "${#web_matches[@]}" -eq 1 && test -n "${web_matches[0]}" || fail S6_PRODUCTION_WEB_AMBIGUOUS
web_container="${web_matches[0]}"
web_container_id="$(docker inspect -f '{{.Id}}' "$web_container" 2>/dev/null)" || fail S6_PRODUCTION_WEB_UNAVAILABLE
execution_image="$(docker inspect -f '{{.Image}}' "$web_container" 2>/dev/null)" || fail S6_PRODUCTION_WEB_UNAVAILABLE
[[ "$execution_image" =~ ^sha256:[0-9a-f]{64}$ ]] || fail S6_EXECUTION_IMAGE_ID_INVALID
candidate_uid="$(docker exec "$web_container" id -u 2>/dev/null)" || fail S6_CANDIDATE_RUNTIME_UID_UNAVAILABLE
candidate_gid="$(docker exec "$web_container" id -g 2>/dev/null)" || fail S6_CANDIDATE_RUNTIME_GID_UNAVAILABLE
case "$candidate_uid:$candidate_gid" in *[!0-9:]*|:*) fail S6_CANDIDATE_RUNTIME_IDENTITY_INVALID ;; esac
test "$candidate_uid" -gt 0 || fail S6_CANDIDATE_RUNTIME_IDENTITY_INVALID
test "$candidate_gid" = "$candidate_gid_from_receipt" || fail S6_CANDIDATE_RUNTIME_GID_MISMATCH
postgres_list="$(docker ps --filter label=com.docker.compose.project=agomtradepro \
  --filter label=com.docker.compose.service=postgres --format '{{.ID}}' 2>/dev/null)" \
  || fail S6_PRODUCTION_POSTGRES_UNAVAILABLE
postgres_matches=()
if [[ -n "$postgres_list" ]]; then mapfile -t postgres_matches <<< "$postgres_list"; fi
test "${#postgres_matches[@]}" -eq 1 && test -n "${postgres_matches[0]}" \
  || fail S6_PRODUCTION_POSTGRES_AMBIGUOUS
production_postgres="${postgres_matches[0]}"
test ! -e "$inputs/provider.env" && test ! -L "$inputs/provider.env" || fail S6_PROVIDER_ENV_REUSE_REJECTED
test ! -e "$inputs/.production-encryption-key" && test ! -L "$inputs/.production-encryption-key" \
  || fail S6_PROVIDER_ENV_REUSE_REJECTED
expected_production_database="$(docker exec "$web_container" python -c '
import django
django.setup()
from django.db import connection, transaction
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("SELECT current_database()")
        print(cursor.fetchone()[0])
' 2>/dev/null)" || fail S6_PRODUCTION_DATABASE_UNAVAILABLE
[[ "$expected_production_database" =~ ^[A-Za-z0-9_]+$ ]] || fail S6_PRODUCTION_DATABASE_IDENTITY_INVALID
production_database_actual="$(docker exec "$production_postgres" sh -eu -c \
  'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atqc "SELECT current_database()"' \
  sh "$expected_production_database" 2>/dev/null)" || fail S6_PRODUCTION_DATABASE_UNAVAILABLE
test "$production_database_actual" = "$expected_production_database" \
  || fail S6_PRODUCTION_DATABASE_IDENTITY_MISMATCH
python3 - "$web_container" "$inputs/provider.env" "$inputs/.production-encryption-key" <<'PY' || fail S6_PROVIDER_ENV_CAPTURE_INVALID
import json, os, re, subprocess, sys
from pathlib import Path

def blocked():
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_PROVIDER_ENV_CAPTURE_INVALID")

container, provider_path, encryption_path = sys.argv[1:]
provider_allowlist = {
    "TUSHARE_TOKEN", "TUSHARE_HTTP_URL", "TUSHARE_REQUEST_MODE",
    "DATA_CENTER_DEPLOYMENT_REGION", "AGOMTRADEPRO_DEPLOYMENT_REGION",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
}
try:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{json .Config.Env}}", container],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        blocked()
    entries = json.loads(result.stdout.decode("utf-8"))
    if not isinstance(entries, list):
        blocked()
    values = {}
    for entry in entries:
        if not isinstance(entry, str) or "=" not in entry:
            blocked()
        key, value = entry.split("=", 1)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is None or key in values:
            blocked()
        if any(char in value for char in "\r\n\x00"):
            blocked()
        values[key] = value
    encryption_key = values.get("AGOMTRADEPRO_ENCRYPTION_KEY", "")
    if not encryption_key:
        blocked()
    provider = {key: values[key] for key in provider_allowlist if key in values}
    provider["DJANGO_SETTINGS_MODULE"] = "core.settings.production"
    for path_text, payload in (
        (provider_path, provider),
        (encryption_path, {"AGOMTRADEPRO_ENCRYPTION_KEY": encryption_key}),
    ):
        path = Path(path_text)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            for key in sorted(payload):
                stream.write(f"{key}={payload[key]}\n")
            stream.flush()
            os.fsync(stream.fileno())
except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
    blocked()
PY
chmod 600 "$inputs/provider.env" "$inputs/.production-encryption-key"

pg_admin_password="$(openssl rand -hex 32 2>/dev/null)" || fail S6_ISOLATED_PASSWORD_GENERATION_FAILED
runtime_password="$(openssl rand -hex 32 2>/dev/null)" || fail S6_ISOLATED_PASSWORD_GENERATION_FAILED
migrator_password="$(openssl rand -hex 32 2>/dev/null)" || fail S6_ISOLATED_PASSWORD_GENERATION_FAILED
exporter_password="$(openssl rand -hex 32 2>/dev/null)" || fail S6_ISOLATED_PASSWORD_GENERATION_FAILED
rehearsal_secret_key="$(openssl rand -hex 64 2>/dev/null)" || fail S6_ISOLATED_PASSWORD_GENERATION_FAILED
rehearsal_export_encryption_key="$(openssl rand -hex 32 2>/dev/null)" || fail S6_ISOLATED_PASSWORD_GENERATION_FAILED
test "$pg_admin_password" != "$runtime_password" && test "$runtime_password" != "$migrator_password" \
  && test "$pg_admin_password" != "$migrator_password" \
  && test "$exporter_password" != "$pg_admin_password" \
  && test "$exporter_password" != "$runtime_password" \
  && test "$exporter_password" != "$migrator_password" || fail S6_ISOLATED_PASSWORD_COLLISION
export S6_PREPARE_ADMIN_PASSWORD="$pg_admin_password"
export S6_PREPARE_RUNTIME_PASSWORD="$runtime_password"
export S6_PREPARE_MIGRATOR_PASSWORD="$migrator_password"
export S6_PREPARE_EXPORTER_PASSWORD="$exporter_password"
export S6_PREPARE_SECRET_KEY="$rehearsal_secret_key"
export S6_PREPARE_EXPORT_ENCRYPTION_KEY="$rehearsal_export_encryption_key"
python3 - "$inputs" "$db" "$pg" "$redis" "$prepare_alias" <<'PY' || fail S6_ISOLATED_ENVIRONMENT_INVALID
import os, re, sys
from pathlib import Path
from urllib.parse import quote
root, database, postgres, redis, prepare_alias = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
admin = os.environ.pop("S6_PREPARE_ADMIN_PASSWORD")
runtime = os.environ.pop("S6_PREPARE_RUNTIME_PASSWORD")
migrator = os.environ.pop("S6_PREPARE_MIGRATOR_PASSWORD")
exporter = os.environ.pop("S6_PREPARE_EXPORTER_PASSWORD")
secret_key = os.environ.pop("S6_PREPARE_SECRET_KEY")
export_encryption_key = os.environ.pop("S6_PREPARE_EXPORT_ENCRYPTION_KEY")
values = {}
for line in (root / "provider.env").read_text(encoding="utf-8").splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        values[key] = value
encryption_key = (root / ".production-encryption-key").read_text(encoding="utf-8").strip().removeprefix("AGOMTRADEPRO_ENCRYPTION_KEY=")
if not secret_key or not encryption_key or not exporter or not export_encryption_key:
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_MIGRATOR_SECRET_INPUT_MISSING")
for password in (admin, runtime, migrator, exporter):
    if re.fullmatch(r"[A-Za-z0-9_-]{32,}", password) is None:
        raise SystemExit("S6_PREPARE_BLOCKED code=S6_ISOLATED_PASSWORD_INVALID")
def write(name, payload):
    for key, value in payload.items():
        if re.fullmatch(r"[A-Z0-9_]+", key) is None or any(ch in value for ch in "\r\n\x00"):
            raise SystemExit("S6_PREPARE_BLOCKED code=S6_ENV_FILE_VALUE_INVALID")
    path = root / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        for key in sorted(payload):
            stream.write(f"{key}={payload[key]}\n")
        stream.flush()
        os.fsync(stream.fileno())
runtime_url = f"postgresql://agomtradepro_runtime:{quote(runtime, safe='')}@{postgres}:5432/{database}"
migrator_url = f"postgresql://agomtradepro_migrator:{quote(migrator, safe='')}@{postgres}:5432/{database}"
exporter_url = f"postgresql://agomtradepro_s6_exporter:{quote(exporter, safe='')}@{prepare_alias}:5432/{database}"
export_values = {}
export_values.update({
    "AGOMTRADEPRO_ENCRYPTION_KEY": export_encryption_key,
    "DATABASE_URL": exporter_url,
    "DJANGO_SETTINGS_MODULE": "core.settings.production",
    "POSTGRES_DB": database,
    "POSTGRES_HOST": prepare_alias,
    "POSTGRES_PASSWORD": exporter,
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "agomtradepro_s6_exporter",
    "SECRET_KEY": secret_key,
})
write("prepare-export.env", export_values)
isolated = dict(values)
isolated.update({
    "AGOM_RELEASE_REHEARSAL_DATABASE": "1",
    "AGOMTRADEPRO_ENCRYPTION_KEY": encryption_key,
    "AGOMTRADEPRO_DATABASE_ROLE": "runtime",
    "DATABASE_URL": runtime_url,
    "DJANGO_SETTINGS_MODULE": "core.settings.production",
    "MIGRATOR_DATABASE_URL": migrator_url,
    "POSTGRES_DB": database,
    "POSTGRES_HOST": postgres,
    "POSTGRES_PASSWORD": runtime,
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "agomtradepro_runtime",
    "SECRET_KEY": secret_key,
    "REDIS_HOST": redis,
    "REDIS_PASSWORD": "",
    "REDIS_PORT": "6379",
    "REDIS_URL": f"redis://{redis}:6379/0",
    "CELERY_BROKER_URL": f"redis://{redis}:6379/1",
})
write("isolated-postgres.env", isolated)
write("isolated-migrator.env", {
    "AGOM_RELEASE_REHEARSAL_DATABASE": "1",
    "AGOMTRADEPRO_ENCRYPTION_KEY": encryption_key,
    "DATABASE_URL": migrator_url,
    "DJANGO_SETTINGS_MODULE": "core.settings.production",
    "POSTGRES_DB": database,
    "POSTGRES_HOST": postgres,
    "POSTGRES_PORT": "5432",
    "SECRET_KEY": secret_key,
})
write("postgres-superuser.env", {
    "POSTGRES_DB": database, "POSTGRES_PASSWORD": admin, "POSTGRES_USER": "agomtradepro"
})
write("bootstrap-secrets.env", {
    "AGOMTRADEPRO_ADMIN_PASSWORD": admin,
    "AGOMTRADEPRO_MIGRATOR_PASSWORD": migrator,
    "AGOMTRADEPRO_RUNTIME_PASSWORD": runtime,
    "AGOMTRADEPRO_S6_EXPORTER_PASSWORD": exporter,
    "PGOPTIONS": "-c log_statement=none -c log_min_duration_statement=-1 -c log_min_duration_sample=-1 -c log_statement_sample_rate=0 -c log_transaction_sample_rate=0 -c log_min_error_statement=panic -c log_parameter_max_length=0 -c log_parameter_max_length_on_error=0",
    "PGPASSWORD": admin,
    "POSTGRES_DB": database,
    "POSTGRES_HOST": postgres,
    "POSTGRES_PASSWORD": admin,
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "agomtradepro",
})
PY
unset S6_PREPARE_ADMIN_PASSWORD S6_PREPARE_RUNTIME_PASSWORD S6_PREPARE_MIGRATOR_PASSWORD \
  S6_PREPARE_EXPORTER_PASSWORD S6_PREPARE_SECRET_KEY S6_PREPARE_EXPORT_ENCRYPTION_KEY
unset pg_admin_password runtime_password migrator_password exporter_password \
  rehearsal_secret_key rehearsal_export_encryption_key
chmod 600 "$inputs/provider.env" "$inputs/prepare-export.env" "$inputs/isolated-postgres.env" \
  "$inputs/isolated-migrator.env" "$inputs/postgres-superuser.env" "$inputs/bootstrap-secrets.env"
test -f "$candidate_source/scripts/postgres_role_bootstrap.sql" \
  && test ! -L "$candidate_source/scripts/postgres_role_bootstrap.sql" || fail S6_BOOTSTRAP_SOURCE_INVALID
test ! -e "$bootstrap" && test ! -L "$bootstrap" || fail S6_BOOTSTRAP_PATH_REUSE_REJECTED
install -m 600 "$candidate_source/scripts/postgres_role_bootstrap.sql" "$bootstrap" \
  || fail S6_BOOTSTRAP_SOURCE_INVALID
test ! -e "$exporter_role_bootstrap" && test ! -L "$exporter_role_bootstrap" \
  || fail S6_BOOTSTRAP_PATH_REUSE_REJECTED
test -f "$candidate_source/scripts/postgres_s6_exporter_role_bootstrap.sql" \
  && test ! -L "$candidate_source/scripts/postgres_s6_exporter_role_bootstrap.sql" \
  || fail S6_BOOTSTRAP_SOURCE_INVALID
install -m 600 "$candidate_source/scripts/postgres_s6_exporter_role_bootstrap.sql" \
  "$exporter_role_bootstrap" || fail S6_BOOTSTRAP_SOURCE_INVALID

phase=isolated_containers
docker network create "$net" >/dev/null 2>&1 || fail S6_ISOLATED_NETWORK_CREATE_FAILED
network_created=1
docker volume create "$volume" >/dev/null 2>&1 || fail S6_ISOLATED_VOLUME_CREATE_FAILED
volume_created=1
docker run -d --name "$pg" --network "$net" --env-file "$inputs/postgres-superuser.env" \
  -v "$volume:/var/lib/postgresql/data" \
  --health-cmd 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  --health-interval=3s --health-timeout=3s --health-retries=60 \
  postgres:16-alpine >/dev/null 2>&1 || fail S6_ISOLATED_POSTGRES_START_FAILED
postgres_created=1
docker run -d --name "$redis" --network "$net" redis:7-alpine >/dev/null 2>&1 \
  || fail S6_ISOLATED_REDIS_START_FAILED
redis_created=1
postgres_ready=0
for _ in $(seq 1 90); do
  health="$(docker inspect -f '{{.State.Health.Status}}' "$pg" 2>/dev/null || true)"
  if [[ "$health" == healthy ]]; then postgres_ready=1; break; fi
  sleep 2
done
test "$postgres_ready" = 1 || fail S6_ISOLATED_POSTGRES_HEALTH_FAILED
redis_ready=0
for _ in $(seq 1 30); do
  if [[ "$(docker exec "$redis" redis-cli ping 2>/dev/null || true)" == PONG ]]; then
    redis_ready=1
    break
  fi
  sleep 1
done
test "$redis_ready" = 1 || fail S6_ISOLATED_REDIS_HEALTH_FAILED

isolated_pg_id="$(docker inspect -f '{{.Id}}' "$pg" 2>/dev/null)" \
  || fail S6_ISOLATED_CONTAINER_IDENTITY_UNAVAILABLE
isolated_redis_id="$(docker inspect -f '{{.Id}}' "$redis" 2>/dev/null)" \
  || fail S6_ISOLATED_CONTAINER_IDENTITY_UNAVAILABLE
isolated_network_id="$(docker network inspect -f '{{.Id}}' "$net" 2>/dev/null)" \
  || fail S6_ISOLATED_NETWORK_IDENTITY_UNAVAILABLE
[[ "$isolated_pg_id" =~ ^[0-9a-f]{64}$ && "$isolated_redis_id" =~ ^[0-9a-f]{64}$ \
  && "$isolated_network_id" =~ ^[0-9a-f]{64}$ ]] || fail S6_ISOLATED_CONTAINER_IDENTITY_INVALID
verify_isolated_runtime_identity() {
  local current_pg current_redis current_network member_output
  local -a members
  current_pg="$(docker inspect -f '{{.Id}}' "$pg" 2>/dev/null)" \
    || fail S6_ISOLATED_CONTAINER_IDENTITY_UNAVAILABLE
  current_redis="$(docker inspect -f '{{.Id}}' "$redis" 2>/dev/null)" \
    || fail S6_ISOLATED_CONTAINER_IDENTITY_UNAVAILABLE
  current_network="$(docker network inspect -f '{{.Id}}' "$net" 2>/dev/null)" \
    || fail S6_ISOLATED_NETWORK_IDENTITY_UNAVAILABLE
  test "$current_pg" = "$isolated_pg_id" && test "$current_redis" = "$isolated_redis_id" \
    && test "$current_network" = "$isolated_network_id" \
    || fail S6_ISOLATED_RUNTIME_IDENTITY_DRIFT
  member_output="$(docker network inspect -f '{{range .Containers}}{{println .Name}}{{end}}' "$net" 2>/dev/null)" \
    || fail S6_ISOLATED_NETWORK_MEMBERS_UNAVAILABLE
  mapfile -t members < <(printf '%s\n' "$member_output" | sed '/^$/d' | sort)
  test "${#members[@]}" -eq 2 && test "${members[0]}" = "$pg" \
    && test "${members[1]}" = "$redis" || fail S6_ISOLATED_NETWORK_MEMBERS_INVALID
}
verify_isolated_runtime_identity

phase=production_snapshot
docker exec "$production_postgres" sh -eu -c \
  'pg_dump -U "$POSTGRES_USER" -d "$1" --format=custom --no-owner --no-acl' \
  sh "$expected_production_database" \
  > "$snapshot" 2> "$root/production-dump.log" || fail S6_PRODUCTION_SNAPSHOT_FAILED
chmod 600 "$root/production-dump.log"
test -s "$snapshot" && test ! -L "$snapshot" || fail S6_PRODUCTION_SNAPSHOT_INVALID
docker exec -i "$pg" sh -eu -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl --exit-on-error' \
  < "$snapshot" > "$root/isolated-restore.log" 2>&1 || fail S6_ISOLATED_RESTORE_FAILED
chmod 600 "$root/isolated-restore.log"
rm -f -- "$snapshot"
test ! -e "$snapshot" && test ! -L "$snapshot" || fail S6_PRODUCTION_DUMP_CLEANUP_FAILED
rm -f -- "$inputs/postgres-superuser.env"

phase=role_bootstrap
docker run --rm --network "$net" --env-file "$inputs/bootstrap-secrets.env" \
  -v "$bootstrap:/postgres-role-bootstrap.sql:ro" --entrypoint sh postgres:16-alpine -eu -c \
  'psql -X -v ON_ERROR_STOP=1 -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" < /postgres-role-bootstrap.sql' \
  > "$root/isolated-role-bootstrap.log" 2>&1 || fail S6_ISOLATED_ROLE_BOOTSTRAP_FAILED
chmod 600 "$root/isolated-role-bootstrap.log"
grep -Fqx 'postgres_role_bootstrap=ok' "$root/isolated-role-bootstrap.log" \
  || fail S6_ISOLATED_ROLE_BOOTSTRAP_RESULT_INVALID
docker run --rm --network "$net" --env-file "$inputs/bootstrap-secrets.env" \
  -v "$exporter_role_bootstrap:/exporter-role-bootstrap.sql:ro" \
  --entrypoint sh postgres:16-alpine -eu -c \
  'psql -X -v ON_ERROR_STOP=1 -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" < /exporter-role-bootstrap.sql' \
  > "$root/isolated-exporter-role-bootstrap.log" 2>&1 \
  || fail S6_ISOLATED_EXPORTER_ROLE_BOOTSTRAP_FAILED
chmod 600 "$root/isolated-exporter-role-bootstrap.log"
grep -Fqx 's6_exporter_role_bootstrap=ok' "$root/isolated-exporter-role-bootstrap.log" \
  || fail S6_ISOLATED_EXPORTER_ROLE_BOOTSTRAP_RESULT_INVALID
rm -f -- "$inputs/bootstrap-secrets.env" "$bootstrap" "$exporter_role_bootstrap"

phase=prepare_network
docker network create --internal "$prepare_network" >/dev/null 2>&1 \
  || fail S6_PREPARE_NETWORK_CREATE_FAILED
prepare_network_created=1
docker network connect --alias "$prepare_alias" "$prepare_network" "$pg" \
  >/dev/null 2>&1 || fail S6_PREPARE_POSTGRES_CONNECT_FAILED
prepare_network_members="$(docker network inspect -f \
  '{{range .Containers}}{{println .Name}}{{end}}' "$prepare_network" 2>/dev/null)" \
  || fail S6_PREPARE_NETWORK_MEMBERS_UNAVAILABLE
test "$prepare_network_members" = "$pg" || fail S6_PREPARE_NETWORK_MEMBERS_INVALID

phase=candidate_exports
mkdir -m 700 -- "$candidate_input_staging" 2>/dev/null || fail S6_CANDIDATE_INPUT_STAGING_CREATE_FAILED
chown "$candidate_uid:$candidate_gid" "$candidate_input_staging" 2>/dev/null \
  || fail S6_CANDIDATE_STAGING_OWNERSHIP_FAILED
mkdir -p -- "$export_root" 2>/dev/null || fail S6_EXPORT_STAGING_CREATE_FAILED
chown "$candidate_uid:$candidate_gid" "$export_root" 2>/dev/null \
  || fail S6_CANDIDATE_STAGING_OWNERSHIP_FAILED
chmod 700 "$export_root" 2>/dev/null || fail S6_CANDIDATE_STAGING_MODE_FAILED

run_candidate_export() {
  local mode="$1"
  local exporter_log="$root/candidate-export-$mode.log"
  local helper_log="$root/candidate-export-cli-$mode.log"
  local current_web_id current_image helper_error docker_argument
  local -a docker_argv helper_argv
  case "$mode" in production|universe|contract) ;; *) fail S6_CANDIDATE_EXPORT_MODE_INVALID ;; esac
  test ! -e "$exporter_log" && test ! -L "$exporter_log" || fail S6_CANDIDATE_EXPORT_LOG_REUSE_REJECTED
  test ! -e "$helper_log" && test ! -L "$helper_log" || fail S6_CANDIDATE_EXPORT_LOG_REUSE_REJECTED
  current_web_id="$(docker inspect -f '{{.Id}}' "$web_container" 2>/dev/null)" || fail S6_PRODUCTION_WEB_UNAVAILABLE
  current_image="$(docker inspect -f '{{.Image}}' "$web_container" 2>/dev/null)" || fail S6_PRODUCTION_WEB_UNAVAILABLE
  test "$current_web_id" = "$web_container_id" && test "$current_image" = "$execution_image" \
    || fail S6_EXECUTION_IMAGE_IDENTITY_DRIFT
  docker_argv=(
    docker run --rm --read-only --user "$candidate_uid:$candidate_gid"
    --network "$prepare_network"
    --tmpfs /tmp:rw,nosuid,nodev,mode=1777,size=2147483648
    --env-file "$inputs/prepare-export.env"
    -e "S6_EXPECTED_CANDIDATE=$sha"
    -e "S6_EXPECTED_DB=$db"
    -e "S6_NETWORK=$net" -e "S6_DATABASE=$db"
    -e "S6_PG_CONTAINER=$pg" -e "S6_REDIS_CONTAINER=$redis"
    -e "S6_ATTEMPT_ID=$attempt_id"
    -e "S6_ATTEMPT_PLAN_SHA256=$attempt_plan_sha256"
    -e "S6_ADVANCE_ISOLATED_MARKET_GRAPH=$advance_isolated_market_graph"
    -e "S6_PG_CONTAINER_ID=$isolated_pg_id"
    -e "S6_REDIS_CONTAINER_ID=$isolated_redis_id"
    -e "S6_NETWORK_ID=$isolated_network_id"
    -e "S6_EXECUTION_IMAGE_ID=$execution_image"
    -e "PGOPTIONS=-c default_transaction_read_only=on -c transaction_read_only=on"
    -v "$candidate_source:/candidate-src:ro"
    -v "$candidate_input_staging:/candidate-inputs:ro"
    -v "$export_root:/candidate-output:rw"
    --entrypoint python "$execution_image"
    /candidate-src/scripts/export_s6_rehearsal_inputs.py "$mode"
  )
  helper_argv=(
    --candidate-sha "$sha" --destination "$candidate_source"
    --receipt "$candidate_source_receipt" --container-gid "$candidate_gid"
    --container-uid "$candidate_uid" --execution-image "$execution_image"
    --input-directory "$candidate_input_staging" --output-directory "$export_root"
    --execution-env-file "$inputs/prepare-export.env" --docker-network "$prepare_network"
    --run-export --export-mode "$mode" --log-path "$exporter_log"
  )
  for docker_argument in "${docker_argv[@]}"; do
    helper_argv+=("--docker-arg=$docker_argument")
  done
  if python3 -B "$candidate_source_helper" "${helper_argv[@]}" > "$helper_log" 2>&1; then
    chmod 600 "$helper_log" "$exporter_log"
    return 0
  fi
  chmod 600 "$helper_log" "$exporter_log" 2>/dev/null || true
  helper_error="$(python3 - "$helper_log" <<'PY'
import json, re, sys
from pathlib import Path
try:
    value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    error = value.get("error") if isinstance(value, dict) else None
    if isinstance(error, str) and re.fullmatch(r"S6_CANDIDATE_(?:SOURCE|EXPORT)_[A-Z0-9_]+", error):
        print(error)
except (OSError, UnicodeError, json.JSONDecodeError):
    pass
PY
)"
  if [[ -n "$helper_error" ]]; then fail "$helper_error"; fi
  fail "$(s6_candidate_export_failure_code "$mode")"
}

run_candidate_market_graph_refresh() {
  local exporter_log="$root/current-market-graph-refresh.log"
  local helper_log="$root/current-market-graph-refresh-cli.log"
  local current_web_id current_image helper_error docker_argument
  local -a docker_argv helper_argv
  test "$advance_isolated_market_graph" = 1 || return 0
  test ! -e "$exporter_log" && test ! -L "$exporter_log" \
    || fail S6_GRAPH_REFRESH_LOG_REUSE_REJECTED
  test ! -e "$helper_log" && test ! -L "$helper_log" \
    || fail S6_GRAPH_REFRESH_LOG_REUSE_REJECTED
  verify_isolated_runtime_identity
  current_web_id="$(docker inspect -f '{{.Id}}' "$web_container" 2>/dev/null)" \
    || fail S6_PRODUCTION_WEB_UNAVAILABLE
  current_image="$(docker inspect -f '{{.Image}}' "$web_container" 2>/dev/null)" \
    || fail S6_PRODUCTION_WEB_UNAVAILABLE
  test "$current_web_id" = "$web_container_id" && test "$current_image" = "$execution_image" \
    || fail S6_EXECUTION_IMAGE_IDENTITY_DRIFT
  docker_argv=(
    docker run --rm --read-only --user "$candidate_uid:$candidate_gid"
    --network "$net"
    --tmpfs /tmp:rw,nosuid,nodev,mode=1777,size=2147483648
    --env-file "$inputs/isolated-postgres.env"
    -e S6_GRAPH_REFRESH_ENABLED=1
    -v "$candidate_source:/candidate-src:ro"
    -v "$candidate_input_staging:/candidate-inputs:ro"
    -v "$export_root:/candidate-output:rw"
    --entrypoint python "$execution_image"
    /candidate-src/scripts/refresh_s6_isolated_market_graph.py
    --candidate-sha "$sha"
    --attempt-id "$attempt_id"
    --attempt-plan-sha256 "$attempt_plan_sha256"
    --database "$db"
    --postgres-container "$pg"
    --redis-container "$redis"
    --database-container-id "$isolated_pg_id"
    --redis-container-id "$isolated_redis_id"
    --network "$net"
    --network-id "$isolated_network_id"
    --execution-image-id "$execution_image"
    --task-id "s6-market-refresh-$attempt_id"
  )
  helper_argv=(
    --candidate-sha "$sha" --destination "$candidate_source"
    --receipt "$candidate_source_receipt" --container-gid "$candidate_gid"
    --container-uid "$candidate_uid" --execution-image "$execution_image"
    --input-directory "$candidate_input_staging" --output-directory "$export_root"
    --execution-env-file "$inputs/isolated-postgres.env" --docker-network "$net"
    --run-market-graph-refresh --attempt-id "$attempt_id"
    --attempt-plan-sha256 "$attempt_plan_sha256" --database "$db"
    --postgres-container "$pg" --redis-container "$redis"
    --postgres-container-id "$isolated_pg_id" --redis-container-id "$isolated_redis_id"
    --network-id "$isolated_network_id" --log-path "$exporter_log"
  )
  for docker_argument in "${docker_argv[@]}"; do
    helper_argv+=("--docker-arg=$docker_argument")
  done
  if python3 -B "$candidate_source_helper" "${helper_argv[@]}" > "$helper_log" 2>&1; then
    chmod 600 "$helper_log" "$exporter_log"
    verify_isolated_runtime_identity
    verify_candidate_files "$export_root" current-market-graph-refresh.json \
      || fail S6_GRAPH_REFRESH_RECEIPT_INVALID
    test ! -e "$candidate_input_staging/current-market-graph-refresh.json" \
      && test ! -L "$candidate_input_staging/current-market-graph-refresh.json" \
      || fail S6_CANDIDATE_INPUT_REUSE_REJECTED
    install -m 400 "$export_root/current-market-graph-refresh.json" \
      "$candidate_input_staging/current-market-graph-refresh.json" \
      || fail S6_CANDIDATE_INPUT_COPY_FAILED
    chown "$candidate_uid:$candidate_gid" "$candidate_input_staging/current-market-graph-refresh.json" \
      || fail S6_CANDIDATE_INPUT_COPY_FAILED
    verify_candidate_files "$candidate_input_staging" current-market-graph-refresh.json \
      || fail S6_GRAPH_REFRESH_RECEIPT_INVALID
    return 0
  fi
  chmod 600 "$helper_log" "$exporter_log" 2>/dev/null || true
  helper_error="$(python3 - "$helper_log" <<'PY'
import json, re, sys
from pathlib import Path
try:
    value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    error = value.get("error") if isinstance(value, dict) else None
    if isinstance(error, str) and re.fullmatch(r"S6_(?:CANDIDATE|GRAPH)_REFRESH_[A-Z0-9_]+", error):
        print(error)
except (OSError, UnicodeError, json.JSONDecodeError):
    pass
PY
)"
  if [[ -n "$helper_error" ]]; then fail "$helper_error"; fi
  fail S6_GRAPH_REFRESH_COMMAND_FAILED
}

verify_candidate_files() {
  local directory="$1"
  shift
  python3 - "$directory" "$candidate_uid" "$candidate_gid" "$@" <<'PY' || fail S6_CANDIDATE_INPUT_TREE_INVALID
import os, stat, sys
from pathlib import Path
root = Path(sys.argv[1])
uid, gid = int(sys.argv[2]), int(sys.argv[3])
expected = set(sys.argv[4:])
try:
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError
    if (info.st_uid, info.st_gid) != (uid, gid):
        raise ValueError
    actual = set()
    for item in os.scandir(root):
        metadata = item.stat(follow_symlinks=False)
        expected_mode = (
            0o400
            if item.name == "current-market-graph-refresh.json"
            and root.name == "candidate-input-staging"
            else 0o600
        )
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != expected_mode:
            raise ValueError
        if (metadata.st_uid, metadata.st_gid) != (uid, gid):
            raise ValueError
        actual.add(item.name)
    if actual != expected:
        raise ValueError
except (OSError, ValueError):
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_CANDIDATE_INPUT_TREE_INVALID")
PY
}

copy_candidate_input() {
  local name="$1"
  test ! -e "$candidate_input_staging/$name" && test ! -L "$candidate_input_staging/$name" \
    || fail S6_CANDIDATE_INPUT_REUSE_REJECTED
  install -m 600 "$export_root/$name" "$candidate_input_staging/$name" \
    || fail S6_CANDIDATE_INPUT_COPY_FAILED
  chown "$candidate_uid:$candidate_gid" "$candidate_input_staging/$name" \
    || fail S6_CANDIDATE_INPUT_COPY_FAILED
}

run_candidate_market_graph_refresh
expected_export_names=(
  provider-settings.json provider-identities.json unit-contract.json provider-policy-preflight.json
)
if [[ "$advance_isolated_market_graph" = 1 ]]; then
  expected_export_names+=(current-market-graph-refresh.json)
fi
run_candidate_export production || fail S6_CANDIDATE_EXPORT_PRODUCTION_FAILED
verify_candidate_files "$export_root" "${expected_export_names[@]}" \
  || fail S6_PRODUCTION_EXPORT_INVALID
python3 -B - "$export_root/provider-settings.json" "$export_root/provider-identities.json" \
  "$export_root/unit-contract.json" "$sha" "$candidate_source" <<'PY' || fail S6_PRODUCTION_EXPORT_INVALID
import json, sys
from pathlib import Path
settings, identities, unit = [json.loads(Path(path).read_text(encoding="utf-8")) for path in sys.argv[1:4]]
sys.path.insert(0, sys.argv[5])
from apps.data_center.infrastructure.rehearsal_identity import parse_complete_rehearsal_identities
if not isinstance(settings, dict) or not settings:
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_PROVIDER_SETTINGS_INVALID")
if not isinstance(identities, list) or not identities:
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_PROVIDER_IDENTITIES_INVALID")
try:
    parse_complete_rehearsal_identities(identities)
except ValueError:
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_PROVIDER_IDENTITIES_INVALID") from None
if not isinstance(unit, dict) or unit.get("schema") != "release.provider-unit-contract.v1" or unit.get("candidate_sha") != sys.argv[4]:
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_UNIT_CONTRACT_INVALID")
PY
copy_candidate_input provider-settings.json
copy_candidate_input provider-identities.json
copy_candidate_input unit-contract.json
expected_input_names=(provider-settings.json provider-identities.json unit-contract.json)
if [[ "$advance_isolated_market_graph" = 1 ]]; then
  expected_input_names+=(current-market-graph-refresh.json)
fi
verify_candidate_files "$candidate_input_staging" "${expected_input_names[@]}" \
  || fail S6_CANDIDATE_INPUT_TREE_INVALID

run_candidate_export universe || fail S6_CANDIDATE_EXPORT_UNIVERSE_FAILED
expected_export_names+=(universe-summary.json)
verify_candidate_files "$export_root" "${expected_export_names[@]}" \
  || fail S6_UNIVERSE_EXPORT_INVALID
python3 - "$export_root/universe-summary.json" <<'PY' || fail S6_UNIVERSE_SCOPE_INVALID
import datetime, json, re, sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
target, count, digest = value.get("target_trade_date"), value.get("universe_count"), value.get("universe_sha256")
try:
    if not isinstance(target, str) or datetime.date.fromisoformat(target).isoformat() != target:
        raise ValueError
except ValueError:
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_UNIVERSE_SCOPE_INVALID")
if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_UNIVERSE_SCOPE_INVALID")
if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
    raise SystemExit("S6_PREPARE_BLOCKED code=S6_UNIVERSE_SCOPE_INVALID")
PY
copy_candidate_input universe-summary.json
expected_input_names+=(universe-summary.json)
if [[ "$advance_isolated_market_graph" = 1 ]]; then
  expected_input_names+=(current-market-graph-refresh.json)
fi
verify_candidate_files "$candidate_input_staging" "${expected_input_names[@]}" \
  || fail S6_CANDIDATE_INPUT_TREE_INVALID
run_candidate_export contract || fail S6_CANDIDATE_EXPORT_CONTRACT_FAILED
verify_candidate_files "$export_root" "${expected_export_names[@]}" \
  || fail S6_EXPORT_FILE_SET_INVALID
for name in provider-settings.json provider-identities.json unit-contract.json \
  provider-policy-preflight.json universe-summary.json; do
  test ! -e "$inputs/$name" && test ! -L "$inputs/$name" || fail S6_PRIVATE_EXPORT_REUSE_REJECTED
  install -m 600 "$export_root/$name" "$inputs/$name" || fail S6_PRIVATE_EXPORT_COPY_FAILED
done
if [[ "$advance_isolated_market_graph" = 1 ]]; then
  test ! -e "$inputs/current-market-graph-refresh.json" \
    && test ! -L "$inputs/current-market-graph-refresh.json" \
    || fail S6_PRIVATE_EXPORT_REUSE_REJECTED
  install -m 400 "$candidate_input_staging/current-market-graph-refresh.json" \
    "$inputs/current-market-graph-refresh.json" \
    || fail S6_PRIVATE_EXPORT_COPY_FAILED
fi

phase=prepare_network_cleanup
docker network disconnect "$prepare_network" "$pg" >/dev/null 2>&1 \
  || fail S6_PREPARE_NETWORK_DISCONNECT_FAILED
docker network rm "$prepare_network" >/dev/null 2>&1 \
  || fail S6_PREPARE_NETWORK_CLEANUP_FAILED
prepare_network_created=0
rm -f -- "$inputs/prepare-export.env" "$inputs/.production-encryption-key"
test ! -e "$inputs/prepare-export.env" && test ! -L "$inputs/prepare-export.env" \
  && test ! -e "$inputs/.production-encryption-key" \
  && test ! -L "$inputs/.production-encryption-key" \
  || fail S6_PREPARE_ENV_CLEANUP_FAILED
if docker network inspect "$prepare_network" >/dev/null 2>&1; then
  fail S6_PREPARE_NETWORK_CLEANUP_FAILED
fi

phase=final_validation
test -x "$runner_python" && test -f "$runner_receipt" && test ! -L "$runner_receipt" \
  || fail S6_RUNNER_RUNTIME_RECEIPT_INVALID
python3 -B "$candidate_source_helper" \
  --candidate-sha "$sha" --destination "$candidate_source" \
  --receipt "$candidate_source_receipt" --container-gid "$candidate_gid" \
  --container-uid "$candidate_uid" --execution-image "$execution_image" \
  --input-directory "$inputs" --output-directory "$export_root" \
  --validate-final-receipt --runner-python "$runner_python" \
  --requirements-sha256 "$requirements_sha256" \
  --postgres-container-id "$isolated_pg_id" \
  --redis-container-id "$isolated_redis_id" --network-id "$isolated_network_id" \
  || fail S6_PREPARE_FINAL_VALIDATION_FAILED
phase=complete
printf 'S6_PREPARE_COMPLETE candidate=%s attempt=%s execution_image_id=%s\n' \
  "$sha" "$attempt_id" "$execution_image"
