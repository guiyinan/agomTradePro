#!/usr/bin/env sh
set -eu

log_info() {
  printf '[INFO] %s\n' "$*"
}

log_warn() {
  printf '[WARN] %s\n' "$*" >&2
}

log_error() {
  printf '[ERROR] %s\n' "$*" >&2
}

die() {
  log_error "$*"
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"
}

prompt_default() {
  prompt="$1"
  default_val="$2"
  printf '%s [%s]: ' "$prompt" "$default_val"
  read -r answer
  if [ -z "$answer" ]; then
    printf '%s' "$default_val"
  else
    printf '%s' "$answer"
  fi
}
