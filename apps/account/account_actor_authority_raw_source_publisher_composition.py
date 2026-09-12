"""Composition root for authenticated Account raw authority publication."""

from __future__ import annotations

from typing import cast

from apps.account.application.account_actor_authority_raw_source_publisher_v3 import (
    PublishAccountActorAuthorityRawSourceV3,
)
from apps.account.infrastructure.account_actor_authority_raw_source_publisher_v3 import (
    SessionProofV3,
    build_account_actor_authority_raw_source_publisher_gateway,
)


def build_account_actor_authority_raw_source_publisher(
    *,
    authenticated_user: object,
    session: object,
    using: str = "default",
) -> PublishAccountActorAuthorityRawSourceV3:
    """Build the typed publisher from the authenticated request boundary."""

    gateway = build_account_actor_authority_raw_source_publisher_gateway(
        authenticated_user=authenticated_user,
        session=cast(SessionProofV3, session),
        using=using,
    )
    return PublishAccountActorAuthorityRawSourceV3(gateway)


__all__ = ["build_account_actor_authority_raw_source_publisher"]
