"""Dormant read and persistence contracts for RBAC mutation binding v3."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption,
)
from apps.account.domain.account_rbac_authority_mutation_binding_v3 import (
    AccountRbacAuthorityMutationBindingV3,
)


def _token(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")
    return value


def _digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be an exact timezone-aware datetime")
    return value


@dataclass(frozen=True, slots=True)
class AccountRbacAuthorityMutationBindingV3Selector:
    """ID/hash/PIT selector for one immutable mutation binding."""

    mutation_id: str
    source_id: str
    source_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Validate exact selector scalars and the aware PIT clock."""

        _token(self.mutation_id, "mutation_id")
        _token(self.source_id, "source_id")
        _token(self.source_version, "source_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class PersistedAccountRbacAuthorityMutationBindingV3:
    """Carry one exact Domain binding across the repository boundary."""

    binding: AccountRbacAuthorityMutationBindingV3

    def __post_init__(self) -> None:
        """Revalidate the immutable binding and reject type substitution."""

        if type(self.binding) is not AccountRbacAuthorityMutationBindingV3:
            raise TypeError("binding must be an exact RBAC mutation binding v3")
        self.binding.__post_init__()


class AccountRbacAuthorityMutationBindingV3Repository(Protocol):
    """Persist mutation bindings and their candidate-independent logical chains."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the repository-owned, same-alias non-nestable unit of work."""

        ...

    def now(self) -> datetime:
        """Return the repository's authoritative aware server clock."""

        ...

    def get_winner(
        self,
        *,
        mutation_id: str,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> PersistedAccountRbacAuthorityMutationBindingV3 | None:
        """Return the exact first winner knowable at the PIT cutoff."""

        ...

    def get_current_head(
        self, *, source_id: str, as_of: datetime
    ) -> PersistedAccountRbacAuthorityMutationBindingV3 | None:
        """Return the final source-epoch binding head, including terminal heads."""

        ...

    def get_exact_by_hash(
        self,
        *,
        mutation_id: str,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountRbacAuthorityMutationBindingV3 | None:
        """Return one exact historical binding at a recorded PIT."""

        ...

    def append(
        self,
        record: PersistedAccountRbacAuthorityMutationBindingV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountRbacAuthorityMutationBindingV3:
        """Append one binding through predecessor CAS; no capture orchestration."""

        ...


class GetExactAccountRbacAuthorityMutationBindingV3:
    """Read one exact historical binding without TTL or head fallback."""

    def __init__(self, repository: AccountRbacAuthorityMutationBindingV3Repository) -> None:
        """Store the injected repository contract."""

        self._repository = repository

    def execute(
        self, selector: AccountRbacAuthorityMutationBindingV3Selector
    ) -> AccountRbacAuthorityMutationBindingV3 | None:
        """Return the exact binding only when it is knowable at the PIT."""

        checked = _selector(selector)
        raw = self._repository.get_exact_by_hash(
            mutation_id=checked.mutation_id,
            source_id=checked.source_id,
            source_version=checked.source_version,
            expected_content_hash=checked.expected_content_hash,
            as_of=checked.as_of,
        )
        if raw is None:
            return None
        record = _record(raw)
        binding = record.binding
        if not binding.is_knowable_at(checked.as_of):
            raise AccountActorAuthorityRawSourceV3Corruption(
                "repository returned a future RBAC mutation binding"
            )
        if _binding_identity(binding) != (
            checked.mutation_id,
            checked.source_id,
            checked.source_version,
            checked.expected_content_hash,
        ):
            raise AccountActorAuthorityRawSourceV3Corruption(
                "RBAC mutation binding exact selector substitution"
            )
        return binding


class GetCurrentAccountRbacAuthorityMutationBindingV3:
    """Return an exact binding only while it is the final temporal head."""

    def __init__(self, repository: AccountRbacAuthorityMutationBindingV3Repository) -> None:
        """Store the injected repository contract."""

        self._repository = repository

    def execute(
        self, selector: AccountRbacAuthorityMutationBindingV3Selector
    ) -> AccountRbacAuthorityMutationBindingV3 | None:
        """Verify exact history, final-head equality, and current authority state."""

        checked = _selector(selector)
        exact = GetExactAccountRbacAuthorityMutationBindingV3(self._repository).execute(checked)
        if exact is None:
            return None
        if not (
            exact.new_authority_state == "current"
            and exact.recorded_at <= checked.as_of < exact.valid_until
        ):
            return None
        raw_head = self._repository.get_current_head(
            source_id=checked.source_id,
            as_of=checked.as_of,
        )
        if raw_head is None:
            return None
        head = _record(raw_head).binding
        if not head.is_knowable_at(checked.as_of):
            raise AccountActorAuthorityRawSourceV3Corruption(
                "repository returned a future RBAC mutation head"
            )
        if _binding_identity(head)[1] != checked.source_id:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "RBAC mutation head source substitution"
            )
        if head != exact:
            if _binding_identity(head)[:3] == _binding_identity(exact)[:3]:
                raise AccountActorAuthorityRawSourceV3Corruption(
                    "RBAC mutation head substituted an exact logical version"
                )
            return None
        return exact


def _selector(value: object) -> AccountRbacAuthorityMutationBindingV3Selector:
    """Validate an exact selector and translate malformed values to Corruption."""

    if type(value) is not AccountRbacAuthorityMutationBindingV3Selector:
        raise AccountActorAuthorityRawSourceV3Corruption("RBAC binding selector substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "RBAC binding selector is corrupt"
        ) from error
    return value


def _record(value: object) -> PersistedAccountRbacAuthorityMutationBindingV3:
    """Validate an exact persisted wrapper and translate malformed values."""

    if type(value) is not PersistedAccountRbacAuthorityMutationBindingV3:
        raise AccountActorAuthorityRawSourceV3Corruption("RBAC binding record substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "RBAC binding record is corrupt"
        ) from error
    return value


def _binding_identity(
    binding: AccountRbacAuthorityMutationBindingV3,
) -> tuple[str, str, str, str]:
    """Project mutation/source/hash identity without a caller PIT clock."""

    return (
        binding.mutation_id,
        binding.epoch.source_id,
        binding.source_version,
        binding.content_hash,
    )


__all__ = [
    "AccountRbacAuthorityMutationBindingV3Repository",
    "AccountRbacAuthorityMutationBindingV3Selector",
    "GetCurrentAccountRbacAuthorityMutationBindingV3",
    "GetExactAccountRbacAuthorityMutationBindingV3",
    "PersistedAccountRbacAuthorityMutationBindingV3",
]
