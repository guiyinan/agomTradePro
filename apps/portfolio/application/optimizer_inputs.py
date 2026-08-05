"""Application orchestration for governed optimizer input bundles."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.portfolio.domain.optimizer_inputs import (
    OptimizationInputEvidence,
    OptimizerInputBundle,
    OptimizerInputContract,
    OptimizerInputReadiness,
    PromotionReference,
    evaluate_optimizer_input_bundle,
)


class OptimizerInputContractProvider(Protocol):
    """Read the active Portfolio-owned optimization input contract."""

    def get_active(self, *, evaluated_at: datetime) -> OptimizerInputContract:
        """Return the contract active at the requested evaluation time."""


class OptimizerInputEvidenceProvider(Protocol):
    """Collect owner-attested input and promotion references."""

    def collect_inputs(
        self,
        *,
        contract: OptimizerInputContract,
        portfolio_snapshot_id: str,
        universe_hash: str,
        evaluated_at: datetime,
    ) -> tuple[OptimizationInputEvidence, ...]:
        """Return available inputs without synthesizing missing evidence."""

    def collect_promotions(
        self,
        *,
        contract: OptimizerInputContract,
        evaluated_at: datetime,
    ) -> tuple[PromotionReference, ...]:
        """Return approved upstream versions required by the contract."""


class EvaluateOptimizerInputsUseCase:
    """Assemble and validate a research-only optimization input bundle."""

    def __init__(
        self,
        *,
        contract_provider: OptimizerInputContractProvider,
        evidence_provider: OptimizerInputEvidenceProvider,
    ) -> None:
        self._contract_provider = contract_provider
        self._evidence_provider = evidence_provider

    def execute(
        self,
        *,
        bundle_id: str,
        portfolio_snapshot_id: str,
        decision_snapshot_id: str,
        universe_hash: str,
        evaluated_at: datetime,
    ) -> OptimizerInputReadiness:
        """Collect exact-version evidence and return a fail-closed report."""

        contract = self._contract_provider.get_active(evaluated_at=evaluated_at)
        evidence = self._evidence_provider.collect_inputs(
            contract=contract,
            portfolio_snapshot_id=portfolio_snapshot_id,
            universe_hash=universe_hash,
            evaluated_at=evaluated_at,
        )
        promotions = self._evidence_provider.collect_promotions(
            contract=contract,
            evaluated_at=evaluated_at,
        )
        bundle = OptimizerInputBundle(
            bundle_id=bundle_id,
            contract_version=contract.contract_version,
            portfolio_snapshot_id=portfolio_snapshot_id,
            decision_snapshot_id=decision_snapshot_id,
            universe_hash=universe_hash,
            evaluated_at=evaluated_at,
            evidence=evidence,
            promotions=promotions,
        )
        return evaluate_optimizer_input_bundle(contract=contract, bundle=bundle)
