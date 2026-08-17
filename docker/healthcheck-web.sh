#!/bin/sh
set -eu

health_url="${WEB_HEALTH_URL:-http://127.0.0.1:8000/api/health/}"
failure_file="/tmp/agomtradepro-web-health-failures"
failure_threshold="${WEB_HEALTH_SELF_TERMINATE_AFTER_FAILURES:-3}"

if curl -fsS --connect-timeout 2 --max-time 5 "$health_url" >/dev/null; then
    rm -f "$failure_file"
    exit 0
fi

case "$failure_threshold" in
    ''|*[!0-9]*) failure_threshold=3 ;;
esac

failure_count=0
if [ -r "$failure_file" ]; then
    failure_count="$(sed -n '1p' "$failure_file" 2>/dev/null || true)"
fi
case "$failure_count" in
    ''|*[!0-9]*) failure_count=0 ;;
esac
failure_count=$((failure_count + 1))
printf '%s\n' "$failure_count" >"$failure_file"

if [ "$failure_threshold" -gt 0 ] && [ "$failure_count" -ge "$failure_threshold" ]; then
    for proc_path in /proc/[0-9]*; do
        [ -r "$proc_path/cmdline" ] || continue
        pid="${proc_path#/proc/}"
        [ "$pid" = "$$" ] && continue
        command_line="$(tr '\000' ' ' <"$proc_path/cmdline" 2>/dev/null || true)"
        case "$command_line" in
            *daphne*core.asgi:application*)
                echo "Web liveness failed $failure_count times; terminating Daphne PID $pid" >&2
                kill -TERM "$pid" 2>/dev/null || true
                break
                ;;
        esac
    done
fi

exit 1
