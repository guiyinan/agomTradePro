"""Explicit reference-only price-limit publication management use cases."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from apps.data_center.application.price_limit_publication_authority import (
    PRICE_LIMIT_PUBLISH_PERMISSION_CODENAME,
    LockedPriceLimitPublisherPrincipal,
)
from apps.data_center.domain.formal_price_limit_publication import (
    PriceLimitFormalPublicationRecord,
    PriceLimitFormalPublicationSeal,
    PriceLimitPublicationPointerExpectation,
)
from apps.data_center.domain.price_limit_snapshot import (
    PriceLimitSnapshot,
    price_limit_request_scope_hash,
)
from core.exceptions import AuthorizationError, InvalidInputError


def require_utc(value: datetime) -> None:
    """Reject naive, non-UTC, or substituted operation clocks."""
    if type(value) is not datetime or value.utcoffset() != timedelta(0):
        raise InvalidInputError("An aware UTC time is required", code="PRICE_LIMIT_TIME_INVALID")


def require_uuid(value: str) -> None:
    """Require canonical UUID text without coercing arbitrary input."""
    try:
        valid = type(value) is str and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise InvalidInputError("A canonical UUID is required", code="PRICE_LIMIT_ID_INVALID")


@dataclass(frozen=True, slots=True)
class PriceLimitPublicationScope:
    """A complete provider/security/effective-date scope, never a client key."""

    provider_id: int
    provider_name: str
    asset_code: str
    effective_trade_date: date

    def __post_init__(self) -> None:
        """Validate scope using the original exact-request contract."""
        self.request_scope_hash()

    def request_scope_hash(self) -> str:
        """Rebuild the original full request digest without accepting arbitrary keys."""
        return price_limit_request_scope_hash(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            asset_code=self.asset_code,
            effective_trade_date=self.effective_trade_date,
        )

    @property
    def publication_key(self) -> str:
        """Return this one request's server-derived publication key."""
        return f"price-limit:{self.request_scope_hash()}"


class PriceLimitPublicationAction(StrEnum):
    """The two explicitly confirmed pointer mutations."""

    PUBLISH = "publish"
    ROLLBACK = "rollback"


@dataclass(frozen=True, slots=True)
class PreviewPriceLimitPublicationIntent:
    """Select an exact saved fact or previously published rollback target."""

    scope: PriceLimitPublicationScope
    action: PriceLimitPublicationAction
    snapshot_id: str | None = None
    target_publication_id: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        """Reject mixed actions or missing exact source identities."""
        if type(self.scope) is not PriceLimitPublicationScope:
            raise InvalidInputError("Explicit scope required", code="PRICE_LIMIT_SCOPE_INVALID")
        self.scope.__post_init__()
        if type(self.action) is not PriceLimitPublicationAction:
            raise InvalidInputError("Unknown action", code="PRICE_LIMIT_ACTION_INVALID")
        if self.action is PriceLimitPublicationAction.PUBLISH:
            if self.snapshot_id is None or self.target_publication_id is not None or self.reason:
                raise InvalidInputError(
                    "Select one saved snapshot", code="PRICE_LIMIT_INTENT_INVALID"
                )
            require_uuid(self.snapshot_id)
        else:
            if self.snapshot_id is not None or self.target_publication_id is None:
                raise InvalidInputError(
                    "Select one rollback target", code="PRICE_LIMIT_INTENT_INVALID"
                )
            require_uuid(self.target_publication_id)
            if (
                type(self.reason) is not str
                or not self.reason.strip()
                or self.reason != self.reason.strip()
                or len(self.reason) > 1000
                or any(ord(character) < 32 for character in self.reason)
            ):
                raise InvalidInputError(
                    "A rollback reason is required", code="PRICE_LIMIT_REASON_INVALID"
                )


@dataclass(frozen=True, slots=True)
class PriceLimitPublicationPreparation:
    """Exact persisted evidence and the current complete pointer expectation."""

    seal: PriceLimitFormalPublicationSeal
    current_pointer: PriceLimitPublicationPointerExpectation


