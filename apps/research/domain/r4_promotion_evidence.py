"""Exact Portfolio record and current-R3 projections for R4 promotion trials."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from apps.portfolio.domain.macro_factor_risk import MacroRiskCandidateKind

from .r4_promotion_scope_policy import (
    _decimal_text,
    _hash_payload,
    _require_aware,
    _require_finite,
    _require_hash,
    _require_token,
    _utc_text,
)

R4RecordSubhash = tuple[str, str]
R4ArtifactBlocker = tuple[str, str, str | None]


@dataclass(frozen=True)
class R4PromotionR3AttestationEvidence:
    """Exact Research-owner R3 attestation projection used by R4."""

    owner: str
    capability_key: str
    purpose: str
    artifact_id: str
    artifact_version: str
    artifact_content_hash: str
    decision_id: str
    decision_version: str
    decision_content_hash: str
    approved_at: datetime
    valid_until: datetime
    retired_at: datetime | None
    attestation_hash: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        artifact_id: str,
        artifact_version: str,
        artifact_content_hash: str,
        decision_id: str,
        decision_version: str,
        decision_content_hash: str,
        approved_at: datetime,
        valid_until: datetime,
        retired_at: datetime | None,
        attestation_hash: str,
    ) -> R4PromotionR3AttestationEvidence:
        """Seal one exact current or record-bound R3 attestation."""

        values = (
            "research",
            "macro_factor_r3",
            "r4_macro_risk_research",
            artifact_id,
            artifact_version,
            artifact_content_hash,
            decision_id,
            decision_version,
            decision_content_hash,
            approved_at,
            valid_until,
            retired_at,
            attestation_hash,
        )
        digest = _hash_payload(_r3_payload(*values))
        return cls(*values, digest)

    def __post_init__(self) -> None:
        if (
            self.owner != "research"
            or self.capability_key != "macro_factor_r3"
            or self.purpose != "r4_macro_risk_research"
        ):
            raise ValueError("R4 promotion R3 attestation authority is invalid")
        for field_name, value in (
            ("artifact_id", self.artifact_id),
            ("artifact_version", self.artifact_version),
            ("decision_id", self.decision_id),
            ("decision_version", self.decision_version),
        ):
            _require_token(value, f"R4 promotion R3 {field_name}")
        for field_name, value in (
            ("artifact_content_hash", self.artifact_content_hash),
            ("decision_content_hash", self.decision_content_hash),
            ("attestation_hash", self.attestation_hash),
            ("content_hash", self.content_hash),
        ):
            _require_hash(value, f"R4 promotion R3 {field_name}")
        _require_aware(self.approved_at, "R4 promotion R3 approved_at")
        _require_aware(self.valid_until, "R4 promotion R3 valid_until")
        if self.valid_until <= self.approved_at:
            raise ValueError("R4 promotion R3 validity is invalid")
        if self.retired_at is not None:
            _require_aware(self.retired_at, "R4 promotion R3 retired_at")
            if self.retired_at <= self.approved_at:
                raise ValueError("R4 promotion R3 retirement is invalid")
        if self.content_hash != r4_promotion_r3_attestation_evidence_hash(self):
            raise ValueError("R4 promotion R3 evidence content hash mismatch")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the exact attestation is active at ``as_of``."""

        _require_aware(as_of, "R4 promotion R3 as_of")
        return self.approved_at <= as_of < self.valid_until and (
            self.retired_at is None or as_of < self.retired_at
        )

    @property
    def effective_valid_until(self) -> datetime:
        """Return the earliest expiry or retirement boundary."""

        return (
            self.valid_until if self.retired_at is None else min(self.valid_until, self.retired_at)
        )


def _r3_payload(
    owner: str,
    capability_key: str,
    purpose: str,
    artifact_id: str,
    artifact_version: str,
    artifact_content_hash: str,
    decision_id: str,
    decision_version: str,
    decision_content_hash: str,
    approved_at: datetime,
    valid_until: datetime,
    retired_at: datetime | None,
    attestation_hash: str,
) -> dict[str, object]:
    return {
        "schema": "research-r4-current-r3-attestation.v1",
        "authority": [owner, capability_key, purpose],
        "artifact": [artifact_id, artifact_version, artifact_content_hash],
        "decision": [decision_id, decision_version, decision_content_hash],
        "window": [
            _utc_text(approved_at),
            _utc_text(valid_until),
            None if retired_at is None else _utc_text(retired_at),
        ],
        "attestation_hash": attestation_hash,
    }


