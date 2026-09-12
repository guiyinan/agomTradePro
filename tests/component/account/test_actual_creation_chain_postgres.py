"""Actual row-to-Binding creation evidence without synthetic ledger parents."""

from uuid import uuid4

from django.db import connections, transaction

from apps.account.application.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3Recorder,
    CaptureAllocatedPhysicalAccountRowObservationV3,
    CaptureAllocatedPhysicalAccountRowObservationV3Command,
    GetExactAllocatedPhysicalAccountRowObservationV3,
    GetExactAllocatedPhysicalAccountRowObservationV3Command,
)
from apps.account.application.canonical_account_creation import (
    AllocateCanonicalAccountCreation,
    AllocateCanonicalAccountCreationCommand,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    BindCanonicalAccountCreationV2,
    BindCanonicalAccountCreationV2Command,
)
from apps.account.application.physical_account_row_observation_v2 import (
    CapturePhysicalAccountRowObservationV2,
    GetExactPhysicalAccountRowObservationV2,
    GetExactPhysicalAccountRowObservationV2Command,
    PhysicalAccountRowObservationV2Recorder,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationRequester,
    CanonicalAccountCreationServiceRecorder,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_repository import (
    DjangoAllocatedPhysicalAccountRowObservationV3Repository,
)
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)
from apps.account.infrastructure.canonical_account_creation_repository import (
    DjangoCanonicalAccountCreationRepository,
)
from apps.account.infrastructure.physical_account_row_observation_v2_repository import (
    DjangoPhysicalAccountRowObservationV2Repository,
)
from apps.simulated_trading.account_physical_row_v2_composition import (
    build_account_physical_row_v2_provider,
)
from apps.simulated_trading.creation_composition import build_simulated_account_creation_stages
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from apps.simulated_trading.infrastructure.simulated_account_evidence_pipeline import (
    SimulatedAccountEvidencePipeline,
    SimulatedAccountEvidencePipelineAliases,
    UnverifiedCanonicalAccountReference,
)
from tests.component.account.creation_chain_postgres_fixture import CREATION_LEDGER_MODELS
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _new_user,
)
from tests.component.account.test_canonical_account_creation_row_postgres import _command
from tests.unit.simulated_trading.test_creation_composition import _settings

pytest_plugins = (
    "tests.component.account.test_current_account_ownership_postgres",
    "tests.component.account.creation_chain_postgres_fixture",
)


class _Generator:
    def generate(self):
        return uuid4().hex


class _AllocationProvider:
    def __init__(self, repository):
        self.repository = repository

    def get_exact_current_unconsumed(self, **selector):
        return self.repository.get_current_unconsumed_allocation(**selector)


class _PhysicalProvider:
    def __init__(self, repository):
        self.reader = GetExactPhysicalAccountRowObservationV2(repository)

    def get_exact_final(self, **selector):
        return self.reader.execute(GetExactPhysicalAccountRowObservationV2Command(**selector))


class _RootProvider:
    def __init__(self, repository):
        self.reader = GetExactAllocatedPhysicalAccountRowObservationV3(repository)

    def get_exact_final(self, **selector):
        return self.reader.execute(
            GetExactAllocatedPhysicalAccountRowObservationV3Command(**selector)
        )


