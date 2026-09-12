"""Bind a real Session-authenticated request to the policy owner transaction."""

from contextlib import AbstractContextManager

from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request

from apps.account.application.owner_policy_authorization_source import (
    OwnerPolicyAuthorizationSource,
)
from apps.account.application.single_owner_policy_publication_settings import (
    SingleOwnerPolicyPublicationSettings,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.infrastructure.single_owner_policy_authentication import (
    authenticated_single_owner_policy_transaction,
)
from core.exceptions import AuthenticationError


def authenticated_policy_publication_transaction(
    *,
    request: Request,
    using: str,
    settings: SingleOwnerPolicyPublicationSettings,
    source: OwnerPolicyAuthorizationSource,
) -> AbstractContextManager[CanonicalAccountCreationRequester]:
    """Require the exact Session backend and repeat its CSRF checks through commit."""
    if not isinstance(request, Request):
        raise AuthenticationError("A real authenticated policy publication request is required")
    authenticator = request.successful_authenticator
    if type(authenticator) is not SessionAuthentication:
        raise AuthenticationError("Policy publication requires Session authentication")

    def reauthenticate() -> tuple[object, object]:
        """Repeat the successful backend rather than trusting cached request identity."""
        result = authenticator.authenticate(request)
        if result is None:
            raise AuthenticationError("Policy publication authentication is no longer available")
        return result[0], result[1]

    return authenticated_single_owner_policy_transaction(
        using=using,
        authenticated_user=request.user,
        session=getattr(request._request, "session", None),
        reauthenticate=reauthenticate,
        settings=settings,
        source=source,
    )
