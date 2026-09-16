#!/usr/bin/env bash
# EVID-09: exact, web-only image exercise. Dry-run is the only default.
set -euo pipefail

MODE="${1:---dry-run}"
case "$MODE" in
  --dry-run|--repair-prerequisites|--exercise) ;;
  *) echo "DENY: unsupported action" >&2; exit 2 ;;
esac

ROOT=/opt/agomtradepro
CURRENT="$ROOT/releases/source-20260915110952"
TARGET="$ROOT/releases/source-20260914021633"
CURRENT_COMMIT=891c40c5769897931b2b513e92df6f9ba72631ea
TARGET_COMMIT=6760c9aa1607c55e9ae0fd0bcb5435ca32080b0b
CURRENT_ID=sha256:554f816b6dd2a7155742d3260f1df3eab94864de7aec47c0e67ad5d5738c164d
TARGET_ID=sha256:f5647b6d4a17c81963a41dd4d66dee70ccfc4b18e881b368db4b89dda7bf86fd
CURRENT_MANIFEST_SHA=b0b58b749ef1488695bb32e158f5d2ead8d83c90d5c5050e1e69d3f5a88b6bb6
TARGET_MANIFEST_SHA=b5fcfa71f5635fa95e8d24b4822894e5f4ce4bf0b4c99ee8e3fa5be5cd154167
BACKUP="$ROOT/backups/database/postgres-20260915-051628.dump"
BACKUP_SHA=0a1210ab4a5e3bd0d8cc2630ce6d3f3c421ab1c28d8b53c00fcc90ed16f7250a
CURRENT_TAG=agomtradepro-web:20260915110952
TARGET_TAG=agomtradepro-web:20260914021633
ALIAS_TAG=agomtradepro-evid09-compatible-rollback:20260914021633

deny() { echo "DENY: $1" >&2; exit 1; }
require_image() {
  local tag="$1" id="$2" revision="$3" actual_id actual_revision
  actual_id="$(docker image inspect "$tag" --format '{{.Id}}' 2>/dev/null)" || deny "missing image tag $tag"
  actual_revision="$(docker image inspect "$tag" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null)" || deny "missing OCI revision $tag"
  [[ "$actual_id" == "$id" && "$actual_revision" == "$revision" ]] || deny "image identity drift $tag"
}
require_manifest() {
  local path="$1" digest="$2" commit="$3" tag="$4" id="$5"
  [[ ! -L "$path" && -f "$path" ]] || deny "manifest unavailable"
  [[ "$(stat -c '%a' "$path")" == 444 ]] || deny "manifest mode drift"
  [[ "$(sha256sum "$path" | cut -d ' ' -f 1)" == "$digest" ]] || deny "manifest digest drift"
  python3 - "$path" "$commit" "$tag" "$id" <<'PY' || deny "manifest identity drift"
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    manifest = json.load(stream)
assert manifest["source_commit"] == sys.argv[2]
assert manifest["image_tag"] == sys.argv[3]
assert manifest["image_id"] == sys.argv[4]
PY
}
require_env() {
  local path="$1"
  [[ ! -L "$path" && -f "$path" ]] || deny "protected query env missing"
  [[ "$(stat -c '%a' "$path")" == 600 ]] || deny "protected query env mode drift"
  [[ "$(stat -c '%s' "$path")" -gt 0 ]] || deny "protected query env empty"
}
require_current() {
  [[ "$(readlink -f "$ROOT/current")" == "$CURRENT" ]] || deny "current release drift"
  require_manifest "$CURRENT/.agom-release-manifest.json" "$CURRENT_MANIFEST_SHA" "$CURRENT_COMMIT" "$CURRENT_TAG" "$CURRENT_ID"
  require_manifest "$TARGET/.agom-release-manifest.json" "$TARGET_MANIFEST_SHA" "$TARGET_COMMIT" "$TARGET_TAG" "$TARGET_ID"
  require_image "$CURRENT_TAG" "$CURRENT_ID" "$CURRENT_COMMIT"
  require_image "$ALIAS_TAG" "$TARGET_ID" "$TARGET_COMMIT"
  [[ -f "$BACKUP" && "$(sha256sum "$BACKUP" | cut -d ' ' -f 1)" == "$BACKUP_SHA" ]] || deny "retained backup drift"
  require_env "$CURRENT/deploy/prometheus-query.env"
  [[ "$(docker inspect agomtradepro-web-1 --format '{{.State.Status}}' 2>/dev/null)" == running ]] || deny "web not running"
  [[ "$(docker inspect agomtradepro-web-1 --format '{{.Image}}')" == "$CURRENT_ID" ]] || deny "running web image drift"
}