def _create(alias, user):
    settings = _settings()
    duration = settings.as_timedelta()
    allocations = DjangoCanonicalAccountCreationRepository(using=alias)
    physical = DjangoPhysicalAccountRowObservationV2Repository(using=alias)
    roots = DjangoAllocatedPhysicalAccountRowObservationV3Repository(using=alias)
    bindings = DjangoCanonicalAccountCreationConsumptionRepository(using=alias)
    allocation = AllocateCanonicalAccountCreation(
        repository=allocations,
        requester=CanonicalAccountCreationRequester(actor_id=f"user-{user.pk}", user_id=user.pk),
        account_id_generator=_Generator(),
        allocator=CanonicalAccountCreationServiceRecorder(
            service_id=settings.allocation_recorder_service_id,
            role="canonical_account_identity_allocator",
        ),
        validity_period=duration,
    ).execute(
        AllocateCanonicalAccountCreationCommand(
            allocation_id="actual-chain-allocation",
            allocation_version="v1",
            request_fingerprint_hash="a" * 64,
            requested_raw_account_type="simulated",
        )
    )
    stages = build_simulated_account_creation_stages(using=alias, settings=settings)
    row = stages.row_writer.execute(_command(user.pk))
    pipeline = SimulatedAccountEvidencePipeline(
        aliases=SimulatedAccountEvidencePipelineAliases(alias, alias, alias, alias),
        raw_writer=stages.raw_writer,
        source_capture=stages.source_capture,
        account_capture=CapturePhysicalAccountRowObservationV2(
            row_provider=build_account_physical_row_v2_provider(using=alias),
            repository=physical,
            recorder=PhysicalAccountRowObservationV2Recorder(
                recorder_id=settings.physical_v2_recorder_service_id,
                service_name=settings.physical_v2_recorder_service_id,
            ),
            validity_period=duration,
        ),
    )
    observations = pipeline.record_create(
        row.mutation,
        UnverifiedCanonicalAccountReference(
            account_namespace=allocation.canonical_account_namespace,
            account_id=allocation.canonical_account_id,
            underlying_unified_account_namespace=(
                allocation.intended_underlying_unified_account_namespace
            ),
            underlying_unified_account_id=row.account.account_id,
        ),
    )
    observation = observations.account_v2
    root = CaptureAllocatedPhysicalAccountRowObservationV3(
        allocation_provider=_AllocationProvider(allocations),
        physical_provider=_PhysicalProvider(physical),
        repository=roots,
        recorder=AllocatedPhysicalAccountRowObservationV3Recorder(
            service_id=settings.allocated_v3_recorder_service_id
        ),
        validity_period=duration,
    ).execute(
        CaptureAllocatedPhysicalAccountRowObservationV3Command(
            observation_id="actual-chain-root",
            observation_version="v1",
            allocation_id=allocation.allocation_id,
            allocation_version=allocation.allocation_version,
            expected_allocation_content_hash=allocation.content_hash,
            physical_observation_id=observation.observation_id,
            physical_observation_version=observation.observation_version,
            expected_physical_content_hash=observation.content_hash,
        )
    )
    binding = BindCanonicalAccountCreationV2(
        allocation_provider=allocations,
        creation_root_provider=_RootProvider(roots),
        repository=bindings,
        binder=CanonicalAccountCreationServiceRecorder(
            service_id=settings.binding_recorder_service_id,
            role="canonical_account_creation_binder",
        ),
    ).execute(
        BindCanonicalAccountCreationV2Command(
            binding_id="actual-chain-binding",
            binding_version="v1",
            allocation_id=allocation.allocation_id,
            allocation_version=allocation.allocation_version,
            expected_allocation_content_hash=allocation.content_hash,
            creation_root_observation_id=root.observation_id,
            creation_root_observation_version=root.observation_version,
            expected_creation_root_content_hash=root.content_hash,
        )
    )
    return row, observations, binding


def test_actual_creation_stages_share_outer_rollback_and_commit(creation_chain_alias):
    alias = creation_chain_alias
    user, _ = _new_user(alias)

    def reject_default(execute, sql, params, many, context):
        raise AssertionError("actual creation chain queried default database")

    with connections["default"].execute_wrapper(reject_default):
        with transaction.atomic(using=alias):
            row, observations, binding = _create(alias, user)
            assert binding.allocation.requested_row_user_id == user.pk
            assert binding.creation_root.physical_observation == observations.account_v2
            assert observations.raw.row_pk == row.account.account_id
            assert observations.raw.row_user_id == user.pk
            assert binding.must_not_execute
            transaction.set_rollback(True, using=alias)
        assert SimulatedAccountModel.objects.using(alias).count() == 0
        assert all(
            model._base_manager.using(alias).count() == 0 for model in CREATION_LEDGER_MODELS
        )
        with transaction.atomic(using=alias):
            row, _, binding = _create(alias, user)
        assert (
            SimulatedAccountModel.objects.using(alias).get(pk=row.account.account_id).user_id
            == user.pk
        )
        assert [model._base_manager.using(alias).count() for model in CREATION_LEDGER_MODELS] == [
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            1,
        ]
