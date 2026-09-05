"""HTTP boundary for the durable queued Terminal Agent routes."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Iterator, Mapping, Sequence
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agent_runtime.application.tasks import execute_terminal_agent_run
from apps.agent_runtime.application.terminal_agent_run_api_contract import (
    TerminalRunAcceptedResponse,
    TerminalRunApiRoute,
    TerminalRunCancelResponse,
    TerminalRunStatusResponse,
    terminal_run_route,
)
from apps.agent_runtime.application.terminal_agent_run_ports import (
    TerminalQueuedSubmissionRequest,
)
from apps.agent_runtime.application.terminal_agent_run_route_guard import (
    TerminalQueuedRuntimeUnavailable,
    reject_terminal_queued_route,
)
from apps.agent_runtime.application.terminal_agent_run_runtime import (
    TerminalRunEventRecord,
)
from apps.agent_runtime.composition import get_terminal_agent_run_repository
from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalRunContractError,
    TerminalRunSelector,
    TerminalRunSubmission,
    TerminalRuntimeMode,
)

logger = logging.getLogger(__name__)


class TerminalEventStreamRenderer(BaseRenderer):
    """Allow DRF content negotiation for the streaming event media type."""

    media_type = "text/event-stream"
    format = "event-stream"
    charset = None
    render_style = "binary"

    def render(
        self,
        data: object,
        accepted_media_type: str | None = None,
        renderer_context: Mapping[str, object] | None = None,
    ) -> bytes:
        """Return an empty body because event responses stream directly."""

        return b""


def _dispatch_queued_run(run_id: str, task_id: int) -> None:
    """Best-effort broker dispatch after the durable admission commits.

    The database row is the source of truth.  A transient broker failure must
    leave that row queued for operational recovery/retry rather than turning a
    committed admission into a misleading HTTP 500 response.
    """

    try:
        execute_terminal_agent_run.apply_async(
            args=[run_id, task_id],
            queue="terminal_agent",
        )
    except Exception:
        logger.exception("Queued terminal run broker dispatch failed; run_id=%s", run_id)


class TerminalQueuedRunUnavailableView(APIView):
    """Return a stable 503 without composing a queued or inline Agent run."""

    permission_classes = [IsAuthenticated]

    def _unavailable_response(self) -> Response:
        """Build the redacted response for the dormant route boundary."""

        try:
            reject_terminal_queued_route()
        except TerminalQueuedRuntimeUnavailable as exc:
            return Response(
                {
                    "error": "Queued terminal runtime is not available.",
                    "code": exc.code,
                    "reason_code": exc.reason_code,
                    "retryable": True,
                    "success": False,
                    "must_not_use_for_decision": True,
                },
                status=exc.status_code,
                headers={"Retry-After": str(exc.retry_after_seconds)},
            )

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Fail closed for reserved read/status/event routes."""

        return self._unavailable_response()

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Fail closed for reserved create/cancel routes."""

        return self._unavailable_response()


class TerminalQueuedRunView(APIView):
    """Owner-scoped durable queued-run API backed by the dedicated worker."""

    permission_classes = [IsAuthenticated]

    def _enabled(self) -> bool:
        """Require both queue flags and no emergency stop before admission."""

        return bool(
            getattr(settings, "TERMINAL_QUEUED_INTAKE_ENABLED", False)
            and getattr(settings, "TERMINAL_QUEUED_WORKER_ENABLED", False)
            and not getattr(settings, "TERMINAL_EMERGENCY_STOP", False)
        )

    def _unavailable_response(self) -> Response:
        """Return the stable fail-closed response while the queue is disabled."""

        try:
            reject_terminal_queued_route()
        except TerminalQueuedRuntimeUnavailable as exc:
            return Response(
                {
                    "error": "Queued terminal runtime is not available.",
                    "code": exc.code,
                    "reason_code": exc.reason_code,
                    "retryable": True,
                    "success": False,
                    "must_not_use_for_decision": True,
                },
                status=exc.status_code,
                headers={"Retry-After": str(exc.retry_after_seconds)},
            )

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Admit one task-backed queued run and dispatch only its identifiers."""

        if not self._enabled():
            return self._unavailable_response()
        try:
            actor_user_id = _actor_user_id(request)
            payload = _mapping(request.data)
            task_id = _positive_int(payload.get("task_id"), "task_id")
            client_request_id = _string(payload.get("client_request_id"), "client_request_id")
            message = _string(payload.get("message"), "message")
            run_id = payload.get("run_id")
            if run_id is None:
                run_id = f"run-{uuid.uuid4().hex}"
            run_id = _string(run_id, "run_id")
            request_digest = payload.get("request_digest")
            if request_digest is None:
                request_digest = hashlib.sha256(
                    json.dumps(
                        {"task_id": task_id, "message": message},
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest()
            request_digest = _string(request_digest, "request_digest")
            accepted_at = timezone.now()
            timeout_seconds = max(
                30,
                min(
                    900,
                    int(getattr(settings, "TERMINAL_AGENT_EXECUTION_TIMEOUT_SECONDS", 60))
                    + int(getattr(settings, "TERMINAL_PER_USER_QUEUED_LIMIT", 4)) * 15,
                ),
            )
            deadline_at = accepted_at + timedelta(seconds=timeout_seconds)
            repository = get_terminal_agent_run_repository()
            submission = TerminalRunSubmission(
                selector=TerminalRunSelector(
                    run_id=run_id,
                    task_id=task_id,
                    actor_user_id=actor_user_id,
                    client_request_id=client_request_id,
                ),
                runtime_mode=TerminalRuntimeMode.WEB_QUEUED,
                request_digest=request_digest,
                accepted_at=accepted_at,
                deadline_at=deadline_at,
            )
            with transaction.atomic():
                run = repository.submit(
                    TerminalQueuedSubmissionRequest(
                        submission=submission,
                        message=message,
                    )
                )
                transaction.on_commit(
                    lambda: _dispatch_queued_run(
                        run.submission.selector.run_id,
                        run.submission.selector.task_id,
                    )
                )
            response = TerminalRunAcceptedResponse(
                run_id=run.submission.selector.run_id,
                task_id=run.submission.selector.task_id,
                status=run.dispatch_status,
                submitted_at=run.submission.accepted_at,
                status_url=terminal_run_route(
                    TerminalRunApiRoute.DETAIL, run.submission.selector.run_id
                ),
                events_url=terminal_run_route(
                    TerminalRunApiRoute.EVENTS, run.submission.selector.run_id
                ),
                cancel_url=terminal_run_route(
                    TerminalRunApiRoute.CANCEL, run.submission.selector.run_id
                ),
            )
            return Response(response.to_payload(), status=202)
        except TerminalRunContractError as exc:
            reason_code = str(getattr(exc, "reason_code", "RUN_REQUEST_INVALID"))
            if reason_code in {
                "per_user_active_limit",
                "per_user_queued_limit",
                "global_active_limit",
                "global_queued_limit",
            }:
                return _capacity_response(reason_code, 429)
            if reason_code in {"IDEMPOTENCY_KEY_CONFLICT", "RUN_ID_CONFLICT"}:
                return Response(
                    {
                        "error": "Queued run identity conflicts with an existing run.",
                        "code": reason_code,
                        "reason_code": reason_code,
                    },
                    status=409,
                )
            return Response(
                {"error": "Invalid queued run request.", "code": "RUN_REQUEST_INVALID"},
                status=400,
            )
        except (KeyError, TypeError, ValueError):
            return Response(
                {"error": "Invalid queued run request.", "code": "RUN_REQUEST_INVALID"},
                status=400,
            )

    def get(
        self, request: Request, run_id: str | None = None, *args: Any, **kwargs: Any
    ) -> Response | StreamingHttpResponse:
        """Return queue summary or one owner-scoped durable status snapshot."""

        if not self._enabled():
            return self._unavailable_response()
        actor_user_id = _actor_user_id(request)
        repository = get_terminal_agent_run_repository()
        if run_id is None:
            summary = repository.queue_summary(actor_user_id=actor_user_id)
            return Response(
                {
                    "user_active": summary.user_active,
                    "user_queued": summary.user_queued,
                    "global_active": summary.global_active,
                    "global_queued": summary.global_queued,
                    "worker_ready": True,
                }
            )
        snapshot = repository.get_snapshot(run_id=run_id, actor_user_id=actor_user_id)
        if snapshot is None:
            return Response({"error": "Run not found."}, status=404)
        response = TerminalRunStatusResponse(
            run_id=snapshot.run_id,
            status=snapshot.status,
            updated_at=snapshot.updated_at,
            status_url=terminal_run_route(TerminalRunApiRoute.DETAIL, snapshot.run_id),
            events_url=terminal_run_route(TerminalRunApiRoute.EVENTS, snapshot.run_id),
            cancel_url=terminal_run_route(TerminalRunApiRoute.CANCEL, snapshot.run_id),
            error_code=snapshot.error_code,
            result_ref=snapshot.result_ref,
        )
        return Response(response.to_payload())

    def delete(self, request: Request, run_id: str, *args: Any, **kwargs: Any) -> Response:
        """Request cooperative cancellation for one owned run."""

        return self._cancel(request, run_id)

    def post_cancel(self, request: Request, run_id: str, *args: Any, **kwargs: Any) -> Response:
        """Handle the canonical ``/cancel/`` route."""

        return self._cancel(request, run_id)

    def _cancel(self, request: Request, run_id: str) -> Response:
        """Persist an idempotent cancellation request."""

        if not self._enabled():
            return self._unavailable_response()
        actor_user_id = _actor_user_id(request)
        repository = get_terminal_agent_run_repository()
        try:
            snapshot = repository.cancel(
                run_id=run_id,
                actor_user_id=actor_user_id,
                requested_at=timezone.now(),
            )
        except TerminalRunContractError as exc:
            reason_code = str(getattr(exc, "reason_code", "RUN_CANCEL_FAILED"))
            if reason_code == "RUN_NOT_CANCELLABLE":
                return Response(
                    {
                        "error": "Run is not cancellable.",
                        "code": reason_code,
                        "reason_code": reason_code,
                        "retryable": False,
                    },
                    status=409,
                )
            return Response(
                {"error": "Unable to cancel run.", "code": reason_code},
                status=400,
            )
        if snapshot is None:
            return Response({"error": "Run not found."}, status=404)
        response = TerminalRunCancelResponse(
            run_id=run_id,
            status=snapshot.dispatch_status,
            cancel_requested_at=snapshot.cancel_requested_at,
        )
        return Response(response.to_payload())

    def events(
        self, request: Request, run_id: str, *args: Any, **kwargs: Any
    ) -> Response | StreamingHttpResponse:
        """Return replayable JSON events for SSE reconnect or polling."""

        if not self._enabled():
            return self._unavailable_response()
        actor_user_id = _actor_user_id(request)
        try:
            after_sequence = _sequence(
                request.headers.get("Last-Event-ID") or request.query_params.get("after")
            )
        except ValueError:
            return Response({"error": "Invalid event cursor."}, status=400)
        repository = get_terminal_agent_run_repository()
        events = repository.list_events(
            run_id=run_id,
            actor_user_id=actor_user_id,
            after_sequence=after_sequence,
            limit=100,
        )
        if events is None:
            return Response({"error": "Run not found."}, status=404)
        payload = {
            "run_id": run_id,
            "events": [
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "sequence": event.sequence,
                    "occurred_at": event.occurred_at.isoformat(),
                    "data": dict(event.data),
                }
                for event in events
            ],
        }
        if "text/event-stream" not in str(request.headers.get("Accept", "")):
            return Response(payload)
        return StreamingHttpResponse(
            _sse_lines(events),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


def _sse_lines(events: Sequence[TerminalRunEventRecord]) -> Iterator[str]:
    """Serialize a bounded event batch as replayable SSE frames."""

    for event in events:
        yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {json.dumps(dict(event.data), ensure_ascii=False)}\n\n"


def _mapping(value: object) -> Mapping[str, object]:
    """Require a JSON object request body."""

    if not isinstance(value, Mapping):
        raise ValueError("request_body_invalid")
    return value


def _string(value: object, field_name: str) -> str:
    """Require one bounded canonical string field."""

    if not isinstance(value, str) or not value or value.strip() != value or len(value) > 4096:
        raise ValueError(f"{field_name}_invalid")
    return value


def _positive_int(value: object, field_name: str) -> int:
    """Require a positive integer while rejecting bool."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name}_invalid")
    return value


def _sequence(value: object) -> int:
    """Parse a non-negative SSE sequence cursor."""

    if value in (None, ""):
        return 0
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("after_sequence_invalid") from exc
    if parsed < 0:
        raise ValueError("after_sequence_invalid")
    return parsed


def _actor_user_id(request: Request) -> int:
    """Resolve the authenticated owner without trusting request payload data."""

    return _positive_int(getattr(request.user, "pk", None), "actor_user_id")


def _capacity_response(reason_code: str, status_code: int) -> Response:
    """Build bounded Retry-After capacity feedback."""

    return Response(
        {
            "error": "Terminal Agent queue capacity is currently full.",
            "code": "QUEUE_CAPACITY_REJECTED",
            "reason_code": reason_code,
            "retryable": True,
        },
        status=status_code,
        headers={"Retry-After": "15"},
    )


class TerminalQueuedRunEventsView(TerminalQueuedRunView):
    """Route adapter for the replayable events endpoint."""

    renderer_classes = [JSONRenderer, TerminalEventStreamRenderer]

    def get(
        self, request: Request, run_id: str | None = None, *args: Any, **kwargs: Any
    ) -> Response | StreamingHttpResponse:
        """Return JSON or SSE events for one owned run."""

        if run_id is None:
            return Response({"error": "Run not found."}, status=404)
        return self.events(request, run_id, *args, **kwargs)


class TerminalQueuedRunCancelView(TerminalQueuedRunView):
    """Route adapter for the cooperative cancellation endpoint."""

    def post(self, request: Request, run_id: str, *args: Any, **kwargs: Any) -> Response:
        """Persist a cancellation request for one owned run."""

        return self.post_cancel(request, run_id, *args, **kwargs)
