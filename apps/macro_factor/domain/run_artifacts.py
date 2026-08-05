"""Canonical external envelope and immutable local R3 run artifact."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from apps.macro_factor.domain.entities import ExternalMacroFactorResearchResult, FactorOutputRole

from ._runner_support import (
    canonical_json,
    decimal_text,
    require_aware,
    require_finite,
    require_positive,
    require_sha256,
    require_text,
    require_token,
    utc_text,
)
from .baselines import FoldBenchmarkResult
from .dated_outputs import ExternalDatedFactorOutput

MACRO_FACTOR_EXTERNAL_ARTIFACT_MEDIA_TYPE = "application/vnd.agom.macro-factor.nested-cv+json"


@dataclass(frozen=True)
class ExternalFoldPrediction:
    """One OOS prediction returned by the external runner."""

    fold_id: str
    row_id: str
    predicted_value: Decimal

    def __post_init__(self) -> None:
        require_token(self.fold_id, "ExternalFoldPrediction.fold_id")
        require_token(self.row_id, "ExternalFoldPrediction.row_id")
        require_finite(self.predicted_value, "ExternalFoldPrediction.predicted_value")


@dataclass(frozen=True)
class ExternalAlphaScore:
    """One external inner-fold score for a predeclared alpha."""

    alpha: Decimal
    score: Decimal

    def __post_init__(self) -> None:
        require_finite(self.alpha, "ExternalAlphaScore.alpha")
        require_finite(self.score, "ExternalAlphaScore.score")
        if self.alpha <= 0:
            raise ValueError("ExternalAlphaScore.alpha must be positive")


@dataclass(frozen=True)
class ExternalInnerFoldScore:
    """Complete alpha-grid scores for one named inner fold."""

    inner_fold_id: str
    alpha_scores: tuple[ExternalAlphaScore, ...]

    def __post_init__(self) -> None:
        require_token(self.inner_fold_id, "ExternalInnerFoldScore.inner_fold_id")
        if not self.alpha_scores:
            raise ValueError("ExternalInnerFoldScore.alpha_scores cannot be empty")
        alphas = tuple(item.alpha for item in self.alpha_scores)
        if len(alphas) != len(set(alphas)):
            raise ValueError("ExternalInnerFoldScore alpha identities must be unique")

    def canonical_payload(self) -> dict[str, object]:
        """Return canonical inner-score evidence."""

        return {
            "inner_fold_id": self.inner_fold_id,
            "alpha_scores": [
                {"alpha": decimal_text(item.alpha), "score": decimal_text(item.score)}
                for item in sorted(self.alpha_scores, key=lambda value: value.alpha)
            ],
        }


@dataclass(frozen=True)
class ExternalProxyCoefficient:
    """Per-fold final-fit coefficient and FMP weight for one candidate."""

    asset_code: str
    lasso_coefficient: Decimal
    factor_weight: Decimal

    def __post_init__(self) -> None:
        require_token(self.asset_code, "ExternalProxyCoefficient.asset_code")
        require_finite(self.lasso_coefficient, "ExternalProxyCoefficient.lasso_coefficient")
        require_finite(self.factor_weight, "ExternalProxyCoefficient.factor_weight")
        if (self.lasso_coefficient == 0) != (self.factor_weight == 0):
            raise ValueError("zero coefficient and factor weight must agree")

    def canonical_payload(self) -> dict[str, str]:
        """Return canonical coefficient evidence."""

        return {
            "asset_code": self.asset_code,
            "lasso_coefficient": decimal_text(self.lasso_coefficient),
            "factor_weight": decimal_text(self.factor_weight),
        }


@dataclass(frozen=True)
class ExternalOuterFoldSelectionEvidence:
    """Complete inner selection and final-fit lineage for one outer fold."""

    fold_id: str
    request_design_hash: str
    selected_alpha: Decimal
    inner_scores: tuple[ExternalInnerFoldScore, ...]
    final_fit_row_ids: tuple[str, ...]
    final_fit_as_of: datetime
    coefficients: tuple[ExternalProxyCoefficient, ...]
    final_fit_lineage_hash: str

    @classmethod
    def create(
        cls,
        *,
        fold_id: str,
        request_design_hash: str,
        selected_alpha: Decimal,
        inner_scores: tuple[ExternalInnerFoldScore, ...],
        final_fit_row_ids: tuple[str, ...],
        final_fit_as_of: datetime,
        coefficients: tuple[ExternalProxyCoefficient, ...],
    ) -> ExternalOuterFoldSelectionEvidence:
        """Build external fold evidence with its complete lineage hash."""

        lineage = cls._lineage_payload(
            fold_id=fold_id,
            request_design_hash=request_design_hash,
            selected_alpha=selected_alpha,
            inner_scores=inner_scores,
            final_fit_row_ids=final_fit_row_ids,
            final_fit_as_of=final_fit_as_of,
            coefficients=coefficients,
        )
        return cls(
            fold_id=fold_id,
            request_design_hash=request_design_hash,
            selected_alpha=selected_alpha,
            inner_scores=inner_scores,
            final_fit_row_ids=final_fit_row_ids,
            final_fit_as_of=final_fit_as_of,
            coefficients=coefficients,
            final_fit_lineage_hash=hashlib.sha256(
                canonical_json(lineage).encode("utf-8")
            ).hexdigest(),
        )

    @staticmethod
    def _lineage_payload(
        *,
        fold_id: str,
        request_design_hash: str,
        selected_alpha: Decimal,
        inner_scores: tuple[ExternalInnerFoldScore, ...],
        final_fit_row_ids: tuple[str, ...],
        final_fit_as_of: datetime,
        coefficients: tuple[ExternalProxyCoefficient, ...],
    ) -> dict[str, object]:
        return {
            "fold_id": fold_id,
            "request_design_hash": request_design_hash,
            "selected_alpha": decimal_text(selected_alpha),
            "inner_scores": [
                item.canonical_payload()
                for item in sorted(inner_scores, key=lambda value: value.inner_fold_id)
            ],
            "final_fit_row_ids": list(final_fit_row_ids),
            "final_fit_as_of": utc_text(final_fit_as_of),
            "coefficients": [
                item.canonical_payload()
                for item in sorted(coefficients, key=lambda value: value.asset_code)
            ],
        }

    def __post_init__(self) -> None:
        require_token(self.fold_id, "ExternalOuterFoldSelectionEvidence.fold_id")
        require_sha256(
            self.request_design_hash,
            "ExternalOuterFoldSelectionEvidence.request_design_hash",
        )
        require_finite(
            self.selected_alpha,
            "ExternalOuterFoldSelectionEvidence.selected_alpha",
        )
        require_aware(
            self.final_fit_as_of,
            "ExternalOuterFoldSelectionEvidence.final_fit_as_of",
        )
        if not self.inner_scores or not self.final_fit_row_ids or not self.coefficients:
            raise ValueError("outer-fold selection evidence must be complete")
        inner_ids = tuple(item.inner_fold_id for item in self.inner_scores)
        if len(inner_ids) != len(set(inner_ids)):
            raise ValueError("outer-fold inner score identities must be unique")
        if len(self.final_fit_row_ids) != len(set(self.final_fit_row_ids)):
            raise ValueError("outer-fold final-fit row identities must be unique")
        coefficient_codes = tuple(item.asset_code for item in self.coefficients)
        if len(coefficient_codes) != len(set(coefficient_codes)):
            raise ValueError("outer-fold coefficient identities must be unique")
        require_sha256(
            self.final_fit_lineage_hash,
            "ExternalOuterFoldSelectionEvidence.final_fit_lineage_hash",
        )
        expected = hashlib.sha256(
            canonical_json(
                self._lineage_payload(
                    fold_id=self.fold_id,
                    request_design_hash=self.request_design_hash,
                    selected_alpha=self.selected_alpha,
                    inner_scores=self.inner_scores,
                    final_fit_row_ids=self.final_fit_row_ids,
                    final_fit_as_of=self.final_fit_as_of,
                    coefficients=self.coefficients,
                )
            ).encode("utf-8")
        ).hexdigest()
        if self.final_fit_lineage_hash.lower() != expected:
            raise ValueError("outer-fold final-fit lineage hash does not match evidence")

    def canonical_payload(self) -> dict[str, object]:
        """Return the complete outer-fold selection evidence and lineage seal."""

        return {
            **self._lineage_payload(
                fold_id=self.fold_id,
                request_design_hash=self.request_design_hash,
                selected_alpha=self.selected_alpha,
                inner_scores=self.inner_scores,
                final_fit_row_ids=self.final_fit_row_ids,
                final_fit_as_of=self.final_fit_as_of,
                coefficients=self.coefficients,
            ),
            "final_fit_lineage_hash": self.final_fit_lineage_hash,
        }


@dataclass(frozen=True)
class ExternalNestedCVArtifact:
    """Canonical byte envelope returned by the typed external runner."""

    evidence_id: str
    producer_ref: str
    produced_at: datetime
    request_hash: str
    result: ExternalMacroFactorResearchResult
    fold_selections: tuple[ExternalOuterFoldSelectionEvidence, ...]
    predictions: tuple[ExternalFoldPrediction, ...]
    dated_outputs: tuple[ExternalDatedFactorOutput, ...]
    artifact_bytes: bytes
    artifact_hash: str
    media_type: str = MACRO_FACTOR_EXTERNAL_ARTIFACT_MEDIA_TYPE

    @classmethod
    def create(
        cls,
        *,
        evidence_id: str,
        producer_ref: str,
        produced_at: datetime,
        request_hash: str,
        result: ExternalMacroFactorResearchResult,
        fold_selections: tuple[ExternalOuterFoldSelectionEvidence, ...],
        predictions: tuple[ExternalFoldPrediction, ...],
        dated_outputs: tuple[ExternalDatedFactorOutput, ...],
    ) -> ExternalNestedCVArtifact:
        """Create the exact canonical JSON bytes an external adapter must return."""

        payload = cls._payload(
            evidence_id=evidence_id,
            producer_ref=producer_ref,
            produced_at=produced_at,
            request_hash=request_hash,
            result=result,
            fold_selections=fold_selections,
            predictions=predictions,
            dated_outputs=dated_outputs,
        )
        artifact_bytes = canonical_json(payload).encode("utf-8")
        return cls(
            evidence_id=evidence_id,
            producer_ref=producer_ref,
            produced_at=produced_at,
            request_hash=request_hash,
            result=result,
            fold_selections=fold_selections,
            predictions=predictions,
            dated_outputs=dated_outputs,
            artifact_bytes=artifact_bytes,
            artifact_hash=hashlib.sha256(artifact_bytes).hexdigest(),
        )

    @staticmethod
    def _payload(
        *,
        evidence_id: str,
        producer_ref: str,
        produced_at: datetime,
        request_hash: str,
        result: ExternalMacroFactorResearchResult,
        fold_selections: tuple[ExternalOuterFoldSelectionEvidence, ...],
        predictions: tuple[ExternalFoldPrediction, ...],
        dated_outputs: tuple[ExternalDatedFactorOutput, ...],
    ) -> dict[str, object]:
        return {
            "evidence_id": evidence_id,
            "producer_ref": producer_ref,
            "produced_at": utc_text(produced_at),
            "request_hash": request_hash,
            "source_result_id": result.result_id,
            "source_result_hash": result.content_hash,
            "fold_selections": [
                item.canonical_payload()
                for item in sorted(fold_selections, key=lambda value: value.fold_id)
            ],
            "predictions": [
                {
                    "fold_id": item.fold_id,
                    "row_id": item.row_id,
                    "predicted_value": decimal_text(item.predicted_value),
                }
                for item in sorted(predictions, key=lambda value: (value.fold_id, value.row_id))
            ],
            "dated_outputs": [
                item.canonical_payload()
                for item in sorted(
                    dated_outputs,
                    key=lambda value: (
                        value.output_role.value,
                        value.observation_date,
                        value.target_period_start,
                        value.target_period_end,
                    ),
                )
            ],
        }

    def __post_init__(self) -> None:
        require_token(self.evidence_id, "ExternalNestedCVArtifact.evidence_id")
        require_text(self.producer_ref, "ExternalNestedCVArtifact.producer_ref", maximum=500)
        require_aware(self.produced_at, "ExternalNestedCVArtifact.produced_at")
        require_sha256(self.request_hash, "ExternalNestedCVArtifact.request_hash")
        require_sha256(self.artifact_hash, "ExternalNestedCVArtifact.artifact_hash")
        if self.media_type != MACRO_FACTOR_EXTERNAL_ARTIFACT_MEDIA_TYPE:
            raise ValueError("external artifact media_type is invalid")
        fold_ids = tuple(item.fold_id for item in self.fold_selections)
        if not self.fold_selections or len(fold_ids) != len(set(fold_ids)):
            raise ValueError("external outer-fold selection identities must be complete and unique")
        identities = tuple((item.fold_id, item.row_id) for item in self.predictions)
        if not self.predictions or len(identities) != len(set(identities)):
            raise ValueError("external prediction identities must be non-empty and unique")
        output_keys = tuple(
            (
                item.output_role,
                item.observation_date,
                item.target_period_start,
                item.target_period_end,
            )
            for item in self.dated_outputs
        )
        if not self.dated_outputs or len(output_keys) != len(set(output_keys)):
            raise ValueError("external dated-output identities must be non-empty and unique")
        expected_bytes = canonical_json(
            self._payload(
                evidence_id=self.evidence_id,
                producer_ref=self.producer_ref,
                produced_at=self.produced_at,
                request_hash=self.request_hash,
                result=self.result,
                fold_selections=self.fold_selections,
                predictions=self.predictions,
                dated_outputs=self.dated_outputs,
            )
        ).encode("utf-8")
        if self.artifact_bytes != expected_bytes:
            raise ValueError("external artifact canonical bytes do not match typed evidence")
        if self.artifact_hash.lower() != hashlib.sha256(self.artifact_bytes).hexdigest():
            raise ValueError("external artifact hash does not match canonical bytes")


@dataclass(frozen=True)
class ReproducibleMacroFactorRunArtifact:
    """Hash-sealed local manifest of one validated external R3 run."""

    artifact_id: str
    run_key: str
    run_version: int
    factor_version: str
    target_code: str
    output_role: FactorOutputRole
    produced_at: datetime
    source_result_id: str
    source_result_hash: str
    external_evidence_id: str
    external_producer_ref: str
    external_artifact_hash: str
    external_artifact_media_type: str
    external_artifact_content_length: int
    external_artifact_bytes: bytes = field(repr=False)
    request_hash: str
    pit_manifest_id: str
    pit_manifest_hash: str
    dataset_hash: str
    benchmark_version: str
    benchmark_hash: str
    fixed_fmp_version: str
    fixed_fmp_hash: str
    cost_model_version: str
    cost_model_hash: str
    split_contract_version: str
    split_contract_hash: str
    plan_hash: str
    selection_protocol_version: str
    selection_protocol_hash: str
    metrics_protocol_version: str
    metrics_protocol_hash: str
    timing_policy_version: str
    timing_policy_hash: str
    code_version: str
    dependency_lock_hash: str
    parameter_version: str
    parameter_hash: str
    random_seed: int
    fold_benchmarks: tuple[FoldBenchmarkResult, ...]
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        require_sha256(self.artifact_id, "RunArtifact.artifact_id")
        require_positive(self.run_version, "RunArtifact.run_version")
        require_aware(self.produced_at, "RunArtifact.produced_at")
        if not isinstance(self.output_role, FactorOutputRole):
            raise ValueError("RunArtifact.output_role is invalid")
        for token_value, token_name in (
            (self.run_key, "run_key"),
            (self.factor_version, "factor_version"),
            (self.target_code, "target_code"),
            (self.source_result_id, "source_result_id"),
            (self.external_evidence_id, "external_evidence_id"),
            (self.pit_manifest_id, "pit_manifest_id"),
            (self.benchmark_version, "benchmark_version"),
            (self.fixed_fmp_version, "fixed_fmp_version"),
            (self.cost_model_version, "cost_model_version"),
            (self.split_contract_version, "split_contract_version"),
            (self.selection_protocol_version, "selection_protocol_version"),
            (self.metrics_protocol_version, "metrics_protocol_version"),
            (self.timing_policy_version, "timing_policy_version"),
            (self.code_version, "code_version"),
            (self.parameter_version, "parameter_version"),
        ):
            require_token(token_value, f"RunArtifact.{token_name}")
        if isinstance(self.random_seed, bool) or self.random_seed < 0:
            raise ValueError("RunArtifact.random_seed cannot be negative")
        require_text(self.external_producer_ref, "RunArtifact.external_producer_ref", maximum=500)
        if self.external_artifact_media_type != MACRO_FACTOR_EXTERNAL_ARTIFACT_MEDIA_TYPE:
            raise ValueError("RunArtifact.external_artifact_media_type is invalid")
        if (
            isinstance(self.external_artifact_content_length, bool)
            or self.external_artifact_content_length <= 0
            or self.external_artifact_content_length != len(self.external_artifact_bytes)
        ):
            raise ValueError("RunArtifact external artifact content length is invalid")
        if hashlib.sha256(self.external_artifact_bytes).hexdigest() != self.external_artifact_hash:
            raise ValueError("RunArtifact external artifact bytes/hash mismatch")
        try:
            external_payload = json.loads(self.external_artifact_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("RunArtifact external artifact bytes must be canonical JSON") from exc
        if not isinstance(external_payload, dict) or (
            canonical_json(external_payload).encode("utf-8") != self.external_artifact_bytes
        ):
            raise ValueError("RunArtifact external artifact bytes must be canonical JSON")
        expected_external_identity = {
            "evidence_id": self.external_evidence_id,
            "producer_ref": self.external_producer_ref,
            "produced_at": utc_text(self.produced_at),
            "request_hash": self.request_hash,
            "source_result_id": self.source_result_id,
            "source_result_hash": self.source_result_hash,
        }
        if any(
            external_payload.get(key) != value for key, value in expected_external_identity.items()
        ):
            raise ValueError("RunArtifact external artifact identity mismatch")
        for value, name in (
            (self.source_result_hash, "source_result_hash"),
            (self.external_artifact_hash, "external_artifact_hash"),
            (self.request_hash, "request_hash"),
            (self.pit_manifest_hash, "pit_manifest_hash"),
            (self.dataset_hash, "dataset_hash"),
            (self.benchmark_hash, "benchmark_hash"),
            (self.fixed_fmp_hash, "fixed_fmp_hash"),
            (self.cost_model_hash, "cost_model_hash"),
            (self.split_contract_hash, "split_contract_hash"),
            (self.plan_hash, "plan_hash"),
            (self.selection_protocol_hash, "selection_protocol_hash"),
            (self.metrics_protocol_hash, "metrics_protocol_hash"),
            (self.timing_policy_hash, "timing_policy_hash"),
            (self.dependency_lock_hash, "dependency_lock_hash"),
            (self.parameter_hash, "parameter_hash"),
        ):
            require_sha256(value, f"RunArtifact.{name}")
        if not self.fold_benchmarks:
            raise ValueError("RunArtifact.fold_benchmarks cannot be empty")
        if not all((self.research_only, self.must_not_use_for_decision, self.must_not_execute)):
            raise ValueError("macro-factor run artifacts must remain research-only and blocked")

    @property
    def canonical_payload(self) -> dict[str, object]:
        """Return every exact data, policy, code, dependency, and metric identity."""

        return {
            "artifact_id": self.artifact_id,
            "run_key": self.run_key,
            "run_version": self.run_version,
            "factor_version": self.factor_version,
            "target_code": self.target_code,
            "output_role": self.output_role.value,
            "produced_at": utc_text(self.produced_at),
            "source_result_id": self.source_result_id,
            "source_result_hash": self.source_result_hash,
            "external_evidence_id": self.external_evidence_id,
            "external_artifact": {
                "producer_ref": self.external_producer_ref,
                "hash": self.external_artifact_hash,
                "media_type": self.external_artifact_media_type,
                "content_length": self.external_artifact_content_length,
            },
            "request_hash": self.request_hash,
            "pit_manifest": {"id": self.pit_manifest_id, "hash": self.pit_manifest_hash},
            "dataset_hash": self.dataset_hash,
            "benchmark": {"version": self.benchmark_version, "hash": self.benchmark_hash},
            "fixed_fmp": {"version": self.fixed_fmp_version, "hash": self.fixed_fmp_hash},
            "cost_model": {"version": self.cost_model_version, "hash": self.cost_model_hash},
            "split_contract": {
                "version": self.split_contract_version,
                "hash": self.split_contract_hash,
            },
            "plan_hash": self.plan_hash,
            "selection_protocol": {
                "version": self.selection_protocol_version,
                "hash": self.selection_protocol_hash,
            },
            "metrics_protocol": {
                "version": self.metrics_protocol_version,
                "hash": self.metrics_protocol_hash,
            },
            "timing_policy": {
                "version": self.timing_policy_version,
                "hash": self.timing_policy_hash,
            },
            "reproducibility": {
                "code_version": self.code_version,
                "dependency_lock_hash": self.dependency_lock_hash,
                "parameter_version": self.parameter_version,
                "parameter_hash": self.parameter_hash,
                "random_seed": self.random_seed,
            },
            "fold_benchmarks": [item.canonical_payload() for item in self.fold_benchmarks],
            "research_only": self.research_only,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "must_not_execute": self.must_not_execute,
        }

    @property
    def canonical_json(self) -> str:
        """Return canonical JSON for persistence."""

        return canonical_json(self.canonical_payload)

    @property
    def content_hash(self) -> str:
        """Seal the complete local run artifact."""

        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()


__all__ = [
    "ExternalAlphaScore",
    "ExternalFoldPrediction",
    "ExternalInnerFoldScore",
    "ExternalNestedCVArtifact",
    "ExternalOuterFoldSelectionEvidence",
    "ExternalProxyCoefficient",
    "MACRO_FACTOR_EXTERNAL_ARTIFACT_MEDIA_TYPE",
    "ReproducibleMacroFactorRunArtifact",
]
