"""Authentication adapters for audit ingest APIs."""

from typing import Any

from rest_framework import authentication

from apps.account.interface.authentication import MultiTokenAuthentication


class AuditIngestTokenAuthentication(MultiTokenAuthentication):
    """Authenticate audit metadata writes without elevating a read-only token."""

    def authenticate(self, request: Any) -> tuple[Any, Any] | None:
        """Validate the token while bypassing the normal business-write restriction."""

        return authentication.TokenAuthentication.authenticate(self, request)

    def authenticate_header(self, request: Any) -> str | None:
        """Keep unsigned or invalid-signature requests on the existing 403 contract."""

        return None
