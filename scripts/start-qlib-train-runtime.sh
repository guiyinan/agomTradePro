#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
ENV_FILE="$PROJECT_ROOT/deploy/.env.qlib-train"
ENV_EXAMPLE="$PROJECT_ROOT/deploy/.env.qlib-train.example"
COMPOSE_FILE="$PROJECT_ROOT/docker/docker-compose.qlib-train.yml"

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] docker is required"
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  echo "[INFO] created $ENV_FILE from example"
  echo "[INFO] review SECRET_KEY / DATABASE_URL / REDIS_URL before first real training run"
fi

mkdir -p "$PROJECT_ROOT/runtime/qlib_data" "$PROJECT_ROOT/runtime/qlib_models"

docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --build

echo "[INFO] qlib train runtime started"
echo "[INFO] worker: agomsaaf_qlib_train_worker"
echo "[INFO] logs: docker compose -f $COMPOSE_FILE --env-file $ENV_FILE logs -f"