def r4_promotion_r3_attestation_evidence_hash(
    evidence: R4PromotionR3AttestationEvidence,
) -> str:
    """Recompute one exact R3 evidence projection hash."""

    return _hash_payload(
        _r3_payload(
            evidence.owner,
            evidence.capability_key,
            evidence.purpose,
            evidence.artifact_id,
            evidence.artifact_version,
            evidence.artifact_content_hash,
            evidence.decision_id,
            evidence.decision_version,
            evidence.decision_content_hash,
            evidence.approved_at,
            evidence.valid_until,
            evidence.retired_at,
            evidence.attestation_hash,
        )
    )


@dataclass(frozen=True)
class R4PromotionWindowEvidence:
    """Exact formation/OOS window identity consumed by the Portfolio record."""

    fold_id: str
    window_content_hash: str
    selection_as_of: datetime
    evaluation_as_of: datetime
    universe_id: str
    universe_hash: str
    asset_codes: tuple[str, ...]
    factor_codes: tuple[str, ...]
    macro_projection_hash: str
    covariance_hash: str
    return_path_hash: str
    regime_assignment_hash: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        fold_id: str,
        window_content_hash: str,
        selection_as_of: datetime,
        evaluation_as_of: datetime,
        universe_id: str,
        universe_hash: str,
        asset_codes: tuple[str, ...],
        factor_codes: tuple[str, ...],
        macro_projection_hash: str,
        covariance_hash: str,
        return_path_hash: str,
        regime_assignment_hash: str,
    ) -> R4PromotionWindowEvidence:
        """Seal one exact Portfolio rolling window projection."""

        values = (
            fold_id,
            window_content_hash,
            selection_as_of,
            evaluation_as_of,
            universe_id,
            universe_hash,
            asset_codes,
            factor_codes,
            macro_projection_hash,
            covariance_hash,
            return_path_hash,
            regime_assignment_hash,
        )
        digest = _hash_payload(_window_payload(*values))
        return cls(*values, digest)

    def __post_init__(self) -> None:
        _require_token(self.fold_id, "R4 promotion fold_id")
        _require_token(self.universe_id, "R4 promotion universe_id")
        for field_name, value in (
            ("window_content_hash", self.window_content_hash),
            ("universe_hash", self.universe_hash),
            ("macro_projection_hash", self.macro_projection_hash),
            ("covariance_hash", self.covariance_hash),
            ("return_path_hash", self.return_path_hash),
            ("regime_assignment_hash", self.regime_assignment_hash),
            ("content_hash", self.content_hash),
        ):
            _require_hash(value, f"R4 promotion window {field_name}")
        for label, values in (
            ("asset_codes", self.asset_codes),
            ("factor_codes", self.factor_codes),
        ):
            if not values or values != tuple(sorted(set(values))):
                raise ValueError(f"R4 promotion window {label} must be unique and ordered")
            for value in values:
                _require_token(value, f"R4 promotion window {label}")
        _require_aware(self.selection_as_of, "R4 promotion selection_as_of")
        _require_aware(self.evaluation_as_of, "R4 promotion evaluation_as_of")
        if self.selection_as_of >= self.evaluation_as_of:
            raise ValueError("R4 promotion window selection must precede evaluation")
        if self.content_hash != r4_promotion_window_evidence_hash(self):
            raise ValueError("R4 promotion window evidence content hash mismatch")


def _window_payload(
    fold_id: str,
    window_content_hash: str,
    selection_as_of: datetime,
    evaluation_as_of: datetime,
    universe_id: str,
    universe_hash: str,
    asset_codes: tuple[str, ...],
    factor_codes: tuple[str, ...],
    macro_projection_hash: str,
    covariance_hash: str,
    return_path_hash: str,
    regime_assignment_hash: str,
) -> dict[str, object]:
    return {
        "schema": "research-r4-promotion-window-evidence.v1",
        "fold": [fold_id, window_content_hash],
        "window": [_utc_text(selection_as_of), _utc_text(evaluation_as_of)],
        "universe": [universe_id, universe_hash, list(asset_codes)],
        "factor_codes": list(factor_codes),
        "evidence_hashes": [
            macro_projection_hash,
            covariance_hash,
            return_path_hash,
            regime_assignment_hash,
        ],
    }


