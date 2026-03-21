#!/bin/sh
set -eu

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-core.settings.production}"

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
