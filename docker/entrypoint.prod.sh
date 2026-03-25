#!/bin/sh
set -eu

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-core.settings.production}"

# ── Auto-generate security keys ──────────────────────────────────────
# If SECRET_KEY or AGOMTRADEPRO_ENCRYPTION_KEY are not provided via
# environment, generate them on first boot and persist in the data
# volume so all containers (web, celery_worker, celery_beat) share
# the same keys across restarts.
# ─────────────────────────────────────────────────────────────────────
ENV_GENERATED="/app/data/.env.generated"
mkdir -p /app/data

_load_generated_env() {
  if [ -f "$ENV_GENERATED" ]; then
    # Source only KEY=VALUE lines (no export prefix needed — we export below)
    while IFS='=' read -r key value; do
      case "$key" in
        SECRET_KEY|AGOMTRADEPRO_ENCRYPTION_KEY)
          if [ -n "$value" ]; then
            eval "export $key=\"$value\""
          fi
          ;;
      esac
    done < "$ENV_GENERATED"
  fi
}

_save_generated_key() {
  key_name="$1"
  key_value="$2"
  if [ -f "$ENV_GENERATED" ] && grep -q "^${key_name}=" "$ENV_GENERATED"; then
    # Replace existing line (platform-safe: write to tmp then move)
    tmp="${ENV_GENERATED}.tmp"
    sed "s|^${key_name}=.*|${key_name}=${key_value}|" "$ENV_GENERATED" > "$tmp"
    mv "$tmp" "$ENV_GENERATED"
  else
    echo "${key_name}=${key_value}" >> "$ENV_GENERATED"
  fi
}

# Load any previously generated keys first
_load_generated_env

# SECRET_KEY
_secret_key="${SECRET_KEY:-}"
case "$_secret_key" in
  ""|*change-this*|*change_this*|*django-insecure*)
    _new_secret=$(python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())")
    export SECRET_KEY="$_new_secret"
    _save_generated_key "SECRET_KEY" "$_new_secret"
    echo "INFO: Auto-generated SECRET_KEY (persisted to $ENV_GENERATED)"
    ;;
esac

# AGOMTRADEPRO_ENCRYPTION_KEY
if [ -z "${AGOMTRADEPRO_ENCRYPTION_KEY:-}" ]; then
  _new_enc=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
  export AGOMTRADEPRO_ENCRYPTION_KEY="$_new_enc"
  _save_generated_key "AGOMTRADEPRO_ENCRYPTION_KEY" "$_new_enc"
  echo "INFO: Auto-generated AGOMTRADEPRO_ENCRYPTION_KEY (persisted to $ENV_GENERATED)"
fi

# ── Wait for dependencies ────────────────────────────────────────────
wait_for_port() {
  host="$1"
  port="$2"
  name="$3"
  timeout="${4:-60}"

  python - "$host" "$port" "$name" "$timeout" <<'PY'
import socket
import sys
import time

host = sys.argv[1]
port = int(sys.argv[2])
name = sys.argv[3]
timeout = int(sys.argv[4])

start = time.time()
while True:
    try:
        with socket.create_connection((host, port), timeout=3):
            print(f"{name} is ready at {host}:{port}")
            break
    except OSError:
        if time.time() - start > timeout:
            raise SystemExit(f"Timeout waiting for {name} at {host}:{port}")
        time.sleep(1)
PY
}

wait_for_port "${REDIS_HOST:-redis}" "${REDIS_PORT:-6379}" "redis"

is_web_command=0
if [ "$#" -eq 0 ] || [ "$1" = "gunicorn" ]; then
  is_web_command=1
fi

python manage.py migrate --noinput
if [ "$is_web_command" = "1" ]; then
  if [ "${AGOMTRADEPRO_BOOTSTRAP_ON_START:-1}" = "1" ]; then
    bootstrap_args=""
    if [ "${AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START:-1}" = "1" ]; then
      bootstrap_args="$bootstrap_args --with-alpha --alpha-universes ${AGOMTRADEPRO_BOOTSTRAP_ALPHA_UNIVERSES:-csi300} --alpha-top-n ${AGOMTRADEPRO_BOOTSTRAP_ALPHA_TOP_N:-30}"
    fi
    python manage.py bootstrap_cold_start $bootstrap_args
  fi
  if ! python manage.py setup_macro_daily_sync \
    --hour "${MACRO_SYNC_HOUR:-8}" \
    --minute "${MACRO_SYNC_MINUTE:-5}"; then
    echo "WARNING: failed to configure macro periodic tasks" >&2
  fi
fi
python manage.py collectstatic --noinput

if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ] && [ -n "${DJANGO_SUPERUSER_EMAIL:-}" ]; then
python <<'PY'
import os
import django

django.setup()
from django.contrib.auth import get_user_model

User = get_user_model()
username = os.environ["DJANGO_SUPERUSER_USERNAME"]
email = os.environ["DJANGO_SUPERUSER_EMAIL"]
password = os.environ["DJANGO_SUPERUSER_PASSWORD"]

if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, email=email, password=password)
    print("Superuser created")
else:
    print("Superuser already exists")
PY
fi

if [ "$is_web_command" = "1" ]; then
  exec gunicorn core.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-120}"
fi

exec "$@"
