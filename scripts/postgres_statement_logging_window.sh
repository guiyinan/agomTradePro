#!/usr/bin/env sh
: "${STATEMENT_LOGGING_STATE:?STATEMENT_LOGGING_STATE is required}"

read_statement_logging_settings() {
  statement_logging_psql query <<'SQL'
SELECT pg_catalog.concat_ws(
  '|',
  current_setting('log_statement'),
  current_setting('log_min_duration_statement'),
  current_setting('log_min_duration_sample'),
  current_setting('log_statement_sample_rate'),
  current_setting('log_transaction_sample_rate'),
  current_setting('log_min_error_statement'),
  current_setting('log_parameter_max_length'),
  current_setting('log_parameter_max_length_on_error')
);
SQL
}

validate_statement_logging_settings() {
  log_statement_value="$1"
  log_min_duration_value="$2"
  log_min_duration_sample_value="$3"
  log_statement_sample_rate_value="$4"
  log_transaction_sample_rate_value="$5"
  log_min_error_value="$6"
  log_parameter_length_value="$7"
  log_parameter_error_length_value="$8"
  case "$log_statement_value" in none|ddl|mod|all) ;;
    *) return 1 ;;
  esac
  printf '%s\n' "$log_min_duration_value" | grep -Eq '^(-1|[0-9]+(us|ms|s|min|h|d)?)$' || return 1
  printf '%s\n' "$log_min_duration_sample_value" | grep -Eq '^(-1|[0-9]+(us|ms|s|min|h|d)?)$' || return 1
  printf '%s\n' "$log_statement_sample_rate_value" | grep -Eq '^(0(\.[0-9]+)?|1(\.0+)?)$' || return 1
  printf '%s\n' "$log_transaction_sample_rate_value" | grep -Eq '^(0(\.[0-9]+)?|1(\.0+)?)$' || return 1
  case "$log_min_error_value" in debug5|debug4|debug3|debug2|debug1|info|notice|warning|error|log|fatal|panic) ;;
    *) return 1 ;;
  esac
  printf '%s\n' "$log_parameter_length_value" | grep -Eq '^(-1|[0-9]+(B|kB|MB|GB|TB)?)$' || return 1
  printf '%s\n' "$log_parameter_error_length_value" | grep -Eq '^(-1|[0-9]+(B|kB|MB|GB|TB)?)$' || return 1
}

load_statement_logging_state() {
  [ -s "$STATEMENT_LOGGING_STATE" ] || return 1
  saved_values="$(cat "$STATEMENT_LOGGING_STATE")"
  old_ifs="$IFS"
  IFS='|'
  set -- $saved_values
  IFS="$old_ifs"
  [ "$#" -eq 8 ] || return 1
  validate_statement_logging_settings "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" || return 1
  SAVED_LOG_STATEMENT="$1"
  SAVED_LOG_MIN_DURATION="$2"
  SAVED_LOG_MIN_DURATION_SAMPLE="$3"
  SAVED_LOG_STATEMENT_SAMPLE_RATE="$4"
  SAVED_LOG_TRANSACTION_SAMPLE_RATE="$5"
  SAVED_LOG_MIN_ERROR="$6"
  SAVED_LOG_PARAMETER_LENGTH="$7"
  SAVED_LOG_PARAMETER_ERROR_LENGTH="$8"
}

