import hashlib
import hmac
import time

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import authentication, exceptions
from rest_framework.permissions import SAFE_METHODS

from apps.account.application.repository_provider import get_account_interface_repository


def _account_interface_repository():
    """Return the lightweight account interface repository."""

    return get_account_interface_repository()


class MultiTokenAuthentication(authentication.TokenAuthentication):
    keyword = "Token"

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None

        user, token = result
        if request.method not in SAFE_METHODS and not getattr(token, "allows_write", True):
            raise exceptions.PermissionDenied("This token is read-only and cannot perform write operations.")
        return user, token

    def authenticate_credentials(self, key):
        token = _account_interface_repository().get_active_access_token(key)
        if token is None:
            raise exceptions.AuthenticationFailed("Invalid token.")

        user = token.user
        if not user.is_active:
            raise exceptions.AuthenticationFailed("User inactive or deleted.")

        profile = getattr(user, "account_profile", None)
        if profile is not None and not profile.mcp_enabled:
            raise exceptions.AuthenticationFailed("MCP access disabled.")

        _account_interface_repository().touch_access_token(token)
        return (user, token)


class TerminalInternalAuthentication(authentication.BaseAuthentication):
    """Authenticate internal terminal/MCP SDK calls as the originating user."""

    SIGNATURE_TTL = 300
    HEADER_SIGNATURE = "HTTP_X_AGOM_INTERNAL_SIGNATURE"
    HEADER_TIMESTAMP = "HTTP_X_AGOM_INTERNAL_TIMESTAMP"
    HEADER_USER_ID = "HTTP_X_AGOM_INTERNAL_USER_ID"
    HEADER_USERNAME = "HTTP_X_AGOM_INTERNAL_USERNAME"

    def authenticate(self, request):
        signature = request.META.get(self.HEADER_SIGNATURE, "").strip()
        if not signature:
            return None

        timestamp = request.META.get(self.HEADER_TIMESTAMP, "").strip()
        user_id = request.META.get(self.HEADER_USER_ID, "").strip()
        username = request.META.get(self.HEADER_USERNAME, "").strip()

        if not timestamp or not user_id:
            raise exceptions.AuthenticationFailed("Incomplete internal auth headers.")

        secret = getattr(settings, "AGOMTRADEPRO_INTERNAL_AUTH_SECRET", "").strip()
        if not secret:
            raise exceptions.AuthenticationFailed("Internal auth is not configured.")

        try:
            request_ts = int(timestamp)
            target_user_id = int(user_id)
        except (TypeError, ValueError):
            raise exceptions.AuthenticationFailed("Invalid internal auth headers.") from None

        if abs(int(time.time()) - request_ts) > self.SIGNATURE_TTL:
            raise exceptions.AuthenticationFailed("Internal auth signature expired.")

        payload = self._build_signature_payload(
            timestamp=timestamp,
            method=request.method,
            path=request.get_full_path(),
            user_id=str(target_user_id),
            username=username,
        )
        expected_signature = hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise exceptions.AuthenticationFailed("Invalid internal auth signature.")

        user = get_user_model()._default_manager.filter(pk=target_user_id).first()
        if user is None or not user.is_active:
            raise exceptions.AuthenticationFailed("Internal auth user is inactive or missing.")
        if username and user.username != username:
            raise exceptions.AuthenticationFailed("Internal auth user mismatch.")

        return (user, None)

    @staticmethod
    def _build_signature_payload(
        *,
        timestamp: str,
        method: str,
        path: str,
        user_id: str,
        username: str,
    ) -> str:
        normalized_path = path or "/"
        return ":".join(
            [
                timestamp,
                method.upper(),
                normalized_path,
                user_id,
                username or "",
            ]
        )
