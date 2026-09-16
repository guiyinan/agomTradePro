#!/usr/bin/env bash
# Exact EVID-09 Web-only target interval with automatic forward recovery.
# Stream over trusted SSH stdin; no source installation or database restore.
set -euo pipefail

MODE="${1:---dry-run}"
case "$MODE" in
  --dry-run|--raw-observation-dry-run|--internal-exercise|--forward-recover|--forward-recover-dry-run) ;;
  *) echo "DENY: unsupported mode" >&2; exit 2 ;;
esac

ROOT=/opt/agomtradepro
CURRENT="$ROOT/releases/source-20260915110952"
TARGET="$ROOT/releases/source-20260914021633"
CURRENT_COMMIT=891c40c5769897931b2b513e92df6f9ba72631ea
TARGET_COMMIT=6760c9aa1607c55e9ae0fd0bcb5435ca32080b0b
CURRENT_ID=sha256:554f816b6dd2a7155742d3260f1df3eab94864de7aec47c0e67ad5d5738c164d
TARGET_ID=sha256:f5647b6d4a17c81963a41dd4d66dee70ccfc4b18e881b368db4b89dda7bf86fd
CURRENT_TAG=agomtradepro-web:20260915110952
TARGET_TAG=agomtradepro-web:20260914021633
CURRENT_MANIFEST_SHA=b0b58b749ef1488695bb32e158f5d2ead8d83c90d5c5050e1e69d3f5a88b6bb6
TARGET_MANIFEST_SHA=b5fcfa71f5635fa95e8d24b4822894e5f4ce4bf0b4c99ee8e3fa5be5cd154167
BACKUP="$ROOT/backups/database/postgres-20260915-051628.dump"
BACKUP_SHA=0a1210ab4a5e3bd0d8cc2630ce6d3f3c421ab1c28d8b53c00fcc90ed16f7250a
NEED_RECOVERY=0
CONTROL_DIR=
CONTROL_FIFO=

