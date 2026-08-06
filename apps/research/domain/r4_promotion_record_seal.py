"""Complete Portfolio owner-record seal for R4 promotion trials."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .r4_promotion_evidence import (
    R4ArtifactBlocker,
    R4PromotionMethodSummaryEvidence,
    R4PromotionR3AttestationEvidence,
    R4PromotionWindowEvidence,
    R4PromotionWindowMetricEvidence,
    R4RecordSubhash,
)
from .r4_promotion_scope_policy import (
    _hash_payload,
    _require_aware,
    _require_hash,
    _require_token,
    _utc_text,
)


@dataclass(frozen=True)
class R4PromotionPortfolioRecordSeal:
    """Complete exact Portfolio Application owner record surface."""

    owner: str
    owner_record_key: str
    record_id: str
    record_version: str
    record_hash: str
    study_id: str
    study_version: str
    study_content_hash: str
    artifact_hash: str
    r3_attestation_hash: str
    split_contract_hash: str
    split_policy_version: str
    record_subhashes: tuple[R4RecordSubhash, ...]
    evaluated_at: datetime
    recorded_at: datetime
    valid_until: datetime
    producer_code_version: str
    dependency_lock_hash: str
    cost_semantics_version: str
    windows: tuple[R4PromotionWindowEvidence, ...]
    window_metrics: tuple[R4PromotionWindowMetricEvidence, ...]
    method_summaries: tuple[R4PromotionMethodSummaryEvidence, ...]
    exposure_point_hashes: tuple[str, ...]
    regime_summary_hashes: tuple[str, ...]
    regime_covered_fold_ids: tuple[str, ...]
    artifact_evidence_complete: bool
    artifact_eligible: bool
    artifact_blockers: tuple[R4ArtifactBlocker, ...]
    record_r3_attestation: R4PromotionR3AttestationEvidence
    content_hash: str
    usage_scope: str = "research_only"
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        owner_record_key: str,
        record_id: str,
        record_version: str,
        record_hash: str,
        study_id: str,
        study_version: str,
        study_content_hash: str,
        artifact_hash: str,
        r3_attestation_hash: str,
        split_contract_hash: str,
        split_policy_version: str,
        record_subhashes: tuple[R4RecordSubhash, ...],
        evaluated_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        producer_code_version: str,
        dependency_lock_hash: str,
        cost_semantics_version: str,
        windows: tuple[R4PromotionWindowEvidence, ...],
        window_metrics: tuple[R4PromotionWindowMetricEvidence, ...],
        method_summaries: tuple[R4PromotionMethodSummaryEvidence, ...],
        exposure_point_hashes: tuple[str, ...],
        regime_summary_hashes: tuple[str, ...],
        regime_covered_fold_ids: tuple[str, ...],
        artifact_evidence_complete: bool,
        artifact_eligible: bool,
        artifact_blockers: tuple[R4ArtifactBlocker, ...],
        record_r3_attestation: R4PromotionR3AttestationEvidence,
    ) -> R4PromotionPortfolioRecordSeal:
        """Seal every promotion-relevant Portfolio owner record field."""

        values = (
            "portfolio",
            owner_record_key,
            record_id,
            record_version,
            record_hash,
            study_id,
            study_version,
            study_content_hash,
            artifact_hash,
            r3_attestation_hash,
            split_contract_hash,
            split_policy_version,
            record_subhashes,
            evaluated_at,
            recorded_at,
            valid_until,
            producer_code_version,
            dependency_lock_hash,
            cost_semantics_version,
            windows,
            window_metrics,
            method_summaries,
            exposure_point_hashes,
            regime_summary_hashes,
            regime_covered_fold_ids,
            artifact_evidence_complete,
            artifact_eligible,
            artifact_blockers,
            record_r3_attestation,
        )
        digest = _hash_payload(_portfolio_record_payload(*values))
        return cls(*values, digest)

    def __post_init__(self) -> None:
        if self.owner != "portfolio":
            raise ValueError("R4 promotion owner record must be Portfolio-owned")
        for identifier_name, identifier_value in (
            ("owner_record_key", self.owner_record_key),
            ("record_id", self.record_id),
            ("record_version", self.record_version),
            ("study_id", self.study_id),
            ("study_version", self.study_version),
            ("producer_code_version", self.producer_code_version),
            ("cost_semantics_version", self.cost_semantics_version),
            ("split_policy_version", self.split_policy_version),
        ):
            _require_token(
                identifier_value,
                f"R4 promotion owner record {identifier_name}",
            )
        for hash_name, hash_value in (
            ("record_hash", self.record_hash),
            ("study_content_hash", self.study_content_hash),
            ("artifact_hash", self.artifact_hash),
            ("r3_attestation_hash", self.r3_attestation_hash),
            ("split_contract_hash", self.split_contract_hash),
            ("dependency_lock_hash", self.dependency_lock_hash),
            ("content_hash", self.content_hash),
        ):
            _require_hash(hash_value, f"R4 promotion owner record {hash_name}")
        for clock_name, clock_value in (
            ("evaluated_at", self.evaluated_at),
            ("recorded_at", self.recorded_at),
            ("valid_until", self.valid_until),
        ):
            _require_aware(clock_value, f"R4 promotion owner record {clock_name}")
        if not self.evaluated_at <= self.recorded_at < self.valid_until:
            raise ValueError("R4 promotion owner record time window is invalid")
        labels = tuple(label for label, _ in self.record_subhashes)
        if not labels or labels != tuple(sorted(set(labels))):
            raise ValueError("R4 promotion record subhashes must be complete and ordered")
        for label, digest in self.record_subhashes:
            _require_token(label, "R4 promotion subhash label", maximum=300)
            _require_hash(digest, f"R4 promotion subhash {label}")
        fold_ids = tuple(item.fold_id for item in self.windows)
        if not fold_ids or fold_ids != tuple(sorted(set(fold_ids))):
            raise ValueError("R4 promotion windows must be unique and ordered")
        metric_keys = tuple((item.fold_id, item.method.value) for item in self.window_metrics)
        if metric_keys != tuple(sorted(set(metric_keys))):
            raise ValueError("R4 promotion window metrics must be unique and ordered")
        summary_methods = tuple(item.method.value for item in self.method_summaries)
        if summary_methods != tuple(sorted(set(summary_methods))):
            raise ValueError("R4 promotion method summaries must be unique and ordered")
        for label, hashes in (
            ("exposure_point_hashes", self.exposure_point_hashes),
            ("regime_summary_hashes", self.regime_summary_hashes),
        ):
            if hashes != tuple(sorted(set(hashes))):
                raise ValueError(f"R4 promotion {label} must be unique and ordered")
            for digest in hashes:
                _require_hash(digest, f"R4 promotion {label}")
        if self.regime_covered_fold_ids != tuple(sorted(set(self.regime_covered_fold_ids))):
            raise ValueError("R4 promotion regime fold coverage must be unique and ordered")
        if any(fold_id not in fold_ids for fold_id in self.regime_covered_fold_ids):
            raise ValueError("R4 promotion regime coverage refers to an unknown fold")
        if (
            type(self.artifact_evidence_complete) is not bool
            or type(self.artifact_eligible) is not bool
        ):
            raise ValueError("R4 promotion artifact states must be boolean")
        if self.artifact_blockers != tuple(
            sorted(set(self.artifact_blockers), key=lambda item: (item[0], item[2] or "", item[1]))
        ):
            raise ValueError("R4 promotion artifact blockers must be unique and ordered")
        if self.r3_attestation_hash != self.record_r3_attestation.attestation_hash:
            raise ValueError("R4 promotion record R3 attestation hash was substituted")
        if self.usage_scope != "research_only":
            raise ValueError("R4 promotion owner record must remain research_only")
        if not self.must_not_use_for_decision or not self.must_not_execute:
            raise ValueError("R4 promotion owner record cannot authorize decisions or execution")
        if self.content_hash != r4_promotion_portfolio_record_seal_hash(self):
            raise ValueError("R4 promotion Portfolio record seal hash mismatch")


def _portfolio_record_payload(
    owner: str,
    owner_record_key: str,
    record_id: str,
    record_version: str,
    record_hash: str,
    study_id: str,
    study_version: str,
    study_content_hash: str,
    artifact_hash: str,
    r3_attestation_hash: str,
    split_contract_hash: str,
    split_policy_version: str,
    record_subhashes: tuple[R4RecordSubhash, ...],
    evaluated_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
    producer_code_version: str,
    dependency_lock_hash: str,
    cost_semantics_version: str,
    windows: tuple[R4PromotionWindowEvidence, ...],
    window_metrics: tuple[R4PromotionWindowMetricEvidence, ...],
    method_summaries: tuple[R4PromotionMethodSummaryEvidence, ...],
    exposure_point_hashes: tuple[str, ...],
    regime_summary_hashes: tuple[str, ...],
    regime_covered_fold_ids: tuple[str, ...],
    artifact_evidence_complete: bool,
    artifact_eligible: bool,
    artifact_blockers: tuple[R4ArtifactBlocker, ...],
    record_r3_attestation: R4PromotionR3AttestationEvidence,
) -> dict[str, object]:
    return {
        "schema": "research-r4-portfolio-owner-record-seal.v1",
        "owner": [owner, owner_record_key],
        "record": [record_id, record_version, record_hash],
        "study": [
            study_id,
            study_version,
            study_content_hash,
            split_contract_hash,
            split_policy_version,
        ],
        "artifact": [artifact_hash, artifact_evidence_complete, artifact_eligible],
        "r3_attestation": [
            r3_attestation_hash,
            record_r3_attestation.content_hash,
        ],
        "subhashes": [list(item) for item in record_subhashes],
        "window": [_utc_text(evaluated_at), _utc_text(recorded_at), _utc_text(valid_until)],
        "reproducibility": [
            producer_code_version,
            dependency_lock_hash,
            cost_semantics_version,
        ],
        "windows": [item.content_hash for item in windows],
        "window_metrics": [item.content_hash for item in window_metrics],
        "method_summaries": [item.content_hash for item in method_summaries],
        "exposure_point_hashes": list(exposure_point_hashes),
        "regime_summary_hashes": list(regime_summary_hashes),
        "regime_covered_fold_ids": list(regime_covered_fold_ids),
        "artifact_blockers": [list(item) for item in artifact_blockers],
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def r4_promotion_portfolio_record_seal_hash(
    seal: R4PromotionPortfolioRecordSeal,
) -> str:
    """Recompute the complete exact Portfolio owner record projection hash."""

    return _hash_payload(
        _portfolio_record_payload(
            seal.owner,
            seal.owner_record_key,
            seal.record_id,
            seal.record_version,
            seal.record_hash,
            seal.study_id,
            seal.study_version,
            seal.study_content_hash,
            seal.artifact_hash,
            seal.r3_attestation_hash,
            seal.split_contract_hash,
            seal.split_policy_version,
            seal.record_subhashes,
            seal.evaluated_at,
            seal.recorded_at,
            seal.valid_until,
            seal.producer_code_version,
            seal.dependency_lock_hash,
            seal.cost_semantics_version,
            seal.windows,
            seal.window_metrics,
            seal.method_summaries,
            seal.exposure_point_hashes,
            seal.regime_summary_hashes,
            seal.regime_covered_fold_ids,
            seal.artifact_evidence_complete,
            seal.artifact_eligible,
            seal.artifact_blockers,
            seal.record_r3_attestation,
        )
    )


__all__ = [
    "R4PromotionPortfolioRecordSeal",
    "r4_promotion_portfolio_record_seal_hash",
]
