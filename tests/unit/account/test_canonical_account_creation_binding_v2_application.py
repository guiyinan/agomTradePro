from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from apps.account.application.canonical_account_creation_binding_v2 import (
    BindCanonicalAccountCreationV2,
    BindCanonicalAccountCreationV2Command,
    CanonicalAccountCreationBindingV2Conflict,
    CanonicalAccountCreationBindingV2Unavailable,
    GetExactCanonicalAccountCreationBindingV2,
    GetExactCanonicalAccountCreationBindingV2Command,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationServiceRecorder
from tests.unit.account.test_allocated_physical_account_row_observation_v3 import _root


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


class _Provider:
    def __init__(self, value: object) -> None:
        self.value = value

    def get_current_unconsumed_allocation(self, **kwargs: object) -> object:
        return self.value

    def get_exact_final(self, **kwargs: object) -> object:
        return self.value


class _Repository:
    def __init__(self) -> None:
        self.clock = _at(8)
        self.value: object | None = None
        self.anchor: object | None = None

    @contextmanager
    def atomic(self) -> Iterator[None]:
        yield

    def now(self) -> datetime:
        return self.clock

    def get_winner(self, **kwargs: object) -> object | None:
        return self.value

    def get_by_any_anchor(self, **kwargs: object) -> object | None:
        return self.anchor

    def get_exact_by_hash(self, **kwargs: object) -> object | None:
        return self.value

    def append(self, binding: object, **kwargs: object) -> object:
        self.value = binding
        return binding


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
    assert value.recorded_by == _service()
    assert value.creation_root_content_hash == root.content_hash
    assert value.physical_source_content_hash == root.physical_observation.source_content_hash
    assert value.must_not_execute is True


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
    use_case._allocation_provider.value = None
    use_case._creation_root_provider.value = None
    assert use_case.execute(_command()) == first
    use_case._allocation_provider.value = root.allocation
    use_case._creation_root_provider.value = root
    repository.value = None
    repository.anchor = first
    with pytest.raises(CanonicalAccountCreationBindingV2Conflict, match="anchor"):
        use_case.execute(_command())


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
