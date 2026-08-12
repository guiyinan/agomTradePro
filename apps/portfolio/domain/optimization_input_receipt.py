"""Independent canonical receipt for the complete governed R8 input graph."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ._optimization_canonical import (
    hash_components,
    require_aware,
    require_sha256,
    require_token,
    utc_text,
)
from .governed_input_set import (
    GovernedOptimizationInputSet,
    governed_input_set_hash,
)

RECEIPT_VERSION = "governed-optimization-input-receipt.v1"


@dataclass(frozen=True)
class GovernedOptimizationInputReceipt:
    """Portfolio-recorded immutable receipt over all thirteen typed inputs."""

    receipt_id: str
    receipt_version: str
    owner: str
    input_set: GovernedOptimizationInputSet
    evidence_graph_hash: str
    pit_manifest_set_hash: str
    recorded_at: datetime
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def record(
        cls,
        *,
        input_set: GovernedOptimizationInputSet,
        server_recorded_at: datetime,
    ) -> GovernedOptimizationInputReceipt:
        """Seal one exact input graph using the repository-owned server clock."""

        receipt_id = derive_input_receipt_id(input_set)
        graph_hash = canonical_input_evidence_graph_hash(input_set)
        pit_hash = canonical_input_pit_manifest_set_hash(input_set)
        return cls(
            receipt_id=receipt_id,
            receipt_version=RECEIPT_VERSION,
            owner="portfolio",
            input_set=input_set,
            evidence_graph_hash=graph_hash,
            pit_manifest_set_hash=pit_hash,
            recorded_at=server_recorded_at,
            content_hash=_input_receipt_hash_values(
                receipt_id=receipt_id,
                receipt_version=RECEIPT_VERSION,
                owner="portfolio",
                input_set=input_set,
                evidence_graph_hash=graph_hash,
                pit_manifest_set_hash=pit_hash,
                recorded_at=server_recorded_at,
            ),
        )

    def __post_init__(self) -> None:
        """Replay identity, clocks, owner, PIT graph, and all receipt seals."""

        require_sha256(self.receipt_id, "input receipt_id")
        require_token(self.receipt_version, "input receipt_version")
        require_token(self.owner, "input receipt owner")
        require_aware(self.recorded_at, "input receipt recorded_at")
        if self.receipt_version != RECEIPT_VERSION:
            raise ValueError("input receipt version is unsupported")
        if self.owner != "portfolio":
            raise ValueError("input receipt owner must be portfolio")
        if not self.input_set.created_at <= self.recorded_at < self.input_set.valid_until:
            raise ValueError("input receipt server clock lies outside the input-set window")
        if self.input_set.content_hash != governed_input_set_hash(self.input_set):
            raise ValueError("input receipt contains a stale input-set seal")
        if self.receipt_id != derive_input_receipt_id(self.input_set):
            raise ValueError("input receipt identity does not match its input set")
        require_sha256(self.evidence_graph_hash, "input receipt evidence_graph_hash")
        if self.evidence_graph_hash != canonical_input_evidence_graph_hash(self.input_set):
            raise ValueError("input receipt evidence graph hash mismatch")
        require_sha256(self.pit_manifest_set_hash, "input receipt pit_manifest_set_hash")
        if self.pit_manifest_set_hash != canonical_input_pit_manifest_set_hash(self.input_set):
            raise ValueError("input receipt PIT manifest set hash mismatch")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("input receipt must remain non-executable research evidence")
        require_sha256(self.content_hash, "input receipt content_hash")
        if self.content_hash != input_receipt_hash(self):
            raise ValueError("input receipt content hash mismatch")

    @property
    def input_set_id(self) -> str:
        """Return the independently persisted input-set identifier."""

        return self.input_set.input_set_id

    @property
    def input_set_hash(self) -> str:
        """Return the complete thirteen-input graph seal."""

        return self.input_set.content_hash

    @property
    def valid_until(self) -> datetime:
        """Return the earliest receipt expiry inherited from the graph."""

        return self.input_set.valid_until


def derive_input_receipt_id(input_set: GovernedOptimizationInputSet) -> str:
    """Derive a stable identity without using the repository clock."""

    return hash_components(
        "governed-optimization-input-receipt-id.v1",
        input_set.input_set_id,
        input_set.input_set_version,
        input_set.content_hash,
    )


def canonical_input_evidence_graph_hash(input_set: GovernedOptimizationInputSet) -> str:
    """Seal every typed payload, owner binding, Promotion, universe, and snapshot."""

    return hash_components(
        "governed-optimization-input-evidence-graph.v1",
        input_set.portfolio_snapshot_id,
        input_set.portfolio_snapshot_hash,
        input_set.universe.universe_hash,
        input_set.universe.owner_attestation_hash,
        *(f"payload|{item.kind.value}|{item.content_hash}" for item in input_set.payloads),
        *(
            f"owner|{item.kind.value}|{item.owner}|{item.owner_attestation_hash}"
            for item in input_set.owner_bindings
        ),
        *(
            f"promotion|{item.capability_key}|{item.attestation_hash}"
            for item in input_set.promotions
        ),
    )


def canonical_input_pit_manifest_set_hash(input_set: GovernedOptimizationInputSet) -> str:
    """Seal the complete per-owner PIT manifest membership set."""

    return hash_components(
        "governed-optimization-input-pit-manifest-set.v1",
        *(
            "|".join(
                (
                    item.kind.value,
                    item.owner,
                    item.pit_manifest_id,
                    item.pit_manifest_hash,
                    utc_text(item.knowledge_as_of),
                )
            )
            for item in input_set.owner_bindings
        ),
    )


def input_receipt_hash(receipt: GovernedOptimizationInputReceipt) -> str:
    """Recompute the independent receipt seal."""

    return _input_receipt_hash_values(
        receipt_id=receipt.receipt_id,
        receipt_version=receipt.receipt_version,
        owner=receipt.owner,
        input_set=receipt.input_set,
        evidence_graph_hash=receipt.evidence_graph_hash,
        pit_manifest_set_hash=receipt.pit_manifest_set_hash,
        recorded_at=receipt.recorded_at,
    )


def _input_receipt_hash_values(
    *,
    receipt_id: str,
    receipt_version: str,
    owner: str,
    input_set: GovernedOptimizationInputSet,
    evidence_graph_hash: str,
    pit_manifest_set_hash: str,
    recorded_at: datetime,
) -> str:
    return hash_components(
        RECEIPT_VERSION,
        receipt_id,
        receipt_version,
        owner,
        input_set.input_set_id,
        input_set.input_set_version,
        input_set.contract_version,
        input_set.content_hash,
        evidence_graph_hash,
        pit_manifest_set_hash,
        utc_text(input_set.created_at),
        utc_text(recorded_at),
        utc_text(input_set.valid_until),
        "research_only",
        "must_not_use_for_decision",
        "must_not_execute",
    )


__all__ = [
    "GovernedOptimizationInputReceipt",
    "RECEIPT_VERSION",
    "canonical_input_evidence_graph_hash",
    "canonical_input_pit_manifest_set_hash",
    "derive_input_receipt_id",
    "input_receipt_hash",
]
