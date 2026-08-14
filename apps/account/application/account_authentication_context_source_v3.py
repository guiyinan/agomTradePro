"""Read contracts for immutable Account authentication-context raw sources v3."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Recorder,
    AccountActorAuthorityRawSourceV3Selector,
)
from apps.account.domain.account_authentication_context_source_v3 import (
    AccountAuthenticationContextSourceV3,
)


@dataclass(frozen=True, slots=True)
class PersistedAccountAuthenticationContextSourceV3:
    """Pair one exact Domain source with its fixed Account service recorder."""

    source: AccountAuthenticationContextSourceV3
    recorded_by: AccountActorAuthorityRawSourceV3Recorder

    def __post_init__(self) -> None:
        """Revalidate the exact source and recorder types at the repository boundary."""

        if type(self.source) is not AccountAuthenticationContextSourceV3:
            raise TypeError("source must be an exact authentication-context source v3")
        self.source.__post_init__()
        if type(self.recorded_by) is not AccountActorAuthorityRawSourceV3Recorder:
            raise TypeError("recorded_by must be an exact raw authority recorder")
        self.recorded_by.__post_init__()


class AccountAuthenticationContextSourceV3Repository(Protocol):
    """Persist and read immutable authentication-context versions and final heads."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the repository-owned atomic write boundary."""

        ...

    def now(self) -> datetime:
        """Return the repository's authoritative aware server clock."""

        ...

    def get_winner(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> PersistedAccountAuthenticationContextSourceV3 | None:
        """Return the immutable first winner for one source identity."""

        ...

    def get_current_head(
        self, *, source_id: str, as_of: datetime
    ) -> PersistedAccountAuthenticationContextSourceV3 | None:
        """Return the final logical head knowable at the cutoff."""

        ...

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountAuthenticationContextSourceV3 | None:
        """Return one exact historical version by identity, hash, and PIT."""

        ...

    def append(
        self,
        record: PersistedAccountAuthenticationContextSourceV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountAuthenticationContextSourceV3:
        """Append one root or successor under exact predecessor CAS."""

        ...


class GetExactAccountAuthenticationContextSourceV3:
    """Read one immutable historical version when it was knowable at the cutoff."""

    def __init__(self, repository: AccountAuthenticationContextSourceV3Repository) -> None:
        self._repository = repository

    def execute(
        self, selector: AccountActorAuthorityRawSourceV3Selector
    ) -> AccountAuthenticationContextSourceV3 | None:
        """Return the selected historical source, with no live-state fallback."""

        record = _load_exact(self._repository, selector)
        return None if record is None else record.source


class GetCurrentAccountAuthenticationContextSourceV3:
    """Return an exact version only when it is the live final ledger head."""

    def __init__(self, repository: AccountAuthenticationContextSourceV3Repository) -> None:
        self._repository = repository

    def execute(
        self, selector: AccountActorAuthorityRawSourceV3Selector
    ) -> AccountAuthenticationContextSourceV3 | None:
        """Prove exact identity, temporal validity, and final-head equality."""

        checked = _selector(selector)
        exact = _load_exact(self._repository, checked)
        if exact is None or not exact.source.is_temporally_current_at(checked.as_of):
            return None
        raw_head = self._repository.get_current_head(
            source_id=checked.source_id, as_of=checked.as_of
        )
        if raw_head is None:
            return None
        head = _record(raw_head)
        if not head.source.is_knowable_at(checked.as_of):
            raise AccountActorAuthorityRawSourceV3Corruption(
                "repository returned a future current head"
            )
        if head.source.identity.source_id != checked.source_id:
            raise AccountActorAuthorityRawSourceV3Corruption("current-head source substitution")
        if (
            head.source.identity.source_version == checked.source_version
            and head.source.content_hash != checked.expected_content_hash
        ):
            raise AccountActorAuthorityRawSourceV3Corruption("current-head hash substitution")
        if head.source == exact.source and head != exact:
            raise AccountActorAuthorityRawSourceV3Corruption("current-head recorder substitution")
        return exact.source if head == exact else None


def _load_exact(
    repository: AccountAuthenticationContextSourceV3Repository,
    selector: AccountActorAuthorityRawSourceV3Selector,
) -> PersistedAccountAuthenticationContextSourceV3 | None:
    checked = _selector(selector)
    raw = repository.get_exact_by_hash(
        source_id=checked.source_id,
        source_version=checked.source_version,
        expected_content_hash=checked.expected_content_hash,
        as_of=checked.as_of,
    )
    if raw is None:
        return None
    record = _record(raw)
    if _identity(record.source) != (
        checked.source_id,
        checked.source_version,
        checked.expected_content_hash,
    ):
        raise AccountActorAuthorityRawSourceV3Corruption("exact selector substitution")
    if not record.source.is_knowable_at(checked.as_of):
        raise AccountActorAuthorityRawSourceV3Corruption(
            "repository returned a source not knowable at the cutoff"
        )
    return record


def _selector(value: object) -> AccountActorAuthorityRawSourceV3Selector:
    if type(value) is not AccountActorAuthorityRawSourceV3Selector:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "authentication-context selector substitution"
        )
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "authentication-context selector is corrupt"
        ) from error
    return value


def _record(value: object) -> PersistedAccountAuthenticationContextSourceV3:
    if type(value) is not PersistedAccountAuthenticationContextSourceV3:
        raise AccountActorAuthorityRawSourceV3Corruption("repository record type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption("repository record is corrupt") from error
    return value


def _identity(source: AccountAuthenticationContextSourceV3) -> tuple[str, str, str]:
    return (
        source.identity.source_id,
        source.identity.source_version,
        source.content_hash,
    )


__all__ = [
    "AccountAuthenticationContextSourceV3Repository",
    "GetCurrentAccountAuthenticationContextSourceV3",
    "GetExactAccountAuthenticationContextSourceV3",
    "PersistedAccountAuthenticationContextSourceV3",
]
