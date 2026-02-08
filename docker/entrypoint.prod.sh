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

wait_for_port "${POSTGRES_HOST:-postgres}" "${POSTGRES_PORT:-5432}" "postgres"
wait_for_port "${REDIS_HOST:-redis}" "${REDIS_PORT:-6379}" "redis"

python manage.py migrate --noinput
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

exec "$@"
