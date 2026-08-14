"""Pure Application read contracts for Account user-authority raw source v3."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Conflict,
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Recorder,
    AccountActorAuthorityRawSourceV3Selector,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.domain.account_user_authority_source_v3 import (
    AccountUserAuthoritySourceV3,
)


@dataclass(frozen=True, slots=True)
class PersistedAccountUserAuthoritySourceV3:
    """Bind one exact Domain source to its fixed historical service recorder."""

    source: AccountUserAuthoritySourceV3
    recorded_by: AccountActorAuthorityRawSourceV3Recorder

    def __post_init__(self) -> None:
        """Reject source or recorder type substitution and revalidate both values."""

        if type(self.source) is not AccountUserAuthoritySourceV3:
            raise TypeError("source must be an exact account user-authority source v3")
        if type(self.recorded_by) is not AccountActorAuthorityRawSourceV3Recorder:
            raise TypeError("recorded_by must be an exact raw-authority recorder")
        self.source.__post_init__()
        self.recorded_by.__post_init__()


class AccountUserAuthoritySourceV3Repository(Protocol):
    """Persist immutable user-authority winners and single-root logical chains."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the repository's private atomic write boundary."""

        ...

    def now(self) -> datetime:
        """Return the repository decision clock."""

        ...

    def get_winner(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> PersistedAccountUserAuthoritySourceV3 | None:
        """Return the immutable first winner for one source identity."""

        ...

    def get_current_head(
        self, *, source_id: str, as_of: datetime
    ) -> PersistedAccountUserAuthoritySourceV3 | None:
        """Return the final logical head knowable at the cutoff."""

        ...

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountUserAuthoritySourceV3 | None:
        """Return one exact permanent version after its knowledge cutoff."""

        ...

    def append(
        self,
        record: PersistedAccountUserAuthoritySourceV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountUserAuthoritySourceV3:
        """Append one exact root or successor under predecessor CAS."""

        ...


class GetExactAccountUserAuthoritySourceV3:
    """Read one exact immutable user-authority version at a PIT cutoff."""

    def __init__(self, repository: AccountUserAuthoritySourceV3Repository) -> None:
        self._repository = repository

    def execute(
        self, selector: AccountActorAuthorityRawSourceV3Selector
    ) -> AccountUserAuthoritySourceV3 | None:
        """Return exact historical evidence permanently after it becomes knowable."""

        record = _load_exact(self._repository, selector)
        return None if record is None else record.source


class GetCurrentAccountUserAuthoritySourceV3:
    """Return an exact user-authority version only when it is the live final head."""

    def __init__(self, repository: AccountUserAuthoritySourceV3Repository) -> None:
        self._repository = repository

    def execute(
        self, selector: AccountActorAuthorityRawSourceV3Selector
    ) -> AccountUserAuthoritySourceV3 | None:
        """Reject terminal, expired, or superseded versions without predecessor fallback."""

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
                "repository returned a future user-authority head"
            )
        if head.source.identity.source_id != checked.source_id:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "user-authority current-head source substitution"
            )
        if (
            head.source.identity.source_version == checked.source_version
            and head.source.content_hash != checked.expected_content_hash
        ):
            raise AccountActorAuthorityRawSourceV3Corruption(
                "user-authority current-head hash substitution"
            )
        if head.source == exact.source and head != exact:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "user-authority current-head recorder substitution"
            )
        return exact.source if head == exact else None


def _load_exact(
    repository: AccountUserAuthoritySourceV3Repository,
    selector: AccountActorAuthorityRawSourceV3Selector,
) -> PersistedAccountUserAuthoritySourceV3 | None:
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
    source = record.source
    if (
        source.identity.source_id,
        source.identity.source_version,
        source.content_hash,
    ) != (
        checked.source_id,
        checked.source_version,
        checked.expected_content_hash,
    ):
        raise AccountActorAuthorityRawSourceV3Corruption(
            "exact user-authority selector was substituted"
        )
    if not source.is_knowable_at(checked.as_of):
        raise AccountActorAuthorityRawSourceV3Corruption(
            "repository returned a future user-authority source"
        )
    return record


def _selector(value: object) -> AccountActorAuthorityRawSourceV3Selector:
    if type(value) is not AccountActorAuthorityRawSourceV3Selector:
        raise AccountActorAuthorityRawSourceV3Corruption("user-authority selector substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "user-authority selector is corrupt"
        ) from error
    return value


def _record(value: object) -> PersistedAccountUserAuthoritySourceV3:
    if type(value) is not PersistedAccountUserAuthoritySourceV3:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "user-authority repository record substitution"
        )
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "user-authority repository record is corrupt"
        ) from error
    return value


__all__ = [
    "AccountActorAuthorityRawSourceV3Conflict",
    "AccountActorAuthorityRawSourceV3Corruption",
    "AccountActorAuthorityRawSourceV3Unavailable",
    "AccountUserAuthoritySourceV3Repository",
    "GetCurrentAccountUserAuthoritySourceV3",
    "GetExactAccountUserAuthoritySourceV3",
    "PersistedAccountUserAuthoritySourceV3",
]
