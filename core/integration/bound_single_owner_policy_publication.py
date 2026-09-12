"""Publish policy from a real request, explicit declaration and exact binding."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from rest_framework.request import Request

from apps.account.application.owner_policy_authorization_source import (
    OwnerPolicyAuthorizationSource,
)
from apps.account.application.single_owner_policy_publication import (
    PublishSingleOwnerAuthorityPolicyV1Command,
)
from apps.account.application.single_owner_policy_publication_settings import (
    SingleOwnerPolicyPublicationSettings,
)
from apps.account.domain.single_owner_authority_policy_v1 import SingleOwnerAuthorityPolicyV1
from apps.account.policy_publication_authentication_composition import (
    authenticated_policy_publication_transaction,
)
from apps.account.policy_publication_binding_composition import resolve_policy_publication_binding
from apps.account.single_owner_policy_publication_composition import (
    build_single_owner_policy_publisher,
)
from core.exceptions import ExternalServiceError
from core.integration.owner_policy_authorization_source_runtime import (
    get_active_owner_policy_authorization_source,
)
from core.integration.single_owner_policy_publication_runtime import (
    get_active_single_owner_policy_publication_settings,
)


def _token(value: object, name: str) -> None:
    """Reject empty, coerced, unbounded or whitespace-containing request selectors."""
    if (
        type(value) is not str
        or not value
        or len(value) > 192
        or any(char.isspace() for char in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


@dataclass(frozen=True, slots=True)
class PublishBoundSingleOwnerPolicyCommand:
    """Accept only a request key and the exact existing account binding selector."""

    idempotency_key: str
    binding_id: str
    binding_version: str
    binding_content_hash: str

    def __post_init__(self) -> None:
        """Validate selectors before attempting authentication or persistence."""
        for name in ("idempotency_key", "binding_id", "binding_version"):
            _token(getattr(self, name), name)
        if (
            type(self.binding_content_hash) is not str
            or len(self.binding_content_hash) != 64
            or any(char not in "0123456789abcdef" for char in self.binding_content_hash)
        ):
            raise ValueError("binding_content_hash must be a lowercase SHA-256 digest")


def _identity(domain: str, values: list[str | int]) -> str:
    """Generate an unambiguous stable server identity without retaining raw request keys."""
    return hashlib.sha256(
        json.dumps([domain, *values], ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _current_inputs(
    environment: str,
) -> tuple[SingleOwnerPolicyPublicationSettings, OwnerPolicyAuthorizationSource] | None:
    """Bracket declaration lookup with settings reads to reject a changed profile."""
    settings = get_active_single_owner_policy_publication_settings(environment)
    if settings is None:
        return None
    source = get_active_owner_policy_authorization_source(
        environment=environment, settings=settings
    )
    if (
        source is None
        or get_active_single_owner_policy_publication_settings(environment) != settings
    ):
        return None
    return settings, source


@dataclass(frozen=True, slots=True)
class _BoundCurrentInputs:
    environment: str
    expected: tuple[SingleOwnerPolicyPublicationSettings, OwnerPolicyAuthorizationSource]

    def read_current(
        self,
    ) -> tuple[SingleOwnerPolicyPublicationSettings, OwnerPolicyAuthorizationSource] | None:
        """Require the exact configuration used to authenticate this publication."""
        current = _current_inputs(self.environment)
        return current if current == self.expected else None


def publish_bound_single_owner_policy(
    *,
    request: Request,
    command: PublishBoundSingleOwnerPolicyCommand,
    environment: str,
    using: str,
) -> SingleOwnerAuthorityPolicyV1:
    """Authenticate, resolve scope and publish atomically with stable retry identity."""
    if type(command) is not PublishBoundSingleOwnerPolicyCommand:
        raise TypeError("An exact bound policy publication command is required")
    command.__post_init__()
    _token(environment, "environment")
    _token(using, "using")
    inputs = _current_inputs(environment)
    if inputs is None:
        raise ExternalServiceError("Policy publication configuration or declaration is unavailable")
    settings, source = inputs
    with authenticated_policy_publication_transaction(
        request=request, using=using, settings=settings, source=source
    ) as requester:
        binding = resolve_policy_publication_binding(
            using=using,
            binding_id=command.binding_id,
            binding_version=command.binding_version,
            expected_content_hash=command.binding_content_hash,
            requester=requester,
            as_of=datetime.now(UTC),
        )
        reader = _BoundCurrentInputs(environment=environment, expected=inputs)
        publisher = build_single_owner_policy_publisher(using=using, current_inputs=reader)
        policy = publisher.execute(
            PublishSingleOwnerAuthorityPolicyV1Command(
                policy_id=_identity(
                    "account.policy-publication.request.v1",
                    [requester.user_id, command.idempotency_key],
                ),
                policy_version=_identity(
                    "account.policy-publication.binding.v1",
                    [command.binding_id, command.binding_version, command.binding_content_hash],
                ),
                account_namespace=binding.account_namespace_claim,
                account_id=binding.account_id_claim,
            ),
            requester=requester,
        )
        checked = resolve_policy_publication_binding(
            using=using,
            binding_id=command.binding_id,
            binding_version=command.binding_version,
            expected_content_hash=command.binding_content_hash,
            requester=requester,
            as_of=datetime.now(UTC),
        )
        if checked != binding or reader.read_current() is None:
            raise ExternalServiceError("Policy publication inputs changed before commit")
        if type(policy) is not SingleOwnerAuthorityPolicyV1 or not policy.is_current_at(
            datetime.now(UTC)
        ):
            raise ExternalServiceError("Published policy is no longer current before commit")
        return policy
