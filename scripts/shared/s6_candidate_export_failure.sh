#!/usr/bin/env bash

# Return the stable, mode-specific prepare error for a failed candidate export.
s6_candidate_export_failure_code() {
  local s6_export_mode="${1-}"
  case "$s6_export_mode" in
    production)
      printf 'S6_CANDIDATE_EXPORT_PRODUCTION_FAILED\n'
      ;;
    universe)
      printf 'S6_CANDIDATE_EXPORT_UNIVERSE_FAILED\n'
      ;;
    contract)
      printf 'S6_CANDIDATE_EXPORT_CONTRACT_FAILED\n'
      ;;
    *)
      printf 'S6_CANDIDATE_EXPORT_MODE_INVALID\n'
      return 2
      ;;
  esac
}
