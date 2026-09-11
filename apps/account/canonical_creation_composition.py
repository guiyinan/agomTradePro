"""Public same-database composition for canonical Account creation evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, Protocol, TypeVar
from uuid import uuid4

from django.db import connections
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3Recorder,
    AllocatedPhysicalAccountRowObservationV3Repository,
    CaptureAllocatedPhysicalAccountRowObservationV3,
    CaptureAllocatedPhysicalAccountRowObservationV3Command,
    GetExactAllocatedPhysicalAccountRowObservationV3,
    GetExactAllocatedPhysicalAccountRowObservationV3Command,
)
from apps.account.application.canonical_account_creation import (
    AllocateCanonicalAccountCreation,
    AllocateCanonicalAccountCreationCommand,
    CanonicalAccountCreationRepository,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    BindCanonicalAccountCreationV2,
    BindCanonicalAccountCreationV2Command,
    GetExactCanonicalAccountCreationBindingV2,
    GetExactCanonicalAccountCreationBindingV2Command,
)
from apps.account.application.canonical_account_creation_replay import (
    FindCompletedCanonicalAccountCreation,
)
from apps.account.application.creation_evidence_settings import (
    CanonicalAccountCreationEvidenceSettings,
)
from apps.account.application.physical_account_row_observation_v2 import (
    CapturePhysicalAccountRowObservationV2,
    CapturePhysicalAccountRowObservationV2Command,
    ExactPhysicalSimulatedAccountRowV2Provider,
    GetExactPhysicalAccountRowObservationV2,
    GetExactPhysicalAccountRowObservationV2Command,
    PhysicalAccountRowObservationV2,
    PhysicalAccountRowObservationV2Recorder,
    PhysicalAccountRowObservationV2Repository,
)
from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
    CanonicalAccountCreationRequester,
    CanonicalAccountCreationServiceRecorder,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
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

_CommandT = TypeVar("_CommandT", contravariant=True)
_ResultT = TypeVar("_ResultT", covariant=True)


class CanonicalCreationOperation(Protocol[_CommandT, _ResultT]):
    """Execute one already-composed creation operation."""

    def execute(self, command: _CommandT) -> _ResultT:
        """Execute the operation using its configured same-database ports."""


@dataclass(frozen=True, slots=True)
class _TransactionBoundOperation(Generic[_CommandT, _ResultT]):
    """Guard a write so the caller owns the outer transaction."""

    _using: str
    _operation: CanonicalCreationOperation[_CommandT, _ResultT]
    _requires_outer_transaction: bool = True

    def execute(self, command: _CommandT) -> _ResultT:
        """Run the operation after checking the caller's transaction alias."""

        if self._requires_outer_transaction:
            _require_caller_transaction(self._using)
        return self._operation.execute(command)


class _UuidCanonicalAccountIdGenerator:
    """Generate opaque Account identities for the allocation application."""

    def generate(self) -> str:
        """Return one server-generated UUID hex identity."""

        return uuid4().hex


