"""Compose request-bound calendar Workbench calls through existing owner APIs."""

from __future__ import annotations

from datetime import datetime

from django.db import DEFAULT_DB_ALIAS, connections
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils import timezone
from rest_framework.request import Request

from apps.data_center.application.calendar_preview_token import (
    CalendarPreviewTokenCodec,
    CalendarPreviewTokenError,
)
from apps.data_center.application.calendar_publication_authority import (
    CalendarPublisherSessionRequestProof,
)
from apps.data_center.application.calendar_publication_operations import (
    CalendarOperationsClock,
    CalendarPublicationPreview,
    CapturedExchangeCalendarSnapshot,
    CaptureExchangeCalendarSnapshotIntent,
    ConfirmCalendarPublicationIntent,
    PreviewCalendarPublicationIntent,
)
from apps.data_center.application.calendar_workbench import (
    CalendarPublicationWorkbench,
    CalendarWorkbenchCapturePort,
    CalendarWorkbenchConfirmationPort,
    CalendarWorkbenchPreview,
    CalendarWorkbenchPreviewPort,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationCommit,
)
from apps.data_center.calendar_publication_operations_composition import (
    capture_exchange_calendar_snapshot,
    confirm_calendar_publication,
    preview_calendar_publication,
)
from apps.data_center.infrastructure.calendar_preview_token import (
    EncryptedCalendarPreviewTokenCodec,
)
from apps.data_center.interface.calendar_publication_session_adapter import (
    CalendarPublisherSessionAdapter,
)


class _ServerClock(CalendarOperationsClock):
    """Read only the server UTC clock for Application expiry checks."""

    def now(self) -> datetime:
        """Return Django's current timezone-aware instant."""

        return timezone.now()


class _RequestBoundCapturePort(CalendarWorkbenchCapturePort):
    """Recheck one real request before delegating to the existing capture owner."""

    def __init__(
        self,
        request: Request,
        initial_proof: CalendarPublisherSessionRequestProof,
    ) -> None:
        """Bind a request and its initial claim without retaining a session token elsewhere."""

        self._request = request
        self._initial_proof = initial_proof

    def execute(
        self,
        intent: CaptureExchangeCalendarSnapshotIntent,
        *,
        proof: CalendarPublisherSessionRequestProof,
    ) -> CapturedExchangeCalendarSnapshot:
        """Validate App claims, then use the existing transaction-owning capture entry."""

        _validate_app_proof(proof, self._initial_proof)
        _revalidate_request_identity(self._request, self._initial_proof)
        return capture_exchange_calendar_snapshot(self._request, intent)


class _RequestBoundPreviewPort(CalendarWorkbenchPreviewPort):
    """Recheck one real request before delegating to the existing preview owner."""

    def __init__(
        self,
        request: Request,
        initial_proof: CalendarPublisherSessionRequestProof,
    ) -> None:
        """Bind the original request identity used by the composed Workbench."""

        self._request = request
        self._initial_proof = initial_proof

    def execute(
        self,
        intent: PreviewCalendarPublicationIntent,
        *,
        proof: CalendarPublisherSessionRequestProof,
    ) -> CalendarPublicationPreview:
        """Use the existing preview use case after request-binding checks."""

        _validate_app_proof(proof, self._initial_proof)
        _revalidate_request_identity(self._request, self._initial_proof)
        return preview_calendar_publication(self._request, intent)


class _RequestBoundConfirmationPort(CalendarWorkbenchConfirmationPort):
    """Recheck one real request before delegating to the existing publisher owner."""

    def __init__(
        self,
        request: Request,
        initial_proof: CalendarPublisherSessionRequestProof,
    ) -> None:
        """Bind the initial actor and session claim for one confirmation request."""

        self._request = request
        self._initial_proof = initial_proof

    def execute(
        self,
        intent: ConfirmCalendarPublicationIntent,
        *,
        proof: CalendarPublisherSessionRequestProof,
    ) -> CalendarFormalPublicationCommit:
        """Delegate the decoded exact intent to the owner authorization gateway."""

        _validate_app_proof(proof, self._initial_proof)
        _revalidate_request_identity(self._request, self._initial_proof)
        return confirm_calendar_publication(self._request, intent)


def prepare_calendar_workbench_preview(
    request: Request,
    intent: CaptureExchangeCalendarSnapshotIntent,
) -> CalendarWorkbenchPreview:
    """Capture and preview through the existing owner gateways for one POST request.

    The capture and preview gateways each own their existing authorization
    transaction. This composition opens no encompassing transaction and returns
    only after both gateways have completed successfully.
    """

    _require_unowned_default_connection(connections[DEFAULT_DB_ALIAS])
    proof = _initial_request_proof(request)
    workbench = _workbench(request, proof)
    return workbench.prepare_preview(intent, proof=proof)


