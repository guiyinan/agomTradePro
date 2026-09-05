#!/bin/sh
set -eu

# Host-level Web recovery for the VPS compose stack.
#
# This intentionally runs outside Docker.  The Web, Celery, and beat
# containers share a neutral PID namespace, so a healthcheck must not kill a
# process in that namespace and must not use a Docker-socket sidecar.  The
# watchdog only restarts the Web container after a bounded unhealthy window.

umask 077

docker_bin="${AGOMTRADEPRO_WATCHDOG_DOCKER_BIN:-docker}"
project="${AGOMTRADEPRO_WATCHDOG_COMPOSE_PROJECT:-agomtradepro}"
target_dir="${AGOMTRADEPRO_WATCHDOG_TARGET_DIR:-/opt/agomtradepro/current}"
compose_file="${AGOMTRADEPRO_WATCHDOG_COMPOSE_FILE:-$target_dir/docker/docker-compose.vps.yml}"
env_file="${AGOMTRADEPRO_WATCHDOG_ENV_FILE:-$target_dir/deploy/.env}"
state_dir="${AGOMTRADEPRO_WATCHDOG_STATE_DIR:-/var/lib/agomtradepro/web-watchdog}"

failure_threshold="${AGOMTRADEPRO_WATCHDOG_FAILURE_THRESHOLD:-3}"
restart_cooldown="${AGOMTRADEPRO_WATCHDOG_RESTART_COOLDOWN_SECONDS:-900}"
restart_window="${AGOMTRADEPRO_WATCHDOG_RESTART_WINDOW_SECONDS:-3600}"
max_restarts="${AGOMTRADEPRO_WATCHDOG_MAX_RESTARTS:-2}"
recovery_timeout="${AGOMTRADEPRO_WATCHDOG_RECOVERY_TIMEOUT_SECONDS:-120}"
recovery_poll="${AGOMTRADEPRO_WATCHDOG_RECOVERY_POLL_SECONDS:-5}"

log() {
    level="$1"
    shift
    printf '[%s] %s\n' "$level" "$*"
}

die() {
    log ERROR "$*" >&2
    exit 2
}

require_uint() {
    name="$1"
    value="$2"
    case "$value" in
        ''|*[!0-9]*) die "$name must be a non-negative integer" ;;
    esac
}

require_uint "AGOMTRADEPRO_WATCHDOG_FAILURE_THRESHOLD" "$failure_threshold"
require_uint "AGOMTRADEPRO_WATCHDOG_RESTART_COOLDOWN_SECONDS" "$restart_cooldown"
require_uint "AGOMTRADEPRO_WATCHDOG_RESTART_WINDOW_SECONDS" "$restart_window"
require_uint "AGOMTRADEPRO_WATCHDOG_MAX_RESTARTS" "$max_restarts"
require_uint "AGOMTRADEPRO_WATCHDOG_RECOVERY_TIMEOUT_SECONDS" "$recovery_timeout"
require_uint "AGOMTRADEPRO_WATCHDOG_RECOVERY_POLL_SECONDS" "$recovery_poll"
[ "$failure_threshold" -gt 0 ] || die "failure threshold must be greater than zero"
[ "$restart_window" -gt 0 ] || die "restart window must be greater than zero"
[ "$recovery_timeout" -gt 0 ] || die "recovery timeout must be greater than zero"
[ "$recovery_poll" -gt 0 ] || die "recovery poll must be greater than zero"

[ -d "$target_dir" ] || die "target directory does not exist: $target_dir"
[ -f "$compose_file" ] || die "compose file does not exist: $compose_file"
[ -f "$env_file" ] || die "compose env file does not exist: $env_file"

mkdir -p "$state_dir"
failure_file="$state_dir/consecutive-unhealthy"
restart_log="$state_dir/restart-epochs"

read_uint_file() {
    file="$1"
    value="0"
    if [ -r "$file" ]; then
        value="$(sed -n '1p' "$file" 2>/dev/null || true)"
    fi
    case "$value" in
        ''|*[!0-9]*) value="0" ;;
    esac
    printf '%s' "$value"
}

write_atomic() {
    file="$1"
    value="$2"
    tmp="$file.tmp.$$"
    printf '%s\n' "$value" >"$tmp"
    mv -f "$tmp" "$file"
}

compose() {
    "$docker_bin" compose \
        -p "$project" \
        -f "$compose_file" \
        --env-file "$env_file" \
        "$@"
}

web_container="$(compose ps -q web 2>/dev/null || true)"
[ -n "$web_container" ] || die "Web container is not present"

health_status="$(
    "$docker_bin" inspect \
        --format '{{.State.Health.Status}}' \
        "$web_container" 2>/dev/null || true
)"
[ -n "$health_status" ] || die "Web container health status is unavailable"

case "$health_status" in
    healthy)
        rm -f "$failure_file"
        log INFO "Web is healthy; no recovery action required"
        exit 0
        ;;
    starting)
        rm -f "$failure_file"
        log INFO "Web healthcheck is still starting; no recovery action required"
        exit 0
        ;;
    unhealthy)
        ;;
    *)
        die "unsupported Web health status: $health_status"
        ;;
esac

failure_count="$(read_uint_file "$failure_file")"
failure_count=$((failure_count + 1))
write_atomic "$failure_file" "$failure_count"

if [ "$failure_count" -lt "$failure_threshold" ]; then
    log WARN "Web is unhealthy ($failure_count/$failure_threshold); waiting before recovery"
    exit 1
fi

now="$(date +%s)"
cutoff=$((now - restart_window))
pruned_log="$restart_log.tmp.$$"
: >"$pruned_log"
if [ -r "$restart_log" ]; then
    while IFS= read -r epoch; do
        case "$epoch" in
            ''|*[!0-9]*) continue ;;
        esac
        if [ "$epoch" -ge "$cutoff" ]; then
            printf '%s\n' "$epoch" >>"$pruned_log"
        fi
    done <"$restart_log"
fi
mv -f "$pruned_log" "$restart_log"

restart_count="$(wc -l <"$restart_log" | tr -d '[:space:]')"
if [ "$max_restarts" -eq 0 ] || [ "$restart_count" -ge "$max_restarts" ]; then
    log ERROR "Web recovery budget exhausted ($restart_count/$max_restarts restarts in ${restart_window}s)"
    exit 1
fi

last_restart=""
if [ -s "$restart_log" ]; then
    last_restart="$(tail -n 1 "$restart_log")"
fi
case "$last_restart" in
    ''|*[!0-9]*) ;;
    *)
        elapsed=$((now - last_restart))
        if [ "$elapsed" -lt 0 ] || [ "$elapsed" -lt "$restart_cooldown" ]; then
            log WARN "Web recovery is in cooldown (${restart_cooldown}s); no restart issued"
            exit 1
        fi
        ;;
esac

log WARN "Web unhealthy for $failure_count checks; restarting only the web service"
if ! compose restart web; then
    log ERROR "compose restart web failed"
    exit 2
fi
printf '%s\n' "$now" >>"$restart_log"
rm -f "$failure_file"

deadline=$((now + recovery_timeout))
while :; do
    health_status="$(
        "$docker_bin" inspect \
            --format '{{.State.Health.Status}}' \
            "$web_container" 2>/dev/null || true
    )"
    if [ "$health_status" = "healthy" ]; then
        log INFO "Web recovered after targeted restart"
        exit 0
    fi

    current="$(date +%s)"
    if [ "$current" -ge "$deadline" ]; then
        break
    fi
    sleep "$recovery_poll"
done

log ERROR "Web did not recover within ${recovery_timeout}s after targeted restart"
exit 1
