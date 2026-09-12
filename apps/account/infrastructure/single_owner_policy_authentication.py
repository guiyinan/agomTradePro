"""Bind a declared policy owner to locked current Session and User facts."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError
from django.utils import timezone

from apps.account.application.owner_policy_authorization_source import (
    OwnerPolicyAuthorizationSource,
)
from apps.account.application.single_owner_policy_publication_settings import (
    SingleOwnerPolicyPublicationSettings,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.infrastructure.account_actor_authority_raw_source_publisher_v3 import (
    _effective_rbac_role,
)
from apps.account.infrastructure.creation_authentication_transaction import (
    authenticated_creation_transaction,
)
from apps.account.infrastructure.identity_models import AccountProfileModel
from core.exceptions import AuthenticationError, ExternalServiceError


@contextmanager
def authenticated_single_owner_policy_transaction(
    *,
    using: str,
    authenticated_user: object,
    session: object,
    reauthenticate: Callable[[], tuple[object, object]],
    settings: SingleOwnerPolicyPublicationSettings,
    source: OwnerPolicyAuthorizationSource,
) -> Iterator[CanonicalAccountCreationRequester]:
    """Authenticate and lock the designated owner before and after publication.

    The reused credential transaction only proves the request identity. This
    boundary additionally verifies the declaration and current administrator
    facts. Callers must revalidate active configuration and account scope.
    No policy, approval or authority is written by this context manager.
    """
    if (
        type(settings) is not SingleOwnerPolicyPublicationSettings
        or type(source) is not OwnerPolicyAuthorizationSource
    ):
        raise AuthenticationError("Explicit owner declaration and settings are required")
    settings.__post_init__()
    source.__post_init__()
    if (
        source.source_id != settings.authorization_source_id
        or source.source_version != settings.authorization_source_version
        or source.content_hash != settings.authorization_content_hash
        or source.owner_username != settings.owner_username
    ):
        raise AuthenticationError("Owner declaration does not match publication settings")
    try:
        with authenticated_creation_transaction(
            using=using,
            mode="session",
            authenticated_user=authenticated_user,
            session=session,
            token=None,
            reauthenticate=reauthenticate,
        ) as requester:
            user = User.objects.using(using).select_for_update().get(pk=requester.user_id)
            profile = (
                AccountProfileModel.objects.using(using)
                .select_for_update()
                .get(user_id=requester.user_id)
            )

            def verify() -> None:
                """Reject revocation, renamed identities and future declarations."""
                user.refresh_from_db(using=using)
                profile.refresh_from_db(using=using)
                if (
                    user.pk != requester.user_id
                    or user.pk != source.declared_user_id
                    or user.username != source.owner_username
                    or user.is_active is not True
                    or user.is_staff is not True
                    or profile.user_id != requester.user_id
                    or _effective_rbac_role(user, profile) != "admin"
                    or source.declared_at > timezone.now()
                ):
                    raise AuthenticationError("The designated policy owner is no longer eligible")

            verify()
            yield requester
            verify()
    except ObjectDoesNotExist as error:
        raise AuthenticationError("The designated policy owner is unavailable") from error
    except DatabaseError as error:
        raise ExternalServiceError("Policy owner authentication storage is unavailable") from error
