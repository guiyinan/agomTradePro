"""EVID-09 secret-free Compose Web-only transition gate tests."""

from __future__ import annotations

import json

import pytest

from scripts.evid09_compose_web_transition_preflight import (
    DISABLED_START_FLAGS,
    ComposeTransitionError,
    build_report,
    normalize_web,
)


def _web(image: str, manifest_source: str) -> dict[str, object]:
    return {
        "image": image,
        "environment": dict.fromkeys(DISABLED_START_FLAGS, "0"),
        "volumes": [
            {
                "type": "bind",
                "source": manifest_source,
                "target": "/run/agomtradepro/release-manifest.json",
                "read_only": True,
            },
            {"type": "volume", "source": "agomtradepro_media", "target": "/app/media"},
        ],
        "depends_on": {"postgres": {"condition": "service_healthy"}},
    }


def test_only_image_and_exact_manifest_source_may_change() -> None:
    report = build_report(
        _web("current", "/current/.agom-release-manifest.json"),
        _web("target", "/target/.agom-release-manifest.json"),
    )
    assert report["decision"] == "PASS_READ_ONLY"
    assert report["normalized_difference_paths"] == []
    assert '"image": "current"' not in json.dumps(report)


def test_secret_or_mount_or_startup_flag_drift_denies_without_values() -> None:
    current = _web("current", "/current/.agom-release-manifest.json")
    target = _web("target", "/target/.agom-release-manifest.json")
    target_environment = target["environment"]
    assert isinstance(target_environment, dict)
    target_environment["DATABASE_URL"] = "PASSWORD_NEVER_EMIT_62420"
    target_environment[DISABLED_START_FLAGS[1]] = "1"
    report = build_report(current, target)
    assert report["decision"] == "DENY_CONFIG_DRIFT"
    assert "web.environment.DATABASE_URL" in report["normalized_difference_paths"]
    assert "PASSWORD_NEVER_EMIT_62420" not in json.dumps(report)


def test_manifest_bind_must_be_unique_and_read_only() -> None:
    service = _web("current", "/current/.agom-release-manifest.json")
    volumes = service["volumes"]
    assert isinstance(volumes, list)
    manifest = volumes[0]
    assert isinstance(manifest, dict)
    manifest["read_only"] = False
    with pytest.raises(ComposeTransitionError, match="read-only"):
        normalize_web(service)
