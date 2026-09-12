"""Resolve publication scope from permanent creation evidence on the locked alias."""

from datetime import datetime

from django.db import connections
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.canonical_account_creation_binding_v2 import (
    GetExactCanonicalAccountCreationBindingV2,
    GetExactCanonicalAccountCreationBindingV2Command,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)
from core.exceptions import AuthenticationError, ExternalServiceError


def resolve_policy_publication_binding(
    *,
    using: str,
    binding_id: str,
    binding_version: str,
    expected_content_hash: str,
    requester: CanonicalAccountCreationRequester,
    as_of: datetime,
) -> CanonicalAccountCreationBindingV2:
    """Require the authenticated user's exact binding within its outer transaction.

    The caller supplies an actual server cutoff and authenticated requester.
    Permanent binding knowledge does not make the old physical observation current.
    """
    if type(requester) is not CanonicalAccountCreationRequester:
        raise AuthenticationError("An authenticated publication requester is required")
    requester.__post_init__()
    if type(using) is not str or not using or any(character.isspace() for character in using):
        raise ExternalServiceError("Policy binding database is unavailable")
    try:
        connection = connections[using]
    except ConnectionDoesNotExist as error:
        raise ExternalServiceError("Policy binding database is unavailable") from error
    if connection.vendor != "postgresql" or not connection.in_atomic_block:
        raise ExternalServiceError("Policy binding requires the outer PostgreSQL transaction")
    reader = GetExactCanonicalAccountCreationBindingV2(
        DjangoCanonicalAccountCreationConsumptionRepository(using=using)
    )
    binding = reader.execute(
        GetExactCanonicalAccountCreationBindingV2Command(
            binding_id=binding_id,
            binding_version=binding_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )
    )
    if binding is None:
        raise ExternalServiceError("The exact policy account binding is unavailable")
    if (
        binding.allocation.requested_by != requester
        or binding.allocation.requested_row_user_id != requester.user_id
    ):
        raise AuthenticationError("The policy account binding belongs to another requester")
    return binding
