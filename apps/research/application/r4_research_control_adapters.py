"""Exact Application adapters for the R4 research-control preflight."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.research.application.r4_promotion_decision import R4PromotionDecisionBundle
from apps.research.application.r4_promotion_lifecycle_evidence import R4PromotionScopeRef
from apps.research.application.r4_promotion_monitoring_persistence import (
    R4MonitoringPersistedAssessment,
)
from apps.research.application.r4_research_control_preflight import (
    R4ResearchControlMonitoringEvidence,
)
from apps.research.domain.r4_promotion_decision import R4PromotionDecision
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity


class R4ActivePromotionQuery(Protocol):
    """Fully owner-revalidated active R4 promotion query."""

    def get_active(
        self,
        scope_ref: R4PromotionScopeRef,
        *,
        as_of: datetime,
    ) -> R4PromotionDecisionBundle | None:
        """Return the active exact decision bundle."""


class R4LatestCompleteMonitoringRepository(Protocol):
    """Read-only server selector over the existing R4 monitoring ledger."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_latest_complete_for_active(
        self,
        *,
        active_decision: R4PromotionDecisionIdentity,
        as_of: datetime,
    ) -> R4MonitoringPersistedAssessment | None:
        """Return the unique latest complete period tied to the active decision."""


class R4ActivePromotionExactAdapter:
    """Project the owner-revalidated active promotion selected by scope and PIT."""

    def __init__(self, source: R4ActivePromotionQuery, *, unit_of_work_key: str) -> None:
        self._source = source
        self._unit_of_work_key = _exact_uow_key(unit_of_work_key)

    @property
    def unit_of_work_key(self) -> str:
        """Return the declared shared Research transaction identity."""

        return self._unit_of_work_key

    def get_active(
        self,
        *,
        scope_id: str,
        as_of: datetime,
    ) -> R4PromotionDecisionIdentity | None:
        """Return only the exact active identity selected by scope and cutoff."""

        bundle = self._source.get_active(R4PromotionScopeRef(scope_id), as_of=as_of)
        if bundle is None:
            return None
        if type(bundle) is not R4PromotionDecisionBundle:
            raise TypeError("R4 active promotion query returned another type")
        R4PromotionDecisionBundle.__post_init__(bundle)
        decision = bundle.decision
        if type(decision) is not R4PromotionDecision:
            raise TypeError("R4 active promotion bundle contains another decision type")
        R4PromotionDecision.__post_init__(decision)
        identity = R4PromotionDecisionIdentity.from_decision(decision)
        if not identity.recorded_at <= as_of < identity.valid_until:
            return None
        return identity


class R4LatestCompleteMonitoringExactAdapter:
    """Project one repository-selected full assessment into a strict seal."""

    def __init__(self, repository: R4LatestCompleteMonitoringRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        """Return the live monitoring-ledger transaction identity."""

        return _exact_uow_key(self._repository.unit_of_work_key)

    def get_latest_complete(
        self,
        *,
        active_decision: R4PromotionDecisionIdentity,
        as_of: datetime,
    ) -> R4ResearchControlMonitoringEvidence | None:
        """Return the server-selected complete assessment, never caller health."""

        bundle = self._repository.get_latest_complete_for_active(
            active_decision=active_decision,
            as_of=as_of,
        )
        if bundle is None:
            return None
        if type(bundle) is not R4MonitoringPersistedAssessment:
            raise TypeError("R4 monitoring repository returned another type")
        projected = R4ResearchControlMonitoringEvidence.create(
            active_decision=bundle.active_decision,
            portfolio_result=bundle.portfolio_result,
            current_r3_attestation=bundle.current_r3_attestation,
            policy=bundle.policy,
            period_calendar=bundle.period_calendar,
            observations=bundle.observations,
            assessment=bundle.assessment,
            ledger_recorded_at=bundle.ledger_recorded_at,
        )
        if (
            projected.assessment_ref != bundle.assessment_ref
            or R4PromotionDecisionIdentity.from_decision(projected.active_decision)
            != active_decision
        ):
            raise ValueError("R4 monitoring repository substituted owner evidence")
        return projected


def _exact_uow_key(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise TypeError("R4 research-control unit_of_work_key must be an exact string")
    return value


__all__ = [
    "R4ActivePromotionExactAdapter",
    "R4LatestCompleteMonitoringExactAdapter",
]
