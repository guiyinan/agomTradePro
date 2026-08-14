"""Pure read and persistence contracts for Account RBAC authority source v3."""

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
from apps.account.domain.account_rbac_authority_source_v3 import (
    AccountRbacAuthoritySourceV3,
)


@dataclass(frozen=True, slots=True)
class PersistedAccountRbacAuthoritySourceV3:
    """Pair one exact immutable RBAC source with its fixed service recorder."""

    source: AccountRbacAuthoritySourceV3
    recorded_by: AccountActorAuthorityRawSourceV3Recorder

    def __post_init__(self) -> None:
        """Revalidate exact domain and recorder types at the repository boundary."""

        if type(self.source) is not AccountRbacAuthoritySourceV3:
            raise TypeError("source must be an exact Account RBAC authority source v3")
        if type(self.recorded_by) is not AccountActorAuthorityRawSourceV3Recorder:
            raise TypeError("recorded_by must be an exact raw authority recorder")
        self.source.__post_init__()
        self.recorded_by.__post_init__()


class AccountRbacAuthoritySourceV3Repository(Protocol):
    """Persist immutable RBAC authority winners and their single logical chain."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the repository-owned, non-nestable unit of work."""

        ...

    def now(self) -> datetime:
        """Return the repository's authoritative aware server clock."""

        ...

    def get_winner(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> PersistedAccountRbacAuthoritySourceV3 | None:
        """Return the first recorded winner for an exact logical version."""

        ...

    def get_current_head(
        self, *, source_id: str, as_of: datetime
    ) -> PersistedAccountRbacAuthoritySourceV3 | None:
        """Return the final chain head knowable at the supplied cutoff."""

        ...

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountRbacAuthoritySourceV3 | None:
        """Return one immutable exact-hash historical version at a PIT cutoff."""

        ...

    def append(
        self,
        record: PersistedAccountRbacAuthoritySourceV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountRbacAuthoritySourceV3:
        """Append through predecessor CAS; capture orchestration is intentionally absent."""

        ...


class GetExactAccountRbacAuthoritySourceV3:
    """Read immutable RBAC authority history without TTL or final-head filtering."""

    def __init__(self, repository: AccountRbacAuthoritySourceV3Repository) -> None:
        """Store the injected repository contract."""

        self._repository = repository

    def execute(
        self, selector: AccountActorAuthorityRawSourceV3Selector
    ) -> AccountRbacAuthoritySourceV3 | None:
        """Return an exact version when it was recorded by the requested cutoff."""

        record = _load_exact(self._repository, selector)
        return None if record is None else record.source


class GetCurrentAccountRbacAuthoritySourceV3:
    """Return an exact RBAC source only when it remains the live final head."""

    def __init__(self, repository: AccountRbacAuthoritySourceV3Repository) -> None:
        """Store the injected repository contract."""

        self._repository = repository

    def execute(
        self, selector: AccountActorAuthorityRawSourceV3Selector
    ) -> AccountRbacAuthoritySourceV3 | None:
        """Verify exact history, final-head equality, and local temporal currentness."""

        exact = _load_exact(self._repository, selector)
        checked = _selector(selector)
        if exact is None or not exact.source.is_temporally_current_at(checked.as_of):
            return None
        head_raw = self._repository.get_current_head(
            source_id=checked.source_id,
            as_of=checked.as_of,
        )
        if head_raw is None:
            return None
        head = _record(head_raw)
        if not head.source.is_knowable_at(checked.as_of):
            raise AccountActorAuthorityRawSourceV3Corruption(
                "repository returned a future RBAC current head"
            )
        if head.source.identity.source_id != checked.source_id:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "RBAC final head substituted the source identity"
            )
        if head != exact:
            if (
                head.source.identity.source_id,
                head.source.identity.source_version,
            ) == (
                exact.source.identity.source_id,
                exact.source.identity.source_version,
            ):
                raise AccountActorAuthorityRawSourceV3Corruption(
                    "RBAC final head substituted an exact logical version"
                )
            return None
        return exact.source


def _load_exact(
    repository: AccountRbacAuthoritySourceV3Repository,
    selector: AccountActorAuthorityRawSourceV3Selector,
) -> PersistedAccountRbacAuthoritySourceV3 | None:
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
        raise AccountActorAuthorityRawSourceV3Corruption("RBAC exact selector substitution")
    if not source.is_knowable_at(checked.as_of):
        raise AccountActorAuthorityRawSourceV3Corruption(
            "repository returned a future RBAC authority source"
        )
    return record


def _selector(value: object) -> AccountActorAuthorityRawSourceV3Selector:
    if type(value) is not AccountActorAuthorityRawSourceV3Selector:
        raise AccountActorAuthorityRawSourceV3Corruption("RBAC selector substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption("RBAC selector is corrupt") from error
    return value


def _record(value: object) -> PersistedAccountRbacAuthoritySourceV3:
    if type(value) is not PersistedAccountRbacAuthoritySourceV3:
        raise AccountActorAuthorityRawSourceV3Corruption("RBAC repository record type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "RBAC repository record is corrupt"
        ) from error
    return value


__all__ = [
    "AccountRbacAuthoritySourceV3Repository",
    "GetCurrentAccountRbacAuthoritySourceV3",
    "GetExactAccountRbacAuthoritySourceV3",
    "PersistedAccountRbacAuthoritySourceV3",
]
