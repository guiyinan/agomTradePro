"""Tests for the fail-closed legacy Strategy decision adapter."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.research.application.evidence_summary import EvidenceSummaryDTO
from apps.research.application.strategy_evidence_adapter import (
    LegacyStrategyDecisionProjection,
    build_strategy_decision_legacy_evidence_summary,
)

NOW = datetime(2026, 8, 13, 9, tzinfo=UTC)


def _projection() -> LegacyStrategyDecisionProjection:
    return LegacyStrategyDecisionProjection(
        action="allow",
        reason_codes=("regime.allowed", "risk.within_limits"),
        reason_text="Regime and risk checks allow the proposed action.",
        valid_until=NOW + timedelta(minutes=15),
        confidence=0.85,
    )


def _summary(projection: LegacyStrategyDecisionProjection) -> EvidenceSummaryDTO:
    return build_strategy_decision_legacy_evidence_summary(projection, evaluated_at=NOW)


def test_strategy_decision_adapter_is_content_bound_and_display_only() -> None:
    first = _summary(_projection())
    changed = _summary(replace(_projection(), confidence=0.75))

    assert first.output_owner == "strategy"
    assert first.output_artifact_type == "decision_result"
    assert first.output_artifact_id == first.output_content_hash
    assert first.output_artifact_version == "decision-result-v1"
    assert first.claim_kind == "recommendation"
    assert first.method_kind == "deterministic"
    assert first.governance_state == "research_only"
    assert first.permission == "display_only"
    assert first.blocker_codes == ("evidence.legacy_unverified",)
    assert first.must_not_use_for_decision is True
    assert first.must_not_execute is True
    assert first.output_content_hash != changed.output_content_hash
    assert first.envelope_content_hash != changed.envelope_content_hash


def test_strategy_decision_adapter_rejects_unverifiable_projection() -> None:
    projections = (
        replace(_projection(), action="buy"),
        replace(_projection(), reason_codes=()),
        replace(_projection(), reason_codes=("risk.z", "risk.a")),
        replace(_projection(), reason_codes=("risk.same", "risk.same")),
        replace(_projection(), reason_text=""),
        replace(_projection(), valid_until=NOW),
        replace(_projection(), valid_until=(NOW + timedelta(minutes=15)).replace(tzinfo=None)),
        replace(_projection(), confidence=float("nan")),
        replace(_projection(), confidence=1.01),
    )
    for projection in projections:
        with pytest.raises((TypeError, ValueError)):
            _summary(projection)


def test_strategy_decision_adapter_rejects_naive_evaluation_clock() -> None:
    with pytest.raises(ValueError, match="evaluated_at"):
        build_strategy_decision_legacy_evidence_summary(
            _projection(), evaluated_at=NOW.replace(tzinfo=None)
        )
