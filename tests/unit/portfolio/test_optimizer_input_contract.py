"""Tests for the R8 research-only optimizer input contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.portfolio.application.optimizer_inputs import EvaluateOptimizerInputsUseCase
from apps.portfolio.domain.optimizer_inputs import (
    OptimizationEvidenceState,
    OptimizationInputEvidence,
    OptimizationInputKind,
    OptimizationInputRequirement,
    OptimizerInputBundle,
    OptimizerInputContract,
    PromotionReference,
    evaluate_optimizer_input_bundle,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)
UNIVERSE_HASH = "sha256:universe-v1"


def _contract() -> OptimizerInputContract:
    return OptimizerInputContract(
        contract_version="multi-asset-input.v1",
        methodology="research_multi_asset",
        requirements=(
            OptimizationInputRequirement(
                OptimizationInputKind.EXPECTED_RETURN,
                "research",
            ),
            OptimizationInputRequirement(
                OptimizationInputKind.ASSET_COVARIANCE,
                "portfolio",
            ),
            OptimizationInputRequirement(
                OptimizationInputKind.SCENARIO_LOSS,
                "risk_center",
            ),
        ),
        required_promotion_keys=("r3", "r4", "r5"),
        activated_at=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=30),
    )


def _evidence(
    kind: OptimizationInputKind,
    owner: str,
    *,
    valid_until: datetime | None = None,
    universe_hash: str = UNIVERSE_HASH,
) -> OptimizationInputEvidence:
    return OptimizationInputEvidence(
        kind=kind,
        owner=owner,
        state=OptimizationEvidenceState.VERIFIED,
        observed_at=NOW - timedelta(hours=1),
        valid_until=valid_until or NOW + timedelta(days=1),
        version=f"{kind.value}.v1",
        evidence_ref=f"evidence:{kind.value}:v1",
        content_hash=f"sha256:{kind.value}",
        universe_hash=universe_hash,
    )


def _promotion(key: str, *, valid_until: datetime | None = None) -> PromotionReference:
    return PromotionReference(
        capability_key=key,
        version=f"{key}.v1",
        decision_ref=f"promotion:{key}:v1",
        approved_at=NOW - timedelta(days=1),
        valid_until=valid_until or NOW + timedelta(days=30),
    )


def _bundle(
    *,
    evidence: tuple[OptimizationInputEvidence, ...],
    promotions: tuple[PromotionReference, ...],
) -> OptimizerInputBundle:
    return OptimizerInputBundle(
        bundle_id="bundle-1",
        contract_version="multi-asset-input.v1",
        portfolio_snapshot_id="portfolio-snapshot-1",
        decision_snapshot_id="decision-snapshot-1",
        universe_hash=UNIVERSE_HASH,
        evaluated_at=NOW,
        evidence=evidence,
        promotions=promotions,
    )


def test_complete_bundle_can_only_run_a_research_preview() -> None:
    contract = _contract()
    evidence = tuple(_evidence(item.kind, item.canonical_owner) for item in contract.requirements)
    promotions = tuple(_promotion(key) for key in contract.required_promotion_keys)

    report = evaluate_optimizer_input_bundle(
        contract=contract,
        bundle=_bundle(evidence=evidence, promotions=promotions),
    )

    assert report.can_run_research_preview is True
    assert report.must_not_execute is True
    assert report.blockers == ()


def test_missing_inputs_and_promotions_are_materialized_as_blockers() -> None:
    report = evaluate_optimizer_input_bundle(
        contract=_contract(),
        bundle=_bundle(evidence=(), promotions=()),
    )

    assert report.can_run_research_preview is False
    assert len(report.evidence) == 3
    assert len(report.blockers) == 6
    assert all(item.reason_code.endswith(".missing") for item in report.blockers)


def test_expired_and_wrong_universe_inputs_fail_closed() -> None:
    contract = _contract()
    evidence = (
        _evidence(
            OptimizationInputKind.EXPECTED_RETURN,
            "research",
            valid_until=NOW,
        ),
        _evidence(
            OptimizationInputKind.ASSET_COVARIANCE,
            "portfolio",
            universe_hash="sha256:other-universe",
        ),
        _evidence(OptimizationInputKind.SCENARIO_LOSS, "risk_center"),
    )

    report = evaluate_optimizer_input_bundle(
        contract=contract,
        bundle=_bundle(
            evidence=evidence,
            promotions=tuple(_promotion(key) for key in contract.required_promotion_keys),
        ),
    )

    states = {item.kind: item.state for item in report.evidence}
    assert states[OptimizationInputKind.EXPECTED_RETURN] is OptimizationEvidenceState.STALE
    assert states[OptimizationInputKind.ASSET_COVARIANCE] is OptimizationEvidenceState.CONFLICT
    assert report.can_run_research_preview is False


def test_owner_mismatch_and_duplicate_evidence_are_rejected() -> None:
    contract = _contract()
    wrong_owner = _evidence(OptimizationInputKind.EXPECTED_RETURN, "portfolio")
    duplicate = _evidence(OptimizationInputKind.EXPECTED_RETURN, "research")

    with pytest.raises(ValueError, match="must be owned by research"):
        evaluate_optimizer_input_bundle(
            contract=contract,
            bundle=_bundle(evidence=(wrong_owner,), promotions=()),
        )
    with pytest.raises(ValueError, match="duplicate optimization input"):
        evaluate_optimizer_input_bundle(
            contract=contract,
            bundle=_bundle(evidence=(duplicate, duplicate), promotions=()),
        )


def test_expired_promotion_blocks_preview() -> None:
    contract = _contract()
    evidence = tuple(_evidence(item.kind, item.canonical_owner) for item in contract.requirements)
    promotions = tuple(
        _promotion(key, valid_until=NOW if key == "r4" else None)
        for key in contract.required_promotion_keys
    )

    report = evaluate_optimizer_input_bundle(
        contract=contract,
        bundle=_bundle(evidence=evidence, promotions=promotions),
    )

    assert report.can_run_research_preview is False
    assert [item.reason_code for item in report.blockers] == ["optimizer_input.promotion.r4.stale"]


class _ContractProvider:
    def get_active(self, *, evaluated_at: datetime) -> OptimizerInputContract:
        assert evaluated_at == NOW
        return _contract()


class _EvidenceProvider:
    def collect_inputs(
        self,
        *,
        contract: OptimizerInputContract,
        portfolio_snapshot_id: str,
        universe_hash: str,
        evaluated_at: datetime,
    ) -> tuple[OptimizationInputEvidence, ...]:
        assert portfolio_snapshot_id == "portfolio-snapshot-1"
        assert universe_hash == UNIVERSE_HASH
        assert evaluated_at == NOW
        return tuple(_evidence(item.kind, item.canonical_owner) for item in contract.requirements)

    def collect_promotions(
        self,
        *,
        contract: OptimizerInputContract,
        evaluated_at: datetime,
    ) -> tuple[PromotionReference, ...]:
        assert evaluated_at == NOW
        return tuple(_promotion(key) for key in contract.required_promotion_keys)


def test_application_use_case_collects_versioned_owner_evidence() -> None:
    report = EvaluateOptimizerInputsUseCase(
        contract_provider=_ContractProvider(),
        evidence_provider=_EvidenceProvider(),
    ).execute(
        bundle_id="bundle-1",
        portfolio_snapshot_id="portfolio-snapshot-1",
        decision_snapshot_id="decision-snapshot-1",
        universe_hash=UNIVERSE_HASH,
        evaluated_at=NOW,
    )

    assert report.can_run_research_preview is True
    assert report.must_not_execute is True
