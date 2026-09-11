"""Compose actual account creation and permanent replay in one user transaction."""

from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.application.allocated_physical_account_row_observation_v3 import (
    CaptureAllocatedPhysicalAccountRowObservationV3Command,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    BindCanonicalAccountCreationV2Command,
)
from apps.account.application.creation_evidence_settings import (
    CanonicalAccountCreationEvidenceSettings,
)
from apps.account.application.physical_account_row_observation_v2 import (
    CapturePhysicalAccountRowObservationV2Command,
)
from apps.account.canonical_creation_composition import build_canonical_account_creation_stages
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.simulated_trading.account_physical_row_v2_composition import (
    build_account_physical_row_v2_provider,
)
from apps.simulated_trading.application.canonical_account_creation_request import (
    CanonicalAccountCreationRequest,
)
from apps.simulated_trading.application.canonical_account_creation_row import (
    CanonicalAccountCreationRowCommand,
    CanonicalAccountCreationRowConflict,
    CanonicalAccountCreationRowCorruption,
    CanonicalAccountCreationRowUnavailable,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    CaptureSimulatedAccountRowSourceV2Command,
)
from apps.simulated_trading.creation_composition import build_simulated_account_creation_stages
from apps.simulated_trading.creation_transaction_composition import account_creation_transaction
from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount


@dataclass(frozen=True, slots=True)
class CanonicalAccountCreationResult:
    """An actual owned row and its permanent evidence-only creation binding."""

    account: SimulatedAccount
    binding: CanonicalAccountCreationBindingV2
    replayed: bool

    def __post_init__(self) -> None:
        """Reject a result whose physical row differs from the durable binding."""

        if (
            type(self.account) is not SimulatedAccount
            or type(self.binding) is not CanonicalAccountCreationBindingV2
        ):
            raise CanonicalAccountCreationRowCorruption("creation result type substitution")
        self.binding.__post_init__()
        physical = self.binding.creation_root.physical_observation
        if (
            type(self.replayed) is not bool
            or type(self.account.account_id) is not int
            or type(self.account.account_type) is not AccountType
            or self.account.account_id != physical.underlying_unified_account_id
            or self.account.account_type.value != physical.raw_account_type
            or self.account.is_active is not True
        ):
            raise CanonicalAccountCreationRowCorruption(
                "creation result does not match its physical binding"
            )


def create_canonical_account(
    *,
    request: CanonicalAccountCreationRequest,
    using: str,
    settings: CanonicalAccountCreationEvidenceSettings,
) -> CanonicalAccountCreationResult:
    """Create or replay under a real user-row lock without granting authority.

    Authentication must precede this call: actor/user in ``request`` are trusted
    server inputs, not HTTP payload identity claims. Configuration is resolved
    before this boundary. Every stage below uses the supplied database alias.
    """

    if type(request) is not CanonicalAccountCreationRequest:
        raise TypeError("request must be an exact canonical creation request")
    request.__post_init__()
    requester = CanonicalAccountCreationRequester(
        actor_id=request.actor_id, user_id=request.user_id
    )
    account_stages = build_canonical_account_creation_stages(
        using=using,
        settings=settings,
        requester=requester,
        physical_row_provider=build_account_physical_row_v2_provider(using=using),
    )
    owner_stages = build_simulated_account_creation_stages(using=using, settings=settings)
    allocation_command = request.allocation_command()
    with account_creation_transaction(using=using, user_id=request.user_id):
        completed = account_stages.find_completed(
            allocation_command,
            binding_id=request.binding_id,
            binding_version=request.binding_version,
        )
        if completed is not None:
            physical = completed.creation_root.physical_observation
            current = owner_stages.account_reader.read_owned(
                user_id=request.user_id,
                account_id=physical.underlying_unified_account_id,
                account_type=request.account_type,
            )
            if current is None:
                raise CanonicalAccountCreationRowUnavailable(
                    "completed creation account is no longer available to this user"
                )
            return CanonicalAccountCreationResult(account=current, binding=completed, replayed=True)
        if owner_stages.account_reader.name_exists(
            user_id=request.user_id, account_name=request.account_name
        ):
            raise CanonicalAccountCreationRowConflict("account name already exists for this user")
        settings.deadline_at(datetime.now(UTC))
        allocation = account_stages.allocate.execute(allocation_command)
        if (
            allocation.allocation_id != allocation_command.allocation_id
            or allocation.allocation_version != allocation_command.allocation_version
            or allocation.requested_by != requester
            or allocation.request_fingerprint_hash != request.fingerprint_hash
            or allocation.requested_raw_account_type != request.account_type.value
        ):
            raise CanonicalAccountCreationRowCorruption(
                "allocation differs from the creation request"
            )
        written = owner_stages.row_writer.execute(
            CanonicalAccountCreationRowCommand(
                requester_user_id=request.user_id,
                account=request.to_account(start_date=datetime.now(UTC).date()),
                observation_id=f"create-row-{request.identity_hash}",
                mutation_version="v1",
            )
        )
        raw = owner_stages.raw_writer.record_create(written.mutation)
        source = owner_stages.source_capture.execute(
            CaptureSimulatedAccountRowSourceV2Command(
                source_id=raw.observation_id,
                source_version=raw.observation_version,
                expected_raw_observation_content_hash=raw.content_hash,
                account_namespace=allocation.canonical_account_namespace,
                account_id=allocation.canonical_account_id,
                underlying_unified_account_namespace=allocation.intended_underlying_unified_account_namespace,
                underlying_unified_account_id=written.account.account_id,
            )
        )
        physical = account_stages.physical_capture.execute(
            CapturePhysicalAccountRowObservationV2Command(
                observation_id=raw.observation_id,
                observation_version=raw.observation_version,
                source_id=source.source_id,
                source_version=source.source_version,
                expected_source_content_hash=source.content_hash,
                account_namespace=allocation.canonical_account_namespace,
                account_id=allocation.canonical_account_id,
                underlying_unified_account_namespace=allocation.intended_underlying_unified_account_namespace,
                underlying_unified_account_id=written.account.account_id,
            )
        )
        root = account_stages.allocated_capture.execute(
            CaptureAllocatedPhysicalAccountRowObservationV3Command(
                observation_id=f"create-root-{request.identity_hash}",
                observation_version="v1",
                allocation_id=allocation.allocation_id,
                allocation_version=allocation.allocation_version,
                expected_allocation_content_hash=allocation.content_hash,
                physical_observation_id=physical.observation_id,
                physical_observation_version=physical.observation_version,
                expected_physical_content_hash=physical.content_hash,
            )
        )
        binding = account_stages.bind.execute(
            BindCanonicalAccountCreationV2Command(
                binding_id=request.binding_id,
                binding_version=request.binding_version,
                allocation_id=allocation.allocation_id,
                allocation_version=allocation.allocation_version,
                expected_allocation_content_hash=allocation.content_hash,
                creation_root_observation_id=root.observation_id,
                creation_root_observation_version=root.observation_version,
                expected_creation_root_content_hash=root.content_hash,
            )
        )
        return CanonicalAccountCreationResult(
            account=written.account, binding=binding, replayed=False
        )


__all__ = ["CanonicalAccountCreationResult", "create_canonical_account"]
