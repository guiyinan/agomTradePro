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