def confirm_calendar_workbench_preview(
    request: Request,
    token: str,
) -> CalendarFormalPublicationCommit:
    """Confirm an opaque preview token through the existing owner gateway.

    The token is non-authorizing. The owner wrapper performs fresh session,
    permission, TTL, publication CAS and Audit checks inside its own outer
    transaction; this composition does not open another transaction.
    """

    _require_unowned_default_connection(connections[DEFAULT_DB_ALIAS])
    proof = _initial_request_proof(request)
    workbench = _workbench(request, proof)
    return workbench.confirm(token, proof=proof)


def _initial_request_proof(request: Request) -> CalendarPublisherSessionRequestProof:
    """Derive the initial claim from SessionAuthentication on the real request."""

    proof = CalendarPublisherSessionAdapter().prove(request, using=DEFAULT_DB_ALIAS)
    return _require_default_proof(proof)


def _workbench(
    request: Request,
    proof: CalendarPublisherSessionRequestProof,
) -> CalendarPublicationWorkbench:
    """Build the real Application Workbench with request-bound owner adapters."""

    capture: CalendarWorkbenchCapturePort = _RequestBoundCapturePort(request, proof)
    preview: CalendarWorkbenchPreviewPort = _RequestBoundPreviewPort(request, proof)
    confirmation: CalendarWorkbenchConfirmationPort = _RequestBoundConfirmationPort(
        request,
        proof,
    )
    codec: CalendarPreviewTokenCodec = EncryptedCalendarPreviewTokenCodec()
    return CalendarPublicationWorkbench(
        capture=capture,
        preview=preview,
        confirmation=confirmation,
        token_codec=codec,
        clock=_ServerClock(),
    )


def _require_default_proof(
    proof: object,
) -> CalendarPublisherSessionRequestProof:
    """Validate a server-issued proof and constrain it to the default alias."""

    if type(proof) is not CalendarPublisherSessionRequestProof:
        raise CalendarPreviewTokenError(
            "Session adapter returned an invalid publisher proof",
            code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
        )
    proof.validate()
    if (
        proof.database_alias != DEFAULT_DB_ALIAS
        or proof.request_user_database_alias != DEFAULT_DB_ALIAS
    ):
        raise CalendarPreviewTokenError(
            "Calendar Workbench supports only the authenticated default database",
            code="CALENDAR_PREVIEW_TOKEN_BINDING_INVALID",
            status_code=409,
        )
    return proof


def _validate_app_proof(
    proof: object,
    initial_proof: CalendarPublisherSessionRequestProof,
) -> None:
    """Compare every App-supplied proof field, including the hidden session key."""

    candidate = _require_default_proof(proof)
    if (
        candidate.user_id != initial_proof.user_id
        or candidate.session_key != initial_proof.session_key
        or candidate.request_authenticated_at != initial_proof.request_authenticated_at
        or candidate.request_user_database_alias != initial_proof.request_user_database_alias
        or candidate.database_alias != initial_proof.database_alias
    ):
        raise CalendarPreviewTokenError(
            "Calendar Workbench App proof changed after request binding",
            code="CALENDAR_PREVIEW_TOKEN_BINDING_MISMATCH",
            status_code=409,
        )


def _revalidate_request_identity(
    request: Request,
    initial_proof: CalendarPublisherSessionRequestProof,
) -> None:
    """Re-read the real request and reject actor/session/alias drift before owner calls."""

    current = _require_default_proof(
        CalendarPublisherSessionAdapter().prove(request, using=DEFAULT_DB_ALIAS)
    )
    if (
        current.user_id != initial_proof.user_id
        or current.session_key != initial_proof.session_key
        or current.request_user_database_alias != initial_proof.request_user_database_alias
        or current.database_alias != initial_proof.database_alias
    ):
        raise CalendarPreviewTokenError(
            "Calendar Workbench request actor, session, or database changed",
            code="CALENDAR_PREVIEW_TOKEN_BINDING_MISMATCH",
            status_code=409,
        )
    if current.request_authenticated_at < initial_proof.request_authenticated_at:
        raise CalendarPreviewTokenError(
            "Calendar Workbench request clock moved backwards",
            code="CALENDAR_PREVIEW_TOKEN_CLOCK_INVALID",
            status_code=409,
        )


def _require_unowned_default_connection(connection: BaseDatabaseWrapper) -> None:
    """Reject caller-owned transactions and disabled autocommit before Session proof."""

    if (
        connection.alias != DEFAULT_DB_ALIAS
        or connection.in_atomic_block
        or not connection.get_autocommit()
    ):
        raise CalendarPreviewTokenError(
            "Calendar Workbench requires the unowned default database connection",
            code="CALENDAR_WORKBENCH_TRANSACTION_OWNER_INVALID",
            status_code=409,
        )


__all__ = [
    "confirm_calendar_workbench_preview",
    "prepare_calendar_workbench_preview",
]
