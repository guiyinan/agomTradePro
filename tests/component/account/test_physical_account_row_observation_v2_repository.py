from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.core.exceptions import ValidationError

from apps.account.application.physical_account_row_observation import (
    PhysicalAccountRowObservationActor,
)
from apps.account.application.physical_account_row_observation_v2 import (
    PersistedPhysicalAccountRowObservationV2,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)
from apps.account.infrastructure.physical_account_row_observation_v2_models import (
    PhysicalAccountRowObservationV2Model,
)
from apps.account.infrastructure.physical_account_row_observation_v2_repository import (
    DjangoPhysicalAccountRowObservationV2Repository,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return _at(8)


def _record() -> PersistedPhysicalAccountRowObservationV2:
    raw = SimulatedAccountRawObservation(
        observation_id="row-7",
        observation_version="event-v1",
        row_pk=7,
        row_user_id=42,
        raw_account_type="REAL",
        is_active=True,
        row_created_at=_at(1),
        row_updated_at=_at(2),
        is_present=True,
        is_tombstone=False,
        observed_at=_at(3),
        valid_until=_at(20),
    )
    source = SimulatedAccountRowSourceV2(
        source_id=raw.observation_id,
        source_version=raw.observation_version,
        account_namespace="account",
        account_id="0007",
        underlying_unified_account_namespace="simulated-account-row",
        underlying_unified_account_id=raw.row_pk,
        row_user_id=raw.row_user_id,
        raw_account_type=raw.raw_account_type,
        is_active=raw.is_active,
        row_created_at=raw.row_created_at,
        row_updated_at=raw.row_updated_at,
        is_present=raw.is_present,
        is_tombstone=raw.is_tombstone,
        observed_at=raw.observed_at,
        recorded_at=_at(4),
        source_valid_until=raw.valid_until,
        ttl_valid_until=_at(15),
        valid_until=_at(15),
        raw_observation_id=raw.observation_id,
        raw_observation_version=raw.observation_version,
        raw_observation_identity_hash=raw.identity_hash,
        raw_observation_content_hash=raw.content_hash,
        raw_observation_observed_at=raw.observed_at,
        raw_observation_valid_until=raw.valid_until,
    )
    observation = PhysicalAccountRowObservationV2(
        observation_id="account-row-7",
        observation_version="capture-v1",
        account_namespace=source.account_namespace,
        account_id=source.account_id,
        underlying_unified_account_namespace=source.underlying_unified_account_namespace,
        underlying_unified_account_id=source.underlying_unified_account_id,
        row_user_id=source.row_user_id,
        raw_account_type=source.raw_account_type,
        is_active=source.is_active,
        row_created_at=source.row_created_at,
        row_updated_at=source.row_updated_at,
        is_present=source.is_present,
        is_tombstone=source.is_tombstone,
        source_id=source.source_id,
        source_version=source.source_version,
        source_identity_hash=source.identity_hash,
        source_content_hash=source.content_hash,
        source_supersedes_content_hash=source.supersedes_content_hash,
        source_observed_at=source.observed_at,
        source_recorded_at=source.recorded_at,
        source_valid_until=source.source_valid_until,
        source_ttl_valid_until=source.ttl_valid_until,
        source_effective_valid_until=source.valid_until,
        raw_observation_id=source.raw_observation_id,
        raw_observation_version=source.raw_observation_version,
        raw_observation_identity_hash=source.raw_observation_identity_hash,
        raw_observation_content_hash=source.raw_observation_content_hash,
        raw_observation_supersedes_content_hash=source.raw_observation_supersedes_content_hash,
        raw_observation_observed_at=source.raw_observation_observed_at,
        raw_observation_valid_until=source.raw_observation_valid_until,
        recorded_at=_at(5),
        ttl_valid_until=_at(12),
        valid_until=_at(12),
    )
    return PersistedPhysicalAccountRowObservationV2(
        observation=observation,
        captured_by=PhysicalAccountRowObservationActor(
            actor_id="account-recorder", user_id=9, role="operator"
        ),
    )


@pytest.mark.django_db(transaction=True)
def test_append_exact_pit_and_current_head_roundtrip() -> None:
    repository = DjangoPhysicalAccountRowObservationV2Repository(clock=_Clock())
    record = _record()
    with repository.atomic():
        assert (
            repository.append(
                record,
                expected_predecessor_hash=None,
                recorded_at=record.observation.recorded_at,
            )
            == record
        )
    assert (
        repository.get_winner(
            observation_id=record.observation.observation_id,
            observation_version=record.observation.observation_version,
            as_of=_at(8),
        )
        == record
    )
    assert (
        repository.get_exact_by_hash(
            observation_id=record.observation.observation_id,
            observation_version=record.observation.observation_version,
            expected_content_hash=record.observation.content_hash,
            as_of=_at(8),
        )
        == record
    )
    assert (
        repository.get_current_head(
            account_namespace=record.observation.account_namespace,
            account_id=record.observation.account_id,
            underlying_unified_account_namespace=record.observation.underlying_unified_account_namespace,
            underlying_unified_account_id=record.observation.underlying_unified_account_id,
            source_id=record.observation.source_id,
            as_of=_at(8),
        )
        == record
    )


@pytest.mark.django_db(transaction=True)
def test_schema_is_zero_seed_and_direct_save_is_blocked() -> None:
    assert PhysicalAccountRowObservationV2Model.objects.count() == 0
    with pytest.raises(ValidationError):
        PhysicalAccountRowObservationV2Model().save()
