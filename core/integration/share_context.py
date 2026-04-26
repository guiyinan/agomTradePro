"""Bridge helpers for share-related UI context."""

from __future__ import annotations

from apps.share.application.query_services import list_share_links_for_account_owner
from apps.share.domain.entities import ShareLinkEntity


def get_account_owner_share_links(owner_id: int, account_id: int) -> list[ShareLinkEntity]:
    """Return share links for one account owner and account."""

    return list_share_links_for_account_owner(
        owner_id=owner_id,
        account_id=account_id,
    )
