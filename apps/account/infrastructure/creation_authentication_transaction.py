"""Hold real credential and identity rows through canonical account creation."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import cast

from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError, connections, transaction
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.infrastructure.account_actor_authority_raw_source_publisher_v3 import (
    SessionProofV3,
    _prove_session,
    _request_user_id,
    _require_user_database_alias,
    _verify_session_user_hash,
)
from apps.account.infrastructure.identity_models import AccountProfileModel, UserAccessTokenModel
from core.exceptions import AuthenticationError, ExternalServiceError


def _same_identity(user: object, *, user_id: int, using: str) -> None:
    """Require the real backend's identity to remain on the selected database."""

    _require_user_database_alias(user, using)
    if _request_user_id(user) != user_id:
        raise AuthenticationError("Authentication identity changed")


def _lock_token(token: object, *, user_id: int, using: str) -> UserAccessTokenModel:
    """Lock the original token without locking joined User rows out of order."""

    if not isinstance(token, UserAccessTokenModel) or token._state.db != using:
        raise AuthenticationError("Token authentication is unavailable")
    if type(token.pk) is not int or token.pk <= 0:
        raise AuthenticationError("Token authentication is unavailable")
    stored = UserAccessTokenModel.objects.using(using).select_for_update().get(pk=token.pk)
    if (
        stored.user_id != user_id
        or stored.key != token.key
        or stored.is_active is not True
        or stored.revoked_at is not None
        or stored.access_level != UserAccessTokenModel.ACCESS_LEVEL_READ_WRITE
    ):
        raise AuthenticationError("Token cannot authorize account creation")
    return stored


@contextmanager
def authenticated_creation_transaction(
    *,
    using: str,
    mode: str,
    authenticated_user: object,
    session: object,
    token: object,
    reauthenticate: Callable[[], tuple[object, object]],
) -> Iterator[CanonicalAccountCreationRequester]:
    """Lock credential then User/Profile, rechecking authentication before commit.

    These facts authorize only the current creation request. They do not publish
    Session-derived authority sources, owner assignments or human approvals.
    """

    if type(using) is not str or not using or using.strip() != using:
        raise ExternalServiceError("Creation authentication database is unavailable")
    if mode not in {"session", "token", "internal"}:
        raise AuthenticationError("Unsupported creation authentication")
    try:
        connection = connections[using]
        if connection.vendor != "postgresql":
            raise ExternalServiceError("Creation authentication requires PostgreSQL")
        _require_user_database_alias(authenticated_user, using)
        user_id = _request_user_id(authenticated_user)
        proof = cast(SessionProofV3, session)
        with transaction.atomic(using=using):
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                if cursor.fetchone() != ("read committed",):
                    raise ExternalServiceError("Creation authentication requires READ COMMITTED")
            locked_token = None
            if mode == "session":
                if session is None or not callable(getattr(session, "get", None)):
                    raise AuthenticationError("Session is unavailable")
                _prove_session(
                    authenticated_user=authenticated_user,
                    session=proof,
                    using=using,
                    now=timezone.now(),
                )
            elif mode == "token":
                locked_token = _lock_token(token, user_id=user_id, using=using)
            user = User.objects.using(using).select_for_update().get(pk=user_id)
            profile = (
                AccountProfileModel.objects.using(using).select_for_update().get(user_id=user_id)
            )

            def verify() -> None:
                """Revalidate revocable facts and time after any lock wait or work."""

                user.refresh_from_db(using=using)
                profile.refresh_from_db(using=using)
                if user.is_active is not True or profile.user_id != user_id:
                    raise AuthenticationError("Account identity is no longer active")
                if mode == "session":
                    _prove_session(
                        authenticated_user=user,
                        session=proof,
                        using=using,
                        now=timezone.now(),
                    )
                    _verify_session_user_hash(proof, user)
                elif profile.mcp_enabled is not True:
                    raise AuthenticationError("MCP access is disabled")
                if mode == "token":
                    _lock_token(token, user_id=user_id, using=using)
                current_user, current_token = reauthenticate()
                _same_identity(current_user, user_id=user_id, using=using)
                if mode == "token" and (
                    not isinstance(current_token, UserAccessTokenModel)
                    or locked_token is None
                    or current_token._state.db != using
                    or current_token.pk != locked_token.pk
                    or current_token.key != locked_token.key
                ):
                    raise AuthenticationError("Authentication credential changed")

            verify()
            yield CanonicalAccountCreationRequester(
                actor_id=f"django-user:{user_id}", user_id=user_id
            )
            verify()
    except AuthenticationError:
        raise
    except (
        ObjectDoesNotExist,
        AccountActorAuthorityRawSourceV3Unavailable,
        AccountActorAuthorityRawSourceV3Corruption,
    ) as error:
        raise AuthenticationError("Creation authentication is no longer valid") from error
    except (DatabaseError, ConnectionDoesNotExist) as error:
        raise ExternalServiceError("Creation authentication storage is unavailable") from error
