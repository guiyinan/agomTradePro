"""Read the issued and presently unrevised canonical price member for an exact benchmark day."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from django.db import connections
from django.db.models import CharField, Subquery
from django.db.models.functions import Cast

from apps.data_center.application.public_published_queries import (
    get_current_publication_freshness_gate,
    get_publication_as_of,
)
from apps.data_center.domain.market_time import (
    cn_market_date_start_utc,
    cn_market_session_close_utc,
)
from apps.data_center.infrastructure.models import PriceBarModel
from apps.data_center.infrastructure.publication_fact_evidence import (
    publication_fact_reference_for_dataset,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    PublicationMemberModel,
    PublicationRollbackModel,
)


def _head(*, asset: str, at: datetime, using: str) -> CanonicalPublicationPointerModel | None:
    if using != "default" or not connections[using].in_atomic_block or at.utcoffset() is None:
        return None
    pointer = (
        CanonicalPublicationPointerModel.objects.using(using)
        .select_for_update()
        .filter(
            dataset_key="equity.price.bar",
            publication_key="current",
        )
        .first()
    )
    if pointer is None or pointer.publication_id is None:
        return None
    gate = get_current_publication_freshness_gate(
        "equity.price.bar", "current", as_of=at, asset_code=asset
    )
    if (
        not gate
        or gate.get("asset_code") != asset
        or gate.get("freshness_scope") != "asset"
        or (gate.get("publication_id"), gate.get("publication_hash"))
        != (str(pointer.publication_id), pointer.publication_hash)
        or gate.get("must_not_use_for_decision") is not False
        or gate.get("blocked_reason")
    ):
        return None
    return pointer


def _member(
    *,
    publication_id: UUID,
    asset: str,
    day: date,
    using: str,
    expected_price: Decimal | None = None,
) -> PublicationMemberModel | None:
    observed = cn_market_session_close_utc(day)
    candidates = PriceBarModel.objects.using(using).filter(
        asset_code=asset, bar_date=day, freq="1d", adjustment="none"
    )
    pks = candidates.values_list(Cast("pk", output_field=CharField()), flat=True)
    members = list(
        PublicationMemberModel.objects.using(using)
        .filter(
            dataset_key="equity.price.bar",
            publication_id=publication_id,
            fact_table=PriceBarModel._meta.db_table,
            fact_pk__in=Subquery(pks),
            observed_at=observed,
        )
        .order_by("pk")[:2]
    )
    if len(members) != 1:
        return None
    member = members[0]
    fact = candidates.select_for_update().filter(pk=int(member.fact_pk)).first()
    if fact is None or (expected_price is not None and fact.close != expected_price):
        return None
    reference = publication_fact_reference_for_dataset(fact, dataset_key="equity.price.bar")
    if (
        reference.fact_content_hash,
        reference.raw_payload_hash,
        reference.natural_key,
        reference.source,
        reference.source_record_id,
        reference.revision_number,
        reference.quality_status,
        reference.observed_at,
    ) != (
        member.fact_content_hash,
        member.raw_payload_hash,
        member.natural_key,
        member.source,
        member.source_record_id,
        member.revision_number,
        member.quality_status,
        member.observed_at,
    ) or reference.quality_status != "accepted":
        return None
    return member


def read_benchmark_member_hash(
    *,
    asset: str,
    day: date,
    at: datetime,
    publication_hash: str,
    expected_price: Decimal,
    using: str,
) -> str | None:
    """Pin the normalized fact selected by the verified publication at first close."""
    pointer = _head(asset=asset, at=at, using=using)
    if (
        pointer is None
        or pointer.publication_id is None
        or pointer.publication_hash != publication_hash
    ):
        return None
    member = _member(
        publication_id=pointer.publication_id,
        asset=asset,
        day=day,
        expected_price=expected_price,
        using=using,
    )
    return member.fact_content_hash if member is not None else None


def read_current_benchmark_day_member_hash(
    *, asset: str, day: date, issued_at: datetime, at: datetime, using: str
) -> str | None:
    """Re-read the original PIT member and reject subsequent corrections, withdrawals and rollbacks."""
    if (
        issued_at.utcoffset() is None
        or at.utcoffset() is None
        or not cn_market_session_close_utc(day) <= issued_at <= at
    ):
        return None
    head = _head(asset=asset, at=at, using=using)
    if head is None:
        return None
    scope = {"dataset_key": "equity.price.bar", "publication_key": "current"}
    if (
        PublicationRollbackModel.objects.using(using)
        .filter(**scope, observed_at__gte=issued_at)
        .exists()
    ):
        return None
    original = get_publication_as_of("equity.price.bar", "current", issued_at)
    if (
        not original
        or original.get("must_not_use_for_decision") is not False
        or original.get("blocked_reason")
    ):
        return None
    original_id = UUID(str(original["publication_id"]))
    member = _member(publication_id=original_id, asset=asset, day=day, using=using)
    if member is None:
        return None
    successors = (
        CanonicalPublicationModel.objects.using(using)
        .filter(**scope, published_at__gte=issued_at)
        .exclude(pk=original_id)
    )
    # A later same-day publication which drops this member, or any later published
    # revision of this asset/day, invalidates the prior close. A routine later
    # session containing only that new day's prices leaves the original intact.
    affected = PublicationMemberModel.objects.using(using).filter(
        publication_id__in=Subquery(successors.values("pk")),
        dataset_key="equity.price.bar",
        natural_key__startswith=asset + ":",
        observed_at=cn_market_session_close_utc(day),
    )
    if (
        successors.filter(as_of__lt=cn_market_date_start_utc(day + timedelta(days=1)))
        .exclude(pk__in=Subquery(affected.values("publication_id")))
        .exists()
    ):
        return None
    # New publications may include an explicit negative scope instead of a row.
    # Bound the exceptional-path scan and fail closed on unsupported histories.
    scope_changes = list(
        successors.exclude(scope_blocks=[]).values_list("scope_blocks", flat=True)[:65]
    )
    if len(scope_changes) > 64:
        return None
    for blocks in scope_changes:
        if not isinstance(blocks, list) or any(
            not isinstance(block, dict)
            or (
                block.get("asset_code") == asset
                and block.get("target_trade_date") in (None, "", day.isoformat())
            )
            for block in blocks
        ):
            return None
    if affected.exclude(
        fact_table=member.fact_table,
        fact_pk=member.fact_pk,
        fact_content_hash=member.fact_content_hash,
        raw_payload_hash=member.raw_payload_hash,
        source=member.source,
        natural_key=member.natural_key,
        revision_number=member.revision_number,
        quality_status=member.quality_status,
    ).exists():
        return None
    return member.fact_content_hash
