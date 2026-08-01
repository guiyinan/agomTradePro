"""Execute approved Agent proposals through the governed MCP core surface."""

from __future__ import annotations

import importlib
import json
import os
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Any, cast

from django.conf import settings

from apps.agent_runtime.domain.entities import AgentProposal
from shared.infrastructure.async_runtime import run_sync_compatible
from shared.infrastructure.django_sdk_transport import DjangoSdkTransport
from shared.infrastructure.mcp_runtime import call_sdk_mcp_tool, ensure_sdk_on_path

_MCP_ROLE_LOCK = RLock()
_CAPABILITY_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
# ``secrets.token_urlsafe`` may begin with ``-`` or ``_``; both are part of
# the server-issued URL-safe alphabet and must survive the local validator.
_CONFIRMATION_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_.:-][A-Za-z0-9_.:-]{0,4095}$")
_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_PROPOSAL_FIELDS = frozenset({"capability_key", "arguments", "session_id"})
_MAX_ARGUMENT_BYTES = 262_144
_MAX_RESULT_BYTES = 1_048_576
_MCP_RUNTIME_EXCEPTIONS = (
    ArithmeticError,
    AttributeError,
    ConnectionError,
    ImportError,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


@dataclass(frozen=True)
class _TrustedActor:
    """Validated actor identity used by embedded MCP transport and audit."""

    user_id: int
    username: str
    is_staff: bool

    @property
    def trusted_role(self) -> str:
        """Return the only MCP role derived from authenticated staff state."""

        return "admin" if self.is_staff else "read_only"

    def as_transport_actor(self) -> dict[str, object]:
        """Return the minimal detached actor mapping for local SDK transport."""

        return {
            "user_id": self.user_id,
            "username": self.username,
            "is_staff": self.is_staff,
            "roles": [self.trusted_role],
        }


@contextmanager
def _trusted_mcp_context(actor: _TrustedActor) -> Iterator[None]:
    """Scope trusted role and internal auth across one stage/resume execution."""

    with _MCP_ROLE_LOCK:
        overrides = {
            "AGOMTRADEPRO_MCP_ROLE": actor.trusted_role,
            "AGOMTRADEPRO_INTERNAL_AUTH_SECRET": _internal_auth_secret(),
            "AGOMTRADEPRO_INTERNAL_USER_ID": str(actor.user_id),
            "AGOMTRADEPRO_INTERNAL_USERNAME": actor.username,
            "AGOMTRADEPRO_INTERNAL_SOURCE": "terminal_approval",
        }
        previous = {key: os.environ.get(key) for key in overrides}
        os.environ.update(overrides)
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def _persist_local_audit_log(payload: dict[str, Any]) -> str | None:
    """Persist an embedded MCP audit event through the Audit application facade."""

    from apps.audit.application.interface_services import log_operation_payload

    result = run_sync_compatible(lambda: log_operation_payload(**payload))
    if not isinstance(result, Mapping) or result.get("success") is not True:
        raise RuntimeError("local_mcp_audit_write_failed")
    log_id = result.get("log_id")
    if log_id is None:
        return None
    if isinstance(log_id, bool) or not isinstance(log_id, (int, str)):
        raise RuntimeError("local_mcp_audit_log_id_invalid")
    normalized = str(log_id).strip()
    if not normalized or len(normalized) > 128 or "\x00" in normalized:
        raise RuntimeError("local_mcp_audit_log_id_invalid")
    return normalized


@contextmanager
def _local_mcp_io(actor: _TrustedActor) -> Iterator[None]:
    """Scope socket-free SDK transport and local audit persistence."""

    ensure_sdk_on_path()
    transport_module = importlib.import_module("agomtradepro.transport")
    audit_module = importlib.import_module("agomtradepro_mcp.audit")
    use_request_transport = cast(
        Callable[[object], AbstractContextManager[None]],
        transport_module.use_request_transport,
    )
    use_audit_sink = cast(
        Callable[[object], AbstractContextManager[None]],
        audit_module.use_audit_sink,
    )

    with (
        use_request_transport(DjangoSdkTransport(actor=actor.as_transport_actor())),
        use_audit_sink(_persist_local_audit_log),
    ):
        yield


class ApprovedMcpCapabilityExecutor:
    """Run one approved proposal via MCP stage-and-resume calls."""

    def execute(
        self,
        *,
        proposal: AgentProposal,
        actor: dict[str, Any] | None,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Execute one immutable capability payload with a validated actor."""

        trusted_actor = _normalize_actor(actor)
        _validate_context(context)
        request_id = _request_id(proposal.request_id)
        capability_key, arguments = _proposal_call(proposal.proposal_payload)
        audit_context = {
            "request_id": request_id,
            "user_id": trusted_actor.user_id,
            "username": trusted_actor.username,
            "mcp_role": trusted_actor.trusted_role,
            "client_id": "terminal_approval",
        }

        try:
            result = _run_mcp_exchange(
                trusted_actor=trusted_actor,
                capability_key=capability_key,
                arguments=arguments,
                audit_context=audit_context,
            )
        except _MCP_RUNTIME_EXCEPTIONS as exc:
            raise RuntimeError(_stable_runtime_error(exc)) from exc

        if result.get("ok") is not True:
            raise RuntimeError(_safe_mcp_failure_code(result.get("error")))
        return cast(dict[str, Any], result)


def _run_mcp_exchange(
    *,
    trusted_actor: _TrustedActor,
    capability_key: str,
    arguments: dict[str, object],
    audit_context: dict[str, object],
) -> dict[str, object]:
    """Run the scoped MCP stage/resume exchange and return its envelope."""

    with _trusted_mcp_context(trusted_actor), _local_mcp_io(trusted_actor):
        staged = _mcp_envelope(
            call_sdk_mcp_tool(
                "agom_capability_call",
                {
                    "capability_key": capability_key,
                    "arguments": arguments,
                    "context": audit_context,
                },
            ),
            label="mcp_stage",
        )

        if staged.get("status") == "confirmation_required":
            confirmation_token = _confirmation_token(staged.get("confirmation_token"))
            return _mcp_envelope(
                call_sdk_mcp_tool(
                    "agom_confirmation_resume",
                    {"confirmation_token": confirmation_token, "approve": True},
                ),
                label="mcp_resume",
            )
        return staged


def _normalize_actor(actor: object) -> _TrustedActor:
    """Validate an authenticated execution actor without truthy coercion."""

    if not isinstance(actor, Mapping) or any(not isinstance(key, str) for key in actor):
        raise RuntimeError("approved_mcp_actor_required")
    user_id = actor.get("user_id")
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise RuntimeError("approved_mcp_actor_user_id_invalid")
    is_staff = actor.get("is_staff", False)
    if not isinstance(is_staff, bool):
        raise RuntimeError("approved_mcp_actor_staff_flag_invalid")
    username = _bounded_single_line_text(
        actor.get("username", "terminal_approver"),
        label="approved_mcp_actor_username_invalid",
        maximum=150,
    )
    return _TrustedActor(user_id=user_id, username=username, is_staff=is_staff)


def _validate_context(context: object) -> None:
    """Reject malformed dynamic guardrail context before MCP execution."""

    if context is None:
        return
    if not isinstance(context, Mapping) or any(not isinstance(key, str) for key in context):
        raise RuntimeError("approved_mcp_context_invalid")


def _proposal_call(payload: object) -> tuple[str, dict[str, object]]:
    """Return an exact capability key and detached finite JSON arguments."""

    if not isinstance(payload, Mapping) or any(not isinstance(key, str) for key in payload):
        raise RuntimeError("approved_mcp_proposal_payload_invalid")
    unknown = set(payload) - _PROPOSAL_FIELDS
    if unknown:
        raise RuntimeError("approved_mcp_proposal_fields_invalid")
    session_id = payload.get("session_id")
    if session_id is not None:
        _bounded_single_line_text(
            session_id,
            label="approved_mcp_session_id_invalid",
            maximum=128,
        )
    capability_key = payload.get("capability_key")
    if (
        not isinstance(capability_key, str)
        or _CAPABILITY_KEY_PATTERN.fullmatch(capability_key.strip()) is None
    ):
        raise RuntimeError("approved_mcp_capability_key_invalid")
    arguments = _bounded_json_object(
        payload.get("arguments"),
        label="approved_mcp_arguments_invalid",
        maximum=_MAX_ARGUMENT_BYTES,
    )
    return capability_key.strip(), arguments


def _mcp_envelope(value: object, *, label: str) -> dict[str, object]:
    """Return a detached, bounded MCP result envelope."""

    return _bounded_json_object(value, label=f"{label}_envelope_invalid", maximum=_MAX_RESULT_BYTES)


def _bounded_json_object(
    value: object,
    *,
    label: str,
    maximum: int,
) -> dict[str, object]:
    """Return a detached finite JSON object with string keys and bounded size."""

    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise RuntimeError(label)
    detached = {key: deepcopy(item) for key, item in value.items()}
    try:
        encoded = json.dumps(detached, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(label) from exc
    if len(encoded.encode("utf-8")) > maximum:
        raise RuntimeError(label)
    return detached


def _request_id(value: object) -> str:
    """Return one bounded trace identifier."""

    if not isinstance(value, str):
        raise RuntimeError("approved_mcp_request_id_invalid")
    normalized = value.strip()
    if _REQUEST_ID_PATTERN.fullmatch(normalized) is None:
        raise RuntimeError("approved_mcp_request_id_invalid")
    return normalized


def _confirmation_token(value: object) -> str:
    """Return one bounded confirmation token."""

    if not isinstance(value, str):
        raise RuntimeError("mcp_confirmation_token_invalid")
    normalized = value.strip()
    if _CONFIRMATION_TOKEN_PATTERN.fullmatch(normalized) is None:
        raise RuntimeError("mcp_confirmation_token_invalid")
    return normalized


def _safe_mcp_failure_code(value: object) -> str:
    """Return a stable failure code without publishing MCP error messages."""

    if isinstance(value, Mapping):
        code = value.get("code")
        if isinstance(code, str):
            normalized = code.strip().lower()
            if _ERROR_CODE_PATTERN.fullmatch(normalized) is not None:
                return normalized
    return "mcp_execution_failed"


def _stable_runtime_error(exc: BaseException) -> str:
    """Preserve only internal stable codes from dynamic MCP failures."""

    candidate = str(exc).strip().lower()
    if _ERROR_CODE_PATTERN.fullmatch(candidate) is not None:
        return candidate
    return "mcp_execution_transport_failed"


def _bounded_single_line_text(value: object, *, label: str, maximum: int) -> str:
    """Return bounded nonempty text without control characters."""

    if not isinstance(value, str):
        raise RuntimeError(label)
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise RuntimeError(label)
    return normalized


def _internal_auth_secret() -> str:
    """Return a string internal-auth secret suitable for scoped environment use."""

    value: object = getattr(settings, "AGOMTRADEPRO_INTERNAL_AUTH_SECRET", "")
    if not isinstance(value, str) or "\x00" in value:
        raise RuntimeError("internal_auth_secret_invalid")
    return value
