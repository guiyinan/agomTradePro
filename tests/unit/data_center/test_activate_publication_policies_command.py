"""Command input-boundary tests for candidate policy activation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from apps.data_center.application.publication_policy_activation import (
    CATALOG_FINGERPRINT_TABLES,
    CatalogFingerprint,
    PublicationPolicyActivationExpectedState,
)
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.management.commands.activate_publication_policies import (
    _candidate_policies,
)


def test_candidate_manifest_hash_and_policy_use_same_read_buffer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A replacement after the first read cannot pair an old hash with new content."""

    dataset = DatasetKey("test.policy", "1.0", "1.0")
    policy = PublicationPolicy(
        dataset=dataset,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "payload_hash"),
        retention_days=365,
    )
    candidate_payload = {
        "schema_version": "1.0",
        "policies": [
            {
                "dataset_key": dataset.value,
                "minimum_coverage_ratio": 1.0,
                "allow_partial": False,
                "conflict_action": "block",
                "required_evidence": ["source", "payload_hash"],
                "retention_days": 365,
            }
        ],
    }
    original_bytes = json.dumps(candidate_payload, separators=(",", ":")).encode("utf-8")
    tampered_payload = json.loads(original_bytes.decode("utf-8"))
    tampered_payload["policies"][0]["minimum_coverage_ratio"] = 0.5
    tampered_bytes = json.dumps(tampered_payload, separators=(",", ":")).encode("utf-8")
    candidate_path = tmp_path / "publication_policies.json"
    candidate_path.write_bytes(original_bytes)
    expected = PublicationPolicyActivationExpectedState(
        active_policies=(policy,),
        active_contract_keys=(dataset,),
        unrelated_catalog_baseline=tuple(
            CatalogFingerprint(table_name=name, row_count=0, sha256="0" * 64)
            for name in sorted(CATALOG_FINGERPRINT_TABLES)
        ),
        published_current_metadata=(),
        candidate_policy_projection_sha256=hashlib.sha256(original_bytes).hexdigest(),
        candidate_target_dataset_keys=(),
    )

    original_read_bytes = Path.read_bytes
    reads = 0

    def replacing_read(path: Path) -> bytes:
        nonlocal reads
        data = original_read_bytes(path)
        if path == candidate_path:
            reads += 1
            if reads == 1:
                path.write_bytes(tampered_bytes)
        return data

    monkeypatch.setattr(Path, "read_bytes", replacing_read)
    candidates, manifest_sha256 = _candidate_policies(candidate_path, expected)

    assert reads == 1
    assert manifest_sha256 == hashlib.sha256(original_bytes).hexdigest()
    assert candidates == (policy,)
