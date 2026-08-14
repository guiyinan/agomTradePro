from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from apps.account.application.canonical_account_creation_binding_v2 import (
    BindCanonicalAccountCreationV2,
    BindCanonicalAccountCreationV2Command,
    CanonicalAccountCreationBindingV2Conflict,
    CanonicalAccountCreationBindingV2Unavailable,
    GetExactCanonicalAccountCreationBindingV2,
    GetExactCanonicalAccountCreationBindingV2Command,
    PersistedCanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationServiceRecorder
from tests.unit.account.test_allocated_physical_account_row_observation_v3 import _root


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


class _Provider:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0
        self.as_of_values: list[datetime] = []

    def get_current_unconsumed_allocation(self, **kwargs: object) -> object:
        self.calls += 1
        self.as_of_values.append(kwargs["as_of"])  # type: ignore[arg-type]
        return self.value

    def get_exact_final(self, **kwargs: object) -> object:
        self.calls += 1
        self.as_of_values.append(kwargs["as_of"])  # type: ignore[arg-type]
        return self.value


class _Repository:
    def __init__(self) -> None:
        self.clock = _at(8)
        self.value: object | None = None
        self.anchor: object | None = None
        self.claim: object | None = None
        self.exact_value: object | None = None
        self.append_kwargs: dict[str, object] = {}

    @contextmanager
    def atomic(self) -> Iterator[None]:
        yield

    def now(self) -> datetime:
        return self.clock

    def get_winner(self, **kwargs: object) -> object | None:
        return self.value

    def get_consumption_claim_by_any_anchor(self, **kwargs: object) -> object | None:
        return self.anchor

    def get_exact_by_hash(self, **kwargs: object) -> object | None:
        return self.exact_value

    def append_with_consumption_claim(
        self, binding: object, claim: object, **kwargs: object
    ) -> tuple[object, object]:
        self.value = PersistedCanonicalAccountCreationBindingV2(binding, claim)  # type: ignore[arg-type]
        self.claim = claim
        self.exact_value = binding
        self.append_kwargs = kwargs
        return binding, claim


class _WinnerRaceRepository(_Repository):
    def __init__(self, winner: object) -> None:
        super().__init__()
        self.winner = winner
        self.winner_reads = 0
        self.append_calls = 0

    def get_winner(self, **kwargs: object) -> object | None:
        self.winner_reads += 1
        return None if self.winner_reads == 1 else self.winner

    def append_with_consumption_claim(
        self, binding: object, claim: object, **kwargs: object
    ) -> tuple[object, object]:
        self.append_calls += 1
        return super().append_with_consumption_claim(binding, claim, **kwargs)


class _AdvancingClockRepository(_Repository):
    def __init__(self) -> None:
        super().__init__()
        self.clocks = iter((_at(8), _at(9)))

    def now(self) -> datetime:
        return next(self.clocks)


def _command() -> BindCanonicalAccountCreationV2Command:
    root = _root()
    return BindCanonicalAccountCreationV2Command(
        "durable-binding-7",
        "v2",
        root.allocation.allocation_id,
        root.allocation.allocation_version,
        root.allocation.content_hash,
        root.observation_id,
        root.observation_version,
        root.content_hash,
    )


def _service() -> CanonicalAccountCreationServiceRecorder:
    return CanonicalAccountCreationServiceRecorder("binder-v2", "canonical_account_creation_binder")


def test_issue_uses_server_binder_clock_and_exact_nested_hashes() -> None:
    root = _root()
    repository = _Repository()
    value = BindCanonicalAccountCreationV2(
        allocation_provider=_Provider(root.allocation),
        creation_root_provider=_Provider(root),
        repository=repository,
        binder=_service(),
    ).execute(_command())
    assert value.recorded_at == repository.clock
    assert repository.claim is not None
    assert repository.claim.recorded_at == value.recorded_at  # type: ignore[union-attr]
    assert repository.claim.consumer_generation == "v2"  # type: ignore[union-attr]
    assert repository.claim.physical_v3_root_content_hash == root.content_hash  # type: ignore[union-attr]
    assert repository.append_kwargs["recorded_at"] == value.recorded_at
    assert value.recorded_by == _service()
    assert value.creation_root_content_hash == root.content_hash
    assert value.physical_source_content_hash == root.physical_observation.source_content_hash
    assert value.must_not_execute is True


def test_issue_rereads_inputs_at_authoritative_recorded_clock() -> None:
    root = _root()
    repository = _AdvancingClockRepository()
    allocation_provider = _Provider(root.allocation)
    creation_root_provider = _Provider(root)

    value = BindCanonicalAccountCreationV2(
        allocation_provider=allocation_provider,
        creation_root_provider=creation_root_provider,
        repository=repository,
        binder=_service(),
    ).execute(_command())

    assert value.recorded_at == _at(9)
    assert allocation_provider.as_of_values == [_at(8), _at(9)]
    assert creation_root_provider.as_of_values == [_at(8), _at(9)]


def test_identity_replay_and_anchor_conflict() -> None:
    root = _root()
    repository = _Repository()
    use_case = BindCanonicalAccountCreationV2(
        allocation_provider=_Provider(root.allocation),
        creation_root_provider=_Provider(root),
        repository=repository,
        binder=_service(),
    )
    first = use_case.execute(_command())
    # A successful binding consumes the allocation. Exact retries must therefore
    # replay the immutable winner without asking a current-unconsumed provider.
    repository.clock = _at(30)
    use_case._allocation_provider.value = None
    use_case._creation_root_provider.value = None
    assert use_case.execute(_command()) == first
    assert use_case._allocation_provider.calls == 2
    assert use_case._creation_root_provider.calls == 2
    use_case._allocation_provider.value = root.allocation
    use_case._creation_root_provider.value = root
    repository.clock = _at(8)
    repository.value = None
    repository.anchor = repository.claim
    with pytest.raises(CanonicalAccountCreationBindingV2Conflict, match="anchor"):
        use_case.execute(_command())


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("binding_id", "substituted-binding"),
        ("binding_version", "substituted-version"),
        ("allocation_id", "substituted-allocation"),
        ("allocation_version", "substituted-allocation-version"),
        ("expected_allocation_content_hash", "a" * 64),
        ("creation_root_observation_id", "substituted-root"),
        ("creation_root_observation_version", "substituted-root-version"),
        ("expected_creation_root_content_hash", "b" * 64),
    ),
)
def test_replay_rejects_every_command_selector_substitution(
    field_name: str, replacement: str
) -> None:
    root = _root()
    repository = _Repository()
    BindCanonicalAccountCreationV2(
        allocation_provider=_Provider(root.allocation),
        creation_root_provider=_Provider(root),
        repository=repository,
        binder=_service(),
    ).execute(_command())
    assert repository.value is not None
    unavailable_allocation = _Provider(None)
    unavailable_root = _Provider(None)
    use_case = BindCanonicalAccountCreationV2(
        allocation_provider=unavailable_allocation,
        creation_root_provider=unavailable_root,
        repository=repository,
        binder=_service(),
    )

    with pytest.raises(CanonicalAccountCreationBindingV2Conflict, match="winner differs"):
        use_case.execute(replace(_command(), **{field_name: replacement}))

    assert unavailable_allocation.calls == 0
    assert unavailable_root.calls == 0


