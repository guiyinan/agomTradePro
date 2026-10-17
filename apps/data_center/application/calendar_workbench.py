"""Request-bound Application orchestration for calendar preview tokens.

This module has no Django or persistence dependency. The supplied session proof
is only an actor/session claim: the request-bound composition must pass it to the
existing owner authorization gateways, which revalidate the live session and
permission under their locks. This workbench never grants publication rights.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from apps.data_center.application.calendar_preview_token import (
    CALENDAR_PREVIEW_DATABASE_ALIAS,
    CalendarPreviewTokenCodec,
    CalendarPreviewTokenContent,
    CalendarPreviewTokenError,
)
from apps.data_center.application.calendar_publication_authority import (
    CalendarPublisherSessionRequestProof,
)
from apps.data_center.application.calendar_publication_operations import (
    CalendarOperationsClock,
    CalendarPublicationOperationsError,
    CalendarPublicationPreview,
    CapturedExchangeCalendarSnapshot,
    CaptureExchangeCalendarSnapshotIntent,
    ConfirmCalendarPublicationIntent,
    PreviewCalendarPublicationIntent,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationCommit,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    exchange_calendar_publication_key,
)


class CalendarWorkbenchCapturePort(Protocol):
    """Capture source evidence through a request-bound owner composition."""

    def execute(
        self,
        intent: CaptureExchangeCalendarSnapshotIntent,
        *,
        proof: CalendarPublisherSessionRequestProof,
    ) -> CapturedExchangeCalendarSnapshot:
        """Return the exact captured reference and its original source clocks."""


class CalendarWorkbenchPreviewPort(Protocol):
    """Create a preview through a request-bound publisher-authority gateway."""

    def execute(
        self,
        intent: PreviewCalendarPublicationIntent,
        *,
        proof: CalendarPublisherSessionRequestProof,
    ) -> CalendarPublicationPreview:
        """Return the exact catalog, CAS and source-bound publication preview."""


class CalendarWorkbenchConfirmationPort(Protocol):
    """Confirm an original preview intent through the existing owner use case."""

    def execute(
        self,
        intent: ConfirmCalendarPublicationIntent,
        *,
        proof: CalendarPublisherSessionRequestProof,
    ) -> CalendarFormalPublicationCommit:
        """Publish or replay exactly the decoded intent under current authority."""


@dataclass(frozen=True, slots=True)
class CalendarWorkbenchPreview:
    """Captured reference and preview plus a nonempty opaque echo token.

    The token is intentionally omitted from ``repr``. Capture and preview are
    separate operations, so a successful capture may remain stored if a later
    preview or token-encoding step fails; this DTO makes no atomicity claim.
    """

    captured: CapturedExchangeCalendarSnapshot
    preview: CalendarPublicationPreview
    confirmation_token: str = field(repr=False)

    def __post_init__(self) -> None:
        """Require validated exact DTOs and a bounded nonempty opaque token."""

        if type(self.captured) is not CapturedExchangeCalendarSnapshot:
            raise CalendarPublicationOperationsError(
                "Workbench preview has no exact capture receipt",
                code="CALENDAR_WORKBENCH_RESULT_INVALID",
            )
        if type(self.preview) is not CalendarPublicationPreview:
            raise CalendarPublicationOperationsError(
                "Workbench preview has no exact publication preview",
                code="CALENDAR_WORKBENCH_RESULT_INVALID",
            )
        self.captured.__post_init__()
        self.preview.__post_init__()
        if (
            type(self.confirmation_token) is not str
            or not self.confirmation_token
            or self.confirmation_token.strip() != self.confirmation_token
        ):
            raise CalendarPreviewTokenError(
                "Preview token codec returned no opaque token",
                code="CALENDAR_PREVIEW_TOKEN_INVALID",
            )
        _validate_capture_preview_binding(self.captured, self.preview)
        _validate_preview_scope(self.preview)


class CalendarPublicationWorkbench:
    """Coordinate exact capture, preview, opaque confirmation and publication.

    ``proof`` carries request identity into the composed owner gateways. It is
    not itself an authenticated session or publication authorization. The
    composition must bind these calls to the original request and hold the
    owner-provided authority lease around confirmation until its outer
    transaction exits successfully.
    """

    def __init__(
        self,
        *,
        capture: CalendarWorkbenchCapturePort,
        preview: CalendarWorkbenchPreviewPort,
        confirmation: CalendarWorkbenchConfirmationPort,
        token_codec: CalendarPreviewTokenCodec,
        clock: CalendarOperationsClock,
    ) -> None:
        """Bind only explicit ports; no provider, clock, or storage is defaulted."""

        self._capture = capture
        self._preview = preview
        self._confirmation = confirmation
        self._token_codec = token_codec
        self._clock = clock

    def prepare_preview(
        self,
        intent: CaptureExchangeCalendarSnapshotIntent,
        *,
        proof: CalendarPublisherSessionRequestProof,
    ) -> CalendarWorkbenchPreview:
        """Capture, preview and encode one exact echo without publishing.

        The opaque token binds the original catalog identity, complete pointer
        expectation, activation, source clocks and response-age expiry. Any
        failure after capture may leave that immutable source snapshot available
        for a later explicit request.
        """

        _validate_capture_intent(intent)
        _validate_proof(proof)
        preflight_now = _read_server_clock(self._clock)
        _ensure_clock_after_request(preflight_now, proof)
        captured = self._capture.execute(intent, proof=proof)
        if type(captured) is not CapturedExchangeCalendarSnapshot:
            raise CalendarPublicationOperationsError(
                "Capture gateway returned an invalid result type",
                code="CALENDAR_WORKBENCH_CAPTURE_INVALID",
            )
        try:
            captured.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise CalendarPublicationOperationsError(
                "Capture gateway returned invalid source evidence",
                code="CALENDAR_WORKBENCH_CAPTURE_INVALID",
            ) from error
        reference = captured.snapshot_reference
        if (
            reference.exchange != intent.exchange
            or reference.coverage_start != intent.coverage_start
            or reference.coverage_end != intent.coverage_end
        ):
            raise CalendarPublicationOperationsError(
                "Captured source differs from the requested exchange or date range",
                code="CALENDAR_WORKBENCH_CAPTURE_SCOPE_MISMATCH",
            )

        preview_intent = PreviewCalendarPublicationIntent(reference)
        preview = self._preview.execute(preview_intent, proof=proof)
        if type(preview) is not CalendarPublicationPreview:
            raise CalendarPublicationOperationsError(
                "Preview gateway returned an invalid result type",
                code="CALENDAR_WORKBENCH_PREVIEW_INVALID",
            )
        try:
            preview.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise CalendarPublicationOperationsError(
                "Preview gateway returned invalid confirmation evidence",
                code="CALENDAR_WORKBENCH_PREVIEW_INVALID",
            ) from error
        _validate_capture_preview_binding(captured, preview)
        if preview.previewed_at < proof.request_authenticated_at:
            raise CalendarPublicationOperationsError(
                "Preview knowledge time predates authenticated request context",
                code="CALENDAR_WORKBENCH_PREVIEW_CLOCK_INVALID",
            )
        _validate_preview_scope(preview)

        now = _read_server_clock(self._clock)
        _ensure_clock_after_request(now, proof)
        if now < preview.previewed_at:
            raise CalendarPreviewTokenError(
                "Server clock precedes the supplied preview knowledge time",
                code="CALENDAR_PREVIEW_TOKEN_CLOCK_INVALID",
            )
        if now >= preview.response_expires_at:
            raise CalendarPreviewTokenError(
                "Source response-age window expired before token creation",
                code="CALENDAR_PREVIEW_TOKEN_EXPIRED",
            )
        content = CalendarPreviewTokenContent.from_preview(
            preview,
            actor_user_id=proof.user_id,
            session_key_sha256=_session_key_digest(proof),
        )
        token = self._token_codec.encode(content)
        result = CalendarWorkbenchPreview(
            captured=captured,
            preview=preview,
            confirmation_token=token,
        )
        result.__post_init__()
        return result

    def confirm(
        self,
        token: str,
        *,
        proof: CalendarPublisherSessionRequestProof,
    ) -> CalendarFormalPublicationCommit:
        """Decode and submit the original intent without refreshing any evidence.

        Confirmation performs no capture or preview call. The injected gateway
        must revalidate the request's live owner authorization and execute inside
        the authority-owned outer transaction. Returning this commit from the
        workbench does not mean that outer transaction has committed.
        """

        _validate_proof(proof)
        if type(token) is not str or not token or token.strip() != token:
            raise CalendarPreviewTokenError(
                "Preview confirmation token is empty or malformed",
                code="CALENDAR_PREVIEW_TOKEN_INVALID",
            )
        now = _read_server_clock(self._clock)
        _ensure_clock_after_request(now, proof)
        digest = _session_key_digest(proof)
        content = self._token_codec.decode(
            token,
            actor_user_id=proof.user_id,
            session_key_sha256=digest,
            database_alias=proof.database_alias,
            now=now,
        )
        if type(content) is not CalendarPreviewTokenContent:
            raise CalendarPreviewTokenError(
                "Preview token codec returned an invalid content type",
                code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
            )
        content.validate()
        if (
            content.actor_user_id != proof.user_id
            or content.session_key_sha256 != digest
            or content.database_alias != proof.database_alias
        ):
            raise CalendarPreviewTokenError(
                "Preview token content is bound to another request identity",
                code="CALENDAR_PREVIEW_TOKEN_BINDING_MISMATCH",
            )
        if now < content.previewed_at:
            raise CalendarPreviewTokenError(
                "Server clock precedes the original preview time",
                code="CALENDAR_PREVIEW_TOKEN_CLOCK_INVALID",
            )
        if now >= content.response_expires_at:
            raise CalendarPreviewTokenError(
                "Original source response-age window has expired",
                code="CALENDAR_PREVIEW_TOKEN_EXPIRED",
            )
        intent = content.intent
        result = self._confirmation.execute(intent, proof=proof)
        if type(result) is not CalendarFormalPublicationCommit:
            raise CalendarPublicationOperationsError(
                "Confirmation gateway returned an invalid result type",
                code="CALENDAR_WORKBENCH_CONFIRMATION_INVALID",
            )
        result.__post_init__()
        _validate_commit_binding(result, intent, proof)
        return result


def _validate_capture_intent(intent: object) -> None:
    """Validate a public capture request before any request-bound gateway call."""

    if type(intent) is not CaptureExchangeCalendarSnapshotIntent:
        raise CalendarPublicationOperationsError(
            "Workbench requires an exact typed capture intent",
            code="CALENDAR_CAPTURE_INTENT_INVALID",
        )
    intent.__post_init__()


def _validate_proof(proof: object) -> None:
    """Validate request identity without treating it as an authorization grant."""

    if type(proof) is not CalendarPublisherSessionRequestProof:
        raise CalendarPreviewTokenError(
            "Calendar workbench requires a server-issued session proof",
            code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
        )
    proof.validate()
    if proof.database_alias != CALENDAR_PREVIEW_DATABASE_ALIAS:
        raise CalendarPreviewTokenError(
            "Calendar preview tokens do not support this database alias",
            code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
        )


def _session_key_digest(proof: CalendarPublisherSessionRequestProof) -> str:
    """Return a one-way binding digest without retaining the raw session key."""

    return hashlib.sha256(proof.session_key.encode("utf-8")).hexdigest()


def _validate_capture_preview_binding(
    captured: CapturedExchangeCalendarSnapshot,
    preview: CalendarPublicationPreview,
) -> None:
    """Require preview to preserve the capture's exact reference and source clocks."""

    if (
        preview.snapshot_reference != captured.snapshot_reference
        or preview.first_seen_at != captured.first_seen_at
        or preview.snapshot_recorded_at != captured.recorded_at
        or preview.source_published_at != captured.source_published_at
    ):
        raise CalendarPublicationOperationsError(
            "Preview changed the captured reference or one of its source clocks",
            code="CALENDAR_WORKBENCH_PREVIEW_BINDING_MISMATCH",
        )


