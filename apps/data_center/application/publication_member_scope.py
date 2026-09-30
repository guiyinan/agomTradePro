"""Shared member-scope selectors for publication-bound decision reads."""

from __future__ import annotations

from collections.abc import Sequence

from apps.data_center.domain.control_plane import PublicationMember, PublicationScopeBlock


def select_asset_members(
    members: Sequence[PublicationMember],
    asset_code: str,
) -> tuple[PublicationMember, ...]:
    """Select publication members whose natural key belongs to one asset."""

    normalized_asset_code = asset_code.strip().upper()
    return tuple(
        member
        for member in members
        if member.natural_key.split(":", 1)[0].strip().upper() == normalized_asset_code
    )


def find_scope_block(
    scope_blocks: Sequence[PublicationScopeBlock],
    asset_code: str,
) -> PublicationScopeBlock | None:
    """Find the recorded publication scope block for one asset."""

    normalized_asset_code = asset_code.strip().upper()
    return next(
        (
            block
            for block in scope_blocks
            if block.asset_code.strip().upper() == normalized_asset_code
        ),
        None,
    )


def scope_block_reason(scope_block: PublicationScopeBlock | None) -> str:
    """Return a stable fail-closed reason when a scope member is absent."""

    return (
        scope_block.reason_code
        if scope_block is not None
        else "canonical_publication_members_missing"
    )


__all__ = ["find_scope_block", "scope_block_reason", "select_asset_members"]
