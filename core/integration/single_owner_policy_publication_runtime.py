"""Read one complete server-owned policy publication configuration snapshot."""

from datetime import UTC, datetime

from apps.account.application.single_owner_policy_publication_settings import (
    SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_KEY,
    SingleOwnerPolicyPublicationSettings,
    decode_single_owner_policy_publication_settings,
)
from core.integration import config_center_runtime


def get_active_single_owner_policy_publication_settings(
    environment: str,
) -> SingleOwnerPolicyPublicationSettings | None:
    """Decode one active snapshot; declaration references are never authentication."""
    if (
        type(environment) is not str
        or not environment
        or any(character.isspace() for character in environment)
    ):
        return None
    try:
        value = config_center_runtime.get_active_runtime_value(
            environment=environment, definition_key=SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_KEY
        )
        if value is None:
            return None
        settings = decode_single_owner_policy_publication_settings(value)
        settings.deadline_at(datetime.now(UTC))
        return settings
    except (TypeError, ValueError, RuntimeError):
        return None
