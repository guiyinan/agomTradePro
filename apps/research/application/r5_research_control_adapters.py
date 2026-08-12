"""Exact Application adapters for the R5 research-control preflight."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from apps.fixed_income.application.relative_value_projection import (
    GetExactR5RelativeValueOwnerRecordCommand,
)
from apps.fixed_income.domain.relative_value_record_seal import (
    R5RelativeValueOwnerRecordSeal,
)
from apps.research.application.r5_relative_value_monitoring_persistence import (
    R5MonitoringPersistedAssessment,
)
from apps.research.application.r5_relative_value_promotion_decision import (
    R5RelativeValuePromotionDecisionBundle,
)
from apps.research.application.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueLifecycleEventBundle,
    R5RelativeValueLifecycleScopeRef,
)
from apps.research.application.r5_research_control_preflight import (
    R5ResearchControlMonitoringEvidence,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
    R5MonitoringFixedIncomeEvidence,
)
from apps.research.domain.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueDecisionIdentity,
    derive_r5_relative_value_lifecycle_state,
)


class R5ActivePromotionQuery(Protocol):
    """Fully owner-revalidated active promotion query."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_active(
        self,
        scope_ref: R5RelativeValueLifecycleScopeRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionDecisionBundle | None:
        """Return the active exact decision bundle."""


class R5LifecycleStreamQuery(Protocol):
    """Research lifecycle ledger needed to seal the active stream head."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Activate the Research lifecycle read boundary."""

    def load_lifecycle_stream(
        self,
        scope_ref: R5RelativeValueLifecycleScopeRef,
    ) -> tuple[R5RelativeValueLifecycleEventBundle, ...]:
        """Return the complete scope-local stream."""


class R5LatestCompleteMonitoringRepository(Protocol):
    """Read-only server selector over the existing R5 monitoring ledger."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_latest_complete_for_active(
        self,
        *,
        active_lifecycle: R5MonitoringActiveLifecycle,
        as_of: datetime,
    ) -> R5MonitoringPersistedAssessment | None:
        """Return the latest complete period tied to the active decision."""


class R5FixedIncomeOwnerRecordQuery(Protocol):
    """FixedIncome Application exact owner-seal query."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def execute(
        self,
        command: GetExactR5RelativeValueOwnerRecordCommand,
    ) -> R5RelativeValueOwnerRecordSeal | None:
        """Return one strictly reconstructed result owner seal."""


class R5ActiveLifecycleExactAdapter:
    """Project the owner-revalidated active promotion plus exact stream head."""

    def __init__(
        self,
        *,
        active_query: R5ActivePromotionQuery,
        lifecycle_stream: R5LifecycleStreamQuery,
    ) -> None:
        if active_query.unit_of_work_key != lifecycle_stream.unit_of_work_key:
            raise ValueError("R5 active lifecycle adapter uses different units of work")
        self._active_query = active_query
        self._lifecycle_stream = lifecycle_stream

    @property
    def unit_of_work_key(self) -> str:
        """Return the live common owner transaction identity."""

        active_key = self._active_query.unit_of_work_key
        stream_key = self._lifecycle_stream.unit_of_work_key
        if active_key != stream_key:
            raise ValueError("R5 active lifecycle adapter unit of work changed")
        return active_key

    def get_active(
        self,
        *,
        scope_id: str,
        as_of: datetime,
    ) -> R5MonitoringActiveLifecycle | None:
        """Return a sealed lifecycle projection selected only by scope and PIT."""

        scope_ref = R5RelativeValueLifecycleScopeRef(scope_id)
        with self._lifecycle_stream.atomic():
            bundle = self._active_query.get_active(scope_ref, as_of=as_of)
            stream = self._lifecycle_stream.load_lifecycle_stream(scope_ref)
        if bundle is None:
            return None
        if type(bundle) is not R5RelativeValuePromotionDecisionBundle:
            raise TypeError("R5 active promotion query returned another type")
        R5RelativeValuePromotionDecisionBundle.__post_init__(bundle)
        if type(stream) is not tuple or not stream:
            return None
        for item in stream:
            if type(item) is not R5RelativeValueLifecycleEventBundle:
                raise TypeError("R5 lifecycle stream returned another bundle type")
            R5RelativeValueLifecycleEventBundle.__post_init__(item)
        prefix = tuple(item.event for item in stream if item.event.recorded_at <= as_of)
        if not prefix:
            return None
        snapshot = derive_r5_relative_value_lifecycle_state(prefix, evaluated_at=as_of)
        active_identity = snapshot.active_decision
        decision_identity = R5RelativeValueDecisionIdentity.from_decision(bundle.decision)
        if active_identity is None or active_identity != decision_identity:
            return None
        head = prefix[-1]
        return R5MonitoringActiveLifecycle.create(
            scope_id=decision_identity.scope.scope_id,
            scope_hash=decision_identity.scope.content_hash,
            decision_id=decision_identity.decision_id,
            decision_version=decision_identity.decision_version,
            decision_hash=decision_identity.content_hash,
            trial_id=decision_identity.trial_id,
            trial_hash=decision_identity.trial_content_hash,
            fixed_income_owner_seal_hashes=tuple(
                sorted({item[3] for item in decision_identity.result_identities})
            ),
            stream_id=snapshot.stream_id,
            latest_event_id=head.event_id,
            latest_event_hash=head.content_hash,
            promoted_at=head.occurred_at,
            recorded_at=head.recorded_at,
            valid_until=decision_identity.valid_until,
        )


