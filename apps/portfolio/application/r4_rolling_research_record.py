"""Application record contract for persisted R4 rolling research evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeAlias

from apps.portfolio.domain.macro_risk_rolling_contracts import (
    R4RollingResearchArtifact,
    R4RollingStudyInput,
)
from apps.portfolio.domain.macro_risk_rolling_service import evaluate_r4_rolling_study
from apps.portfolio.domain.r4_rolling_evidence import ExactR3PromotionAttestation

R4ResearchSubhash: TypeAlias = tuple[str, str]

_RECORD_VERSION = "r4-rolling-research-record.v1"


def _require_text(value: str, field_name: str, *, maximum: int = 200) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    if "\0" in value:
        raise ValueError(f"{field_name} cannot contain a null character")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError(f"{field_name} must be a sha256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _hash_parts(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class R4RollingResearchDraft:
    """Caller-supplied reproducibility inputs without a self-reported record time."""

    study: R4RollingStudyInput
    promotion_attestation: ExactR3PromotionAttestation
    evaluated_at: datetime
    producer_code_version: str
    dependency_lock_hash: str
    valid_until: datetime

    def __post_init__(self) -> None:
        """Validate stable identity and validity before repository recording."""

        _require_aware(self.evaluated_at, "evaluated_at")
        _require_aware(self.valid_until, "valid_until")
        _require_text(self.producer_code_version, "producer_code_version")
        _require_sha256(self.dependency_lock_hash, "dependency_lock_hash")
        if self.valid_until <= self.evaluated_at:
            raise ValueError("valid_until must follow evaluated_at")
        approval_end = self.promotion_attestation.valid_until
        if self.promotion_attestation.retired_at is not None:
            approval_end = min(approval_end, self.promotion_attestation.retired_at)
        if self.valid_until > approval_end:
            raise ValueError("record validity cannot outlive the exact R3 promotion")

    @property
    def record_id(self) -> str:
        """Return the stable retry identity, independent of the server clock."""

        return _record_id(
            study=self.study,
            evaluated_at=self.evaluated_at,
            producer_code_version=self.producer_code_version,
            dependency_lock_hash=self.dependency_lock_hash,
        )


@dataclass(frozen=True)
class R4RollingResearchRecord:
    """One Portfolio-owned, reproducible, research-only ledger record."""

    record_id: str
    record_version: str
    owner: str
    study_id: str
    study_version: str
    study_content_hash: str
    artifact_hash: str
    r3_promotion_attestation_hash: str
    split_contract_hash: str
    subhashes: tuple[R4ResearchSubhash, ...]
    evaluated_at: datetime
    recorded_at: datetime
    producer_code_version: str
    dependency_lock_hash: str
    valid_until: datetime
    record_hash: str
    study: R4RollingStudyInput
    promotion_attestation: ExactR3PromotionAttestation
    artifact: R4RollingResearchArtifact
    usage_scope: str
    must_not_use_for_decision: bool
    must_not_execute: bool

    @classmethod
    def from_server_clock(
        cls,
        *,
        draft: R4RollingResearchDraft,
        server_recorded_at: datetime,
    ) -> R4RollingResearchRecord:
        """Seal a draft using only a repository/server-owned clock claim."""

        artifact = evaluate_r4_rolling_study(
            draft.study,
            promotion_attestation=draft.promotion_attestation,
            evaluated_at=draft.evaluated_at,
        )
        subhashes = _derive_subhashes(draft.study, artifact)
        record_id = draft.record_id
        record_hash = _record_hash(
            record_id=record_id,
            study=draft.study,
            artifact=artifact,
            promotion_attestation=draft.promotion_attestation,
            subhashes=subhashes,
            evaluated_at=draft.evaluated_at,
            recorded_at=server_recorded_at,
            producer_code_version=draft.producer_code_version,
            dependency_lock_hash=draft.dependency_lock_hash,
            valid_until=draft.valid_until,
        )
        return cls(
            record_id=record_id,
            record_version=_RECORD_VERSION,
            owner="portfolio",
            study_id=draft.study.study_id,
            study_version=draft.study.study_version,
            study_content_hash=draft.study.content_hash,
            artifact_hash=artifact.content_hash,
            r3_promotion_attestation_hash=draft.promotion_attestation.content_hash,
            split_contract_hash=draft.study.split_contract_hash,
            subhashes=subhashes,
            evaluated_at=draft.evaluated_at,
            recorded_at=server_recorded_at,
            producer_code_version=draft.producer_code_version,
            dependency_lock_hash=draft.dependency_lock_hash,
            valid_until=draft.valid_until,
            record_hash=record_hash,
            study=draft.study,
            promotion_attestation=draft.promotion_attestation,
            artifact=artifact,
            usage_scope="research_only",
            must_not_use_for_decision=True,
            must_not_execute=True,
        )

    def __post_init__(self) -> None:
        """Reject non-canonical metadata, payloads, or derived outputs."""

        if self.record_version != _RECORD_VERSION:
            raise ValueError("R4 rolling record version is invalid")
        if self.owner != "portfolio":
            raise ValueError("R4 rolling record owner must be portfolio")
        for field_name, value in (
            ("record_id", self.record_id),
            ("study_id", self.study_id),
            ("study_version", self.study_version),
            ("producer_code_version", self.producer_code_version),
        ):
            _require_text(value, field_name)
        for field_name, value in (
            ("study_content_hash", self.study_content_hash),
            ("artifact_hash", self.artifact_hash),
            ("r3_promotion_attestation_hash", self.r3_promotion_attestation_hash),
            ("split_contract_hash", self.split_contract_hash),
            ("dependency_lock_hash", self.dependency_lock_hash),
            ("record_hash", self.record_hash),
        ):
            _require_sha256(value, field_name)
        for timestamp_name, timestamp_value in (
            ("evaluated_at", self.evaluated_at),
            ("recorded_at", self.recorded_at),
            ("valid_until", self.valid_until),
        ):
            _require_aware(timestamp_value, timestamp_name)
        if self.recorded_at < self.evaluated_at:
            raise ValueError("recorded_at cannot precede evaluated_at")
        if self.recorded_at >= self.valid_until:
            raise ValueError("recorded_at must precede valid_until")
        approval_end = self.promotion_attestation.valid_until
        if self.promotion_attestation.retired_at is not None:
            approval_end = min(approval_end, self.promotion_attestation.retired_at)
        if self.valid_until > approval_end:
            raise ValueError("record validity cannot outlive the exact R3 promotion")
        if (
            self.study_id != self.study.study_id
            or self.study_version != self.study.study_version
            or self.study_content_hash.lower() != self.study.content_hash.lower()
            or self.split_contract_hash.lower() != self.study.split_contract_hash.lower()
        ):
            raise ValueError("record study identity or split hash mismatch")
        if (
            self.r3_promotion_attestation_hash.lower()
            != self.promotion_attestation.content_hash.lower()
        ):
            raise ValueError("record R3 promotion attestation hash mismatch")
        recomputed = evaluate_r4_rolling_study(
            self.study,
            promotion_attestation=self.promotion_attestation,
            evaluated_at=self.evaluated_at,
        )
        if self.artifact != recomputed or self.artifact_hash.lower() != recomputed.content_hash:
            raise ValueError("record artifact differs from the canonical R4 factory output")
        expected_subhashes = _derive_subhashes(self.study, recomputed)
        if self.subhashes != expected_subhashes:
            raise ValueError("record subhash ledger is incomplete or non-canonical")
        if self.usage_scope != "research_only":
            raise ValueError("R4 rolling records must remain research_only")
        if not self.must_not_use_for_decision or not self.must_not_execute:
            raise ValueError("R4 rolling records cannot authorize decisions or execution")
        expected_record_id = _record_id(
            study=self.study,
            evaluated_at=self.evaluated_at,
            producer_code_version=self.producer_code_version,
            dependency_lock_hash=self.dependency_lock_hash,
        )
        if self.record_id != expected_record_id:
            raise ValueError("R4 rolling record identity mismatch")
        expected_record_hash = _record_hash(
            record_id=self.record_id,
            study=self.study,
            artifact=recomputed,
            promotion_attestation=self.promotion_attestation,
            subhashes=self.subhashes,
            evaluated_at=self.evaluated_at,
            recorded_at=self.recorded_at,
            producer_code_version=self.producer_code_version,
            dependency_lock_hash=self.dependency_lock_hash,
            valid_until=self.valid_until,
        )
        if self.record_hash.lower() != expected_record_hash:
            raise ValueError("R4 rolling record_hash mismatch")


def _record_id(
    *,
    study: R4RollingStudyInput,
    evaluated_at: datetime,
    producer_code_version: str,
    dependency_lock_hash: str,
) -> str:
    digest = _hash_parts(
        "r4-rolling-research-record-identity.v1",
        study.study_id,
        study.study_version,
        _utc_text(evaluated_at),
        producer_code_version,
        dependency_lock_hash.lower(),
    )
    return f"r4r:{digest}"


def _record_hash(
    *,
    record_id: str,
    study: R4RollingStudyInput,
    artifact: R4RollingResearchArtifact,
    promotion_attestation: ExactR3PromotionAttestation,
    subhashes: tuple[R4ResearchSubhash, ...],
    evaluated_at: datetime,
    recorded_at: datetime,
    producer_code_version: str,
    dependency_lock_hash: str,
    valid_until: datetime,
) -> str:
    return _hash_parts(
        _RECORD_VERSION,
        record_id,
        "portfolio",
        study.study_id,
        study.study_version,
        study.content_hash.lower(),
        artifact.content_hash.lower(),
        promotion_attestation.content_hash.lower(),
        study.split_contract_hash.lower(),
        _utc_text(evaluated_at),
        _utc_text(recorded_at),
        producer_code_version,
        dependency_lock_hash.lower(),
        _utc_text(valid_until),
        *(f"{label}|{digest.lower()}" for label, digest in subhashes),
        "research_only",
        "True",
        "True",
    )


def _derive_subhashes(
    study: R4RollingStudyInput,
    artifact: R4RollingResearchArtifact,
) -> tuple[R4ResearchSubhash, ...]:
    values: list[R4ResearchSubhash] = [("study.split", study.split_contract_hash)]
    for window in study.windows:
        prefix = f"study.window.{window.fold.fold_id}"
        values.extend(
            (
                (prefix, window.content_hash),
                (f"{prefix}.macro_projection", window.macro_projection.content_hash),
                (f"{prefix}.macro_source", window.macro_projection.source_content_hash),
                (
                    f"{prefix}.factor_artifact",
                    window.macro_projection.factor_artifact_content_hash,
                ),
                (
                    f"{prefix}.promotion_decision",
                    window.macro_projection.promotion_decision_content_hash,
                ),
                (f"{prefix}.asset_covariance", window.asset_covariance.content_hash),
                (f"{prefix}.return_path", window.return_path.content_hash),
                (f"{prefix}.regime_assignment", window.regime_assignment.content_hash),
                (f"{prefix}.regime_source", window.regime_assignment.source_content_hash),
            )
        )
        values.extend(
            (f"{prefix}.asset_covariance_source.{index}", digest)
            for index, digest in enumerate(window.asset_covariance.source_content_hashes)
        )
        values.extend(
            (f"{prefix}.return_path_source.{index}", digest)
            for index, digest in enumerate(window.return_path.source_content_hashes)
        )
        values.extend(
            (f"{prefix}.candidate.{candidate.kind.value}", candidate.input_hash)
            for candidate in window.candidates
        )
    values.extend(
        (
            f"artifact.window_metric.{item.fold_id}.{item.kind.value}",
            item.content_hash,
        )
        for item in artifact.window_metrics
    )
    values.extend(
        (
            f"artifact.candidate_report.{item.fold_id}.{item.kind.value}",
            item.candidate_report_hash,
        )
        for item in artifact.window_metrics
    )
    values.extend(
        (
            f"artifact.exposure.{item.fold_id}.{item.asset_code}.{item.factor_code}",
            item.content_hash,
        )
        for item in artifact.exposure_points
    )
    values.extend(
        (
            f"artifact.regime.{item.regime_code}.{item.asset_code}.{item.factor_code}",
            item.content_hash,
        )
        for item in artifact.regime_summaries
    )
    values.extend(
        (f"artifact.method.{item.kind.value}", item.content_hash)
        for item in artifact.method_summaries
    )
    ordered = tuple(sorted(values, key=lambda item: item[0]))
    labels = tuple(label for label, _ in ordered)
    if len(labels) != len(set(labels)):
        raise ValueError("R4 rolling subhash labels must be unique")
    for label, digest in ordered:
        _require_text(label, "subhash label", maximum=300)
        _require_sha256(digest, f"subhash {label}")
    return ordered


__all__ = [
    "R4ResearchSubhash",
    "R4RollingResearchDraft",
    "R4RollingResearchRecord",
]
