"""Dormant adapter from the strict scope-source reader to the scope grant port.

The adapter deliberately accepts only a server-issued source selector.  It does
not derive owner, tenant, account, actor, hashes, or clocks from a request or
mutable Django rows.  Until an immutable lifecycle-backed selector provider is
composed, a missing selector remains an unavailable scope rather than a
permissive fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.application.evidence_scope import (
    EvidenceScopeCorruption,
    EvidenceScopeGrant,
    EvidenceScopeProvider,
    EvidenceScopeUnavailable,
)
from apps.research.application.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1Corruption,
    EvidenceScopeSourceV1Unavailable,
    GetCurrentEvidenceScopeSourceV1,
    GetCurrentEvidenceScopeSourceV1Command,
)
from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.domain.evidence_scope_source_v1 import EvidenceScopeSourceV1


@dataclass(frozen=True, slots=True)
class EvidenceScopeSourceV1Selector:
    """Server-issued exact source identity used for one artifact lookup."""

    source_id: str
    source_version: str
    expected_content_hash: str

    def __post_init__(self) -> None:
        _token(self.source_id, "source_id")
        _token(self.source_version, "source_version")
        _digest(self.expected_content_hash, "expected_content_hash")


class EvidenceScopeSourceV1SelectorProvider(Protocol):
    """Resolve a selector from an immutable authority source, never a request."""

    def get_selector(
        self, *, artifact: ArtifactRef, as_of: datetime
    ) -> EvidenceScopeSourceV1Selector | None:
        """Return the exact server-issued selector or ``None`` when unavailable."""


class EvidenceScopeSourceV1CurrentReader(Protocol):
    """Application reader port for one exact/current source candidate."""

    def execute(
        self, command: GetCurrentEvidenceScopeSourceV1Command
    ) -> EvidenceScopeSourceV1 | None:
        """Return the final current source, or ``None`` without predecessor fallback."""


class EvidenceScopeSourceV1Provider(EvidenceScopeProvider):
    """Map a trusted current source to the existing fail-closed scope grant."""

    __slots__ = ("_reader", "_selectors")

    def __init__(
        self,
        *,
        reader: EvidenceScopeSourceV1CurrentReader | GetCurrentEvidenceScopeSourceV1,
        selectors: EvidenceScopeSourceV1SelectorProvider,
    ) -> None:
        self._reader = reader
        self._selectors = selectors

    def get_current_scope(
        self,
        *,
        artifact: ArtifactRef,
        as_of: datetime,
    ) -> EvidenceScopeGrant | None:
        """Return one exact active grant without any mutable-row fallback."""

        if type(artifact) is not ArtifactRef:
            raise TypeError("artifact must be an exact ArtifactRef")
        _aware(as_of, "as_of")
        try:
            selector = self._selectors.get_selector(artifact=artifact, as_of=as_of)
        except EvidenceScopeSourceV1Unavailable as error:
            raise EvidenceScopeUnavailable("scope selector is unavailable") from error
        except EvidenceScopeSourceV1Corruption as error:
            raise EvidenceScopeCorruption("scope selector is corrupt") from error
        except (TypeError, ValueError) as error:
            raise EvidenceScopeCorruption(
                "scope selector provider returned invalid data"
            ) from error
        except Exception:
            # A concrete selector source may call User/RBAC/tenant storage.
            # Keep infrastructure failures opaque and fail closed as an
            # unavailable authority rather than widening the read scope.
            raise EvidenceScopeUnavailable("scope selector is unavailable") from None
        if selector is None:
            return None
        if type(selector) is not EvidenceScopeSourceV1Selector:
            raise EvidenceScopeCorruption("scope selector provider returned an invalid type")
        try:
            selector.__post_init__()
            source = self._reader.execute(
                GetCurrentEvidenceScopeSourceV1Command(
                    source_id=selector.source_id,
                    source_version=selector.source_version,
                    expected_content_hash=selector.expected_content_hash,
                    as_of=as_of,
                )
            )
        except EvidenceScopeSourceV1Unavailable as error:
            raise EvidenceScopeUnavailable("scope source is unavailable") from error
        except EvidenceScopeSourceV1Corruption as error:
            raise EvidenceScopeCorruption("scope source is corrupt") from error
        except (TypeError, ValueError) as error:
            raise EvidenceScopeCorruption("scope source selector is invalid") from error
        except Exception:
            # Do not expose database/provider details through this boundary.
            raise EvidenceScopeUnavailable("scope source is unavailable") from None
        if source is None:
            return None
        if type(source) is not EvidenceScopeSourceV1:
            raise EvidenceScopeCorruption("scope source reader returned an invalid type")
        try:
            source.__post_init__()
        except (TypeError, ValueError, AttributeError) as error:
            raise EvidenceScopeCorruption(
                "scope source reader returned corrupt evidence"
            ) from error
        if (
            source.source_id,
            source.source_version,
            source.content_hash,
        ) != (
            selector.source_id,
            selector.source_version,
            selector.expected_content_hash,
        ):
            raise EvidenceScopeCorruption("scope source selector substitution")
        if source.artifact != artifact:
            raise EvidenceScopeCorruption("scope source artifact substitution")
        if not source.is_temporally_current_at(as_of):
            return None
        try:
            return EvidenceScopeGrant(
                scope_id=source.source_id,
                scope_version=source.source_version,
                actor_id=source.actor_id,
                owner_id=source.owner_id,
                tenant_id=source.tenant_id,
                account_id=source.account_id,
                artifact=source.artifact,
                status=source.status,
                permission=source.permission,
                recorded_at=source.recorded_at,
                valid_until=source.valid_until,
                # EvidenceScopeGrant has its own canonical projection hash;
                # the source hash is already bound by the exact selector and
                # is intentionally not confused with the grant hash.
                content_hash="",
            )
        except (TypeError, ValueError, AttributeError) as error:
            raise EvidenceScopeCorruption("scope grant projection is invalid") from error


def _token(value: object, label: str) -> None:
    if (
        type(value) is not str
        or not value
        or len(value) > 192
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} must be a bounded canonical token")


def _digest(value: object, label: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _aware(value: object, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


__all__ = [
    "EvidenceScopeSourceV1CurrentReader",
    "EvidenceScopeSourceV1Provider",
    "EvidenceScopeSourceV1Selector",
    "EvidenceScopeSourceV1SelectorProvider",
]