@dataclass(frozen=True, slots=True)
class PriceLimitPublicationPreview:
    """Server-minted, actor-bound intent; transport must authenticate its signature."""

    intent: PreviewPriceLimitPublicationIntent
    publication_hash: str
    expected_pointer: PriceLimitPublicationPointerExpectation
    operation_id: str
    actor_id: str
    previewed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        """Reject incomplete or scope-substituted confirmation evidence."""
        if type(self.intent) is not PreviewPriceLimitPublicationIntent:
            raise InvalidInputError("Typed intent required", code="PRICE_LIMIT_PREVIEW_INVALID")
        self.intent.__post_init__()
        require_uuid(self.operation_id)
        require_utc(self.previewed_at)
        require_utc(self.expires_at)
        if (
            type(self.publication_hash) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.publication_hash) is None
            or type(self.actor_id) is not str
            or re.fullmatch(r"django-user:[1-9][0-9]*", self.actor_id) is None
            or self.expires_at <= self.previewed_at
            or type(self.expected_pointer) is not PriceLimitPublicationPointerExpectation
            or self.expected_pointer.dataset_key != "equity.price.limit"
            or self.expected_pointer.publication_key != self.intent.scope.publication_key
        ):
            raise InvalidInputError(
                "Preview evidence is inconsistent", code="PRICE_LIMIT_PREVIEW_INVALID"
            )
        self.expected_pointer.__post_init__()


@dataclass(frozen=True, slots=True)
class PriceLimitPublicationPreviewResult:
    """A read-only preview and its original exact source values."""

    preview: PriceLimitPublicationPreview
    snapshot: PriceLimitSnapshot


@dataclass(frozen=True, slots=True)
class PriceLimitPublicationReceipt:
    """One verified reference publication transition or its exact replay."""

    record: PriceLimitFormalPublicationRecord
    pointer: PriceLimitPublicationPointerExpectation
    operation_id: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class ReadPriceLimitPublicationIntent:
    """Read the current scope, its historical winner, or one exact publication."""

    scope: PriceLimitPublicationScope
    as_of: datetime | None = None
    publication_id: str | None = None

    def __post_init__(self) -> None:
        """Keep lookup identity separate from the knowledge cutoff."""
        if type(self.scope) is not PriceLimitPublicationScope:
            raise InvalidInputError("Explicit scope required", code="PRICE_LIMIT_SCOPE_INVALID")
        self.scope.__post_init__()
        if self.as_of is not None:
            require_utc(self.as_of)
        if self.publication_id is not None:
            require_uuid(self.publication_id)


@dataclass(frozen=True, slots=True)
class PriceLimitPublicationReadResult:
    """Selected reference and its known visible start, distinct from first publication."""

    record: PriceLimitFormalPublicationRecord
    as_of: datetime
    visible_from: datetime | None
    lookup_basis: Literal["visible_at_cutoff", "exact_identity"]


class PriceLimitPublicationOperationsPort(Protocol):
    """Own exact source replay, current catalog, CAS, and atomic Audit persistence."""

    def prepare(
        self,
        intent: PreviewPriceLimitPublicationIntent,
        *,
        principal: LockedPriceLimitPublisherPrincipal,
        server_now: datetime,
    ) -> PriceLimitPublicationPreparation:
        """Rebuild exact evidence while holding the scope and authority fences."""

    def confirm(
        self,
        preview: PriceLimitPublicationPreview,
        *,
        principal: LockedPriceLimitPublisherPrincipal,
        server_now: datetime,
    ) -> PriceLimitPublicationReceipt:
        """Revalidate and atomically publish/rollback or verify the original replay."""

    def read(
        self,
        intent: ReadPriceLimitPublicationIntent,
        *,
        principal: LockedPriceLimitPublisherPrincipal,
        server_now: datetime,
    ) -> PriceLimitPublicationReadResult | None:
        """Verify the complete current chain before resolving the requested point."""


def _check_principal(principal: LockedPriceLimitPublisherPrincipal, now: datetime) -> None:
    """Reject a different capability even if a caller supplies a structural Protocol."""
    require_utc(now)
    principal.assert_live()
    if (
        principal.permission_codename != PRICE_LIMIT_PUBLISH_PERMISSION_CODENAME
        or principal.actor_type != "django_user"
        or principal.actor_id != f"django-user:{principal.user_id}"
        or now < principal.verified_at
        or now >= principal.session_expires_at
    ):
        raise AuthorizationError(
            "Publisher lease unavailable", code="PRICE_LIMIT_AUTHORITY_INVALID"
        )


