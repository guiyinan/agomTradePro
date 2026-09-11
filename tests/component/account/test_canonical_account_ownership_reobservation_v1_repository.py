"""Component coverage for the closed ownership re-observation v1 ledger."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    PersistedCanonicalAccountOwnershipReobservationV1,
)
from apps.account.application.physical_account_row_observation_v2 import (
    PersistedPhysicalAccountRowObservationV2,
    PhysicalAccountRowObservationV2Recorder,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_creation_consumption import (
    CanonicalAccountCreationConsumptionClaim,
)
from apps.account.domain.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_models import (
    CanonicalAccountOwnershipReobservationV1Model,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_repository import (
    DjangoCanonicalAccountOwnershipReobservationV1Conflict,
    DjangoCanonicalAccountOwnershipReobservationV1Corruption,
    DjangoCanonicalAccountOwnershipReobservationV1Repository,
)
from apps.account.infrastructure.physical_account_row_observation_v2_repository import (
    DjangoPhysicalAccountRowObservationV2Repository,
)
from tests.component.account.test_canonical_account_creation_consumption_repository import (
    _append_pair,
    _seed_v2_foreign_evidence,
)
from tests.unit.account.test_canonical_account_creation_consumption import _claim
from tests.unit.account.test_canonical_account_ownership_reobservation_v1 import (
    _current_physical,
    _reobservation,
)


def _at(day: int) -> datetime:
    """Return one fixed timezone-aware test instant."""

    return datetime(2026, 8, day, 12, tzinfo=UTC)


class _Clock:
    """Use a deterministic persistence clock after all source observations."""

    def now(self) -> datetime:
        """Return the fixed test cutoff."""

        return _at(30)


def _seed_parents(value: CanonicalAccountOwnershipReobservationV1) -> None:
    """Persist the exact Binding-v2 and Physical-v2 evidence named by a proof."""

    binding, claim = _pair_for(value)
    _seed_v2_foreign_evidence(binding)
    from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
        DjangoCanonicalAccountCreationConsumptionRepository,
    )

    binding_repository = DjangoCanonicalAccountCreationConsumptionRepository(clock=_Clock())
    with binding_repository.atomic():
        _append_pair(binding_repository, binding, claim)

    physical_repository = DjangoPhysicalAccountRowObservationV2Repository(clock=_Clock())
    physical_record = PersistedPhysicalAccountRowObservationV2(
        observation=value.current_physical,
        recorded_by=PhysicalAccountRowObservationV2Recorder(
            recorder_id="ownership-reobservation-component",
            service_name="account",
        ),
    )
    with physical_repository.atomic():
        physical_repository.append(
            physical_record,
            expected_predecessor_hash=None,
            recorded_at=value.current_physical.recorded_at,
        )


def _pair_for(
    value: CanonicalAccountOwnershipReobservationV1,
) -> tuple[CanonicalAccountCreationBindingV2, CanonicalAccountCreationConsumptionClaim]:
    """Build a Binding-v2/claim pair with the proof's exact Binding value."""

    binding = value.binding
    return binding, _claim(consumer_generation="v2", consumer=binding)


@pytest.mark.django_db(transaction=True)
def test_append_replay_and_historical_exact_restore_full_parent_evidence() -> None:
    """Append once, replay once, and retain the expired proof for history."""

    value = _reobservation()
    _seed_parents(value)
    repository = DjangoCanonicalAccountOwnershipReobservationV1Repository(clock=_Clock())
    expected = PersistedCanonicalAccountOwnershipReobservationV1(value)

    with repository.atomic():
        assert repository.append(expected, recorded_at=value.recorded_at) == expected
        assert repository.append(expected, recorded_at=value.recorded_at) == expected

    row = CanonicalAccountOwnershipReobservationV1Model.objects.get()
    assert row.binding_id > 0
    assert row.current_physical_id > 0
    assert row.canonical_payload["reobservation"]["current_physical"] == (
        value.current_physical.to_payload()
    )
    assert row.record_seal == expected.record_seal
    assert row.ledger_seal == expected.ledger_seal
    assert (
        repository.get_winner(
            observation_id=value.observation_id,
            observation_version=value.observation_version,
            as_of=_at(30),
        )
        == expected
    )
    assert (
        repository.get_exact_by_hash(
            observation_id=value.observation_id,
            observation_version=value.observation_version,
            expected_content_hash=value.content_hash,
            as_of=_at(30),
        )
        == expected
    )


@pytest.mark.django_db(transaction=True)
def test_append_requires_private_uow_and_direct_model_write_is_blocked() -> None:
    """Keep the ledger append-only and require the repository transaction."""

    value = _reobservation()
    repository = DjangoCanonicalAccountOwnershipReobservationV1Repository(clock=_Clock())
    with pytest.raises(DjangoCanonicalAccountOwnershipReobservationV1Conflict, match="private UOW"):
        repository.append(
            PersistedCanonicalAccountOwnershipReobservationV1(value),
            recorded_at=value.recorded_at,
        )
    with pytest.raises(ValidationError):
        CanonicalAccountOwnershipReobservationV1Model.objects.create()


@pytest.mark.django_db(transaction=True)
def test_closed_world_model_tamper_fails_before_unrelated_selector() -> None:
    """Restore all rows and reject payload/header corruption before filtering."""

    value = _reobservation()
    _seed_parents(value)
    repository = DjangoCanonicalAccountOwnershipReobservationV1Repository(clock=_Clock())
    with repository.atomic():
        repository.append(
            PersistedCanonicalAccountOwnershipReobservationV1(value),
            recorded_at=value.recorded_at,
        )
    table = connection.ops.quote_name(CanonicalAccountOwnershipReobservationV1Model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table} SET observation_id = %s", ["tampered"])  # noqa: S608

    with pytest.raises(DjangoCanonicalAccountOwnershipReobservationV1Corruption):
        repository.get_winner(
            observation_id="unrelated",
            observation_version="v9",
            as_of=_at(30),
        )


def test_helper_keeps_the_domain_value_exact() -> None:
    """Ensure the component fixture does not accidentally alter V1 semantics."""

    value = _reobservation(current_physical=_current_physical())
    assert type(value) is CanonicalAccountOwnershipReobservationV1
