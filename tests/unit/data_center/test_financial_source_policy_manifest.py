"""Financial decision policy must reject calendar-only legacy provenance."""

from __future__ import annotations

import json
from pathlib import Path


def test_financial_candidate_requires_source_time_and_original_response_evidence() -> None:
    """The rollout must not allow normalized row hashes to certify source evidence."""

    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / "governance/publication_policies.json").read_text("utf-8"))
    financial = next(
        row for row in manifest["policies"] if row["dataset_key"] == "equity.financial.fact"
    )
    assert financial["policy_version"] == "3"
    assert {
        "source",
        "observed_at",
        "available_at",
        "fetched_at",
        "payload_hash",
        "fact_content_hash",
        "source_record_id",
        "published_at",
        "raw_payload_hash",
        "raw_payload_scope",
    } <= set(financial["required_evidence"])