def r4_promotion_window_evidence_hash(evidence: R4PromotionWindowEvidence) -> str:
    """Recompute one exact rolling-window projection hash."""

    return _hash_payload(
        _window_payload(
            evidence.fold_id,
            evidence.window_content_hash,
            evidence.selection_as_of,
            evidence.evaluation_as_of,
            evidence.universe_id,
            evidence.universe_hash,
            evidence.asset_codes,
            evidence.factor_codes,
            evidence.macro_projection_hash,
            evidence.covariance_hash,
            evidence.return_path_hash,
            evidence.regime_assignment_hash,
        )
    )


@dataclass(frozen=True)
class R4PromotionWindowMetricEvidence:
    """Exact realized method/window values sealed by Portfolio."""

    fold_id: str
    method: MacroRiskCandidateKind
    period_returns: tuple[Decimal, ...]
    gross_return: Decimal
    realized_variance: Decimal
    maximum_drawdown: Decimal
    turnover: Decimal
    expected_cost: Decimal
    cost_semantics_version: str
    candidate_report_hash: str
    source_content_hash: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        fold_id: str,
        method: MacroRiskCandidateKind,
        period_returns: tuple[Decimal, ...],
        gross_return: Decimal,
        realized_variance: Decimal,
        maximum_drawdown: Decimal,
        turnover: Decimal,
        expected_cost: Decimal,
        cost_semantics_version: str,
        candidate_report_hash: str,
        source_content_hash: str,
    ) -> R4PromotionWindowMetricEvidence:
        """Seal full realized metric values rather than a caller summary."""

        values = (
            fold_id,
            method,
            period_returns,
            gross_return,
            realized_variance,
            maximum_drawdown,
            turnover,
            expected_cost,
            cost_semantics_version,
            candidate_report_hash,
            source_content_hash,
        )
        digest = _hash_payload(_window_metric_payload(*values))
        return cls(*values, digest)

    def __post_init__(self) -> None:
        _require_token(self.fold_id, "R4 promotion metric fold_id")
        _require_token(self.cost_semantics_version, "R4 promotion metric cost semantics")
        if not self.period_returns:
            raise ValueError("R4 promotion window metric requires period returns")
        for field_name, value in (
            *(("period_return", item) for item in self.period_returns),
            ("gross_return", self.gross_return),
            ("realized_variance", self.realized_variance),
            ("maximum_drawdown", self.maximum_drawdown),
            ("turnover", self.turnover),
            ("expected_cost", self.expected_cost),
        ):
            _require_finite(value, f"R4 promotion metric {field_name}")
        if self.realized_variance < 0 or not Decimal("0") <= self.maximum_drawdown <= 1:
            raise ValueError("R4 promotion window risk metrics are invalid")
        if self.turnover < 0 or self.expected_cost < 0:
            raise ValueError("R4 promotion turnover/cost cannot be negative")
        _require_hash(self.candidate_report_hash, "R4 promotion candidate_report_hash")
        _require_hash(self.source_content_hash, "R4 promotion metric source_content_hash")
        _require_hash(self.content_hash, "R4 promotion metric content_hash")
        if self.content_hash != r4_promotion_window_metric_evidence_hash(self):
            raise ValueError("R4 promotion window metric content hash mismatch")


def _window_metric_payload(
    fold_id: str,
    method: MacroRiskCandidateKind,
    period_returns: tuple[Decimal, ...],
    gross_return: Decimal,
    realized_variance: Decimal,
    maximum_drawdown: Decimal,
    turnover: Decimal,
    expected_cost: Decimal,
    cost_semantics_version: str,
    candidate_report_hash: str,
    source_content_hash: str,
) -> dict[str, object]:
    return {
        "schema": "research-r4-promotion-window-metric.v1",
        "identity": [fold_id, method.value],
        "period_returns": [_decimal_text(item) for item in period_returns],
        "metrics": [
            _decimal_text(gross_return),
            _decimal_text(realized_variance),
            _decimal_text(maximum_drawdown),
            _decimal_text(turnover),
            _decimal_text(expected_cost),
        ],
        "cost_semantics_version": cost_semantics_version,
        "candidate_report_hash": candidate_report_hash,
        "source_content_hash": source_content_hash,
    }


def r4_promotion_window_metric_evidence_hash(
    evidence: R4PromotionWindowMetricEvidence,
) -> str:
    """Recompute one exact method/window evidence projection hash."""

    return _hash_payload(
        _window_metric_payload(
            evidence.fold_id,
            evidence.method,
            evidence.period_returns,
            evidence.gross_return,
            evidence.realized_variance,
            evidence.maximum_drawdown,
            evidence.turnover,
            evidence.expected_cost,
            evidence.cost_semantics_version,
            evidence.candidate_report_hash,
            evidence.source_content_hash,
        )
    )


