"""Read-only owner adapter from the raw ledger to source-v2 capture."""

from __future__ import annotations

from datetime import datetime

from apps.simulated_trading.application.simulated_account_raw_observation import (
    PersistedSimulatedAccountRawObservation,
    SimulatedAccountRawObservationConflict,
    SimulatedAccountRawObservationCorruption,
    SimulatedAccountRawObservationRepository,
    SimulatedAccountRawObservationUnavailable,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    ExactRawSimulatedAccountObservationV2,
    SimulatedAccountRowSourceV2Corruption,
)


class DjangoExactRawSimulatedAccountObservationV2Provider:
    """Expose an exact raw first winner only while it remains the PIT head."""

    __slots__ = ("_repository",)

    def __init__(self, repository: SimulatedAccountRawObservationRepository) -> None:
        self._repository = repository

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        row_pk: int,
        as_of: datetime,
    ) -> ExactRawSimulatedAccountObservationV2 | None:
        """Map an exact logical-final raw fact without rewriting any field."""

        try:
            winner = self._repository.get_winner(
                observation_id=observation_id,
                observation_version=observation_version,
                as_of=as_of,
            )
            if winner is None:
                return None
            head = self._repository.get_current_head(
                observation_id=observation_id,
                row_pk=row_pk,
                as_of=as_of,
            )
        except SimulatedAccountRawObservationUnavailable:
            return None
        except (
            SimulatedAccountRawObservationConflict,
            SimulatedAccountRawObservationCorruption,
        ) as error:
            raise SimulatedAccountRowSourceV2Corruption(
                "raw observation ledger failed closed-world verification"
            ) from error

        checked_winner = self._require_record(winner)
        if head is None:
            return None
        checked_head = self._require_record(head)
        if checked_head != checked_winner:
            return None
        observation = checked_winner.observation
        if (
            observation.observation_id != observation_id
            or observation.observation_version != observation_version
            or observation.content_hash != expected_content_hash
            or observation.row_pk != row_pk
        ):
            raise SimulatedAccountRowSourceV2Corruption(
                "raw observation ledger selector substitution"
            )
        if checked_winner.recorded_at > as_of or not observation.is_knowable_at(as_of):
            return None
        return ExactRawSimulatedAccountObservationV2(
            observation_id=observation.observation_id,
            observation_version=observation.observation_version,
            identity_hash=observation.identity_hash,
            content_hash=observation.content_hash,
            row_pk=observation.row_pk,
            row_user_id=observation.row_user_id,
            raw_account_type=observation.raw_account_type,
            is_active=observation.is_active,
            row_created_at=observation.row_created_at,
            row_updated_at=observation.row_updated_at,
            is_present=observation.is_present,
            is_tombstone=observation.is_tombstone,
            observed_at=observation.observed_at,
            valid_until=observation.valid_until,
            supersedes_content_hash=observation.supersedes_content_hash,
            owner=observation.owner,
            artifact_type=observation.artifact_type,
            schema=observation.schema,
        )

    @staticmethod
    def _require_record(value: object) -> PersistedSimulatedAccountRawObservation:
        if type(value) is not PersistedSimulatedAccountRawObservation:
            raise SimulatedAccountRowSourceV2Corruption(
                "raw observation ledger record type substitution"
            )
        try:
            PersistedSimulatedAccountRawObservation.__post_init__(value)
        except (TypeError, ValueError) as error:
            raise SimulatedAccountRowSourceV2Corruption(
                "raw observation ledger returned an invalid record"
            ) from error
        return value


__all__ = ["DjangoExactRawSimulatedAccountObservationV2Provider"]
