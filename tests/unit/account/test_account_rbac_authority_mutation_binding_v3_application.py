from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption,
)
from apps.account.application.account_rbac_authority_mutation_binding_v3 import (
    AccountRbacAuthorityMutationBindingV3Selector,
    GetCurrentAccountRbacAuthorityMutationBindingV3,
    GetExactAccountRbacAuthorityMutationBindingV3,
    PersistedAccountRbacAuthorityMutationBindingV3,
)
from tests.unit.account.test_account_rbac_authority_mutation_binding_v3 import _binding

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)


class _Repository:
    def __init__(self) -> None:
        root = _binding()
        changed = _binding("role_change", previous=root, new_role="admin")
        self.records = [
            PersistedAccountRbacAuthorityMutationBindingV3(root),
            PersistedAccountRbacAuthorityMutationBindingV3(changed),
        ]
        self.return_future = False
        self.return_substitution = False

    @contextmanager
    def atomic(self) -> Iterator[None]:
        yield

    def now(self) -> datetime:
        return NOW

    def get_winner(self, **kwargs: object):
        return self.get_exact_by_hash(
            **kwargs, expected_content_hash=kwargs["expected_content_hash"]
        )

    def get_current_head(self, *, source_id: str, as_of: datetime):
        records = [
            record
            for record in self.records
            if record.binding.epoch.source_id == source_id
            and (self.return_future or record.binding.recorded_at <= as_of)
        ]
        return records[-1] if records else None

    def get_exact_by_hash(
        self,
        *,
        mutation_id: str,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ):
        if self.return_substitution:
            return self.records[0]
        for record in self.records:
            binding = record.binding
            if (
                binding.mutation_id,
                binding.epoch.source_id,
                binding.source_version,
                binding.content_hash,
            ) == (mutation_id, source_id, source_version, expected_content_hash):
                if self.return_future or binding.recorded_at <= as_of:
                    return record
        return None

    def append(self, record, *, expected_predecessor_hash: str | None, recorded_at: datetime):
        self.records.append(record)
        return record


def _selector(binding, as_of: datetime) -> AccountRbacAuthorityMutationBindingV3Selector:
    return AccountRbacAuthorityMutationBindingV3Selector(
        mutation_id=binding.mutation_id,
        source_id=binding.epoch.source_id,
        source_version=binding.source_version,
        expected_content_hash=binding.content_hash,
        as_of=as_of,
    )


def test_exact_is_permanent_recorded_knowledge_and_current_is_final_head_only() -> None:
    repository = _Repository()
    root = repository.records[0].binding
    changed = repository.records[1].binding
    exact = GetExactAccountRbacAuthorityMutationBindingV3(repository)
    current = GetCurrentAccountRbacAuthorityMutationBindingV3(repository)

    assert exact.execute(_selector(root, NOW + timedelta(days=1))) == root
    assert current.execute(_selector(root, root.recorded_at)) == root
    assert current.execute(_selector(root, changed.recorded_at)) is None
    assert current.execute(_selector(changed, changed.recorded_at)) == changed


def test_terminal_final_head_is_exactly_readable_but_never_current() -> None:
    repository = _Repository()
    changed = repository.records[1].binding
    revoked = _binding("revoke", previous=changed, new_role="admin")
    repository.records.append(PersistedAccountRbacAuthorityMutationBindingV3(revoked))
    selector = _selector(revoked, revoked.recorded_at)

    assert GetExactAccountRbacAuthorityMutationBindingV3(repository).execute(selector) == revoked
    assert GetCurrentAccountRbacAuthorityMutationBindingV3(repository).execute(selector) is None


def test_future_repository_row_is_corruption_not_unavailable() -> None:
    repository = _Repository()
    repository.return_future = True
    root = repository.records[0].binding
    selector = _selector(root, root.recorded_at - timedelta(days=1))

    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        GetExactAccountRbacAuthorityMutationBindingV3(repository).execute(selector)


def test_selector_type_and_hash_substitution_fail_closed() -> None:
    repository = _Repository()
    root = repository.records[0].binding
    reader = GetExactAccountRbacAuthorityMutationBindingV3(repository)
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        reader.execute(object())  # type: ignore[arg-type]
    repository.return_substitution = True
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        reader.execute(
            AccountRbacAuthorityMutationBindingV3Selector(
                mutation_id=root.mutation_id,
                source_id=root.epoch.source_id,
                source_version=root.source_version,
                expected_content_hash="0" * 64,
                as_of=root.recorded_at,
            )
        )
