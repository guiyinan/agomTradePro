"""Read-only latest-complete selector for the R4 research-control gate."""

from __future__ import annotations

from datetime import datetime

from apps.research.application.r4_promotion_monitoring_persistence import (
    R4MonitoringPersistedAssessment,
    R4MonitoringPersistenceCorruption,
    R4MonitoringPersistenceUnavailable,
)
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import R4MonitoringAssessmentStatus
from apps.research.infrastructure.r4_promotion_monitoring_models import (
    R4MonitoringAssessmentLedgerModel,
)
from apps.research.infrastructure.r4_promotion_monitoring_repository import (
    DjangoR4MonitoringRepository,
)


class DjangoR4ResearchControlMonitoringRepository(DjangoR4MonitoringRepository):
    """Add one server-side selector without widening the base public repository."""

    def get_latest_complete_for_active(
        self,
        *,
        active_decision: R4PromotionDecisionIdentity,
        as_of: datetime,
    ) -> R4MonitoringPersistedAssessment | None:
        """Select the unique latest complete period for one active decision."""

        self._require_pit_cutoff(as_of)
        try:
            if type(active_decision) is not R4PromotionDecisionIdentity:
                raise TypeError("active decision identity type differs")
            R4PromotionDecisionIdentity.__post_init__(active_decision)
        except (AttributeError, TypeError, ValueError) as error:
            raise R4MonitoringPersistenceUnavailable(
                "R4 monitoring active selector is malformed"
            ) from error
        if not active_decision.recorded_at <= as_of < active_decision.valid_until:
            return None
        rows = tuple(
            R4MonitoringAssessmentLedgerModel._default_manager.using(self._using)
            .filter(
                active_decision_stable_id=active_decision.decision_id,
                active_decision_version=active_decision.decision_version,
                active_decision_hash=active_decision.content_hash,
                evaluated_at__lte=as_of,
                ledger_recorded_at__lte=as_of,
                observation_count__gt=0,
                status__in=(
                    R4MonitoringAssessmentStatus.HEALTHY.value,
                    R4MonitoringAssessmentStatus.BREACHED.value,
                    R4MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED.value,
                ),
            )
            .select_related(
                "active_decision",
                "active_decision__receipt",
                "active_decision__policy",
            )
        )
        restored = tuple(self._restore_bundle(row) for row in rows)
        complete = tuple(
            bundle
            for bundle in restored
            if _is_complete_active_monitoring_bundle(
                bundle,
                active_decision=active_decision,
                as_of=as_of,
            )
        )
        if not complete:
            return None
        ordered = tuple(sorted(complete, key=_latest_complete_sort_key, reverse=True))
        winner = ordered[0]
        winner_key = _latest_complete_rank_key(winner)
        ties = tuple(item for item in ordered if _latest_complete_rank_key(item) == winner_key)
        if len(ties) != 1:
            raise R4MonitoringPersistenceCorruption(
                "R4 monitoring latest complete selector has multiple winners"
            )
        return winner


def _is_complete_active_monitoring_bundle(
    bundle: R4MonitoringPersistedAssessment,
    *,
    active_decision: R4PromotionDecisionIdentity,
    as_of: datetime,
) -> bool:
    assessment = bundle.assessment
    completed = tuple(
        entry
        for entry in bundle.period_calendar.entries
        if entry.period_end <= assessment.evaluated_at
    )
    return bool(
        R4PromotionDecisionIdentity.from_decision(bundle.active_decision) == active_decision
        and bundle.ledger_recorded_at <= as_of
        and assessment.evaluated_at <= bundle.ledger_recorded_at
        and completed
        and tuple(item.period_id for item in bundle.observations)
        == tuple(item.period_id for item in completed)
        and assessment.observation_hashes
        == tuple(item.content_hash for item in bundle.observations)
        and assessment.status
        in {
            R4MonitoringAssessmentStatus.HEALTHY,
            R4MonitoringAssessmentStatus.BREACHED,
            R4MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED,
        }
        and assessment.research_only
        and assessment.must_not_publish_current
        and assessment.must_not_use_for_decision
        and assessment.must_not_execute
    )


def _latest_complete_sort_key(
    bundle: R4MonitoringPersistedAssessment,
) -> tuple[datetime, datetime, datetime, str]:
    completed = tuple(
        entry
        for entry in bundle.period_calendar.entries
        if entry.period_end <= bundle.assessment.evaluated_at
    )
    return (
        completed[-1].period_end,
        bundle.assessment.evaluated_at,
        bundle.ledger_recorded_at,
        bundle.assessment_ref.assessment_id,
    )


def _latest_complete_rank_key(
    bundle: R4MonitoringPersistedAssessment,
) -> tuple[datetime, datetime, datetime]:
    return _latest_complete_sort_key(bundle)[:3]


__all__ = ["DjangoR4ResearchControlMonitoringRepository"]
