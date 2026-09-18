"""Collect a candidate-bound, read-only TUI-02 observation reset snapshot.

Stream this source to the trusted VPS as ``python3 -``. It emits only Docker
identity/count metadata and public probe statuses; no credentials or bodies.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import cast

ORIGIN = "https://demo.agomtrade.pro"
CURRENT_IMAGE = "sha256:554f816b6dd2a7155742d3260f1df3eab94864de7aec47c0e67ad5d5738c164d"
CURRENT_MANIFEST_SHA256 = "b0b58b749ef1488695bb32e158f5d2ead8d83c90d5c5050e1e69d3f5a88b6bb6"
PROMETHEUS_IMAGE = "sha256:63805ebb8d2b3920190daf1cb14a60871b16fd38bed42b857a3182bc621f4996"


class ResetProbeError(ValueError):
    """Reject incomplete or drifted reset evidence."""


def _run(*arguments: str) -> str:
    """Run one fixed Docker read and return stripped stdout."""

    result = subprocess.run(
        list(arguments),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return result.stdout.strip()


def _inspect(container: str) -> dict[str, object]:
    """Return one Docker container's bounded identity metadata."""

    raw = _run("docker", "inspect", container)
    value = json.loads(raw)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ResetProbeError("Docker inspect shape drift")
    item = cast(dict[str, object], value[0])
    state = item.get("State")
    if not isinstance(state, dict):
        raise ResetProbeError("Docker state missing")
    health = state.get("Health")
    return {
        "container_id": item.get("Id"),
        "image_id": item.get("Image"),
        "started_at_utc": state.get("StartedAt"),
        "status": state.get("Status"),
        "health": health.get("Status") if isinstance(health, dict) else None,
        "restart_count": item.get("RestartCount"),
    }


def _request(path: str) -> tuple[int, bytes]:
    request = urllib.request.Request(ORIGIN + path)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read(256_000)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read(256_000)


def main() -> int:
    """Emit one exact healthy-current reset snapshot or fail closed."""

    try:
        web = _inspect("agomtradepro-web-1")
        prometheus = _inspect("agomtradepro-prometheus-1")
        mounted_manifest_sha = _run(
            "docker",
            "exec",
            "agomtradepro-web-1",
            "sha256sum",
            "/run/agomtradepro/release-manifest.json",
        ).split()[0]
        health_status, health_body = _request("/api/health/")
        ready_status, ready_body = _request("/api/ready/")
        decision_status, decision_body = _request("/api/decision-ready/")
        decision_payload = json.loads(decision_body)
        decision_blocked = (
            isinstance(decision_payload, dict)
            and decision_payload.get("must_not_use_for_decision") is True
        )
        if (
            web.get("image_id") != CURRENT_IMAGE
            or web.get("status") != "running"
            or web.get("health") != "healthy"
            or prometheus.get("image_id") != PROMETHEUS_IMAGE
            or prometheus.get("status") != "running"
            or mounted_manifest_sha != CURRENT_MANIFEST_SHA256
            or health_status != 200
            or ready_status != 200
            or decision_status != 503
            or not decision_blocked
        ):
            raise ResetProbeError("candidate, monitoring or public stop-line drift")
        report = {
            "schema": "tui02.observation-reset-probe.v1",
            "observed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "web": web,
            "prometheus": prometheus,
            "mounted_manifest_sha256": mounted_manifest_sha,
            "public_probes": {
                "health": {"http_status": health_status, "body_bytes": len(health_body)},
                "ready": {"http_status": ready_status, "body_bytes": len(ready_body)},
                "decision_ready": {
                    "http_status": decision_status,
                    "must_not_use_for_decision": decision_blocked,
                },
            },
            "business_dml_performed": False,
            "decision": "PASS_READ_ONLY",
        }
    except (OSError, ValueError, subprocess.SubprocessError, urllib.error.URLError) as exc:
        print(f"DENY: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
