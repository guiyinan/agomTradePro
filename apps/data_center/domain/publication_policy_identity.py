"""Canonical content identity for immutable publication policy versions."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contracts import PublicationPolicy


def publication_policy_content_payload(policy: PublicationPolicy) -> dict[str, object]:
    """Return exact policy decision content, preserving unbound v1 encoding."""

    payload: dict[str, object] = {
        "encoding": "publication-policy-v1",
        "dataset_key": policy.dataset.value,
        "contract_version": policy.dataset.contract_version,
        "schema_version": policy.dataset.schema_version,
        "policy_version": policy.policy_version,
        "minimum_coverage_ratio": float(policy.minimum_coverage_ratio),
        "allow_partial": policy.allow_partial,
        "conflict_action": policy.conflict_action,
        "required_evidence": list(policy.required_evidence),
        "retention_days": policy.retention_days,
    }
    if policy.member_codec_version is not None:
        payload["encoding"] = "publication-policy-v2"
        payload["member_codec_version"] = policy.member_codec_version.value
    return payload


def publication_policy_content_hash(policy: PublicationPolicy) -> str:
    """Hash every decision field, independently of database row update times."""

    raw = json.dumps(
        publication_policy_content_payload(policy),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
