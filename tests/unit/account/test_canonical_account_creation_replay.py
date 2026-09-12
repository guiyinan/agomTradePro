from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.account.application.canonical_account_creation import (
    AllocateCanonicalAccountCreationCommand,
    CanonicalAccountCreationRequester,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    GetExactCanonicalAccountCreationBindingV2Command,
    PersistedCanonicalAccountCreationBindingV2,
)
from apps.account.application.canonical_account_creation_replay import (
    CanonicalAccountCreationReplayConflict,
    CanonicalAccountCreationReplayCorruption,
    FindCompletedCanonicalAccountCreation,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_creation_consumption import (
    CanonicalAccountCreationConsumptionClaim,
    resolve_canonical_account_creation_consumption_claim_identity,
)
from tests.unit.account.test_canonical_account_creation_binding_v2 import _binding


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


def _command(**changes: object) -> AllocateCanonicalAccountCreationCommand:
    values: dict[str, object] = {
        "allocation_id": "allocation-7",
        "allocation_version": "v1",
        "request_fingerprint_hash": "a" * 64,
        "requested_raw_account_type": "SIMULATED",
    }
    values.update(changes)
    return AllocateCanonicalAccountCreationCommand(**values)  # type: ignore[arg-type]


def _claim(binding: CanonicalAccountCreationBindingV2) -> CanonicalAccountCreationConsumptionClaim:
    claim_id, claim_version = resolve_canonical_account_creation_consumption_claim_identity(
        binding.allocation,
        consumer_generation="v2",
    )
    physical = binding.creation_root.physical_observation
    return CanonicalAccountCreationConsumptionClaim(
        claim_id=claim_id,
        claim_version=claim_version,
        allocation=binding.allocation,
        consumer_generation="v2",
        consumer=binding,
        account_namespace=binding.account_namespace_claim,
        account_id=binding.account_id_claim,
        underlying_unified_account_namespace=(binding.underlying_unified_account_namespace_claim),
        underlying_unified_account_id=binding.underlying_unified_account_id_claim,
        physical_v2_content_hash=physical.content_hash,
        physical_v3_root_content_hash=binding.creation_root.content_hash,
        recorded_at=binding.recorded_at,
    )


class _ConsumptionReader:
    def __init__(self, winner: object | None, clock: datetime) -> None:
        self.winner = winner
        self.clock = clock

    def now(self) -> datetime:
        return self.clock

    def get_winner(
        self,
        *,
        binding_id: str,
        binding_version: str,
        as_of: datetime,
    ) -> PersistedCanonicalAccountCreationBindingV2 | None:
        del binding_id, binding_version, as_of
        return self.winner  # type: ignore[return-value]


class _AllocationReader:
    def __init__(self, allocation: object | None) -> None:
        self.allocation = allocation
        self.calls = 0

    def get_allocation_winner(
        self,
        *,
        allocation_id: str,
        allocation_version: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationAllocation | None:
        del allocation_id, allocation_version, as_of
        self.calls += 1
        return self.allocation  # type: ignore[return-value]


class _ExactReader:
    def __init__(self, binding: object | None) -> None:
        self.binding = binding
        self.commands: list[GetExactCanonicalAccountCreationBindingV2Command] = []

    def execute(
        self,
        command: GetExactCanonicalAccountCreationBindingV2Command,
    ) -> CanonicalAccountCreationBindingV2 | None:
        self.commands.append(command)
        return self.binding  # type: ignore[return-value]


def _service(
    *,
    binding: CanonicalAccountCreationBindingV2 | None = None,
    allocation: object | None = None,
    clock: datetime = _at(30),
    requester: CanonicalAccountCreationRequester | None = None,
) -> tuple[
    FindCompletedCanonicalAccountCreation,
    _AllocationReader,
    _ExactReader,
]:
    winner = None
    if binding is not None:
        winner = PersistedCanonicalAccountCreationBindingV2(binding, _claim(binding))
    allocation_reader = _AllocationReader(allocation)
    exact_reader = _ExactReader(binding)
    return (
        FindCompletedCanonicalAccountCreation(
            requester=requester
            or (
                binding.allocation.requested_by
                if binding is not None
                else _binding().allocation.requested_by
            ),
            allocation_repository=allocation_reader,
            consumption_repository=_ConsumptionReader(winner, clock),
            binding_reader=exact_reader,
        ),
        allocation_reader,
        exact_reader,
    )


def test_find_completed_replays_permanent_binding_after_source_ttl() -> None:
    binding = _binding()
    cutoff = _at(30)
    assert binding.creation_root.valid_until < cutoff
    assert binding.creation_root.physical_observation.valid_until < cutoff
    service, allocation_reader, exact_reader = _service(binding=binding)

    result = service.execute(
        _command(),
        binding_id=binding.binding_id,
        binding_version=binding.binding_version,
    )

    assert result == binding
    assert allocation_reader.calls == 0
    assert len(exact_reader.commands) == 1
    assert exact_reader.commands[0].expected_content_hash == binding.content_hash
    assert exact_reader.commands[0].as_of == cutoff


@pytest.mark.parametrize(
    ("command_changes", "selector_changes"),
    [
        ({"request_fingerprint_hash": "b" * 64}, {}),
        ({"requested_raw_account_type": "PAPER"}, {}),
        ({}, {"binding_id": "other-binding"}),
        ({}, {"binding_version": "other-version"}),
        ({"allocation_id": "other-allocation"}, {}),
        ({"allocation_version": "other-version"}, {}),
    ],
)
def test_find_completed_rejects_request_or_binding_selector_substitution(
    command_changes: dict[str, object], selector_changes: dict[str, str]
) -> None:
    binding = _binding()
    service, _, exact_reader = _service(binding=binding)
    selector = {
        "binding_id": binding.binding_id,
        "binding_version": binding.binding_version,
        **selector_changes,
    }

    with pytest.raises(CanonicalAccountCreationReplayConflict):
        service.execute(_command(**command_changes), **selector)

    assert exact_reader.commands == []


def test_find_completed_rejects_allocation_without_binding_and_empty_world_is_none() -> None:
    allocation = _binding().allocation
    service, allocation_reader, exact_reader = _service(allocation=allocation)

    with pytest.raises(CanonicalAccountCreationReplayConflict, match="without"):
        service.execute(
            _command(),
            binding_id="binding-7",
            binding_version="v2",
        )
    assert allocation_reader.calls == 1
    assert exact_reader.commands == []

    empty, empty_allocation_reader, empty_exact_reader = _service()
    assert (
        empty.execute(
            _command(),
            binding_id="binding-7",
            binding_version="v2",
        )
        is None
    )
    assert empty_allocation_reader.calls == 1
    assert empty_exact_reader.commands == []


def test_find_completed_rejects_future_winner_and_exact_reader_tamper() -> None:
    future_binding = _binding(recorded_at=_at(13))
    service, _, exact_reader = _service(binding=future_binding, clock=_at(12))

    with pytest.raises(CanonicalAccountCreationReplayCorruption, match="newer"):
        service.execute(
            _command(),
            binding_id=future_binding.binding_id,
            binding_version=future_binding.binding_version,
        )
    assert exact_reader.commands == []

    binding = _binding()
    service, _, exact_reader = _service(binding=binding)
    exact_reader.binding = None
    with pytest.raises(CanonicalAccountCreationReplayCorruption, match="unavailable"):
        service.execute(
            _command(),
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
        )


def test_find_completed_requires_exact_allocate_command_and_requester() -> None:
    binding = _binding()
    service, _, _ = _service(binding=binding)

    with pytest.raises(TypeError, match="AllocateCanonicalAccountCreationCommand"):
        service.execute(  # type: ignore[arg-type]
            object(),
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
        )

    for other_requester in (
        CanonicalAccountCreationRequester(actor_id="actor-7", user_id=99),
        CanonicalAccountCreationRequester(actor_id="other", user_id=42),
    ):
        other_service, _, _ = _service(binding=binding, requester=other_requester)
        with pytest.raises(CanonicalAccountCreationReplayConflict):
            other_service.execute(
                _command(),
                binding_id=binding.binding_id,
                binding_version=binding.binding_version,
            )
