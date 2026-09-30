#!/usr/bin/env bash
set -euo pipefail
set +x

TARGET_DIR="${1:-/opt/agomtradepro}"
MODE="${2:---plan}"
RELEASE_DIR="${3:-$TARGET_DIR/current}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-agomtradepro}"
ENV_FILE="$RELEASE_DIR/deploy/.env"
COMPOSE_FILE="$RELEASE_DIR/docker/docker-compose.vps.yml"

if [ "$MODE" != "--plan" ] && [ "$MODE" != "--apply" ]; then
  echo "usage: $0 [target-dir] [--plan|--apply] [release-dir]" >&2
  exit 2
fi
if [ ! -f "$ENV_FILE" ] || [ ! -f "$COMPOSE_FILE" ]; then
  echo "[ERROR] current VPS release or deploy env file is missing" >&2
  exit 1
fi

get_env_kv() {
  key="$1"
  file="$2"
  grep "^${key}=" "$file" | tail -n 1 | cut -d '=' -f2- || true
}

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "[ERROR] docker compose is required" >&2
  exit 1
fi

compose() {
  $COMPOSE -p "$COMPOSE_PROJECT_NAME" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

if [ "$MODE" = "--plan" ]; then
  compose exec -T postgres sh -eu -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT current_database() AS database_name,
       current_user AS connected_admin,
       (SELECT count(*) FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'S')) AS public_relations,
       (SELECT string_agg(r.rolname, ',' ORDER BY r.rolname)
        FROM pg_catalog.pg_roles r
        WHERE r.rolname IN ('agomtradepro_owner', 'agomtradepro_migrator', 'agomtradepro_runtime'))
         AS existing_role_names;
SELECT n.nspname, c.relname, c.relkind, r.rolname AS current_owner
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
JOIN pg_catalog.pg_roles r ON r.oid = c.relowner
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'S')
ORDER BY c.relkind, c.relname;
SQL
  echo "[INFO] Plan only; rerun with --apply to provision roles and transfer public application objects"
  exit 0
fi

AGOMTRADEPRO_RUNTIME_PASSWORD="$(get_env_kv AGOMTRADEPRO_RUNTIME_PASSWORD "$ENV_FILE")"
AGOMTRADEPRO_MIGRATOR_PASSWORD="$(get_env_kv AGOMTRADEPRO_MIGRATOR_PASSWORD "$ENV_FILE")"
AGOMTRADEPRO_ADMIN_PASSWORD="$(get_env_kv POSTGRES_PASSWORD "$ENV_FILE")"
if [ -z "$AGOMTRADEPRO_RUNTIME_PASSWORD" ] \
  || [ -z "$AGOMTRADEPRO_MIGRATOR_PASSWORD" ] \
  || [ -z "$AGOMTRADEPRO_ADMIN_PASSWORD" ]; then
  echo "[ERROR] admin and role passwords must be configured in deploy/.env" >&2
  exit 1
fi
export AGOMTRADEPRO_RUNTIME_PASSWORD AGOMTRADEPRO_MIGRATOR_PASSWORD AGOMTRADEPRO_ADMIN_PASSWORD

compose exec -T \
  -e AGOMTRADEPRO_ADMIN_PASSWORD \
  -e AGOMTRADEPRO_RUNTIME_PASSWORD \
  -e AGOMTRADEPRO_MIGRATOR_PASSWORD \
  postgres sh -eu -c \
  'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "$RELEASE_DIR/scripts/postgres_role_bootstrap.sql"
