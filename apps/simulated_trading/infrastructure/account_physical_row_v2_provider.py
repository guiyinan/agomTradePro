"""Read-only owner adapter exposing raw-bound source-v2 rows to Account."""

from __future__ import annotations

from datetime import datetime

from apps.account.application.physical_account_row_observation_v2 import (
    ExactPhysicalSimulatedAccountRowV2,
    PhysicalAccountRowObservationV2Corruption,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    PersistedSimulatedAccountRowSourceV2,
    SimulatedAccountRowSourceV2Conflict,
    SimulatedAccountRowSourceV2Corruption,
    SimulatedAccountRowSourceV2Repository,
    SimulatedAccountRowSourceV2Unavailable,
)


class DjangoExactPhysicalSimulatedAccountRowV2Provider:
    """Expose one exact logical-final source-v2 revision without rewriting it."""

    __slots__ = ("_repository",)

    def __init__(self, repository: SimulatedAccountRowSourceV2Repository) -> None:
        self._repository = repository

    def get_exact_final(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> ExactPhysicalSimulatedAccountRowV2 | None:
        """Return an exact recorded and unexpired final, including tombstones."""

        record = self._read_final(
            source_id=source_id,
            source_version=source_version,
            expected_content_hash=expected_content_hash,
            account_namespace=account_namespace,
            account_id=account_id,
            underlying_unified_account_namespace=underlying_unified_account_namespace,
            underlying_unified_account_id=underlying_unified_account_id,
            as_of=as_of,
        )
        if record is None or not record.source.is_knowable_at(as_of):
            return None
        return self._map(record)

    def get_exact_current(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> ExactPhysicalSimulatedAccountRowV2 | None:
        """Return an exact final only while it is also a live source revision."""

        record = self._read_final(
            source_id=source_id,
            source_version=source_version,
            expected_content_hash=expected_content_hash,
            account_namespace=account_namespace,
            account_id=account_id,
            underlying_unified_account_namespace=underlying_unified_account_namespace,
            underlying_unified_account_id=underlying_unified_account_id,
            as_of=as_of,
        )
        if record is None or not record.source.is_current_at(as_of):
            return None
        return self._map(record)

    def _read_final(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSourceV2 | None:
        try:
            winner = self._repository.get_winner(
                source_id=source_id,
                source_version=source_version,
                as_of=as_of,
            )
            if winner is None:
                return None
            head = self._repository.get_current_head(
                source_id=source_id,
                account_namespace=account_namespace,
                account_id=account_id,
                underlying_unified_account_namespace=underlying_unified_account_namespace,
                underlying_unified_account_id=underlying_unified_account_id,
                as_of=as_of,
            )
        except SimulatedAccountRowSourceV2Unavailable:
            return None
        except (
            SimulatedAccountRowSourceV2Conflict,
            SimulatedAccountRowSourceV2Corruption,
        ) as error:
            raise PhysicalAccountRowObservationV2Corruption(
                "source-v2 ledger failed closed-world verification"
            ) from error

        checked_winner = self._require_record(winner)
        if head is None:
            return None
        checked_head = self._require_record(head)
        if checked_head != checked_winner:
            return None
        source = checked_winner.source
        selectors = (
            source.source_id,
            source.source_version,
            source.content_hash,
            source.account_namespace,
            source.account_id,
            source.underlying_unified_account_namespace,
            source.underlying_unified_account_id,
        )
        expected = (
            source_id,
            source_version,
            expected_content_hash,
            account_namespace,
            account_id,
            underlying_unified_account_namespace,
            underlying_unified_account_id,
        )
        if selectors != expected:
            raise PhysicalAccountRowObservationV2Corruption(
                "source-v2 ledger selector substitution"
            )
        return checked_winner

    @staticmethod
    def _require_record(value: object) -> PersistedSimulatedAccountRowSourceV2:
        if type(value) is not PersistedSimulatedAccountRowSourceV2:
            raise PhysicalAccountRowObservationV2Corruption(
                "source-v2 ledger record type substitution"
            )
        try:
            PersistedSimulatedAccountRowSourceV2.__post_init__(value)
        except (TypeError, ValueError) as error:
            raise PhysicalAccountRowObservationV2Corruption(
                "source-v2 ledger returned an invalid record"
            ) from error
        return value

    @staticmethod
    def _map(
        record: PersistedSimulatedAccountRowSourceV2,
    ) -> ExactPhysicalSimulatedAccountRowV2:
        source = record.source
        try:
            return ExactPhysicalSimulatedAccountRowV2(
                source_id=source.source_id,
                source_version=source.source_version,
                identity_hash=source.identity_hash,
                content_hash=source.content_hash,
                source_supersedes_content_hash=source.supersedes_content_hash,
                account_namespace=source.account_namespace,
                account_id=source.account_id,
                underlying_unified_account_namespace=(source.underlying_unified_account_namespace),
                underlying_unified_account_id=source.underlying_unified_account_id,
                row_user_id=source.row_user_id,
                raw_account_type=source.raw_account_type,
                is_active=source.is_active,
                row_created_at=source.row_created_at,
                row_updated_at=source.row_updated_at,
                is_present=source.is_present,
                is_tombstone=source.is_tombstone,
                observed_at=source.observed_at,
                recorded_at=source.recorded_at,
                source_valid_until=source.source_valid_until,
                ttl_valid_until=source.ttl_valid_until,
                valid_until=source.valid_until,
                raw_observation_id=source.raw_observation_id,
                raw_observation_version=source.raw_observation_version,
                raw_observation_identity_hash=source.raw_observation_identity_hash,
                raw_observation_content_hash=source.raw_observation_content_hash,
                raw_observation_supersedes_content_hash=(
                    source.raw_observation_supersedes_content_hash
                ),
                raw_observation_observed_at=source.raw_observation_observed_at,
                raw_observation_valid_until=source.raw_observation_valid_until,
                owner_assignment_state=source.owner_assignment_state,
                owner=source.owner,
                artifact_type=source.artifact_type,
                schema=source.schema,
                raw_observation_owner=source.raw_observation_owner,
                raw_observation_artifact_type=source.raw_observation_artifact_type,
                raw_observation_schema=source.raw_observation_schema,
            )
        except (TypeError, ValueError) as error:
            raise PhysicalAccountRowObservationV2Corruption(
                "source-v2 fields cannot be mapped without rewriting"
            ) from error


__all__ = ["DjangoExactPhysicalSimulatedAccountRowV2Provider"]