class R5LatestCompleteMonitoringExactAdapter:
    """Project the repository-selected full assessment into the preflight seal."""

    def __init__(self, repository: R5LatestCompleteMonitoringRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        """Return the live monitoring-ledger transaction identity."""

        return self._repository.unit_of_work_key

    def get_latest_complete(
        self,
        *,
        active_lifecycle: R5MonitoringActiveLifecycle,
        as_of: datetime,
    ) -> R5ResearchControlMonitoringEvidence | None:
        """Return only the server-selected latest complete monitoring evidence."""

        bundle = self._repository.get_latest_complete_for_active(
            active_lifecycle=active_lifecycle,
            as_of=as_of,
        )
        if bundle is None:
            return None
        if type(bundle) is not R5MonitoringPersistedAssessment:
            raise TypeError("R5 monitoring repository returned another type")
        replayed = bundle.assessment.validated_copy(
            policy=bundle.policy,
            calendar=bundle.calendar,
            facts=bundle.portfolio_facts,
        )
        if replayed != bundle.assessment or bundle.active_lifecycle != active_lifecycle:
            raise ValueError("R5 monitoring repository substituted owner evidence")
        latest_period_id = bundle.assessment.latest_period_id
        if latest_period_id is None or latest_period_id != bundle.calendar.entries[-1].period_id:
            raise ValueError("R5 monitoring repository returned an incomplete period")
        return R5ResearchControlMonitoringEvidence.create(
            assessment_id=bundle.assessment_ref.assessment_id,
            assessment_hash=bundle.assessment_ref.assessment_hash,
            active_lifecycle=bundle.active_lifecycle,
            fixed_income=bundle.fixed_income,
            latest_period_id=latest_period_id,
            latest_period_end=bundle.calendar.entries[-1].period_end,
            evaluated_at=bundle.assessment.evaluated_at,
            ledger_recorded_at=bundle.ledger_recorded_at,
            status=bundle.assessment.status,
        )


class R5FixedIncomeOwnerSealExactAdapter:
    """Map an exact FixedIncome owner record into monitoring evidence."""

    def __init__(self, query: R5FixedIncomeOwnerRecordQuery) -> None:
        self._query = query

    @property
    def unit_of_work_key(self) -> str:
        """Return the live FixedIncome transaction identity."""

        return self._query.unit_of_work_key

    def get_exact(
        self,
        *,
        evidence: R5MonitoringFixedIncomeEvidence,
        as_of: datetime,
    ) -> R5MonitoringFixedIncomeEvidence | None:
        """Reread the exact result and reject any owner-seal substitution."""

        if type(evidence) is not R5MonitoringFixedIncomeEvidence:
            raise TypeError("R5 FixedIncome monitoring evidence type differs")
        expected = evidence.validated_copy()
        if expected.owner_seal_version != "v1":
            return None
        record = self._query.execute(
            GetExactR5RelativeValueOwnerRecordCommand(
                result_id=expected.result_id,
                result_version=expected.result_version,
                expected_record_hash=expected.result_hash,
                as_of=as_of,
            )
        )
        if record is None:
            return None
        if type(record) is not R5RelativeValueOwnerRecordSeal:
            raise TypeError("R5 FixedIncome owner query returned another type")
        R5RelativeValueOwnerRecordSeal.__post_init__(record)
        actual = R5MonitoringFixedIncomeEvidence.create(
            result_id=record.result_id,
            result_version=record.result_version,
            result_hash=record.result_record_hash,
            owner_seal_id=record.owner_record_key,
            owner_seal_version="v1",
            owner_seal_hash=record.content_hash,
            recorded_at=record.recorded_at,
        )
        return actual if actual == expected else None


__all__ = [
    "R5ActiveLifecycleExactAdapter",
    "R5FixedIncomeOwnerSealExactAdapter",
    "R5LatestCompleteMonitoringExactAdapter",
]
