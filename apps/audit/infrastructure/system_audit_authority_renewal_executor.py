"""Infrastructure adapter for the scheduled, hash-bound renewal command."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError


def execute_configured_system_audit_authority_renewal() -> dict[str, object]:
    """Execute the configured renewal envelope through the existing command.

    The request file is intentionally host/container supplied.  It contains
    selectors and predecessor hashes, never credentials.  If it is absent,
    the scheduled guard reports a blocked outcome; it never invents a request
    or reuses an expired approval.
    """

    raw_path = os.environ.get("AGOM_SYSTEM_AUDIT_RENEWAL_REQUEST_PATH", "").strip()
    if not raw_path:
        return _blocked("renewal_request_not_configured")
    path = Path(raw_path)
    try:
        if not path.is_file():
            return _blocked("renewal_request_not_found")
    except OSError:
        return _blocked("renewal_request_unavailable")
    output = io.StringIO()
    errors = io.StringIO()
    try:
        call_command(
            "renew_system_audit_authority",
            input=str(path),
            execute=True,
            stdout=output,
            stderr=errors,
        )
    except (CommandError, OSError, TypeError, ValueError):
        return _blocked("renewal_command_failed")
    try:
        payload = json.loads(output.getvalue())
    except (TypeError, ValueError):
        return _blocked("renewal_result_invalid")
    if type(payload) is not dict:
        return _blocked("renewal_result_invalid")
    outcome = payload.get("outcome")
    if outcome not in {"success", "noop", "blocked", "failed"}:
        return _blocked("renewal_result_invalid")
    return {str(key): value for key, value in payload.items()}


def _blocked(reason_code: str) -> dict[str, object]:
    """Return a redacted blocked task payload."""

    return {
        "outcome": "blocked",
        "success": False,
        "stage": "renewal",
        "requested": 1,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
        "block_reason_code": reason_code,
    }


__all__ = ["execute_configured_system_audit_authority_renewal"]