def _validate_preview_scope(preview: CalendarPublicationPreview) -> None:
    """Bind catalog and publication-pointer scope to the reference exchange."""

    if (
        preview.identity.dataset_key != preview.expected_pointer.dataset_key
        or preview.expected_pointer.publication_key
        != exchange_calendar_publication_key(preview.snapshot_reference.exchange)
    ):
        raise CalendarPublicationOperationsError(
            "Preview catalog or pointer scope differs from its exact source",
            code="CALENDAR_WORKBENCH_PREVIEW_SCOPE_MISMATCH",
        )


def _validate_commit_binding(
    commit: CalendarFormalPublicationCommit,
    intent: ConfirmCalendarPublicationIntent,
    proof: CalendarPublisherSessionRequestProof,
) -> None:
    """Ensure a successful confirmation result matches the decoded request."""

    seal = commit.record.seal
    expected_identity = intent.expected_identity
    if (
        seal.snapshot_reference != intent.snapshot_reference
        or seal.dataset.value != expected_identity.dataset_key
        or seal.dataset.contract_version != expected_identity.contract_version
        or seal.dataset.schema_version != expected_identity.schema_version
        or seal.policy_identity != expected_identity.policy_identity
        or seal.policy_version != expected_identity.policy_version
        or seal.calendar_response_max_age_seconds
        != expected_identity.calendar_response_max_age_seconds
        or seal.publication_hash != intent.expected_publication_hash
        or commit.record.activation_id != intent.activation_id
        or commit.pointer.dataset_key != expected_identity.dataset_key
        or commit.pointer.publication_key != intent.expected_pointer.publication_key
        or commit.audit_pair.actor_user_id != proof.user_id
        or commit.audit_pair.database_alias != proof.database_alias
    ):
        raise CalendarPublicationOperationsError(
            "Confirmation gateway returned a different publication identity",
            code="CALENDAR_WORKBENCH_CONFIRMATION_BINDING_MISMATCH",
        )


