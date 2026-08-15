"""Dormant exact/current Application readers for Evidence scope source v1.

The repository port is intentionally read-only here.  A future Infrastructure
implementation must restore the complete ledger before applying selectors; it
must return the final logical head, including terminal or expired rows, rather
than falling back to an earlier active row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.evidence_scope_source_v1 import EvidenceScopeSourceV1


class EvidenceScopeSourceV1Unavailable(RuntimeError):
    """The requested exact/current scope source cannot be proven."""


class EvidenceScopeSourceV1Corruption(RuntimeError):
    """A repository returned substituted or malformed scope evidence."""


def _token(value: object, name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a canonical token")


def _digest(value: object, name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _aware(value: object, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class GetExactEvidenceScopeSourceV1Command:
    """Select one source version by immutable identity and content hash."""

    source_id: str
    source_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.source_id, "source_id")
        _token(self.source_version, "source_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentEvidenceScopeSourceV1Command:
    """Select one source only when it is the final current chain head."""

    source_id: str
    source_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        GetExactEvidenceScopeSourceV1Command(
            source_id=self.source_id,
            source_version=self.source_version,
            expected_content_hash=self.expected_content_hash,
            as_of=self.as_of,
        )


class EvidenceScopeSourceV1Repository(Protocol):
    """Read port for a full-world-restored scope-source ledger.

    ``get_current_head`` must return the final logical head even when it is
    revoked or expired.  It must never filter a terminal row and resurrect an
    earlier active predecessor.
    """

    def get_exact(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceScopeSourceV1 | None:
        """Return one exact knowable row, or None when not knowable."""

    def get_current_head(
        self,
        *,
        source_id: str,
        as_of: datetime,
    ) -> EvidenceScopeSourceV1 | None:
        """Return the final head for this source chain at the cutoff."""


class GetExactEvidenceScopeSourceV1:
    """Read one historical source without applying its validity window."""

    __slots__ = ("_repository",)

    def __init__(self, repository: EvidenceScopeSourceV1Repository) -> None:
        self._repository = repository

    def execute(
        self, command: GetExactEvidenceScopeSourceV1Command
    ) -> EvidenceScopeSourceV1 | None:
        """Return the exact source after selector and PIT revalidation."""

        if type(command) is not GetExactEvidenceScopeSourceV1Command:
            raise TypeError("command must be an exact source command")
        command.__post_init__()
        raw = self._repository.get_exact(
            source_id=command.source_id,
            source_version=command.source_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if raw is None:
            return None
        source = _restore(raw)
        if source.recorded_at > command.as_of:
            raise EvidenceScopeSourceV1Corruption("repository returned a future source")
        if (
            source.source_id != command.source_id
            or source.source_version != command.source_version
            or source.content_hash != command.expected_content_hash
        ):
            raise EvidenceScopeSourceV1Corruption("exact source selector substitution")
        return source


class GetCurrentEvidenceScopeSourceV1:
    """Read a source only when its exact row is the final temporal head."""

    __slots__ = ("_repository", "_exact")

    def __init__(self, repository: EvidenceScopeSourceV1Repository) -> None:
        self._repository = repository
        self._exact = GetExactEvidenceScopeSourceV1(repository)

    def execute(
        self, command: GetCurrentEvidenceScopeSourceV1Command
    ) -> EvidenceScopeSourceV1 | None:
        """Return current source or None without predecessor fallback."""

        if type(command) is not GetCurrentEvidenceScopeSourceV1Command:
            raise TypeError("command must be an exact current source command")
        command.__post_init__()
        source = self._exact.execute(
            GetExactEvidenceScopeSourceV1Command(
                source_id=command.source_id,
                source_version=command.source_version,
                expected_content_hash=command.expected_content_hash,
                as_of=command.as_of,
            )
        )
        if source is None or not source.is_temporally_current_at(command.as_of):
            return None
        raw_head = self._repository.get_current_head(
            source_id=command.source_id,
            as_of=command.as_of,
        )
        if raw_head is None:
            return None
        head = _restore(raw_head)
        if head.recorded_at > command.as_of:
            raise EvidenceScopeSourceV1Corruption("repository returned a future head")
        if not _same_scope_identity(source, head):
            raise EvidenceScopeSourceV1Corruption("current head scope identity substitution")
        if head != source:
            return None
        return source


def _restore(value: object) -> EvidenceScopeSourceV1:
    if type(value) is not EvidenceScopeSourceV1:
        raise EvidenceScopeSourceV1Corruption("repository returned an invalid source type")
    source = value
    try:
        _digest(source.identity_hash, "identity_hash")
        _digest(source.content_hash, "content_hash")
        source.__post_init__()
    except (TypeError, ValueError, AttributeError) as error:
        raise EvidenceScopeSourceV1Corruption("repository returned a corrupt source") from error
    return source


def _same_scope_identity(left: EvidenceScopeSourceV1, right: EvidenceScopeSourceV1) -> bool:
    return (
        left.source_id == right.source_id
        and left.owner_id == right.owner_id
        and left.tenant_id == right.tenant_id
        and left.account_id == right.account_id
        and left.actor_id == right.actor_id
        and left.artifact == right.artifact
    )


__all__ = [
    "EvidenceScopeSourceV1Corruption",
    "EvidenceScopeSourceV1Repository",
    "EvidenceScopeSourceV1Unavailable",
    "GetCurrentEvidenceScopeSourceV1",
    "GetCurrentEvidenceScopeSourceV1Command",
    "GetExactEvidenceScopeSourceV1",
    "GetExactEvidenceScopeSourceV1Command",
]
