"""Thin exact-read adapters for the canonical R4 monitoring owner graph."""

from __future__ import annotations

from datetime import datetime

from apps.portfolio.application.macro_risk_rolling_research import (
    ExactR3PromotionProvider,
)
from apps.portfolio.application.r4_rolling_research_query import (
    R4RollingResearchExactQuery,
)
from apps.portfolio.infrastructure.r4_monitoring_raw_fact_repository import (
    DjangoPortfolioR4MonitoringRawFactRepository,
)
from apps.research.application.r4_promotion_lifecycle import R4ActivePromotionProvider
from apps.research.application.r4_promotion_lifecycle_evidence import R4PromotionScopeRef
from apps.research.application.r4_promotion_projection import (
    project_r4_portfolio_owner_record,
    project_r4_promotion_r3_attestation,
)
from apps.research.domain.r4_promotion_decision import R4PromotionDecision
from apps.research.domain.r4_promotion_evidence import R4PromotionR3AttestationEvidence
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import (
    R4MonitoringMetricKey,
    R4MonitoringMetricObservation,
    R4MonitoringObservation,
)
from apps.research.domain.r4_promotion_record_seal import R4PromotionPortfolioRecordSeal


def _require_uow_key(value: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("canonical owner unit_of_work_key must be non-blank")
    return value


class R4MonitoringActiveDecisionAdapter:
    """Adapt the canonical promotion lifecycle provider to exact monitoring reads."""

    def __init__(self, source: R4ActivePromotionProvider, *, unit_of_work_key: str) -> None:
        self._source = source
        self._unit_of_work_key = _require_uow_key(unit_of_work_key)

    @property
    def unit_of_work_key(self) -> str:
        return self._unit_of_work_key

    def get_exact_active(
        self,
        *,
        active_decision: R4PromotionDecisionIdentity,
        as_of: datetime,
    ) -> R4PromotionDecision | None:
        bundle = self._source.get_active(
            R4PromotionScopeRef(active_decision.scope.scope_id), as_of=as_of
        )
        if bundle is None:
            return None
        decision = bundle.decision
        if (
            type(decision) is not R4PromotionDecision
            or R4PromotionDecisionIdentity.from_decision(decision) != active_decision
        ):
            return None
        return decision


class R4MonitoringPortfolioResultAdapter:
    """Project the canonical Portfolio rolling-research owner record exactly."""

    def __init__(self, source: R4RollingResearchExactQuery) -> None:
        self._source = source

    @property
    def unit_of_work_key(self) -> str:
        return _require_uow_key(self._source.unit_of_work_key)

    def get_exact(
        self,
        *,
        record_id: str,
        record_version: str,
        expected_record_hash: str,
        as_of: datetime,
    ) -> R4PromotionPortfolioRecordSeal | None:
        owner = self._source.get_exact(
            record_id=record_id,
            expected_record_hash=expected_record_hash,
            as_of=as_of,
        )
        if owner is None:
            return None
        record = project_r4_portfolio_owner_record(owner)
        if (
            record.record_id != record_id
            or record.record_version != record_version
            or record.record_hash.lower() != expected_record_hash.lower()
        ):
            return None
        return record


class R4MonitoringR3AttestationAdapter:
    """Project the canonical R3 exact provider without latest fallback."""

    def __init__(self, source: ExactR3PromotionProvider, *, unit_of_work_key: str) -> None:
        self._source = source
        self._unit_of_work_key = _require_uow_key(unit_of_work_key)

    @property
    def unit_of_work_key(self) -> str:
        return self._unit_of_work_key

    def get_exact(
        self,
        *,
        artifact_id: str,
        artifact_version: str,
        artifact_content_hash: str,
        decision_id: str,
        decision_version: str,
        decision_content_hash: str,
        expected_attestation_hash: str,
        as_of: datetime,
    ) -> R4PromotionR3AttestationEvidence | None:
        owner = self._source.get_exact(
            capability_key="macro_factor_r3",
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            artifact_content_hash=artifact_content_hash,
            decision_id=decision_id,
            decision_version=decision_version,
            decision_content_hash=decision_content_hash,
            as_of=as_of,
        )
        if owner is None:
            return None
        evidence = project_r4_promotion_r3_attestation(owner)
        if evidence.attestation_hash.lower() != expected_attestation_hash.lower():
            return None
        return evidence


class R4MonitoringRawFactAdapter:
    """Project Portfolio owner receipts into Research monitoring observations."""

    def __init__(self, source: DjangoPortfolioR4MonitoringRawFactRepository) -> None:
        self._source = source

    @property
    def unit_of_work_key(self) -> str:
        return self._source.unit_of_work_key

    def list_exact(
        self,
        *,
        active_decision: R4PromotionDecisionIdentity,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        as_of: datetime,
    ) -> tuple[R4MonitoringObservation, ...]:
        receipts = self._source.list_exact(
            active_decision_id=active_decision.decision_id,
            active_decision_version=active_decision.decision_version,
            active_decision_hash=active_decision.content_hash,
            policy_id=policy_id,
            policy_version=policy_version,
            policy_hash=expected_policy_hash,
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            calendar_hash=expected_calendar_hash,
            as_of=as_of,
        )
        return tuple(
            R4MonitoringObservation(
                observation_id=item.observation_id,
                observation_version=item.observation_version,
                period_id=item.period_id,
                period_calendar_id=item.calendar_id,
                period_calendar_version=item.calendar_version,
                period_calendar_hash=item.calendar_hash,
                period_start=item.period_start,
                period_end=item.period_end,
                active_decision=active_decision,
                policy_id=item.policy_id,
                policy_version=item.policy_version,
                policy_hash=item.policy_hash,
                source_owner=item.owner,
                portfolio_record_id=item.portfolio_record_id,
                portfolio_record_hash=item.portfolio_record_hash,
                portfolio_record_content_hash=item.portfolio_record_content_hash,
                r3_attestation_content_hash=item.r3_attestation_content_hash,
                observed_at=item.observed_at,
                available_at=item.available_at,
                recorded_at=item.owner_recorded_at,
                valid_until=item.valid_until,
                pit_manifest_id=item.pit_manifest_id,
                pit_manifest_hash=item.pit_manifest_hash,
                evidence_ref=item.evidence_ref,
                label_protocol_version=item.label_protocol_version,
                observed_label_set_hash=item.observed_label_set_hash,
                observed_data_schema_hash=item.observed_data_schema_hash,
                metrics=tuple(
                    R4MonitoringMetricObservation(
                        metric_key=R4MonitoringMetricKey(metric.metric_key),
                        unit=metric.unit,
                        value=metric.value,
                    )
                    for metric in item.metrics
                ),
            )
            for item in receipts
        )


__all__ = [
    "R4MonitoringActiveDecisionAdapter",
    "R4MonitoringPortfolioResultAdapter",
    "R4MonitoringR3AttestationAdapter",
    "R4MonitoringRawFactAdapter",
]