class _PhysicalV2FinalProvider:
    """Adapt the Physical-v2 repository reader to the root application port."""

    def __init__(self, repository: PhysicalAccountRowObservationV2Repository) -> None:
        self._reader = GetExactPhysicalAccountRowObservationV2(repository)

    def get_exact_final(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PhysicalAccountRowObservationV2 | None:
        """Read one exact Physical-v2 capture at the supplied PIT."""

        return self._reader.execute(
            GetExactPhysicalAccountRowObservationV2Command(
                observation_id=observation_id,
                observation_version=observation_version,
                expected_content_hash=expected_content_hash,
                as_of=as_of,
            )
        )


class _CurrentAllocationProvider:
    """Adapt the allocation repository to the root capture port."""

    def __init__(self, repository: CanonicalAccountCreationRepository) -> None:
        self._repository = repository

    def get_exact_current_unconsumed(
        self,
        *,
        allocation_id: str,
        allocation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationAllocation | None:
        """Read one exact live allocation that has not been consumed."""

        return self._repository.get_current_unconsumed_allocation(
            allocation_id=allocation_id,
            allocation_version=allocation_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )


class _RootFinalProvider:
    """Adapt the allocated Physical-v3 reader to the Binding-v2 port."""

    def __init__(self, repository: AllocatedPhysicalAccountRowObservationV3Repository) -> None:
        self._reader = GetExactAllocatedPhysicalAccountRowObservationV3(repository)

    def get_exact_final(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AllocatedPhysicalAccountRowObservationV3 | None:
        """Read one exact allocated Physical-v3 root at the supplied PIT."""

        return self._reader.execute(
            GetExactAllocatedPhysicalAccountRowObservationV3Command(
                observation_id=observation_id,
                observation_version=observation_version,
                expected_content_hash=expected_content_hash,
                as_of=as_of,
            )
        )


@dataclass(frozen=True, slots=True)
class CanonicalAccountCreationStages:
    """Same-alias canonical creation operations and permanent winner readers."""

    database_alias: str
    allocate: CanonicalCreationOperation[
        AllocateCanonicalAccountCreationCommand, CanonicalAccountCreationAllocation
    ]
    physical_capture: CanonicalCreationOperation[
        CapturePhysicalAccountRowObservationV2Command, PhysicalAccountRowObservationV2
    ]
    allocated_capture: CanonicalCreationOperation[
        CaptureAllocatedPhysicalAccountRowObservationV3Command,
        AllocatedPhysicalAccountRowObservationV3,
    ]
    bind: CanonicalCreationOperation[
        BindCanonicalAccountCreationV2Command, CanonicalAccountCreationBindingV2
    ]
    get_exact_binding: CanonicalCreationOperation[
        GetExactCanonicalAccountCreationBindingV2Command,
        CanonicalAccountCreationBindingV2 | None,
    ]
    _completion_finder: FindCompletedCanonicalAccountCreation

    def find_completed(
        self,
        command: AllocateCanonicalAccountCreationCommand,
        *,
        binding_id: str,
        binding_version: str,
    ) -> CanonicalAccountCreationBindingV2 | None:
        """Recover a completed creation from permanent Binding-v2 evidence."""

        return self._completion_finder.execute(
            command,
            binding_id=binding_id,
            binding_version=binding_version,
        )


def build_canonical_account_creation_stages(
    *,
    using: str,
    settings: CanonicalAccountCreationEvidenceSettings,
    requester: CanonicalAccountCreationRequester,
    physical_row_provider: ExactPhysicalSimulatedAccountRowV2Provider,
) -> CanonicalAccountCreationStages:
    """Build all Account creation stages for one explicit caller-owned alias.

    The factory only constructs ports and use cases.  Every write operation
    checks for a caller-owned transaction on ``using`` before delegating to the
    existing application, whose private UOWs remain responsible for their
    append-only savepoints.  The factory never opens or commits a transaction.
    """

    alias = _require_database_alias(using)
    if type(settings) is not CanonicalAccountCreationEvidenceSettings:
        raise TypeError("settings must be an exact creation evidence settings snapshot")
    settings.__post_init__()
    settings.deadline_at(datetime.now(UTC))
    if type(requester) is not CanonicalAccountCreationRequester:
        raise TypeError("requester must be an exact CanonicalAccountCreationRequester")
    requester.__post_init__()
    if not callable(getattr(physical_row_provider, "get_exact_final", None)):
        raise TypeError("physical_row_provider must expose get_exact_final")
    duration = settings.as_timedelta()

    allocation_repository = DjangoCanonicalAccountCreationRepository(using=alias)
    physical_repository = DjangoPhysicalAccountRowObservationV2Repository(using=alias)
    root_repository = DjangoAllocatedPhysicalAccountRowObservationV3Repository(using=alias)
    consumption_repository = DjangoCanonicalAccountCreationConsumptionRepository(using=alias)

    allocation_operation = AllocateCanonicalAccountCreation(
        repository=allocation_repository,
        requester=requester,
        account_id_generator=_UuidCanonicalAccountIdGenerator(),
        allocator=CanonicalAccountCreationServiceRecorder(
            service_id=settings.allocation_recorder_service_id,
            role="canonical_account_identity_allocator",
        ),
        validity_period=duration,
    )
    physical_operation = CapturePhysicalAccountRowObservationV2(
        row_provider=physical_row_provider,
        repository=physical_repository,
        recorder=PhysicalAccountRowObservationV2Recorder(
            recorder_id=settings.physical_v2_recorder_service_id,
            service_name=settings.physical_v2_recorder_service_id,
        ),
        validity_period=duration,
    )
    allocated_operation = CaptureAllocatedPhysicalAccountRowObservationV3(
        allocation_provider=_CurrentAllocationProvider(allocation_repository),
        physical_provider=_PhysicalV2FinalProvider(physical_repository),
        repository=root_repository,
        recorder=AllocatedPhysicalAccountRowObservationV3Recorder(
            service_id=settings.allocated_v3_recorder_service_id
        ),
        validity_period=duration,
    )
    binding_operation = BindCanonicalAccountCreationV2(
        allocation_provider=allocation_repository,
        creation_root_provider=_RootFinalProvider(root_repository),
        repository=consumption_repository,
        binder=CanonicalAccountCreationServiceRecorder(
            service_id=settings.binding_recorder_service_id,
            role="canonical_account_creation_binder",
        ),
    )
    exact_binding_operation = GetExactCanonicalAccountCreationBindingV2(consumption_repository)
    completion_finder = FindCompletedCanonicalAccountCreation(
        requester=requester,
        allocation_repository=allocation_repository,
        consumption_repository=consumption_repository,
        binding_reader=exact_binding_operation,
    )
    return CanonicalAccountCreationStages(
        database_alias=alias,
        allocate=_TransactionBoundOperation(alias, allocation_operation),
        physical_capture=_TransactionBoundOperation(alias, physical_operation),
        allocated_capture=_TransactionBoundOperation(alias, allocated_operation),
        bind=_TransactionBoundOperation(alias, binding_operation),
        get_exact_binding=_TransactionBoundOperation(
            alias, exact_binding_operation, _requires_outer_transaction=False
        ),
        _completion_finder=completion_finder,
    )


def _require_database_alias(using: object) -> str:
    """Validate one exact non-whitespace Django database alias."""

    if (
        type(using) is not str
        or not using
        or using.strip() != using
        or any(character.isspace() for character in using)
    ):
        raise ValueError("using must be an exact database alias")
    return using


def _require_caller_transaction(using: str) -> None:
    """Require a caller-owned transaction on the exact configured alias."""

    try:
        connection = connections[using]
    except ConnectionDoesNotExist as error:
        raise ValueError("using must name a configured database alias") from error
    if not connection.in_atomic_block:
        raise RuntimeError("caller-owned outer transaction is required")


__all__ = [
    "CanonicalAccountCreationStages",
    "CanonicalCreationOperation",
    "build_canonical_account_creation_stages",
]