deny() { echo "DENY: $1" >&2; exit 1; }
require_image() {
  local tag="$1" id="$2" revision="$3" actual_id actual_revision
  actual_id="$(docker image inspect "$tag" --format '{{.Id}}' 2>/dev/null)" || deny "image tag unavailable"
  actual_revision="$(docker image inspect "$tag" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null)" || deny "image revision unavailable"
  [[ "$actual_id" == "$id" && "$actual_revision" == "$revision" ]] || deny "image identity drift"
}
require_manifest() {
  local path="$1" digest="$2" commit="$3" tag="$4" id="$5"
  [[ ! -L "$path" && -f "$path" && "$(stat -c '%a' "$path")" == 444 ]] || deny "release manifest unavailable or mode drift"
  [[ "$(sha256sum "$path" | cut -d ' ' -f 1)" == "$digest" ]] || deny "release manifest SHA drift"
  python3 - "$path" "$commit" "$tag" "$id" <<'PY' || deny "release manifest identity drift"
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    manifest = json.load(stream)
assert manifest["source_commit"] == sys.argv[2]
assert manifest["image_tag"] == sys.argv[3]
assert manifest["image_id"] == sys.argv[4]
PY
}
compose_web() {
  local release="$1"
  shift
  (cd "$release" && docker compose -p agomtradepro -f docker/docker-compose.vps.yml --env-file deploy/.env "$@")
}
require_current_static() {
  [[ "$(readlink -f "$ROOT/current")" == "$CURRENT" ]] || deny "current release symlink drift"
  require_manifest "$CURRENT/.agom-release-manifest.json" "$CURRENT_MANIFEST_SHA" "$CURRENT_COMMIT" "$CURRENT_TAG" "$CURRENT_ID"
  require_image "$CURRENT_TAG" "$CURRENT_ID" "$CURRENT_COMMIT"
  [[ -f "$BACKUP" && "$(sha256sum "$BACKUP" | cut -d ' ' -f 1)" == "$BACKUP_SHA" ]] || deny "retained database backup drift"
  [[ ! -L "$CURRENT/deploy/prometheus-query.env" && -f "$CURRENT/deploy/prometheus-query.env" ]] || deny "current query env missing"
  [[ "$(stat -c '%a' "$CURRENT/deploy/prometheus-query.env")" == 600 ]] || deny "current query env mode drift"
  compose_web "$CURRENT" config --quiet >/dev/null 2>&1 || deny "current Compose config denied"
}
require_target_static() {
  require_manifest "$TARGET/.agom-release-manifest.json" "$TARGET_MANIFEST_SHA" "$TARGET_COMMIT" "$TARGET_TAG" "$TARGET_ID"
  require_image "$TARGET_TAG" "$TARGET_ID" "$TARGET_COMMIT"
  [[ ! -L "$TARGET/deploy/prometheus-query.env" && -f "$TARGET/deploy/prometheus-query.env" ]] || deny "target query env missing"
  [[ "$(stat -c '%a' "$TARGET/deploy/prometheus-query.env")" == 600 ]] || deny "target query env mode drift"
  compose_web "$TARGET" config --quiet >/dev/null 2>&1 || deny "target Compose config denied"
  cmp -s "$CURRENT/deploy/prometheus-query.env" "$TARGET/deploy/prometheus-query.env" || deny "protected query env source drift"
}
raw_observation_empty() {
  # A direct shell invocation must not bypass the operator's retained-source
  # stop line. Emit no credential, raw label, value, or query body on failure.
  python3 - <<'PY'
import base64
import json
import stat
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

secret = Path('/opt/agomtradepro/prometheus-query-client.secret')
metric_name = 'web_to_tui_migration_events_total'
url = 'https://demo.agomtrade.pro/internal/prometheus/api/v1/query?' + urllib.parse.urlencode({'query': metric_name})
try:
    if secret.is_symlink():
        raise ValueError('credential symlink')
    metadata = secret.stat()
    if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError('credential owner or mode')
    fields = dict(line.split('=', 1) for line in secret.read_text(encoding='utf-8').splitlines())
    if set(fields) != {'PROMETHEUS_QUERY_USER', 'PROMETHEUS_QUERY_PASSWORD'} or not all(fields.values()):
        raise ValueError('credential shape')
    encoded = base64.b64encode((fields['PROMETHEUS_QUERY_USER'] + ':' + fields['PROMETHEUS_QUERY_PASSWORD']).encode()).decode('ascii')
    request = urllib.request.Request(url, headers={'Authorization': 'Basic ' + encoded})
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 200:
            raise ValueError('protected query status')
        payload = json.loads(response.read(256_000))
    if not isinstance(payload, dict) or payload.get('status') != 'success':
        raise ValueError('protected query response')
    data = payload.get('data')
    if not isinstance(data, dict) or data.get('resultType') != 'vector':
        raise ValueError('protected query vector')
    rows = data.get('result')
    if not isinstance(rows, list):
        raise ValueError('protected query rows')
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('metric'), dict) or row['metric'].get('__name__') != metric_name:
            raise ValueError('protected query metric')
    if rows:
        raise ValueError('active raw observation')
except (OSError, ValueError, urllib.error.URLError):
    raise SystemExit(1) from None
