"""Narrow actual browser authentication before owner confirmation orchestration."""

from __future__ import annotations

from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.base import SessionBase
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request

from apps.simulated_trading.application.fee_correction import FeeCorrectionBlockedError
from apps.simulated_trading.application.fee_correction_confirmation import BrowserContext


def fee_correction_browser_context(request: Request) -> BrowserContext:
    """Extract session claims; the owner repository must re-prove them under locks."""

    session = getattr(request, "session", None)
    actor_id = getattr(request.user, "pk", None)
    if (
        type(request.successful_authenticator) is not SessionAuthentication
        or request.user.is_authenticated is not True
        or type(actor_id) is not int
        or actor_id <= 0
        or not isinstance(session, SessionBase)
    ):
        raise _session_unavailable()
    session_key = session.session_key
    backend = session.get(BACKEND_SESSION_KEY)
    auth_hash = session.get(HASH_SESSION_KEY)
    if (
        type(session_key) is not str
        or not session_key
        or session.get(SESSION_KEY) != str(actor_id)
        or type(backend) is not str
        or not backend
        or type(auth_hash) is not str
        or not auth_hash
    ):
        raise _session_unavailable()
    return BrowserContext(
        actor_user_id=actor_id,
        session_key=session_key,
        auth_backend=backend,
        auth_session_hash=auth_hash,
    )


def _session_unavailable() -> FeeCorrectionBlockedError:
    """Avoid disclosing session material in authentication failures."""

    return FeeCorrectionBlockedError(
        "请使用有效的登录会话准备并确认费用更正。",
        code="FEE_CORRECTION_AUTHORITY_UNAVAILABLE",
    )
