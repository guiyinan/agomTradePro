"""Static consistency checks for the read-only VPS runtime verification artifact."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = ROOT / "docs" / "deployment" / "vps-runtime-verification-2026-08-16.json"
PREFLIGHT_PATH = (
    ROOT / "docs" / "deployment" / "web-to-tui-deployment-preflight-20260816004134.json"
)


def _load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


def test_vps_runtime_verification_is_bound_to_current_candidate() -> None:
    artifact = _load(ARTIFACT_PATH)
    preflight = _load(PREFLIGHT_PATH)
    candidate = artifact["candidate"]
    preflight_candidate = preflight["release"]
    assert isinstance(candidate, dict)
    assert isinstance(preflight_candidate, dict)
    assert artifact["version"] == "vps-runtime-verification.v1"
    assert artifact["environment"] == "production"
    assert artifact["read_only"] is True
    assert artifact["outcome"] == "runtime_verified_candidate"
    assert candidate["stable_version"] == preflight_candidate["stable_version"]
    assert candidate["source_commit"] == preflight_candidate["source_commit"]
    assert candidate["image_id"] == preflight["oci_image"]["image_id"]
    assert candidate["release"] == "agomtradepro-web:20260816004134"
    assert artifact["checks"]["health_http_status"] == 200
    assert artifact["checks"]["canonical_schema"] == "ok"
    assert artifact["checks"]["tui_metadata_registry"] == "published and matched"
    assert artifact["checks"]["qlib"]["wrong_qlib_distribution"] == "absent"
    backup = artifact["checks"]["backup"]
    assert backup["bytes"] == 140318641
    assert backup["sha256"] == "4760a38fdfc7ef8570323cfb5dde92ab01eb933cd60d4f6dd08700fc34772752"
    assert backup["remote_pg_restore_list"] == "passed"
    assert backup["download_and_local_hash"] == "passed"
