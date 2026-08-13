from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.canonical_account_creation import (
    AllocateCanonicalAccountCreation,
    AllocateCanonicalAccountCreationCommand,
    BindCanonicalAccountCreation,
    BindCanonicalAccountCreationCommand,
    CanonicalAccountCreationConflict,
    CanonicalAccountCreationUnavailable,
    PersistedCanonicalAccountCreationBinding,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
    CanonicalAccountCreationBinding,
    CanonicalAccountCreationRequester,
    CanonicalAccountCreationServiceRecorder,
)
from apps.account.domain.canonical_account_creation_consumption import (
    CanonicalAccountCreationConsumptionClaim,
    resolve_canonical_account_creation_consumption_claim_identity,
)
from tests.unit.account.test_canonical_account_creation import _physical


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


class _Ids:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self) -> str:
        self.calls += 1
        return "acct-opaque-0007"


class _Repo:
    def __init__(self) -> None:
        self.clock = _at(1)
        self.allocations: list[CanonicalAccountCreationAllocation] = []
        self.bindings: list[CanonicalAccountCreationBinding] = []
        self.claims: list[CanonicalAccountCreationConsumptionClaim] = []

    def atomic(self):  # type: ignore[no-untyped-def]
        return nullcontext()

    def now(self) -> datetime:
        return self.clock

    def get_allocation_winner(
        self, *, allocation_id: str, allocation_version: str, as_of: datetime
    ):  # type: ignore[no-untyped-def]
        return next(
            (
                x
                for x in self.allocations
                if (x.allocation_id, x.allocation_version) == (allocation_id, allocation_version)
                and x.allocated_at <= as_of
            ),
            None,
        )

    def get_allocation_by_request(
        self,
        *,
        requester_actor_id: str,
        requester_user_id: int,
        request_fingerprint_hash: str,
        as_of: datetime,
    ):  # type: ignore[no-untyped-def]
        return next(
            (
                x
                for x in self.allocations
                if x.requested_by.actor_id == requester_actor_id
                and x.requested_by.user_id == requester_user_id
                and x.request_fingerprint_hash == request_fingerprint_hash
                and x.allocated_at <= as_of
            ),
            None,
        )

    def get_exact_allocation(
        self,
        *,
        allocation_id: str,
        allocation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ):  # type: ignore[no-untyped-def]
        value = self.get_allocation_winner(
            allocation_id=allocation_id, allocation_version=allocation_version, as_of=as_of
        )
        return value if value is not None and value.content_hash == expected_content_hash else None

    def get_current_unconsumed_allocation(
        self,
        *,
        allocation_id: str,
        allocation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ):  # type: ignore[no-untyped-def]
        value = self.get_exact_allocation(
            allocation_id=allocation_id,
            allocation_version=allocation_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )
        consumed = any(x.allocation.content_hash == expected_content_hash for x in self.claims)
        return (
            value
            if value is not None
            and value.allocated_at <= as_of < value.valid_until
            and not consumed
            else None
        )

    def append_allocation(
        self, allocation: CanonicalAccountCreationAllocation, *, recorded_at: datetime
    ):  # type: ignore[no-untyped-def]
        winner = self.get_allocation_winner(
            allocation_id=allocation.allocation_id,
            allocation_version=allocation.allocation_version,
            as_of=recorded_at,
        )
        request = self.get_allocation_by_request(
            requester_actor_id=allocation.requested_by.actor_id,
            requester_user_id=allocation.requested_by.user_id,
            request_fingerprint_hash=allocation.request_fingerprint_hash,
            as_of=recorded_at,
        )
        if winner is not None:
            return winner
        if request is not None:
            return request
        self.allocations.append(allocation)
        return allocation

    def get_binding_winner(self, *, binding_id: str, binding_version: str, as_of: datetime):  # type: ignore[no-untyped-def]
        binding = next(
            (
                x
                for x in self.bindings
                if (x.binding_id, x.binding_version) == (binding_id, binding_version)
                and x.recorded_at <= as_of
            ),
            None,
        )
        if binding is None:
            return None
        claim = next(x for x in self.claims if x.consumer == binding)
        return PersistedCanonicalAccountCreationBinding(binding, claim)

    def get_consumption_claim_by_any_anchor(
        self,
        *,
        claim_id: str,
        claim_version: str,
        allocation_identity_hash: str,
        allocation_content_hash: str,
        consumer_identity_hash: str,
        consumer_content_hash: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        physical_v2_content_hash: str,
        physical_v3_root_content_hash: None,
        as_of: datetime,
    ):  # type: ignore[no-untyped-def]
        return next(
            (
                x
                for x in self.claims
                if x.recorded_at <= as_of
                and (
                    (x.claim_id, x.claim_version) == (claim_id, claim_version)
                    or x.allocation.identity_hash == allocation_identity_hash
                    or x.allocation.content_hash == allocation_content_hash
                    or x.consumer.identity_hash == consumer_identity_hash
                    or x.consumer.content_hash == consumer_content_hash
                    or (x.account_namespace, x.account_id) == (account_namespace, account_id)
                    or (
                        x.underlying_unified_account_namespace,
                        x.underlying_unified_account_id,
                    )
                    == (underlying_unified_account_namespace, underlying_unified_account_id)
                    or x.physical_v2_content_hash == physical_v2_content_hash
                )
            ),
            None,
        )

    def get_exact_binding(
        self, *, binding_id: str, binding_version: str, expected_content_hash: str, as_of: datetime
    ):  # type: ignore[no-untyped-def]
        value = self.get_binding_winner(
            binding_id=binding_id, binding_version=binding_version, as_of=as_of
        )
        return (
            value.binding
            if value is not None and value.binding.content_hash == expected_content_hash
            else None
        )

    def append_binding_with_consumption_claim(
        self,
        binding: CanonicalAccountCreationBinding,
        claim: CanonicalAccountCreationConsumptionClaim,
        *,
        expected_allocation_content_hash: str,
        expected_account_claim_hash: str,
        expected_underlying_claim_hash: str,
        expected_physical_content_hash: str,
        expected_consumption_claim_content_hash: str,
        recorded_at: datetime,
    ):  # type: ignore[no-untyped-def]
        winner = self.get_binding_winner(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            as_of=recorded_at,
        )
        if winner is not None:
            return winner.binding, winner.claim
        anchor = self.get_consumption_claim_by_any_anchor(
            claim_id=claim.claim_id,
            claim_version=claim.claim_version,
            allocation_identity_hash=claim.allocation.identity_hash,
            allocation_content_hash=expected_allocation_content_hash,
            consumer_identity_hash=binding.identity_hash,
            consumer_content_hash=binding.content_hash,
            account_namespace=claim.account_namespace,
            account_id=claim.account_id,
            underlying_unified_account_namespace=claim.underlying_unified_account_namespace,
            underlying_unified_account_id=claim.underlying_unified_account_id,
            physical_v2_content_hash=expected_physical_content_hash,
            physical_v3_root_content_hash=None,
            as_of=recorded_at,
        )
        if anchor is not None:
            return anchor.consumer, anchor
        assert binding.account_claim_hash == expected_account_claim_hash
        assert binding.underlying_claim_hash == expected_underlying_claim_hash
        assert claim.content_hash == expected_consumption_claim_content_hash
        self.bindings.append(binding)
        self.claims.append(claim)
        return binding, claim


