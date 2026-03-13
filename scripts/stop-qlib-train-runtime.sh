#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
ENV_FILE="$PROJECT_ROOT/deploy/.env.qlib-train"
COMPOSE_FILE="$PROJECT_ROOT/docker/docker-compose.qlib-train.yml"

docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" down

echo "[INFO] qlib train runtime stopped"
