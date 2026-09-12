"""Resolve declaration bytes against explicit server publication selectors."""

from datetime import UTC, datetime

from apps.account.application.owner_policy_authorization_source import (
    OWNER_POLICY_AUTHORIZATION_SOURCE_KEY,
    OwnerPolicyAuthorizationSource,
    decode_owner_policy_authorization_source,
)
from apps.account.application.single_owner_policy_publication_settings import (
    SingleOwnerPolicyPublicationSettings,
    decode_single_owner_policy_publication_settings,
)
from core.integration import config_center_runtime


def get_active_owner_policy_authorization_source(
    *, environment: str, settings: SingleOwnerPolicyPublicationSettings
) -> OwnerPolicyAuthorizationSource | None:
    """Read verified declaration content; callers must still authenticate the owner.

    This checks the supplied settings selectors, not their continued activation.
    A publisher must re-read both settings and source before appending a policy.
    """
    if (
        type(environment) is not str
        or not environment
        or any(character.isspace() for character in environment)
        or type(settings) is not SingleOwnerPolicyPublicationSettings
    ):
        return None
    try:
        validated = decode_single_owner_policy_publication_settings(settings.to_payload())
        validated.deadline_at(datetime.now(UTC))
        value = config_center_runtime.get_active_runtime_value(
            environment=environment, definition_key=OWNER_POLICY_AUTHORIZATION_SOURCE_KEY
        )
        if value is None:
            return None
        source = decode_owner_policy_authorization_source(value)
        if (
            source.source_id != validated.authorization_source_id
            or source.source_version != validated.authorization_source_version
            or source.content_hash != validated.authorization_content_hash
            or source.owner_username != validated.owner_username
            or source.declared_at > datetime.now(UTC)
        ):
            return None
        return source
    except (TypeError, ValueError, RuntimeError):
        return None
