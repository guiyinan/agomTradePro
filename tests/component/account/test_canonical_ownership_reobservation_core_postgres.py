"""Actual Core transactions preserve creation identity while observing current facts."""

from collections.abc import Iterator
from dataclasses import replace

import pytest
from django.db import connections, transaction
from django.utils import timezone

from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    PersistedCanonicalAccountOwnershipReobservationV1,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_models import (
    CanonicalAccountOwnershipReobservationV1Model,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_repository import (
    DjangoCanonicalAccountOwnershipReobservationV1Repository,
)
from apps.account.infrastructure.physical_account_row_observation_v2_models import (
    PhysicalAccountRowObservationV2Model,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_models import (
    SimulatedAccountRawObservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_models import (
    SimulatedAccountRowSourceV2Model,
)
from core.integration.canonical_account_ownership_reobservation import (
    CanonicalAccountOwnershipReobservationCommand,
    CanonicalAccountOwnershipReobservationConflict,
    reobserve_canonical_account_ownership,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_http import (
    _logged_in_client,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _new_user,
)
from tests.component.account.test_authenticated_creation_http_postgres import (
    _post,
)
from tests.component.account.test_authenticated_creation_http_postgres import (
    creation_http_alias as creation_http_alias,
)
from tests.unit.simulated_trading.test_creation_composition import _settings

pytest_plugins = (
    "tests.component.account.test_current_account_ownership_postgres",
    "tests.component.account.creation_chain_postgres_fixture",
)


@pytest.fixture
def reobservation_alias(creation_http_alias: str) -> Iterator[str]:
    """Add the durable re-observation ledger after all parent ledgers."""

    connection = connections[creation_http_alias]
    with connection.schema_editor() as editor:
        editor.create_model(CanonicalAccountOwnershipReobservationV1Model)
    try:
        yield creation_http_alias
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(CanonicalAccountOwnershipReobservationV1Model)


def test_core_reobserves_exact_binding_rejects_other_user_and_rolls_back(
    reobservation_alias: str,
) -> None:
    alias = reobservation_alias
    client, user, csrf = _logged_in_client(alias)
    created = _post(client, csrf)
    assert created.status_code == 201, created.content
    binding_row = CanonicalAccountCreationBindingV2Model.objects.using(alias).get()
    original_payload = binding_row.canonical_payload
    physical = PhysicalAccountRowObservationV2Model.objects.using(alias).get()
    row = SimulatedAccountModel.objects.using(alias).get(pk=created.json()["account"]["account_id"])
    original_row = (row.created_at, row.updated_at, row.user_id, row.initial_capital)
    command = CanonicalAccountOwnershipReobservationCommand(
        binding_id=binding_row.binding_id,
        binding_version=binding_row.binding_version,
        expected_binding_content_hash=binding_row.content_hash,
        observation_id=physical.observation_id,
        observation_version="core-reobserve-v2",
    )
    # This is a Core port test; real HTTP authentication was exercised above,
    # while the Core itself explicitly accepts a trusted server-side requester.
    requester = CanonicalAccountCreationRequester(
        actor_id=f"django-user:{user.pk}", user_id=user.pk
    )
    result = reobserve_canonical_account_ownership(
        command=command,
        requester=requester,
        using=alias,
        settings=_settings(),
    )
    assert result.binding.content_hash == binding_row.content_hash
    assert result.current_physical.content_hash != physical.content_hash
    assert result.recorded_at >= result.current_physical.recorded_at
    assert result.activation_available is False
    durable_repository = DjangoCanonicalAccountOwnershipReobservationV1Repository(using=alias)
    durable_record = PersistedCanonicalAccountOwnershipReobservationV1(result)
    with durable_repository.atomic():
        assert (
            durable_repository.append(
                durable_record,
                recorded_at=result.recorded_at,
            )
            == durable_record
        )
    successor = reobserve_canonical_account_ownership(
        command=replace(command, observation_version="core-reobserve-v3"),
        requester=requester,
        using=alias,
        settings=_settings(),
    )
    assert successor.binding == result.binding
    assert successor.current_physical.content_hash != result.current_physical.content_hash
    assert (
        durable_repository.get_exact_by_hash(
            observation_id=result.observation_id,
            observation_version=result.observation_version,
            expected_content_hash=result.content_hash,
            as_of=timezone.now(),
        )
        == durable_record
    )
    ledgers = (
        SimulatedAccountRawObservationModel,
        SimulatedAccountRowSourceV2Model,
        PhysicalAccountRowObservationV2Model,
        CanonicalAccountOwnershipReobservationV1Model,
    )
    assert [model.objects.using(alias).count() for model in ledgers] == [3, 3, 3, 2]
    other_user, _ = _new_user(alias, username="evid07-other-owner")
    with pytest.raises(CanonicalAccountOwnershipReobservationConflict):
        reobserve_canonical_account_ownership(
            command=replace(command, observation_version="wrong-user-v3"),
            requester=CanonicalAccountCreationRequester(
                actor_id=f"django-user:{other_user.pk}",
                user_id=other_user.pk,
            ),
            using=alias,
            settings=_settings(),
        )
    assert [model.objects.using(alias).count() for model in ledgers] == [3, 3, 3, 2]
    with pytest.raises(RuntimeError, match="rollback Core"):
        with transaction.atomic(using=alias):
            reobserve_canonical_account_ownership(
                command=replace(command, observation_version="rollback-core-v3"),
                requester=requester,
                using=alias,
                settings=_settings(),
            )
            raise RuntimeError("rollback Core")
    assert [model.objects.using(alias).count() for model in ledgers] == [3, 3, 3, 2]
    binding_row.refresh_from_db(using=alias)
    assert binding_row.canonical_payload == original_payload
    row.refresh_from_db(using=alias)
    assert (row.created_at, row.updated_at, row.user_id, row.initial_capital) == original_row
    replay = _post(client, csrf)
    assert replay.status_code == 200, replay.content
    assert replay.json()["replayed"] is True
