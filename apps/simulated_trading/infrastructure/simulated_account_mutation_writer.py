"""Transaction-bound writer for SimulatedAccount physical-row observations."""

from __future__ import annotations

from datetime import timedelta

from django.db import connections

from apps.simulated_trading.application.simulated_account_raw_observation import (
    RecordSimulatedAccountRawObservation,
    SimulatedAccountPhysicalRowMutation,
    SimulatedAccountRawObservationConflict,
    SimulatedAccountRawObservationRepository,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)


class DjangoSimulatedAccountMutationWriter:
    """Append raw evidence inside an already-active owner database transaction."""

    __slots__ = ("_recorder", "_repository", "_using", "_validity_period")

    def __init__(
        self,
        *,
        repository: SimulatedAccountRawObservationRepository,
        using: str,
        validity_period: timedelta,
    ) -> None:
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be an explicit canonical database alias")
        if repository.database_alias != using:
            raise ValueError("raw repository database alias differs from owner mutation alias")
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._repository = repository
        self._recorder = RecordSimulatedAccountRawObservation(repository)
        self._using = using
        self._validity_period = validity_period

    def record_create(
        self, mutation: SimulatedAccountPhysicalRowMutation
    ) -> SimulatedAccountRawObservation:
        """Record an exact present root, or replay the same opaque event."""

        return self._record(mutation, is_present=True, is_tombstone=False, require_head=False)

    def record_update(
        self, mutation: SimulatedAccountPhysicalRowMutation
    ) -> SimulatedAccountRawObservation:
        """Record an exact present successor, or replay the same opaque event."""

        return self._record(mutation, is_present=True, is_tombstone=False, require_head=True)

    def record_delete(
        self, mutation: SimulatedAccountPhysicalRowMutation
    ) -> SimulatedAccountRawObservation:
        """Record an exact tombstone successor, or replay the same opaque event."""

        return self._record(mutation, is_present=False, is_tombstone=True, require_head=True)

    def _record(
        self,
        mutation: SimulatedAccountPhysicalRowMutation,
        *,
        is_present: bool,
        is_tombstone: bool,
        require_head: bool,
    ) -> SimulatedAccountRawObservation:
        if type(mutation) is not SimulatedAccountPhysicalRowMutation:
            raise TypeError("mutation must be an exact SimulatedAccountPhysicalRowMutation")
        SimulatedAccountPhysicalRowMutation.__post_init__(mutation)
        if not connections[self._using].in_atomic_block:
            raise SimulatedAccountRawObservationConflict(
                "raw observation write requires the owner mutation transaction"
            )
        cutoff = self._repository.now()
        winner = self._repository.get_winner(
            observation_id=mutation.observation_id,
            observation_version=mutation.mutation_version,
            as_of=cutoff,
        )
        head = self._repository.get_physical_row_head(row_pk=mutation.row_pk, as_of=cutoff)
        if winner is not None:
            predecessor_hash = winner.observation.supersedes_content_hash
        else:
            predecessor_hash = head.observation.content_hash if head is not None else None
        if head is not None and head.observation.observation_id != mutation.observation_id:
            raise SimulatedAccountRawObservationConflict(
                "opaque observation_id changed for the physical row"
            )
        if winner is None and require_head != (head is not None):
            raise SimulatedAccountRawObservationConflict(
                "physical-row mutation kind does not match ledger existence"
            )
        observation = SimulatedAccountRawObservation(
            observation_id=mutation.observation_id,
            observation_version=mutation.mutation_version,
            row_pk=mutation.row_pk,
            row_user_id=mutation.row_user_id,
            raw_account_type=mutation.raw_account_type,
            is_active=mutation.is_active if is_present else False,
            row_created_at=mutation.row_created_at,
            row_updated_at=mutation.row_updated_at,
            is_present=is_present,
            is_tombstone=is_tombstone,
            observed_at=mutation.observed_at,
            valid_until=mutation.observed_at + self._validity_period,
            supersedes_content_hash=predecessor_hash,
        )
        return self._recorder.execute(observation)


__all__ = ["DjangoSimulatedAccountMutationWriter"]
