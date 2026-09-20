"""Date-bound suspension evidence from a completed Qlib build."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from uuid import uuid4


def write_scope_evidence(
    provider_uri: Path,
    target_date: date,
    requested_codes: list[str],
    suspended: dict[str, date],
) -> None:
    """Atomically publish exclusions only after the complete build succeeds."""
    folder = provider_uri / "build_evidence"
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{target_date.isoformat()}.json"
    temporary = folder / f"{uuid4()}.tmp"
    temporary.write_text(
        json.dumps(
            {
                "target_date": target_date.isoformat(),
                "requested_codes": sorted(requested_codes),
                "verified_suspensions": {code: day.isoformat() for code, day in suspended.items()},
            }
        ),
        encoding="utf-8",
    )
    temporary.replace(destination)


def read_scope_suspensions(
    provider_uri: str, target_date: date, requested_codes: list[str]
) -> dict[str, str]:
    """Return verified exclusions for this date and a fully covered requested scope."""
    path = Path(provider_uri).expanduser() / "build_evidence" / f"{target_date.isoformat()}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("target_date") != target_date.isoformat():
            return {}
        covered = payload.get("requested_codes")
        suspended = payload.get("verified_suspensions")
        if (
            not isinstance(covered, list)
            or not all(isinstance(code, str) for code in covered)
            or not set(requested_codes) <= set(covered)
            or not isinstance(suspended, dict)
        ):
            return {}
        result: dict[str, str] = {}
        for code, last_observed in suspended.items():
            if (
                not isinstance(code, str)
                or code not in covered
                or not isinstance(last_observed, str)
                or date.fromisoformat(last_observed) >= target_date
            ):
                return {}
            if code in requested_codes:
                result[code] = last_observed
        return result
    except (OSError, ValueError, TypeError):
        return {}