class PreviewPriceLimitPublicationUseCase:
    """Prepare an exact intent without creating a publication or changing a pointer."""

    def __init__(
        self,
        repository: PriceLimitPublicationOperationsPort,
        *,
        clock: Callable[[], datetime],
        operation_ids: Callable[[], str],
    ) -> None:
        """Inject persistence, the server clock and server operation identities."""
        self._repository = repository
        self._clock = clock
        self._operation_ids = operation_ids

    def execute(
        self,
        intent: PreviewPriceLimitPublicationIntent,
        *,
        principal: LockedPriceLimitPublisherPrincipal,
    ) -> PriceLimitPublicationPreviewResult:
        """Bind the preview to the current session expiry without refreshing source time."""
        intent.__post_init__()
        now = self._clock()
        _check_principal(principal, now)
        prepared = self._repository.prepare(intent, principal=principal, server_now=now)
        prepared.seal.validate()
        if (
            prepared.seal.publication_key != intent.scope.publication_key
            or prepared.seal.recorded_at > now
            or prepared.seal.response_completed_at > now
            or (
                intent.action is PriceLimitPublicationAction.PUBLISH
                and prepared.seal.snapshot.snapshot_id != intent.snapshot_id
            )
        ):
            raise InvalidInputError(
                "Prepared source differs from intent", code="PRICE_LIMIT_PREPARATION_MISMATCH"
            )
        preview = PriceLimitPublicationPreview(
            intent=intent,
            publication_hash=prepared.seal.publication_hash,
            expected_pointer=prepared.current_pointer,
            operation_id=self._operation_ids(),
            actor_id=principal.actor_id,
            previewed_at=now,
            expires_at=principal.session_expires_at,
        )
        principal.assert_live()
        return PriceLimitPublicationPreviewResult(preview, prepared.seal.snapshot)


class ConfirmPriceLimitPublicationUseCase:
    """Confirm one authentic preview using the current publisher permission."""

    def __init__(
        self, repository: PriceLimitPublicationOperationsPort, *, clock: Callable[[], datetime]
    ) -> None:
        """Inject the atomic writer and actual server clock."""
        self._repository = repository
        self._clock = clock

    def execute(
        self,
        preview: PriceLimitPublicationPreview,
        *,
        principal: LockedPriceLimitPublisherPrincipal,
    ) -> PriceLimitPublicationReceipt:
        """Reject another actor, future preview, or expired confirmation before persistence."""
        preview.__post_init__()
        now = self._clock()
        _check_principal(principal, now)
        if preview.actor_id != principal.actor_id:
            raise AuthorizationError(
                "Preview belongs to another actor", code="PRICE_LIMIT_PREVIEW_ACTOR_MISMATCH"
            )
        if now < preview.previewed_at or now >= preview.expires_at:
            raise InvalidInputError(
                "Preview expired or future-dated",
                code="PRICE_LIMIT_PREVIEW_EXPIRED",
                status_code=409,
            )
        result = self._repository.confirm(preview, principal=principal, server_now=now)
        result.record.validate()
        result.pointer.validate()
        if (
            result.record.publication_hash != preview.publication_hash
            or result.operation_id != preview.operation_id
            or result.pointer.publication_id != result.record.publication_id
            or result.pointer.publication_hash != result.record.publication_hash
            or result.pointer.activation_id != preview.operation_id
            or result.pointer.publication_key != preview.intent.scope.publication_key
        ):
            raise InvalidInputError(
                "Publication receipt differs from preview", code="PRICE_LIMIT_RECEIPT_MISMATCH"
            )
        principal.assert_live()
        if self._clock() >= preview.expires_at:
            raise InvalidInputError(
                "Preview expired before commit", code="PRICE_LIMIT_PREVIEW_EXPIRED", status_code=409
            )
        return result


class ReadPriceLimitPublicationUseCase:
    """Read reference evidence under current authorization and explicit knowledge time."""

    def __init__(
        self, repository: PriceLimitPublicationOperationsPort, *, clock: Callable[[], datetime]
    ) -> None:
        """Inject the exact reader and actual server clock."""
        self._repository = repository
        self._clock = clock

    def execute(
        self,
        intent: ReadPriceLimitPublicationIntent,
        *,
        principal: LockedPriceLimitPublisherPrincipal,
    ) -> PriceLimitPublicationReadResult | None:
        """Refuse future cutoffs, then verify the entire chain and requested member."""
        intent.__post_init__()
        now = self._clock()
        _check_principal(principal, now)
        if intent.as_of is not None and intent.as_of > now:
            raise InvalidInputError("Future cutoff unavailable", code="PRICE_LIMIT_FUTURE_CUTOFF")
        result = self._repository.read(intent, principal=principal, server_now=now)
        principal.assert_live()
        return result