@dataclass(frozen=True)
class R4PromotionMethodSummaryEvidence:
    """Exact aggregate method summary sealed by Portfolio."""

    method: MacroRiskCandidateKind
    window_count: int
    compounded_gross_return: Decimal
    realized_variance: Decimal
    maximum_drawdown: Decimal
    total_turnover: Decimal
    total_expected_cost: Decimal
    cost_semantics_version: str
    source_content_hash: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        method: MacroRiskCandidateKind,
        window_count: int,
        compounded_gross_return: Decimal,
        realized_variance: Decimal,
        maximum_drawdown: Decimal,
        total_turnover: Decimal,
        total_expected_cost: Decimal,
        cost_semantics_version: str,
        source_content_hash: str,
    ) -> R4PromotionMethodSummaryEvidence:
        """Seal one exact Portfolio method summary projection."""

        values = (
            method,
            window_count,
            compounded_gross_return,
            realized_variance,
            maximum_drawdown,
            total_turnover,
            total_expected_cost,
            cost_semantics_version,
            source_content_hash,
        )
        digest = _hash_payload(_method_summary_payload(*values))
        return cls(*values, digest)

    def __post_init__(self) -> None:
        if isinstance(self.window_count, bool) or self.window_count < 1:
            raise ValueError("R4 promotion summary window_count must be positive")
        for field_name, value in (
            ("compounded_gross_return", self.compounded_gross_return),
            ("realized_variance", self.realized_variance),
            ("maximum_drawdown", self.maximum_drawdown),
            ("total_turnover", self.total_turnover),
            ("total_expected_cost", self.total_expected_cost),
        ):
            _require_finite(value, f"R4 promotion summary {field_name}")
        if self.realized_variance < 0 or not Decimal("0") <= self.maximum_drawdown <= 1:
            raise ValueError("R4 promotion summary risk metrics are invalid")
        if self.total_turnover < 0 or self.total_expected_cost < 0:
            raise ValueError("R4 promotion summary turnover/cost cannot be negative")
        _require_token(self.cost_semantics_version, "R4 promotion summary cost semantics")
        _require_hash(self.source_content_hash, "R4 promotion summary source_content_hash")
        _require_hash(self.content_hash, "R4 promotion summary content_hash")
        if self.content_hash != r4_promotion_method_summary_evidence_hash(self):
            raise ValueError("R4 promotion method summary content hash mismatch")


def _method_summary_payload(
    method: MacroRiskCandidateKind,
    window_count: int,
    compounded_gross_return: Decimal,
    realized_variance: Decimal,
    maximum_drawdown: Decimal,
    total_turnover: Decimal,
    total_expected_cost: Decimal,
    cost_semantics_version: str,
    source_content_hash: str,
) -> dict[str, object]:
    return {
        "schema": "research-r4-promotion-method-summary.v1",
        "method": method.value,
        "window_count": window_count,
        "metrics": [
            _decimal_text(compounded_gross_return),
            _decimal_text(realized_variance),
            _decimal_text(maximum_drawdown),
            _decimal_text(total_turnover),
            _decimal_text(total_expected_cost),
        ],
        "cost_semantics_version": cost_semantics_version,
        "source_content_hash": source_content_hash,
    }


def r4_promotion_method_summary_evidence_hash(
    evidence: R4PromotionMethodSummaryEvidence,
) -> str:
    """Recompute one exact method-summary projection hash."""

    return _hash_payload(
        _method_summary_payload(
            evidence.method,
            evidence.window_count,
            evidence.compounded_gross_return,
            evidence.realized_variance,
            evidence.maximum_drawdown,
            evidence.total_turnover,
            evidence.total_expected_cost,
            evidence.cost_semantics_version,
            evidence.source_content_hash,
        )
    )


__all__ = [
    "R4ArtifactBlocker",
    "R4PromotionMethodSummaryEvidence",
    "R4PromotionR3AttestationEvidence",
    "R4PromotionWindowEvidence",
    "R4PromotionWindowMetricEvidence",
    "R4RecordSubhash",
    "r4_promotion_method_summary_evidence_hash",
    "r4_promotion_r3_attestation_evidence_hash",
    "r4_promotion_window_evidence_hash",
    "r4_promotion_window_metric_evidence_hash",
]