require_current
if [[ "$MODE" == --dry-run ]]; then
  READY=1
  if docker image inspect "$TARGET_TAG" >/dev/null 2>&1; then
    require_image "$TARGET_TAG" "$TARGET_ID" "$TARGET_COMMIT"
    echo "PASS: target original tag"
  else
    echo "DENY: target original tag missing"
    READY=0
  fi
  if [[ -f "$TARGET/deploy/prometheus-query.env" ]]; then
    require_env "$TARGET/deploy/prometheus-query.env"
    echo "PASS: target protected-query env"
  else
    echo "DENY: target protected-query env missing"
    READY=0
  fi
  echo "PASS: current/target/forward manifests, retained images, backup, current env and web binding"
  echo "DRY_RUN_ONLY: no Docker or release mutation"
  [[ "$READY" == 1 ]] || exit 1
  exit 0
fi

[[ "${EVID09_OWNER_ACTION_TOKEN:-}" == "EVID09-891c40c57-6760c9aa-20260915" ]] || deny "exact owner action token missing"
if [[ "$MODE" == --repair-prerequisites ]]; then
  if docker image inspect "$TARGET_TAG" >/dev/null 2>&1; then
    require_image "$TARGET_TAG" "$TARGET_ID" "$TARGET_COMMIT"
  else
    docker tag "$ALIAS_TAG" "$TARGET_TAG"
    require_image "$TARGET_TAG" "$TARGET_ID" "$TARGET_COMMIT"
  fi
  if [[ -e "$TARGET/deploy/prometheus-query.env" ]]; then
    require_env "$TARGET/deploy/prometheus-query.env"
    cmp -s "$CURRENT/deploy/prometheus-query.env" "$TARGET/deploy/prometheus-query.env" || deny "target query env differs from approved current source"
  else
    install -m 600 "$CURRENT/deploy/prometheus-query.env" "$TARGET/deploy/prometheus-query.env"
    require_env "$TARGET/deploy/prometheus-query.env"
    cmp -s "$CURRENT/deploy/prometheus-query.env" "$TARGET/deploy/prometheus-query.env" || deny "query env copy mismatch"
  fi
  echo "PASS: exact target tag and host-only query env repaired; credential contents not printed"
  exit 0
fi

require_image "$TARGET_TAG" "$TARGET_ID" "$TARGET_COMMIT"
require_env "$TARGET/deploy/prometheus-query.env"
cmp -s "$CURRENT/deploy/prometheus-query.env" "$TARGET/deploy/prometheus-query.env" || deny "target query env source drift"
[[ "${EVID09_FRESH_PRESERVATION_VERIFIED:-}" == true ]] || deny "fresh Authority/Policy/Catalog/News preservation not independently verified"
[[ "${EVID09_HTTPS_STOP_LINES_VERIFIED:-}" == true ]] || deny "fresh TLS health/db/ready 200 and decision 503 not independently verified"
[[ "${EVID09_TUI_RESET_ACCEPTED:-}" == true ]] || deny "TUI-02 observation reset not accepted"
[[ "${EVID09_DOWNTIME_ACCEPTED:-}" == true ]] || deny "bounded web interruption not accepted"
deny "live web switch disabled until independently captured fresh preservation and recovery evidence is bound to this runner"