def test_replay_rejects_authenticated_binder_substitution_without_live_inputs() -> None:
    root = _root()
    repository = _Repository()
    BindCanonicalAccountCreationV2(
        allocation_provider=_Provider(root.allocation),
        creation_root_provider=_Provider(root),
        repository=repository,
        binder=_service(),
    ).execute(_command())
    assert repository.value is not None
    unavailable_allocation = _Provider(None)
    unavailable_root = _Provider(None)
    use_case = BindCanonicalAccountCreationV2(
        allocation_provider=unavailable_allocation,
        creation_root_provider=unavailable_root,
        repository=repository,
        binder=CanonicalAccountCreationServiceRecorder(
            "substituted-binder", "canonical_account_creation_binder"
        ),
    )

    with pytest.raises(CanonicalAccountCreationBindingV2Conflict, match="winner differs"):
        use_case.execute(_command())

    assert unavailable_allocation.calls == 0
    assert unavailable_root.calls == 0


def test_atomic_winner_race_replays_without_second_current_input_read() -> None:
    root = _root()
    seed_repository = _Repository()
    winner = BindCanonicalAccountCreationV2(
        allocation_provider=_Provider(root.allocation),
        creation_root_provider=_Provider(root),
        repository=seed_repository,
        binder=_service(),
    ).execute(_command())
    allocation_provider = _Provider(root.allocation)
    creation_root_provider = _Provider(root)
    assert seed_repository.value is not None
    race_repository = _WinnerRaceRepository(seed_repository.value)

    replay = BindCanonicalAccountCreationV2(
        allocation_provider=allocation_provider,
        creation_root_provider=creation_root_provider,
        repository=race_repository,
        binder=_service(),
    ).execute(_command())

    assert replay == winner
    assert race_repository.winner_reads == 2
    assert allocation_provider.calls == 1
    assert creation_root_provider.calls == 1
    assert race_repository.append_calls == 0


def test_unavailable_allocation_or_root_fails_closed() -> None:
    root = _root()
    for allocation, creation_root in ((None, root), (root.allocation, None)):
        with pytest.raises(CanonicalAccountCreationBindingV2Unavailable):
            BindCanonicalAccountCreationV2(
                allocation_provider=_Provider(allocation),
                creation_root_provider=_Provider(creation_root),
                repository=_Repository(),
                binder=_service(),
            ).execute(_command())


def test_exact_reader_is_permanent_after_recorded_at_not_ttl_current() -> None:
    root = _root()
    repository = _Repository()
    binding = BindCanonicalAccountCreationV2(
        allocation_provider=_Provider(root.allocation),
        creation_root_provider=_Provider(root),
        repository=repository,
        binder=_service(),
    ).execute(_command())
    reader = GetExactCanonicalAccountCreationBindingV2(repository)
    assert (
        reader.execute(
            GetExactCanonicalAccountCreationBindingV2Command(
                binding.binding_id, binding.binding_version, binding.content_hash, _at(7)
            )
        )
        is None
    )
    assert (
        reader.execute(
            GetExactCanonicalAccountCreationBindingV2Command(
                binding.binding_id, binding.binding_version, binding.content_hash, _at(30)
            )
        )
        == binding
    )


def test_commands_are_exact_id_hash_only_and_reject_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        GetExactCanonicalAccountCreationBindingV2Command("id", "v2", "a" * 64, datetime(2026, 8, 8))
    with pytest.raises(TypeError, match="exact"):
        BindCanonicalAccountCreationV2(
            allocation_provider=_Provider(None),
            creation_root_provider=_Provider(None),
            repository=_Repository(),
            binder=_service(),
        ).execute(
            object()
        )  # type: ignore[arg-type]
