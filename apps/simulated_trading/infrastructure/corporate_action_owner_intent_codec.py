"""Bounded, session-bound codecs for server-generated company-action confirmations.

The token preserves original Domain facts for exact retries. It confers no
financial permission: every execution still requires the current locked grant.
Only trusted static type hints select constructors; payloads name no Python type.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import zlib
from datetime import datetime
from decimal import InvalidOperation
from typing import NoReturn, cast

from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request

from apps.audit.domain.system_audit_event import JSONValue
from apps.simulated_trading.application.corporate_action_owner_intent import (
    OwnerCorporateActionPreparedIntent,
)
from apps.simulated_trading.infrastructure.corporate_action_constructor_codec import (
    encode_corporate_action_constructor,
    restore_corporate_action_constructor,
)
from core.exceptions import BusinessLogicError
from shared.config.secrets import get_secrets

_KEY_DOMAIN = b"simulated-trading.corporate-action-owner-intent.v1/key"
_TOKEN_DOMAIN = b"simulated-trading.corporate-action-owner-intent.v1/token"
_SCHEMA = "simulated.corporate_action.owner_intent.v1"
_MAX_TOKEN = 65_536
_MAX_BODY = 1_048_576


def _blocked() -> BusinessLogicError:
    """Return a safe confirmation failure without leaking token material."""
    return BusinessLogicError(
        "Owner confirmation is invalid or unavailable", code="CORPORATE_ACTION_CONFIRMATION_INVALID"
    )


def _key() -> bytes:
    """Derive an intent-only MAC key from the configured application encryption key."""
    configured = get_secrets(require_tushare_token=False).field_encryption_key
    try:
        if not configured:
            raise ValueError("missing configured server key")
        raw = base64.b64decode(configured.encode("ascii"), altchars=b"-_", validate=True)
        if len(raw) != 32:
            raise ValueError("invalid configured key size")
    except (ValueError, UnicodeError, binascii.Error) as error:
        raise _blocked() from error
    return hmac.digest(raw, _KEY_DOMAIN, "sha256")


def owner_corporate_action_session_binding(request: Request) -> str:
    """Bind confirmations to the actual authenticated Session without retaining its key."""
    if not isinstance(request.successful_authenticator, SessionAuthentication):
        raise _blocked()
    session = getattr(request._request, "session", None)
    session_key: object = getattr(session, "session_key", None)
    if type(session_key) is not str or not session_key or len(session_key) > 4096:
        raise _blocked()
    return hmac.digest(_key(), b"session\0" + session_key.encode(), "sha256").hex()


def _strict_object(pairs: list[tuple[str, JSONValue]]) -> dict[str, JSONValue]:
    """Reject duplicate JSON keys before they could hide a conflicting owner field."""
    result: dict[str, JSONValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate intent object field")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    """Reject JSON non-finite numeric extensions at the parser boundary."""
    raise ValueError("invalid non-finite intent JSON")


def seal_owner_corporate_action_intent(
    intent: OwnerCorporateActionPreparedIntent,
    *,
    session_binding: str,
) -> str:
    """Seal complete original server facts, without granting or extending any permission."""
    try:
        if (
            type(intent) is not OwnerCorporateActionPreparedIntent
            or type(session_binding) is not str
            or not session_binding
        ):
            raise ValueError("typed intent and session binding required")
        intent.__post_init__()
        payload: dict[str, JSONValue] = {
            "schema": _SCHEMA,
            "session_binding": session_binding,
            "intent": encode_corporate_action_constructor(intent),
        }
        body = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
        if len(body) > _MAX_BODY:
            raise ValueError("intent exceeds its technical bound")
        compressed = zlib.compress(body)
        signature = hmac.digest(_key(), _TOKEN_DOMAIN + b"\0" + compressed, "sha256").hex()
        token = "v1." + base64.urlsafe_b64encode(compressed).decode() + "." + signature
        if len(token) > _MAX_TOKEN:
            raise ValueError("intent exceeds its transport bound")
        return token
    except (ValueError, TypeError, OverflowError, InvalidOperation) as error:
        raise _blocked() from error


def restore_owner_corporate_action_intent(
    token: str,
    *,
    owner_user_id: int,
    account_id: int,
    session_binding: str,
    as_of: datetime,
) -> OwnerCorporateActionPreparedIntent:
    """Authenticate before bounded decompression and exact Domain reconstruction."""
    try:
        if type(token) is not str or len(token) > _MAX_TOKEN:
            raise ValueError("invalid intent transport")
        version, encoded, signature = token.split(".")
        if version != "v1":
            raise ValueError("unsupported intent version")
        compressed = base64.b64decode(encoded, altchars=b"-_", validate=True)
        expected_mac = hmac.digest(_key(), _TOKEN_DOMAIN + b"\0" + compressed, "sha256").hex()
        if not hmac.compare_digest(signature, expected_mac):
            raise ValueError("invalid intent seal")
        stream = zlib.decompressobj()
        body = stream.decompress(compressed, _MAX_BODY + 1)
        if len(body) > _MAX_BODY or not stream.eof or stream.unused_data or stream.unconsumed_tail:
            raise ValueError("invalid intent compression")
        payload: object = json.loads(
            body, object_pairs_hook=_strict_object, parse_constant=_reject_constant
        )
        if type(payload) is not dict or set(payload) != {"schema", "session_binding", "intent"}:
            raise ValueError("invalid intent envelope")
        packet = cast(dict[str, JSONValue], payload)
        if packet["schema"] != _SCHEMA or packet["session_binding"] != session_binding:
            raise ValueError("intent session differs")
        intent = restore_corporate_action_constructor(
            packet["intent"], OwnerCorporateActionPreparedIntent
        )
        if type(intent) is not OwnerCorporateActionPreparedIntent:
            raise ValueError("intent constructor differs")
        intent.__post_init__()
        if (
            type(owner_user_id) is not int
            or type(account_id) is not int
            or intent.owner_user_id != owner_user_id
            or intent.account_id != account_id
            or type(as_of) is not datetime
            or as_of.tzinfo is None
            or as_of.utcoffset() is None
            or not intent.prepared_at <= as_of < intent.valid_until
        ):
            raise ValueError("intent is expired, future or cross-owner")
        return intent
    except (
        ValueError,
        TypeError,
        OverflowError,
        UnicodeError,
        binascii.Error,
        zlib.error,
        InvalidOperation,
    ) as error:
        raise _blocked() from error