PY
}
web_image() { docker inspect agomtradepro-web-1 --format '{{.Image}}' 2>/dev/null || true; }
web_health() { docker inspect agomtradepro-web-1 --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null || true; }
web_started_at() { docker inspect agomtradepro-web-1 --format '{{.State.StartedAt}}' 2>/dev/null || true; }
web_manifest_sha() { docker exec agomtradepro-web-1 sha256sum /run/agomtradepro/release-manifest.json 2>/dev/null | cut -d ' ' -f 1 || true; }
wait_web() {
  local expected_id="$1" expected_manifest="$2" attempt
  for attempt in $(seq 1 60); do
    if [[ "$(web_image)" == "$expected_id" && "$(web_health)" == healthy ]]; then
      [[ "$(docker inspect agomtradepro-web-1 --format '{{.State.Status}}')" == running ]] || deny "Web status not running"
      [[ "$(web_manifest_sha)" == "$expected_manifest" ]] || deny "Web mounted release manifest drift"
      return 0
    fi
    sleep 3
  done
  return 1
}
forward_recovery_lock_dry_run() (
  # Exercise the same read-only manifest inode lock as both recovery paths.
  # This is an identity preflight, never a container recreation or recovery.
  trap - EXIT
  exec 9< "$CURRENT/.agom-release-manifest.json" || exit 1
  flock -x -w 30 9 || exit 1
  require_manifest "$CURRENT/.agom-release-manifest.json" "$CURRENT_MANIFEST_SHA" "$CURRENT_COMMIT" "$CURRENT_TAG" "$CURRENT_ID"
  require_image "$CURRENT_TAG" "$CURRENT_ID" "$CURRENT_COMMIT"
  [[ "$(readlink -f "$ROOT/current")" == "$CURRENT" ]] || exit 1
  [[ "$(web_image)" == "$CURRENT_ID" && "$(web_health)" == healthy && "$(web_manifest_sha)" == "$CURRENT_MANIFEST_SHA" && -n "$(web_started_at)" ]] || exit 1
  echo "FORWARD_RECOVERY_LOCK_DRY_RUN image=$(web_image) started_at=$(web_started_at) health=$(web_health) no_container_changed=true"
)
forward_recover() (
  # Both the EXIT trap and the independent manual entry lock the same
  # immutable manifest inode. A subshell releases the lock on every path.
  trap - EXIT
  echo "FORWARD_RECOVERY_ATTEMPT"
  exec 9< "$CURRENT/.agom-release-manifest.json" || exit 1
  flock -x -w 30 9 || exit 1
  [[ "$(web_image)" == "$TARGET_ID" || "$(web_image)" == "$CURRENT_ID" || -z "$(web_image)" ]] || exit 1
  if [[ "$(web_image)" == "$CURRENT_ID" && "$(web_health)" == healthy && "$(web_manifest_sha)" == "$CURRENT_MANIFEST_SHA" && "$(readlink -f "$ROOT/current")" == "$CURRENT" ]]; then
    echo "FORWARD_RECOVERED image=$(web_image) started_at=$(web_started_at) health=$(web_health) already_current=true"
    exit 0
  fi
  compose_web "$CURRENT" up -d --no-deps --no-build --force-recreate web >/dev/null || exit 1
  wait_web "$CURRENT_ID" "$CURRENT_MANIFEST_SHA" || exit 1
  [[ "$(readlink -f "$ROOT/current")" == "$CURRENT" ]] || exit 1
  echo "FORWARD_RECOVERED image=$(web_image) started_at=$(web_started_at) health=$(web_health)"
)
exit_recover() {
  local previous_exit="$?"
  local recovery_failed=0
  trap - EXIT
  if [[ "$NEED_RECOVERY" == 1 ]]; then
    if forward_recover; then
      echo "RECOVERY_TRAP_SUCCESS previous_exit=$previous_exit"
    else
      echo "RECOVERY_TRAP_FAILED previous_exit=$previous_exit" >&2
      recovery_failed=1
    fi
  fi
  if [[ -n "$CONTROL_DIR" && "$CONTROL_DIR" == /tmp/evid09-web-recovery-* && -d "$CONTROL_DIR" && ! -L "$CONTROL_DIR" ]]; then
    exec 3>&- 3<&- || true
    [[ -z "$CONTROL_FIFO" || "$CONTROL_FIFO" == "$CONTROL_DIR/recovery.fifo" ]] || deny "control FIFO path drift"
    [[ -z "$CONTROL_FIFO" ]] || rm -f -- "$CONTROL_FIFO"
    if ! rmdir -- "$CONTROL_DIR"; then
      echo "CONTROL_FIFO_CLEANUP_DENY" >&2
      recovery_failed=1
    fi
  fi
  if [[ "$previous_exit" != 0 ]]; then
    exit "$previous_exit"
  fi
  if [[ "$recovery_failed" != 0 ]]; then
    exit 1
  fi
}

