"""Connect real request authentication to the canonical creation transaction."""

import os

from django.db import DEFAULT_DB_ALIAS
from rest_framework.request import Request

from apps.account.creation_authentication_composition import (
    authenticated_account_creation_transaction,
)
from apps.simulated_trading.application.canonical_account_creation_input import (
    CanonicalAccountCreationInput,
)
from apps.simulated_trading.application.canonical_account_creation_row import (
    CanonicalAccountCreationRowUnavailable,
)
from core.integration.account_creation_evidence_runtime import (
    get_active_account_creation_evidence_settings,
)
from core.integration.canonical_account_creation import (
    CanonicalAccountCreationResult,
    create_canonical_account,
)


def create_authenticated_canonical_account(
    *,
    request: Request,
    parameters: CanonicalAccountCreationInput,
    using: str = DEFAULT_DB_ALIAS,
    environment: str | None = None,
) -> CanonicalAccountCreationResult:
    """Create or replay while the real authentication locks remain held.

    Creation evidence configuration comes from one active server snapshot.
    Missing configuration never falls back to a provenance-free row write.
    The authentication context also rechecks expiry before committing.
    """

    if type(parameters) is not CanonicalAccountCreationInput:
        raise TypeError("parameters must be exact canonical creation input")
    if environment is None:
        module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
        environment = "production" if module.endswith(".production") else "development"
    settings = get_active_account_creation_evidence_settings(environment)
    if settings is None:
        raise CanonicalAccountCreationRowUnavailable(
            "canonical account creation configuration is unavailable"
        )
    with authenticated_account_creation_transaction(request=request, using=using) as requester:
        return create_canonical_account(
            request=parameters.bind(requester), using=using, settings=settings
        )