restore_statement_logging() {
  [ -e "$STATEMENT_LOGGING_STATE" ] || return 0
  if ! load_statement_logging_state; then
    echo "[ERROR] PostgreSQL statement logging recovery state is invalid" >&2
    return 1
  fi
  statement_logging_psql execute <<'SQL'
ALTER SYSTEM RESET log_statement;
ALTER SYSTEM RESET log_min_duration_statement;
ALTER SYSTEM RESET log_min_duration_sample;
ALTER SYSTEM RESET log_statement_sample_rate;
ALTER SYSTEM RESET log_transaction_sample_rate;
ALTER SYSTEM RESET log_min_error_statement;
ALTER SYSTEM RESET log_parameter_max_length;
ALTER SYSTEM RESET log_parameter_max_length_on_error;
SELECT pg_catalog.pg_reload_conf();
SQL
  current_values="$(read_statement_logging_settings)"
  expected_values="$SAVED_LOG_STATEMENT|$SAVED_LOG_MIN_DURATION|$SAVED_LOG_MIN_DURATION_SAMPLE|$SAVED_LOG_STATEMENT_SAMPLE_RATE|$SAVED_LOG_TRANSACTION_SAMPLE_RATE|$SAVED_LOG_MIN_ERROR|$SAVED_LOG_PARAMETER_LENGTH|$SAVED_LOG_PARAMETER_ERROR_LENGTH"
  if [ "$current_values" != "$expected_values" ]; then
    export SAVED_LOG_STATEMENT SAVED_LOG_MIN_DURATION SAVED_LOG_MIN_DURATION_SAMPLE
    export SAVED_LOG_STATEMENT_SAMPLE_RATE SAVED_LOG_TRANSACTION_SAMPLE_RATE
    export SAVED_LOG_MIN_ERROR SAVED_LOG_PARAMETER_LENGTH SAVED_LOG_PARAMETER_ERROR_LENGTH
    statement_logging_psql execute <<'SQL'
\getenv saved_log_statement SAVED_LOG_STATEMENT
\getenv saved_log_min_duration SAVED_LOG_MIN_DURATION
\getenv saved_log_min_duration_sample SAVED_LOG_MIN_DURATION_SAMPLE
\getenv saved_log_statement_sample_rate SAVED_LOG_STATEMENT_SAMPLE_RATE
\getenv saved_log_transaction_sample_rate SAVED_LOG_TRANSACTION_SAMPLE_RATE
\getenv saved_log_min_error SAVED_LOG_MIN_ERROR
\getenv saved_log_parameter_length SAVED_LOG_PARAMETER_LENGTH
\getenv saved_log_parameter_error_length SAVED_LOG_PARAMETER_ERROR_LENGTH
SELECT pg_catalog.format('ALTER SYSTEM SET log_statement = %L', :'saved_log_statement')
\gexec
SELECT pg_catalog.format('ALTER SYSTEM SET log_min_duration_statement = %L', :'saved_log_min_duration')
\gexec
SELECT pg_catalog.format('ALTER SYSTEM SET log_min_duration_sample = %L', :'saved_log_min_duration_sample')
\gexec
SELECT pg_catalog.format('ALTER SYSTEM SET log_statement_sample_rate = %L', :'saved_log_statement_sample_rate')
\gexec
SELECT pg_catalog.format('ALTER SYSTEM SET log_transaction_sample_rate = %L', :'saved_log_transaction_sample_rate')
\gexec
SELECT pg_catalog.format('ALTER SYSTEM SET log_min_error_statement = %L', :'saved_log_min_error')
\gexec
SELECT pg_catalog.format('ALTER SYSTEM SET log_parameter_max_length = %L', :'saved_log_parameter_length')
\gexec
SELECT pg_catalog.format('ALTER SYSTEM SET log_parameter_max_length_on_error = %L', :'saved_log_parameter_error_length')
\gexec
SELECT pg_catalog.pg_reload_conf();
SQL
  fi
  restored_values="$(read_statement_logging_settings)"
  if [ "$restored_values" != "$expected_values" ]; then
    echo "[ERROR] PostgreSQL statement logging settings were not restored" >&2
    return 1
  fi
  rm -f "$STATEMENT_LOGGING_STATE"
  echo "[INFO] PostgreSQL statement logging settings restored"
}

enter_statement_logging_window() {
  if [ -e "$STATEMENT_LOGGING_STATE" ]; then
    echo "[INFO] Recovering an interrupted PostgreSQL statement logging window"
    restore_statement_logging
  fi
  original_values="$(read_statement_logging_settings)"
  old_ifs="$IFS"
  IFS='|'
  set -- $original_values
  IFS="$old_ifs"
  [ "$#" -eq 8 ] || {
    echo "[ERROR] PostgreSQL statement logging settings could not be captured" >&2
    return 1
  }
  validate_statement_logging_settings "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" || {
    echo "[ERROR] PostgreSQL statement logging settings are invalid" >&2
    return 1
  }
  state_tmp="$STATEMENT_LOGGING_STATE.tmp"
  printf '%s|%s|%s|%s|%s|%s|%s|%s\n' "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" > "$state_tmp"
  chmod 600 "$state_tmp"
  mv -f "$state_tmp" "$STATEMENT_LOGGING_STATE"
  statement_logging_psql execute <<'SQL'
ALTER SYSTEM SET log_statement = 'none';
ALTER SYSTEM SET log_min_duration_statement = '-1';
ALTER SYSTEM SET log_min_duration_sample = '-1';
ALTER SYSTEM SET log_statement_sample_rate = '0';
ALTER SYSTEM SET log_transaction_sample_rate = '0';
ALTER SYSTEM SET log_min_error_statement = 'panic';
ALTER SYSTEM SET log_parameter_max_length = '0';
ALTER SYSTEM SET log_parameter_max_length_on_error = '0';
SELECT pg_catalog.pg_reload_conf();
SQL
  disabled_values="$(read_statement_logging_settings)"
  if [ "$disabled_values" != "none|-1|-1|0|0|panic|0|0" ]; then
    echo "[ERROR] PostgreSQL statement logging was not disabled" >&2
    return 1
  fi
  echo "[INFO] PostgreSQL statement logging disabled for the maintenance window"
}

cleanup_statement_logging_window() {
  status="$?"
  trap - EXIT HUP INT TERM
  if ! restore_statement_logging; then
    exit 1
  fi
  exit "$status"
}
