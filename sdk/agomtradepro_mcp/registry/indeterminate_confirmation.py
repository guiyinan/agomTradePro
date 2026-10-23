"""Typed handling for confirmed writes with an indeterminate outcome."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Protocol

from agomtradepro.exceptions import AgomTradeProAPIError
from agomtradepro.exceptions import ConnectionError as SDKConnectionError
from agomtradepro.exceptions import ExecutionOutcomeUnknownError as SDKExecutionOutcomeUnknownError
from agomtradepro.exceptions import TimeoutError as SDKTimeoutError
from agomtradepro_mcp.audit import AuditContext

from .manifest import CapabilityManifest

_PUBLIC_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_UNKNOWN_RESULT_MESSAGE = "执行结果尚未核实；请复用原确认与幂等键重试。"


class _DispatcherOutcomePort(Protocol):
    """The narrow dispatcher state and envelope operations used by this helper."""

    _pending_confirmations: dict[str, dict[str, Any]]
    _idempotency_records: dict[tuple[str, str], dict[str, Any]]

    def _error_envelope(
        self,
        *,
        code: str,
        message: str,
        capability_key: str | None = None,
        confirmation_token: str | None = None,
        missing_required: list[str] | None = None,
        required_roles: list[str] | None = None,
    ) -> dict[str, Any]: ...

    def _execution_error_envelope(
        self,
        exc: Exception,
        *,
        default_code: str,
        capability_key: str,
        confirmation_token: str | None = None,
    ) -> dict[str, Any]: ...

    def _extract_idempotency_key(
        self,
        manifest: CapabilityManifest,
        arguments: dict[str, Any],
    ) -> str | None: ...

    def _audit_capability_event(
        self,
        *,
        manifest: CapabilityManifest,
        audit_context: AuditContext,
        tool_name: str,
        event_type: str,
        confirmation_status: str,
        arguments: dict[str, Any],
        request_arguments: dict[str, Any],
        response: dict[str, Any],
        error: Exception | None = None,
        idempotency_key: str | None = None,
        preview_result: Any | None = None,
        confirmation_token: str | None = None,
    ) -> None: ...


class IndeterminateConfirmationOutcomes:
    """Build and audit confirmation outcomes that may have committed upstream."""

    def __init__(self, dispatcher: _DispatcherOutcomePort) -> None:
        """Bind the narrow dispatcher state and envelope port."""
        self._dispatcher = dispatcher

    def handle_exception(
        self,
        *,
        exception: Exception,
        manifest: CapabilityManifest,
        arguments: dict[str, Any],
        pending: dict[str, Any],
        record_key: tuple[str, str] | None,
        confirmation_token: str,
        audit_context: AuditContext,
        request_arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Retain retry identity when the confirmed write may have committed."""
        indeterminate = self._should_preserve_confirmation(
            manifest=manifest,
            exception=exception,
            record_key=record_key,
        )
        if indeterminate:
            self._dispatcher._pending_confirmations[confirmation_token] = pending
        elif record_key is not None:
            self._dispatcher._idempotency_records.pop(record_key, None)
        if indeterminate:
            payload = self._error_envelope(
                exception=exception,
                manifest=manifest,
                arguments=arguments,
                confirmation_token=confirmation_token,
            )
        else:
            payload = self._dispatcher._execution_error_envelope(
                exception,
                default_code="capability_execution_failed",
                capability_key=manifest.capability_key,
                confirmation_token=confirmation_token,
            )
        self._dispatcher._audit_capability_event(
            manifest=manifest,
            audit_context=audit_context,
            tool_name="agom_confirmation_resume",
            event_type="confirmation_indeterminate" if indeterminate else "confirmation_failed",
            confirmation_status="pending" if indeterminate else "failed",
            arguments=request_arguments,
            request_arguments=request_arguments,
            response=payload,
            preview_result=pending.get("preview_result"),
            error=exception,
            confirmation_token=confirmation_token,
        )
        return payload

    def handle_result(
        self,
        *,
        manifest: CapabilityManifest,
        result: Any,
        record_key: tuple[str, str] | None,
        arguments: dict[str, Any],
        pending: dict[str, Any],
        confirmation_token: str,
        audit_context: AuditContext,
        request_arguments: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Preserve a structured unknown result and its explicit retry identity."""
        if not self._is_indeterminate_result(
            manifest=manifest,
            result=result,
            record_key=record_key,
        ):
            return None
        self._dispatcher._pending_confirmations[confirmation_token] = pending
        payload = self._result_envelope(
            manifest=manifest,
            arguments=arguments,
            result=result,
            confirmation_token=confirmation_token,
        )
        self._dispatcher._audit_capability_event(
            manifest=manifest,
            audit_context=audit_context,
            tool_name="agom_confirmation_resume",
            event_type="confirmation_indeterminate",
            confirmation_status="pending",
            arguments=request_arguments,
            request_arguments=request_arguments,
            response=payload,
            preview_result=pending.get("preview_result"),
            confirmation_token=confirmation_token,
        )
        return payload

    def _is_indeterminate_result(
        self,
        *,
        manifest: CapabilityManifest,
        result: Any,
        record_key: tuple[str, str] | None,
    ) -> bool:
        """Recognize an explicitly opted-in structured unknown result."""
        return (
            manifest.preserve_confirmation_on_indeterminate_outcome
            and manifest.idempotency == "required"
            and manifest.requires_confirmation
            and record_key is not None
            and type(result) is dict
            and result.get("success") is False
            and result.get("status") == "unknown"
            and result.get("effects_indeterminate") is True
            and result.get("retry_with_same_idempotency_key") is True
            and type(result.get("error")) is dict
        )

    def _is_safe_response(self, response: Any) -> bool:
        """Limit forwarded upstream JSON to the known safe error-envelope fields."""
        allowed_keys = {
            "code",
            "error_code",
            "success",
            "error",
            "message",
            "detail",
            "effects_indeterminate",
            "retry_with_same_idempotency_key",
            "request_id",
            "trace_id",
        }
        if type(response) is not dict or response.get("effects_indeterminate") is not True:
            return False
        for key, value in response.items():
            if type(key) is not str or key not in allowed_keys:
                return False
            if key == "success" and value is not False:
                return False
            if key == "error" and (type(value) is not str or not value.strip()):
                return False
            if key in {"code", "error_code"} and (
                type(value) is not str or not _PUBLIC_CODE_PATTERN.fullmatch(value.strip())
            ):
                return False
            if type(value) is str:
                normalized = value.lower()
                if (
                    len(value) > 240
                    or ("<" in normalized and ">" in normalized)
                    or "traceback" in normalized
                    or "password" in normalized
                    or "passwd" in normalized
                    or "secret" in normalized
                    or "authorization" in normalized
                    or "bearer " in normalized
                    or "api_key=" in normalized
                    or "access_key=" in normalized
                    or "credential" in normalized
                    or "token=" in normalized
                    or "://" in normalized
                ):
                    return False
            elif type(value) not in {bool, int}:
                return False
        return True

    def _result_envelope(
        self,
        *,
        manifest: CapabilityManifest,
        arguments: dict[str, Any],
        result: Any,
        confirmation_token: str,
    ) -> dict[str, Any]:
        """Keep a structured unknown result pending without wrapping it as success."""
        payload = self._dispatcher._error_envelope(
            code="indeterminate_operation_outcome",
            message=_UNKNOWN_RESULT_MESSAGE,
            capability_key=manifest.capability_key,
            confirmation_token=confirmation_token,
        )
        payload["status"] = "unknown"
        payload["effects_indeterminate"] = True
        payload["retry_with_same_idempotency_key"] = True
        idempotency_key = self._dispatcher._extract_idempotency_key(manifest, arguments)
        if idempotency_key is not None:
            payload["idempotency_key"] = idempotency_key
            if result.get("idempotency_key") != idempotency_key:
                payload["error"]["source_idempotency_key_mismatch"] = True
        error = payload["error"]
        raw_error = result.get("error")
        if type(raw_error) is dict and type(raw_error.get("code")) is str:
            source_code = raw_error["code"].strip().lower()
            if _PUBLIC_CODE_PATTERN.fullmatch(source_code):
                error["source_error_code"] = source_code
        upstream_response = result.get("upstream_response")
        if self._is_safe_response(upstream_response):
            error["upstream_response"] = deepcopy(upstream_response)
        return payload

    def _should_preserve_confirmation(
        self,
        *,
        manifest: CapabilityManifest,
        exception: Exception,
        record_key: tuple[str, str] | None,
    ) -> bool:
        """Return whether this opted-in idempotent write may have committed."""
        if (
            not manifest.preserve_confirmation_on_indeterminate_outcome
            or manifest.idempotency != "required"
            or not manifest.requires_confirmation
            or record_key is None
        ):
            return False
        if isinstance(
            exception, (SDKExecutionOutcomeUnknownError, SDKTimeoutError, SDKConnectionError)
        ):
            return True
        if (
            manifest.capability_key == "trading.close.simulated_position"
            and isinstance(exception, AgomTradeProAPIError)
            and type(exception.status_code) is int
            and 300 <= exception.status_code <= 399
        ):
            return True
        return (
            isinstance(exception, AgomTradeProAPIError)
            and type(exception.status_code) is int
            and 500 <= exception.status_code <= 599
        )

    def _error_envelope(
        self,
        *,
        exception: Exception,
        manifest: CapabilityManifest,
        arguments: dict[str, Any],
        confirmation_token: str,
    ) -> dict[str, Any]:
        """Preserve retry identity and a typed upstream body without claiming success."""
        if isinstance(exception, SDKExecutionOutcomeUnknownError):
            payload = self._dispatcher._error_envelope(
                code=exception.code,
                message=_UNKNOWN_RESULT_MESSAGE,
                capability_key=manifest.capability_key,
                confirmation_token=confirmation_token,
            )
        elif (
            isinstance(exception, AgomTradeProAPIError)
            and type(exception.status_code) is int
            and 500 <= exception.status_code <= 599
        ):
            source_payload = self._dispatcher._execution_error_envelope(
                exception,
                default_code="capability_execution_failed",
                capability_key=manifest.capability_key,
                confirmation_token=confirmation_token,
            )
            source_error = source_payload.get("error")
            raw_code = source_error.get("code") if type(source_error) is dict else None
            source_code: str = "capability_execution_failed"
            if type(raw_code) is str:
                source_code = raw_code
            payload = self._dispatcher._error_envelope(
                code=source_code,
                message=_UNKNOWN_RESULT_MESSAGE,
                capability_key=manifest.capability_key,
                confirmation_token=confirmation_token,
            )
            payload["error"]["upstream_status_code"] = exception.status_code
        elif (
            manifest.capability_key == "trading.close.simulated_position"
            and isinstance(exception, AgomTradeProAPIError)
            and type(exception.status_code) is int
            and 300 <= exception.status_code <= 399
        ):
            payload = self._dispatcher._error_envelope(
                code="upstream_http_redirect",
                message=_UNKNOWN_RESULT_MESSAGE,
                capability_key=manifest.capability_key,
                confirmation_token=confirmation_token,
            )
            payload["error"]["upstream_status_code"] = exception.status_code
        else:
            payload = self._dispatcher._execution_error_envelope(
                exception,
                default_code="capability_execution_failed",
                capability_key=manifest.capability_key,
                confirmation_token=confirmation_token,
            )
        payload["status"] = "unknown"
        payload["effects_indeterminate"] = True
        payload["retry_with_same_idempotency_key"] = True
        error = payload.get("error")
        if type(error) is dict:
            error["effects_indeterminate"] = True
            error["retry_with_same_idempotency_key"] = True
            if (
                isinstance(exception, AgomTradeProAPIError)
                and type(exception.status_code) is int
                and exception.status_code == 503
                and self._is_safe_response(exception.response)
            ):
                error["upstream_response"] = deepcopy(exception.response)
        idempotency_key = self._dispatcher._extract_idempotency_key(manifest, arguments)
        if idempotency_key is not None:
            payload["idempotency_key"] = idempotency_key
        return payload
