"""Collect production provider-policy parity evidence for the release rehearsal.

The S6 publication stages never read the production Config Center provider
policy, so a route-capability regression can stay green through rehearsal and
only block the real full-market task after an hour of provider I/O. This
collector evaluates the exact production preflight gate against an explicit,
hash-bound provider settings snapshot so that class of failure surfaces inside
S6 in seconds.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

from apps.data_center.application.full_market_publication_preflight import (
    CHECK_PROVIDER_POLICY_AND_ROUTES,
)
from apps.data_center.full_market_publication_preflight_composition import (
    build_full_market_publication_preflight_use_case,
)

POLICY_PARITY_REPORT_SCHEMA = "release.production-policy-parity.v1"
POLICY_PARITY_REPORT_KIND = "production_policy_parity"
POLICY_PARITY_EVIDENCE_MODE = "production_policy_snapshot"
POLICY_PARITY_REPORT_NAME = "production-policy-parity.json"

_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")


def _canonical_json_digest(payload: Mapping[str, object]) -> str:
    """Hash the canonical JSON form of one payload deterministically."""

    canonical = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_provider_settings(path: Path) -> dict[str, object]:
    """Read the explicit production provider settings snapshot."""

    if path.is_symlink() or not path.is_file():
        raise ValueError("REHEARSAL_POLICY_SETTINGS_INVALID")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("REHEARSAL_POLICY_SETTINGS_INVALID") from exc
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        raise ValueError("REHEARSAL_POLICY_SETTINGS_INVALID")
    return dict(payload)


def collect_production_policy_parity(
    *,
    candidate_sha: str,
    target_trade_date: date,
    universe_sha256: str,
    provider_identities_sha256: str,
    provider_settings_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Evaluate the production bulk-route gate against the policy snapshot.

    The report is only written when the provider policy check passes; any
    blocked check raises before an artifact exists so the rehearsal stage
    fails closed with the stable REHEARSAL_POLICY_PARITY_* code.
    """

    if output_dir.exists():
        raise ValueError("REHEARSAL_POLICY_PARITY_OUTPUT_EXISTS")
    if _COMMIT.fullmatch(candidate_sha) is None or any(
        _SHA256.fullmatch(value) is None for value in (universe_sha256, provider_identities_sha256)
    ):
        raise ValueError("REHEARSAL_POLICY_PARITY_IDENTITY_INVALID")
    candidate_image_id = os.environ.get("AGOM_CANDIDATE_IMAGE_ID", "")
    if _IMAGE_ID.fullmatch(candidate_image_id) is None:
        raise ValueError("REHEARSAL_POLICY_PARITY_IMAGE_IDENTITY_UNAVAILABLE")
    settings_payload = _read_provider_settings(provider_settings_path)
    settings_digest = _canonical_json_digest(settings_payload)

    started = datetime.now(UTC)
    report = build_full_market_publication_preflight_use_case(
        provider_settings_override=settings_payload,
    ).execute(checks=(CHECK_PROVIDER_POLICY_AND_ROUTES,))
    finished = datetime.now(UTC)
    provider_check = report.checks[0]
    if provider_check.status != "pass":
        raise ValueError("REHEARSAL_POLICY_PARITY_BLOCKED")

    payload: dict[str, object] = {
        "schema": POLICY_PARITY_REPORT_SCHEMA,
        "kind": POLICY_PARITY_REPORT_KIND,
        "candidate_sha": candidate_sha,
        "candidate_image_id": candidate_image_id,
        "candidate_source_attestation": "image_release_manifest",
        "target_trade_date": target_trade_date.isoformat(),
        "universe_sha256": universe_sha256,
        "provider_identities_sha256": provider_identities_sha256,
        "outcome": "success",
        "evidence_mode": POLICY_PARITY_EVIDENCE_MODE,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "provider_settings": settings_payload,
        "provider_settings_sha256": settings_digest,
        "preflight": provider_check.to_dict(),
    }
    output_dir.mkdir(parents=True)
    report_path = output_dir / POLICY_PARITY_REPORT_NAME
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


__all__ = [
    "POLICY_PARITY_EVIDENCE_MODE",
    "POLICY_PARITY_REPORT_KIND",
    "POLICY_PARITY_REPORT_NAME",
    "POLICY_PARITY_REPORT_SCHEMA",
    "collect_production_policy_parity",
]
