"""Permanent, fail-closed discovery of completed canonical Account creation."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.account.application.canonical_account_creation import (
    AllocateCanonicalAccountCreationCommand,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    GetExactCanonicalAccountCreationBindingV2Command,
    PersistedCanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
    CanonicalAccountCreationRequester,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from core.exceptions import DataValidationError, DuplicateResourceError


class CanonicalAccountCreationReplayConflict(DuplicateResourceError):
    """A completed creation selector conflicts with an immutable winner."""

    default_message = "canonical Account creation replay conflicts with an existing winner"
    default_code = "CANONICAL_ACCOUNT_CREATION_REPLAY_CONFLICT"


class CanonicalAccountCreationReplayCorruption(DataValidationError):
    """A trusted permanent creation reader returned inconsistent evidence."""

    default_message = "canonical Account creation replay evidence is invalid"
    default_code = "CANONICAL_ACCOUNT_CREATION_REPLAY_CORRUPTION"


class CanonicalAccountCreationReplayAllocationReader(Protocol):
    """Read one allocation identity when no completed binding exists."""

    def get_allocation_winner(
        self,
        *,
        allocation_id: str,
        allocation_version: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationAllocation | None:
        """Return the immutable allocation identity known at ``as_of``."""


class CanonicalAccountCreationReplayConsumptionReader(Protocol):
    """Read the permanent Binding-v2/claim winner at one server cutoff."""

    def now(self) -> datetime:
        """Return the authoritative aware server clock."""

    def get_winner(
        self,
        *,
        binding_id: str,
        binding_version: str,
        as_of: datetime,
    ) -> PersistedCanonicalAccountCreationBindingV2 | None:
        """Return the exact permanent winner knowable at ``as_of``."""


class CanonicalAccountCreationReplayBindingReader(Protocol):
    """Read one exact permanent Binding-v2 by its server-provided content hash."""

    def execute(
        self,
        command: GetExactCanonicalAccountCreationBindingV2Command,
    ) -> CanonicalAccountCreationBindingV2 | None:
        """Return exact Binding-v2 evidence without applying a live-source TTL."""


def _require_aware(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalAccountCreationReplayCorruption("replay server clock is invalid")
    return value


def _require_allocation(value: object) -> CanonicalAccountCreationAllocation:
    if type(value) is not CanonicalAccountCreationAllocation:
        raise CanonicalAccountCreationReplayCorruption("allocation type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationReplayCorruption("allocation is corrupt") from error
    return value


def _require_persisted(
    value: object,
) -> PersistedCanonicalAccountCreationBindingV2:
    if type(value) is not PersistedCanonicalAccountCreationBindingV2:
        raise CanonicalAccountCreationReplayCorruption("winner pair type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationReplayCorruption("winner pair is corrupt") from error
    return value


class FindCompletedCanonicalAccountCreation:
    """Find one permanent completed creation without reviving expired sources.

    The caller supplies a previously authenticated requester snapshot.  This
    class validates that snapshot's immutable actor/user facts against the
    allocation embedded in the Binding-v2 winner; the requester object itself
    is not an authentication proof.
    """

    def __init__(
        self,
        *,
        requester: CanonicalAccountCreationRequester,
        allocation_repository: CanonicalAccountCreationReplayAllocationReader,
        consumption_repository: CanonicalAccountCreationReplayConsumptionReader,
        binding_reader: CanonicalAccountCreationReplayBindingReader,
    ) -> None:
        if type(requester) is not CanonicalAccountCreationRequester:
            raise TypeError("requester must be exact CanonicalAccountCreationRequester")
        requester.__post_init__()
        self._requester = requester
        self._allocation_repository = allocation_repository
        self._consumption_repository = consumption_repository
        self._binding_reader = binding_reader

    def execute(
        self,
        command: AllocateCanonicalAccountCreationCommand,
        *,
        binding_id: str,
        binding_version: str,
    ) -> CanonicalAccountCreationBindingV2 | None:
        """Return a permanent winner, an empty result, or an explicit conflict.

        Only the Consumption repository and the permanent Binding-v2 exact
        reader participate after a winner is found.  Physical-v2 and
        allocated-v3 current readers are intentionally absent, so a completed
        creation remains discoverable after their capture TTLs expire.
        """

        if type(command) is not AllocateCanonicalAccountCreationCommand:
            raise TypeError("command must be exact AllocateCanonicalAccountCreationCommand")
        command.__post_init__()
        cutoff = _require_aware(self._consumption_repository.now())
        GetExactCanonicalAccountCreationBindingV2Command(
            binding_id=binding_id,
            binding_version=binding_version,
            expected_content_hash="0" * 64,
            as_of=cutoff,
        )
        winner = self._consumption_repository.get_winner(
            binding_id=binding_id,
            binding_version=binding_version,
            as_of=cutoff,
        )
        if winner is None:
            allocation = self._allocation_repository.get_allocation_winner(
                allocation_id=command.allocation_id,
                allocation_version=command.allocation_version,
                as_of=cutoff,
            )
            if allocation is None:
                return None
            checked_allocation = _require_allocation(allocation)
            if (
                checked_allocation.allocation_id != command.allocation_id
                or checked_allocation.allocation_version != command.allocation_version
            ):
                raise CanonicalAccountCreationReplayCorruption("allocation selector substitution")
            raise CanonicalAccountCreationReplayConflict(
                "allocation exists without a completed Binding-v2"
            )

        persisted = _require_persisted(winner)
        binding = persisted.binding
        allocation = binding.allocation
        if binding.recorded_at > cutoff or persisted.claim.recorded_at > cutoff:
            raise CanonicalAccountCreationReplayCorruption(
                "completed Binding-v2 winner is newer than the replay cutoff"
            )
        if (
            binding.binding_id != binding_id
            or binding.binding_version != binding_version
            or allocation.allocation_id != command.allocation_id
            or allocation.allocation_version != command.allocation_version
            or allocation.requested_by != self._requester
            or allocation.request_fingerprint_hash != command.request_fingerprint_hash
            or allocation.requested_raw_account_type != command.requested_raw_account_type
        ):
            raise CanonicalAccountCreationReplayConflict(
                "completed Binding-v2 winner differs from the creation request"
            )

        exact = self._binding_reader.execute(
            GetExactCanonicalAccountCreationBindingV2Command(
                binding_id=binding_id,
                binding_version=binding_version,
                expected_content_hash=binding.content_hash,
                as_of=cutoff,
            )
        )
        if exact is None:
            raise CanonicalAccountCreationReplayCorruption(
                "completed Binding-v2 exact read is unavailable"
            )
        if type(exact) is not CanonicalAccountCreationBindingV2:
            raise CanonicalAccountCreationReplayCorruption(
                "completed Binding-v2 exact read type substitution"
            )
        try:
            exact.__post_init__()
        except (TypeError, ValueError) as error:
            raise CanonicalAccountCreationReplayCorruption(
                "completed Binding-v2 exact read is corrupt"
            ) from error
        if exact != binding:
            raise CanonicalAccountCreationReplayCorruption(
                "completed Binding-v2 exact read differs from the winner"
            )
        return exact


__all__ = [
    "CanonicalAccountCreationReplayAllocationReader",
    "CanonicalAccountCreationReplayBindingReader",
    "CanonicalAccountCreationReplayConflict",
    "CanonicalAccountCreationReplayConsumptionReader",
    "CanonicalAccountCreationReplayCorruption",
    "FindCompletedCanonicalAccountCreation",
]
