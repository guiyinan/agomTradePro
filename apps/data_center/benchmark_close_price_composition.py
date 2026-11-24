"""Read the current, locked price publication for an exact Portfolio benchmark close."""

from datetime import date, datetime

from django.db import connections

from apps.data_center.application.public_published_queries import get_published_price_bar_series
from apps.data_center.infrastructure.models import AssetMasterModel
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationPointerModel,
)


def locked_benchmark_close_payload(
    *, asset: str, day: date, at: datetime, using: str
) -> dict[str, object] | None:
    """Verify the public price row was derived from the current pointer that's locked through use."""
    if using != "default" or not connections[using].in_atomic_block:
        return None
    pointer = (
        CanonicalPublicationPointerModel.objects.using(using)
        .select_for_update()
        .filter(dataset_key="equity.price.bar", publication_key="current")
        .first()
    )
    if pointer is None or pointer.publication_id is None:
        return None
    payload = get_published_price_bar_series(
        asset, publication_key="current", start=day, end=day, limit=1, knowledge_cutoff=at
    )
    if str(pointer.publication_id) != payload.get(
        "publication_id"
    ) or pointer.publication_hash != payload.get("publication_hash"):
        return None
    security = (
        AssetMasterModel.objects.using(using)
        .select_for_update()
        .filter(code=asset, is_active=True, currency="CNY", list_date__lte=day)
        .first()
    )
    if security is None or (security.delist_date is not None and security.delist_date <= day):
        return None
    return payload | {
        "benchmark_asset_class": security.asset_type,
        "benchmark_venue": security.exchange,
    }
