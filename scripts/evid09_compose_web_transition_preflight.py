"""Read-only EVID-09 Web-only Compose transition semantic preflight.

Stream to the VPS host as ``python3 -``. Compose may contain secrets; only a
secret-free verdict, non-value path names and canonical digests are emitted.
This probe never starts or stops a container.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import cast

CURRENT = Path("/opt/agomtradepro/releases/source-20260915110952")
TARGET = Path("/opt/agomtradepro/releases/source-20260914021633")
MANIFEST_DESTINATION = "/run/agomtradepro/release-manifest.json"
DISABLED_START_FLAGS = (
    "AGOMTRADEPRO_CHECK_DEPLOY_ON_START",
    "AGOMTRADEPRO_AUTO_MIGRATE_ON_START",
    "AGOMTRADEPRO_BOOTSTRAP_ON_START",
    "AGOMTRADEPRO_COLLECTSTATIC_ON_START",
    "AGOMTRADEPRO_SETUP_SCHEDULE_ON_START",
    "AGOMTRADEPRO_ENSURE_SUPERUSER_ON_START",
    "AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START",
)


class ComposeTransitionError(ValueError):
    """Reject an unbounded or unverified production Web service change."""


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ComposeTransitionError("Compose service must be an object")
    return cast(dict[str, object], value)


def collect_web_service(release: Path) -> dict[str, object]:
    """Render, but do not print, the exact release's Web Compose service."""

    command = [
        "docker",
        "compose",
        "-p",
        "agomtradepro",
        "-f",
        "docker/docker-compose.vps.yml",
        "--env-file",
        "deploy/.env",
        "config",
        "--format",
        "json",
    ]
    completed = subprocess.run(
        command, cwd=release, capture_output=True, text=True, timeout=45, check=False
    )
    if completed.returncode != 0:
        raise ComposeTransitionError("release Compose config failed")
    try:
        payload = _object(json.loads(completed.stdout))
        services = _object(payload["services"])
        return _object(services["web"])
    except (KeyError, json.JSONDecodeError) as exc:
        raise ComposeTransitionError("release Web Compose config unavailable") from exc


def normalize_web(service: dict[str, object]) -> dict[str, object]:
    """Normalize only image tag and exact release-manifest bind source."""

    normalized = {**service, "image": "<exact-release-image>"}
    volumes = service.get("volumes")
    if not isinstance(volumes, list):
        raise ComposeTransitionError("Web volumes unavailable")
    bound_manifest = 0
    safe_volumes: list[object] = []
    for raw in cast(list[object], volumes):
        volume = _object(raw)
        if volume.get("target") == MANIFEST_DESTINATION:
            if volume.get("type") != "bind" or volume.get("read_only") is not True:
                raise ComposeTransitionError("manifest bind is not read-only")
            safe_volumes.append({**volume, "source": "<exact-release-manifest>"})
            bound_manifest += 1
        else:
            safe_volumes.append(volume)
    if bound_manifest != 1:
        raise ComposeTransitionError("exactly one manifest bind required")
    normalized["volumes"] = safe_volumes
    return normalized


def difference_paths(left: object, right: object, prefix: str = "web") -> list[str]:
    """Return only structural path names, never Compose scalar values."""

    if isinstance(left, dict) and isinstance(right, dict):
        differences: list[str] = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                differences.append(f"{prefix}.{key}")
            else:
                differences.extend(difference_paths(left[key], right[key], f"{prefix}.{key}"))
        return differences
    if isinstance(left, list) and isinstance(right, list):
        differences = []
        for index in range(max(len(left), len(right))):
            if index >= len(left) or index >= len(right):
                differences.append(f"{prefix}[{index}]")
            else:
                differences.extend(
                    difference_paths(left[index], right[index], f"{prefix}[{index}]")
                )
        return differences
    return [] if left == right else [prefix]


def build_report(current: dict[str, object], target: dict[str, object]) -> dict[str, object]:
    """Require identical Web semantics except image and manifest source."""

    current_normalized = normalize_web(current)
    target_normalized = normalize_web(target)
    differences = difference_paths(current_normalized, target_normalized)
    current_env = _object(current.get("environment"))
    target_env = _object(target.get("environment"))
    start_flags_off = all(
        str(current_env.get(flag)) == "0" and str(target_env.get(flag)) == "0"
        for flag in DISABLED_START_FLAGS
    )
    digests = {
        name: hashlib.sha256(
            json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        for name, config in (("current", current_normalized), ("target", target_normalized))
    }
    return {
        "schema": "evid09.compose-web-transition-preflight.v1",
        "current_release": CURRENT.name,
        "target_release": TARGET.name,
        "rendered_web_config_sha256": digests,
        "only_image_and_manifest_bind_source_may_change": True,
        "normalized_difference_paths": differences,
        "all_startup_mutation_flags_disabled": start_flags_off,
        "compose_or_secret_values_emitted": False,
        "containers_changed": False,
        "decision": (
            "PASS_READ_ONLY" if not differences and start_flags_off else "DENY_CONFIG_DRIFT"
        ),
    }


def main() -> int:
    """Collect both release configs without changing the Docker project."""

    try:
        report = build_report(collect_web_service(CURRENT), collect_web_service(TARGET))
    except (OSError, subprocess.TimeoutExpired, ComposeTransitionError) as exc:
        print(f"DENY: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["decision"] == "PASS_READ_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
