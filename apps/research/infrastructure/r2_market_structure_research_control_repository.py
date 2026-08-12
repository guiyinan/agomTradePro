"""Read-only latest-complete selection for the R2 research-control preflight."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.research.application.r2_market_structure_research_control_preflight import (
    R2LatestCompleteTrialMonitoringEvidence,
)
from apps.research.application.r2_market_structure_trial_monitoring_persistence import (
    R2TrialMonitoringPersistenceCorruption,
    R2TrialMonitoringPersistenceUnavailable,
)
from apps.research.domain.r2_market_structure_trial_monitoring import (
    R2EvidenceRef,
    R2MonitoringStatus,
    R2TrialStatus,
)
from apps.research.infrastructure.r2_market_structure_trial_monitoring_models import (
    R2MonitoringAssessmentLedgerModel,
)
from apps.research.infrastructure.r2_market_structure_trial_monitoring_repository import (
    DjangoR2TrialMonitoringRepository,
    _restore_trial_row,
)


class R2ResearchControlClock(Protocol):
    """Caller-independent server clock used by the read repository."""

    def now(self) -> datetime:
        """Return a timezone-aware server timestamp."""


class DjangoR2ResearchControlReadRepository:
    """Shared read UoW and unique latest-complete 0016 selector."""

    __slots__ = ("_clock", "_reader", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R2ResearchControlClock | None = None,
    ) -> None:
        self._using = _exact_using(using)
        self._clock = clock
        self._reader = DjangoR2TrialMonitoringRepository(using=self._using)

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database-alias identity."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Open one shared read transaction."""

        return transaction.atomic(using=self._using)

    def server_now(self) -> datetime:
        """Return the trusted application-server timestamp."""

        value = timezone.now() if self._clock is None else self._clock.now()
        return _aware(value, "R2 research-control server clock")

    def get_latest_complete(
        self,
        *,
        policy_ref: R2EvidenceRef,
        as_of: datetime,
    ) -> R2LatestCompleteTrialMonitoringEvidence | None:
        """Select one latest complete pair; reject a same-rank fork."""

        if type(policy_ref) is not R2EvidenceRef:
            raise R2TrialMonitoringPersistenceUnavailable(
                "R2 research-control policy reference type differs"
            )
        R2EvidenceRef.__post_init__(policy_ref)
        cutoff = _aware(as_of, "R2 research-control PIT cutoff")
        if cutoff > self.server_now():
            raise R2TrialMonitoringPersistenceUnavailable(
                "R2 research-control PIT cutoff is in the future"
            )
        try:
            rows = tuple(
                R2MonitoringAssessmentLedgerModel._default_manager.using(self._using)
                .filter(
                    Q(
                        policy_id=policy_ref.evidence_id,
                        policy_version=policy_ref.evidence_version,
                    )
                    | Q(policy_hash=policy_ref.content_hash.lower()),
                    ledger_recorded_at__lte=cutoff,
                    owner_valid_until__gt=cutoff,
                    trial_assessment__ledger_recorded_at__lte=cutoff,
                    trial_assessment__owner_valid_until__gt=cutoff,
                )
                .select_related("trial_assessment")
                .order_by("-assessed_at", "-ledger_recorded_at", "-pk")
            )
            complete: list[R2LatestCompleteTrialMonitoringEvidence] = []
            for row in rows:
                trial = _restore_trial_row(row.trial_assessment)
                monitoring = self._reader._restore_monitoring_row(row)
                if trial.evidence.policy.reference != policy_ref:
                    raise R2TrialMonitoringPersistenceCorruption(
                        "R2 latest-complete policy identity is aliased"
                    )
                if (
                    trial.evidence.assessment.status is R2TrialStatus.PASSED
                    and monitoring.evidence.assessment.status is not R2MonitoringStatus.BLOCKED
                ):
                    complete.append(
                        R2LatestCompleteTrialMonitoringEvidence.create(
                            trial=trial,
                            monitoring=monitoring,
                        )
                    )
            return _select_latest_complete(tuple(complete))
        except (
            R2TrialMonitoringPersistenceCorruption,
            R2TrialMonitoringPersistenceUnavailable,
        ):
            raise
        except Exception as error:
            raise R2TrialMonitoringPersistenceUnavailable(
                "R2 latest-complete read is unavailable"
            ) from error


def _select_latest_complete(
    values: tuple[R2LatestCompleteTrialMonitoringEvidence, ...],
) -> R2LatestCompleteTrialMonitoringEvidence | None:
    """Select the highest assessed/ledger rank and reject an exact-rank fork."""

    if not values:
        return None
    validated = tuple(item.validated_copy() for item in values)
    highest_rank = max(_latest_rank(item) for item in validated)
    winners = tuple(item for item in validated if _latest_rank(item) == highest_rank)
    if len(winners) != 1:
        raise R2TrialMonitoringPersistenceCorruption(
            "R2 latest-complete assessment has a same-rank fork"
        )
    return winners[0]


def _latest_rank(
    value: R2LatestCompleteTrialMonitoringEvidence,
) -> tuple[datetime, datetime]:
    return (
        value.monitoring.evidence.assessment.assessed_at,
        value.monitoring.ledger_recorded_at,
    )


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise R2TrialMonitoringPersistenceUnavailable(f"{field_name} must be timezone-aware")
    return value


def _exact_using(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 192:
        raise ValueError("R2 research-control database alias is invalid")
    return value


__all__ = ["DjangoR2ResearchControlReadRepository"]