class _PhysicalProvider:
    def __init__(self, physical):  # type: ignore[no-untyped-def]
        self.physical = physical

    def get_exact_final(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ):  # type: ignore[no-untyped-def]
        value = self.physical
        if (value.observation_id, value.observation_version, value.content_hash) != (
            observation_id,
            observation_version,
            expected_content_hash,
        ):
            return None
        return value if value.recorded_at <= as_of < value.valid_until else None


class _FailingPhysicalProvider:
    def get_exact_final(self, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("replay must not read live Physical-v2 evidence")


def _allocate(
    repo: _Repo, ids: _Ids, *, allocation_id: str = "allocation-7"
) -> CanonicalAccountCreationAllocation:
    return AllocateCanonicalAccountCreation(
        repository=repo,
        requester=CanonicalAccountCreationRequester(actor_id="user-42", user_id=42),
        account_id_generator=ids,
        allocator=CanonicalAccountCreationServiceRecorder(
            service_id="allocator", role="canonical_account_identity_allocator"
        ),
        validity_period=timedelta(days=20),
    ).execute(
        AllocateCanonicalAccountCreationCommand(
            allocation_id=allocation_id,
            allocation_version="v1",
            request_fingerprint_hash="a" * 64,
            requested_raw_account_type="SIMULATED",
        )
    )


def test_allocate_is_id_only_first_winner_and_request_idempotent_across_clocks() -> None:
    repo, ids = _Repo(), _Ids()
    first = _allocate(repo, ids)
    repo.clock = _at(2)
    replay = _allocate(repo, ids, allocation_id="another-client-key")

    assert replay is first
    assert first.canonical_account_id == "acct-opaque-0007"
    assert first.requested_row_user_id == 42
    assert ids.calls == 1


def test_allocate_rejects_identity_collision_and_request_substitution() -> None:
    repo, ids = _Repo(), _Ids()
    _allocate(repo, ids)
    with pytest.raises(CanonicalAccountCreationConflict):
        AllocateCanonicalAccountCreation(
            repository=repo,
            requester=CanonicalAccountCreationRequester(actor_id="user-99", user_id=99),
            account_id_generator=ids,
            allocator=CanonicalAccountCreationServiceRecorder(
                service_id="allocator", role="canonical_account_identity_allocator"
            ),
            validity_period=timedelta(days=20),
        ).execute(
            AllocateCanonicalAccountCreationCommand(
                allocation_id="allocation-7",
                allocation_version="v1",
                request_fingerprint_hash="b" * 64,
                requested_raw_account_type="SIMULATED",
            )
        )


def test_bind_double_reads_and_consumes_four_anchor_exact_winner() -> None:
    repo, ids = _Repo(), _Ids()
    allocation = _allocate(repo, ids)
    physical = _physical(account_id=allocation.canonical_account_id)
    repo.clock = _at(7)
    command = BindCanonicalAccountCreationCommand(
        binding_id="binding-7",
        binding_version="v1",
        allocation_id=allocation.allocation_id,
        allocation_version=allocation.allocation_version,
        expected_allocation_content_hash=allocation.content_hash,
        physical_observation_id=physical.observation_id,
        physical_observation_version=physical.observation_version,
        expected_physical_content_hash=physical.content_hash,
    )
    use_case = BindCanonicalAccountCreation(
        repository=repo,
        physical_provider=_PhysicalProvider(physical),
        binder=CanonicalAccountCreationServiceRecorder(
            service_id="binder", role="canonical_account_creation_binder"
        ),
    )

    binding = use_case.execute(command)
    assert use_case.execute(command) is binding
    assert binding.allocation is allocation
    assert len(repo.claims) == 1
    claim = repo.claims[0]
    assert claim.consumer is binding
    assert claim.recorded_at == binding.recorded_at
    assert (claim.claim_id, claim.claim_version) == (
        f"allocation-consumption-{allocation.identity_hash}",
        "v1",
    )
    assert (
        repo.get_current_unconsumed_allocation(
            allocation_id=allocation.allocation_id,
            allocation_version=allocation.allocation_version,
            expected_content_hash=allocation.content_hash,
            as_of=_at(8),
        )
        is None
    )


def test_claim_identity_is_frozen_and_replay_precedes_live_upstream_reads() -> None:
    repo, ids = _Repo(), _Ids()
    allocation = _allocate(repo, ids)
    assert resolve_canonical_account_creation_consumption_claim_identity(
        allocation, consumer_generation="v1"
    ) == (
        f"allocation-consumption-{allocation.identity_hash}",
        "v1",
    )
    physical = _physical(account_id=allocation.canonical_account_id)
    repo.clock = _at(7)
    command = BindCanonicalAccountCreationCommand(
        binding_id="binding-7",
        binding_version="v1",
        allocation_id=allocation.allocation_id,
        allocation_version=allocation.allocation_version,
        expected_allocation_content_hash=allocation.content_hash,
        physical_observation_id=physical.observation_id,
        physical_observation_version=physical.observation_version,
        expected_physical_content_hash=physical.content_hash,
    )
    first = BindCanonicalAccountCreation(
        repository=repo,
        physical_provider=_PhysicalProvider(physical),
        binder=CanonicalAccountCreationServiceRecorder(
            service_id="binder", role="canonical_account_creation_binder"
        ),
    ).execute(command)

    repo.allocations.clear()
    replay = BindCanonicalAccountCreation(
        repository=repo,
        physical_provider=_FailingPhysicalProvider(),
        binder=CanonicalAccountCreationServiceRecorder(
            service_id="binder", role="canonical_account_creation_binder"
        ),
    ).execute(command)

    assert replay is first


def test_bind_fails_closed_when_allocation_unavailable_or_anchor_consumed() -> None:
    repo, ids = _Repo(), _Ids()
    allocation = _allocate(repo, ids)
    physical = _physical(account_id=allocation.canonical_account_id)
    repo.clock = _at(7)
    command = BindCanonicalAccountCreationCommand(
        binding_id="binding-7",
        binding_version="v1",
        allocation_id=allocation.allocation_id,
        allocation_version=allocation.allocation_version,
        expected_allocation_content_hash=allocation.content_hash,
        physical_observation_id=physical.observation_id,
        physical_observation_version=physical.observation_version,
        expected_physical_content_hash=physical.content_hash,
    )
    use_case = BindCanonicalAccountCreation(
        repository=repo,
        physical_provider=_PhysicalProvider(physical),
        binder=CanonicalAccountCreationServiceRecorder(
            service_id="binder", role="canonical_account_creation_binder"
        ),
    )
    use_case.execute(command)
    with pytest.raises(CanonicalAccountCreationUnavailable):
        use_case.execute(replace(command, binding_id="binding-8"))
    empty = _Repo()
    empty.clock = _at(7)
    with pytest.raises(CanonicalAccountCreationUnavailable):
        BindCanonicalAccountCreation(
            repository=empty,
            physical_provider=_PhysicalProvider(physical),
            binder=CanonicalAccountCreationServiceRecorder(
                service_id="binder", role="canonical_account_creation_binder"
            ),
        ).execute(command)
