"""Active-policy gate for original financial source evidence."""

from __future__ import annotations

from .publication_policy_repository import PublicationPolicyRepository

_FINANCIAL_SOURCE_EVIDENCE_KEYS = frozenset(
    {"source_record_id", "published_at", "raw_payload_hash", "raw_payload_scope"}
)


def requires_verified_financial_source_evidence() -> bool:
    """Return whether the active financial policy requires original source proof."""

    policy = PublicationPolicyRepository().get_active("equity.financial.fact")
    return policy is not None and _FINANCIAL_SOURCE_EVIDENCE_KEYS.issubset(policy.required_evidence)


__all__ = ["requires_verified_financial_source_evidence"]
