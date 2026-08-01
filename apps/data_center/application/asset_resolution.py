"""Read-only asset identity resolution helpers."""

from __future__ import annotations

from apps.data_center.domain.entities import AssetMaster
from apps.data_center.domain.protocols import AssetRepositoryProtocol


def resolve_unique_exact_asset_name(
    repo: AssetRepositoryProtocol,
    raw_query: str,
) -> AssetMaster | None:
    """Return one exact name/short-name match and reject ambiguous search results."""

    query = str(raw_query or "").strip()
    candidates = repo.search(query, limit=20)
    matches = [item for item in candidates if query in {item.name, item.short_name}]
    return matches[0] if len(matches) == 1 else None
