"""Read-only web-interval-identity-probe for one EVID-09 Web-only interval.

This source is streamed to the trusted VPS over SSH stdin. It emits only the
selected Web identity and mounted release-manifest digest, never inspect JSON
or environment values. An operator must compare it with its sealed binding.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime

WEB_CONTAINER = "agomtradepro-web-1"
MANIFEST = "/run/agomtradepro/release-manifest.json"
SHA256_LINE = re.compile(r"^([0-9a-f]{64})  /run/agomtradepro/release-manifest\.json$")


class WebIntervalIdentityError(ValueError):
    """Reject missing or malformed read-only Docker evidence."""


def _command(argv: list[str]) -> str:
    """Run one bounded read-only Docker command without printing its body."""

    result = subprocess.run(argv, capture_output=True, text=True, timeout=15, check=False)
    if result.returncode != 0:
        raise WebIntervalIdentityError("Docker identity query failed")
    return result.stdout.strip()


def collect_identity() -> dict[str, object]:
    """Select one running Web image/start event and mounted manifest hash."""

    inspect = json.loads(_command(["docker", "inspect", WEB_CONTAINER]))
    if not isinstance(inspect, list) or len(inspect) != 1 or not isinstance(inspect[0], dict):
        raise WebIntervalIdentityError("Docker inspect shape drift")
    container = inspect[0]
    state = container.get("State")
    if not isinstance(state, dict):
        raise WebIntervalIdentityError("Docker state unavailable")
    health = state.get("Health")
    if not isinstance(health, dict):
        raise WebIntervalIdentityError("Docker health unavailable")
    digest = _command(["docker", "exec", WEB_CONTAINER, "sha256sum", MANIFEST])
    match = SHA256_LINE.fullmatch(digest)
    if match is None:
        raise WebIntervalIdentityError("mounted release manifest digest unavailable")
    return {
        "schema": "evid09.web-interval-identity.v1",
        "observed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "image_id": container.get("Image"),
        "started_at_utc": state.get("StartedAt"),
        "status": state.get("Status"),
        "health": health.get("Status"),
        "release_manifest_sha256": match.group(1),
        "business_dml_performed": False,
        "decision": "PASS_READ_ONLY",
    }


def main() -> int:
    """Emit only selected, nonsecret read-only Docker evidence."""

    try:
        report = collect_identity()
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print("DENY: Web Docker identity unavailable", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
