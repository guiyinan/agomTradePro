"""Application-level query helpers for share consumers."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.share.application.use_cases import ShareLinkUseCases
from apps.share.domain.entities import ShareLinkEntity


def list_share_links_for_account_owner(owner_id: int, account_id: int) -> list[ShareLinkEntity]:
    """Return share links for one account owner, newest first."""

    links = ShareLinkUseCases().list_share_links(
        owner_id=owner_id,
        account_id=account_id,
    )
    return sorted(
        links,
        key=lambda link: link.created_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
