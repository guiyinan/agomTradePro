from django.utils import timezone
from rest_framework import authentication, exceptions

from apps.account.infrastructure.models import UserAccessTokenModel


class MultiTokenAuthentication(authentication.TokenAuthentication):
    keyword = "Token"
    model = UserAccessTokenModel

    def authenticate_credentials(self, key):
        try:
            token = self.get_model()._default_manager.select_related(
                "user",
                "user__account_profile",
            ).get(key=key, is_active=True)
        except self.get_model().DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid token.")

        user = token.user
        if not user.is_active:
            raise exceptions.AuthenticationFailed("User inactive or deleted.")

        profile = getattr(user, "account_profile", None)
        if profile is not None and not profile.mcp_enabled:
            raise exceptions.AuthenticationFailed("MCP access disabled.")

        token.last_used_at = timezone.now()
        token.save(update_fields=["last_used_at", "updated_at"])
        return (user, token)
