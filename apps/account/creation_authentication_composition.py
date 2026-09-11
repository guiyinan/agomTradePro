"""Bind supported real DRF authentication to the Account creation transaction."""

from contextlib import AbstractContextManager

from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request

from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.infrastructure.creation_authentication_transaction import (
    authenticated_creation_transaction,
)
from apps.account.interface.authentication import (
    MultiTokenAuthentication,
    TerminalInternalAuthentication,
)
from core.exceptions import AuthenticationError


def authenticated_account_creation_transaction(
    *, request: Request, using: str
) -> AbstractContextManager[CanonicalAccountCreationRequester]:
    """Use only a supported successful authenticator, never client identity fields."""

    if not isinstance(request, Request):
        raise AuthenticationError("A real authenticated request is required")
    authenticator = request.successful_authenticator
    if type(authenticator) is SessionAuthentication:
        mode = "session"
    elif type(authenticator) is MultiTokenAuthentication:
        mode = "token"
    elif type(authenticator) is TerminalInternalAuthentication:
        mode = "internal"
    else:
        raise AuthenticationError("Unsupported account creation authentication")

    def reauthenticate() -> tuple[object, object]:
        """Repeat the selected backend, including CSRF, write permission or HMAC TTL."""

        if authenticator is None:
            raise AuthenticationError("Authentication is unavailable")
        result = authenticator.authenticate(request)
        if result is None:
            raise AuthenticationError("Authentication is no longer available")
        return result[0], result[1]

    return authenticated_creation_transaction(
        using=using,
        mode=mode,
        authenticated_user=request.user,
        session=getattr(request._request, "session", None),
        token=request.auth,
        reauthenticate=reauthenticate,
    )