def _read_server_clock(clock: CalendarOperationsClock) -> datetime:
    """Read an exact timezone-aware UTC instant from the injected server clock."""

    try:
        value = clock.now()
    except (AttributeError, TypeError, ValueError) as error:
        raise CalendarPreviewTokenError(
            "Calendar workbench server clock is unavailable",
            code="CALENDAR_PREVIEW_TOKEN_CLOCK_INVALID",
        ) from error
    if type(value) is not datetime or value.tzinfo is None:
        raise CalendarPreviewTokenError(
            "Calendar workbench server clock must return an aware UTC instant",
            code="CALENDAR_PREVIEW_TOKEN_CLOCK_INVALID",
        )
    try:
        offset = value.utcoffset()
    except (OverflowError, TypeError, ValueError) as error:
        raise CalendarPreviewTokenError(
            "Calendar workbench server clock must return an aware UTC instant",
            code="CALENDAR_PREVIEW_TOKEN_CLOCK_INVALID",
        ) from error
    if offset != timedelta(0):
        raise CalendarPreviewTokenError(
            "Calendar workbench server clock must return an aware UTC instant",
            code="CALENDAR_PREVIEW_TOKEN_CLOCK_INVALID",
        )
    return value.astimezone(UTC)


def _ensure_clock_after_request(
    now: datetime,
    proof: CalendarPublisherSessionRequestProof,
) -> None:
    """Reject server/request clock rollback before token or owner gateway access."""

    if now < proof.request_authenticated_at:
        raise CalendarPreviewTokenError(
            "Server clock precedes request authentication time",
            code="CALENDAR_PREVIEW_TOKEN_CLOCK_INVALID",
        )


__all__ = [
    "CalendarPublicationWorkbench",
    "CalendarWorkbenchCapturePort",
    "CalendarWorkbenchConfirmationPort",
    "CalendarWorkbenchPreview",
    "CalendarWorkbenchPreviewPort",
]
