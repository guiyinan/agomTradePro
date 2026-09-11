"""Actual PostgreSQL reads append observations while preserving creation and replay."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from time import sleep

import pytest
from django.db import transaction

from apps.account.application.canonical_account_creation_binding_v2 import (
    GetExactCanonicalAccountCreationBindingV2Command,
)
from apps.account.application.physical_account_row_observation_v2 import (
    CapturePhysicalAccountRowObservationV2Command,
)
from apps.account.canonical_creation_composition import build_canonical_account_creation_stages
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.domain.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_codec import (
    decode_canonical_account_ownership_reobservation_v1,
)
from apps.account.infrastructure.physical_account_row_observation_v2_models import (
    PhysicalAccountRowObservationV2Model,
)
from apps.simulated_trading.account_reobservation_composition import (
    build_existing_account_reobserver,
)
from apps.simulated_trading.application.account_row_reobservation import (
    ReobserveExistingAccountRowCommand,
)
from apps.simulated_trading.application.current_account_ownership import (
    CurrentAccountOwnershipUnavailable,
)
from apps.simulated_trading.application.simulated_account_raw_observation import (
    SimulatedAccountRawObservationConflict,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    CaptureSimulatedAccountRowSourceV2Command,
)
from apps.simulated_trading.creation_composition import build_simulated_account_creation_stages
from apps.simulated_trading.domain.entities import AccountType
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_models import (
    SimulatedAccountRawObservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_repository import (
    DjangoSimulatedAccountRawObservationRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_models import (
    SimulatedAccountRowSourceV2Model,
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


def test_actual_reobservation_preserves_row_and_permanent_replay_then_rolls_back(
    creation_http_alias,
):
    alias = creation_http_alias
    client, user, csrf = _logged_in_client(alias)
    created = _post(client, csrf)
    assert created.status_code == 201, created.content
    row = SimulatedAccountModel.objects.using(alias).get(pk=created.json()["account"]["account_id"])
    original = (row.created_at, row.updated_at, row.user_id, row.initial_capital)
    repository = DjangoSimulatedAccountRawObservationRepository(using=alias)
    head = repository.get_physical_row_head(row_pk=row.pk, as_of=repository.now())
    assert head is not None
    before = head.observation
    command = ReobserveExistingAccountRowCommand(
        observation_id=before.observation_id,
        observation_version="reobserve-v2",
        row_pk=row.pk,
        expected_user_id=user.pk,
        expected_account_type=AccountType.SIMULATED,
        expected_created_at=row.created_at,
        minimum_updated_at=row.updated_at,
    )
    observer = build_existing_account_reobserver(using=alias, settings=_settings())
    with pytest.raises(CurrentAccountOwnershipUnavailable):
        observer.execute(command)
    with transaction.atomic(using=alias):
        observed = observer.execute(command)
    assert observed.observed_at > before.observed_at
    assert observed.row_created_at == before.row_created_at
    assert observed.row_updated_at == before.row_updated_at
    assert observed.supersedes_content_hash == before.content_hash
    row.refresh_from_db(using=alias)
    assert (row.created_at, row.updated_at, row.user_id, row.initial_capital) == original
    assert SimulatedAccountRawObservationModel.objects.using(alias).count() == 2
    replay = _post(client, csrf)
    assert replay.status_code == 200, replay.content
    assert replay.json()["replayed"] is True
    assert replay.json()["account"]["account_id"] == row.pk
    with pytest.raises(RuntimeError, match="rollback observation"):
        with transaction.atomic(using=alias):
            observer.execute(replace(command, observation_version="rollback-v3"))
            raise RuntimeError("rollback observation")
    assert SimulatedAccountRawObservationModel.objects.using(alias).count() == 2
    row.refresh_from_db(using=alias)
    assert (row.created_at, row.updated_at, row.user_id, row.initial_capital) == original


def test_legacy_row_without_raw_chain_cannot_be_given_a_creation_root(creation_http_alias):
    alias = creation_http_alias
    user, _ = _new_user(alias)
    row = SimulatedAccountModel.objects.using(alias).create(
        user=user,
        account_name="Legacy without creation evidence",
        account_type="real",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        total_value=Decimal("10000.00"),
        auto_trading_enabled=False,
    )
    command = ReobserveExistingAccountRowCommand(
        observation_id="legacy-without-chain",
        observation_version="reobserve-v1",
        row_pk=row.pk,
        expected_user_id=user.pk,
        expected_account_type=AccountType.REAL,
        expected_created_at=row.created_at,
        minimum_updated_at=row.updated_at,
    )
    observer = build_existing_account_reobserver(using=alias, settings=_settings())
    with pytest.raises(SimulatedAccountRawObservationConflict):
        with transaction.atomic(using=alias):
            observer.execute(command)
    assert SimulatedAccountRawObservationModel.objects.using(alias).count() == 0
    assert SimulatedAccountModel.objects.using(alias).count() == 1


@pytest.mark.parametrize("expire_creation", [False, True], ids=["current", "expired"])
def test_public_stages_persist_three_successors_and_roll_back_together(
    creation_http_alias, monkeypatch, expire_creation
):
    """Verify real stage compatibility before relying on the new Core orchestration."""
    alias = creation_http_alias
    if expire_creation:
        from core.integration import authenticated_canonical_account_creation as bridge

        monkeypatch.setattr(
            bridge,
            "get_active_account_creation_evidence_settings",
            lambda _: replace(_settings(), ttl_seconds=60),
        )
    client, user, csrf = _logged_in_client(alias)
    response = _post(client, csrf)
    assert response.status_code == 201, response.content
    binding_row = CanonicalAccountCreationBindingV2Model.objects.using(alias).get()
    stored_binding = binding_row.canonical_payload
    account_stages = build_canonical_account_creation_stages(
        using=alias,
        settings=_settings(),
        requester=CanonicalAccountCreationRequester(
            actor_id=f"django-user:{user.pk}", user_id=user.pk
        ),
    )
    binding = account_stages.get_exact_binding.execute(
        GetExactCanonicalAccountCreationBindingV2Command(
            binding_id=binding_row.binding_id,
            binding_version=binding_row.binding_version,
            expected_content_hash=binding_row.content_hash,
            as_of=datetime.now(UTC),
        )
    )
    assert binding is not None
    old = binding.creation_root.physical_observation
    if expire_creation:
        deadline = max(binding.creation_root.valid_until, old.valid_until)
        while datetime.now(UTC) < deadline:
            sleep(0.2)
        cutoff = datetime.now(UTC)
        assert binding.is_knowable_at(cutoff)
        assert not binding.creation_root.is_knowable_at(cutoff)
        assert not old.is_current_at(cutoff)
    row = SimulatedAccountModel.objects.using(alias).get(pk=old.underlying_unified_account_id)
    original = (row.created_at, row.updated_at, row.user_id, row.initial_capital)
    owner_stages = build_simulated_account_creation_stages(using=alias, settings=_settings())
    observer = build_existing_account_reobserver(using=alias, settings=_settings())

    def capture(version: str) -> CanonicalAccountOwnershipReobservationV1:
        raw = observer.execute(
            ReobserveExistingAccountRowCommand(
                observation_id=old.raw_observation_id,
                observation_version=version,
                row_pk=row.pk,
                expected_user_id=user.pk,
                expected_account_type=AccountType.SIMULATED,
                expected_created_at=old.row_created_at,
                minimum_updated_at=old.row_updated_at,
            )
        )
        source = owner_stages.source_capture.execute(
            CaptureSimulatedAccountRowSourceV2Command(
                source_id=raw.observation_id,
                source_version=version,
                expected_raw_observation_content_hash=raw.content_hash,
                account_namespace=old.account_namespace,
                account_id=old.account_id,
                underlying_unified_account_namespace=old.underlying_unified_account_namespace,
                underlying_unified_account_id=row.pk,
            )
        )
        physical = account_stages.physical_capture.execute(
            CapturePhysicalAccountRowObservationV2Command(
                observation_id=old.observation_id,
                observation_version=version,
                source_id=source.source_id,
                source_version=source.source_version,
                expected_source_content_hash=source.content_hash,
                account_namespace=old.account_namespace,
                account_id=old.account_id,
                underlying_unified_account_namespace=old.underlying_unified_account_namespace,
                underlying_unified_account_id=row.pk,
            )
        )
        return CanonicalAccountOwnershipReobservationV1(
            observation_id=old.observation_id,
            observation_version=version,
            binding=binding,
            current_physical=physical,
            recorded_at=datetime.now(UTC),
            valid_until=physical.valid_until,
        )

    with transaction.atomic(using=alias):
        proof = capture("physical-successor-v2")
    assert decode_canonical_account_ownership_reobservation_v1(proof.to_payload()) == proof
    assert proof.current_physical.raw_observation_content_hash != old.raw_observation_content_hash
    assert proof.current_physical.source_content_hash != old.source_content_hash
    assert proof.current_physical.content_hash != old.content_hash
    ledgers = (
        SimulatedAccountRawObservationModel,
        SimulatedAccountRowSourceV2Model,
        PhysicalAccountRowObservationV2Model,
    )
    assert [model.objects.using(alias).count() for model in ledgers] == [2, 2, 2]
    with pytest.raises(RuntimeError, match="rollback all stages"):
        with transaction.atomic(using=alias):
            capture("physical-successor-v3")
            raise RuntimeError("rollback all stages")
    assert [model.objects.using(alias).count() for model in ledgers] == [2, 2, 2]
    binding_row.refresh_from_db(using=alias)
    assert binding_row.canonical_payload == stored_binding
    row.refresh_from_db(using=alias)
    assert (row.created_at, row.updated_at, row.user_id, row.initial_capital) == original
    replay = _post(client, csrf)
    assert replay.status_code == 200, replay.content
    assert replay.json()["replayed"] is True