require_current_static
command -v flock >/dev/null 2>&1 || deny "read-only Web recovery lock unavailable"
if [[ "$MODE" != --forward-recover && "$MODE" != --forward-recover-dry-run ]]; then
  require_target_static
fi
if [[ "$MODE" == --dry-run ]]; then
  [[ "$(web_image)" == "$CURRENT_ID" && "$(web_health)" == healthy && "$(web_manifest_sha)" == "$CURRENT_MANIFEST_SHA" ]] || deny "current Web identity not healthy"
  echo "DRY_RUN_ONLY exact images/manifests/backup/query env/Compose/current Web checked; no container changed"
  exit 0
fi
if [[ "$MODE" == --forward-recover-dry-run ]]; then
  forward_recovery_lock_dry_run || deny "read-only recovery lock preflight failed"
  exit 0
fi
if [[ "$MODE" == --raw-observation-dry-run ]]; then
  raw_observation_empty || deny "active TUI-02 raw observation or query unavailable"
  echo "RAW_OBSERVATION_DRY_RUN no_container_changed=true"
  exit 0
fi

[[ "${EVID09_OWNER_ACTION_TOKEN:-}" == EVID09-891c40c57-6760c9aa-20260915 ]] || deny "owner exact action token missing"
if [[ "$MODE" == --forward-recover ]]; then
  forward_recover || deny "independent forward recovery failed"
  exit 0
fi

# The operator-side entry sets this only after it ran the source-bound fresh
# collectors. It is not an independent attestation or a substitute for them.
[[ "${EVID09_INTERNAL_GATE_SHA256:-}" =~ ^[0-9a-f]{64}$ ]] || deny "source-bound operator gate missing"
[[ "${EVID09_TUI_RESET_ACCEPTED:-}" == true ]] || deny "TUI-02 reset not accepted"
[[ "${EVID09_DOWNTIME_ACCEPTED:-}" == true ]] || deny "bounded Web interruption not accepted"
[[ "$(web_image)" == "$CURRENT_ID" && "$(web_health)" == healthy && "$(web_manifest_sha)" == "$CURRENT_MANIFEST_SHA" ]] || deny "current Web binding drift"
raw_observation_empty || deny "active TUI-02 raw observation or query unavailable"

NEED_RECOVERY=1
trap exit_recover EXIT
CONTROL_DIR="$(mktemp -d -p /tmp evid09-web-recovery-XXXXXX)" || deny "control directory creation failed"
[[ "$CONTROL_DIR" == /tmp/evid09-web-recovery-* && ! -L "$CONTROL_DIR" && "$(stat -c '%a' "$CONTROL_DIR")" == 700 ]] || deny "control directory identity drift"
CONTROL_FIFO="$CONTROL_DIR/recovery.fifo"
mkfifo -m 600 "$CONTROL_FIFO" || deny "control FIFO creation failed"
exec 3<>"$CONTROL_FIFO"
compose_web "$TARGET" up -d --no-deps --no-build --force-recreate web >/dev/null || deny "target Web-only Compose up failed"
wait_web "$TARGET_ID" "$TARGET_MANIFEST_SHA" || deny "target Web did not become healthy within 180s"
echo "TARGET_READY image=$(web_image) started_at=$(web_started_at) health=$(web_health) fifo=$CONTROL_FIFO"

# The source stdin has ended. Recovery instructions arrive only on the
# separately opened, root-only FIFO; 180s timeout reaches the EXIT trap.
IFS= read -r -t 180 operator_instruction <&3 || deny "operator recovery instruction absent or timed out"
[[ "$operator_instruction" == FORWARD_RECOVER ]] || deny "unsupported operator instruction"
forward_recover || deny "forward recovery failed"
NEED_RECOVERY=0
echo "PASS: target Web-only interval and original-image forward recovery"
