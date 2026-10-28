"""Compose exact price-source reads inside the established publication snapshot."""

from __future__ import annotations

from datetime import date, datetime

from django.db import DatabaseError

from apps.data_center.application.published_price_source import (
    PublishedPriceSourceResult,
    ReadPublishedPriceSource,
    validate_price_source_request,
)
from apps.data_center.application.query_services import get_current_publication_gate
from apps.data_center.composition import get_canonical_publication_repository
from apps.data_center.infrastructure.published_price_source_repository import (
    DjangoPublishedPriceSourceRepository,
)
from apps.data_center.publication_read_composition import publication_snapshot
from core.exceptions import DataFetchError, DataValidationError


def read_published_price_source(
    asset_code: str,
    *,
    trade_date: date,
    knowledge_cutoff: datetime,
    publication_key: str,
) -> PublishedPriceSourceResult:
    """Validate explicit request inputs and fail closed if the consistent read is unavailable."""
    try:
        validate_price_source_request(asset_code, trade_date, knowledge_cutoff, publication_key)
        return _read_source_snapshot(
            asset_code,
            trade_date=trade_date,
            knowledge_cutoff=knowledge_cutoff,
            publication_key=publication_key,
        )
    except DataValidationError as error:
        return PublishedPriceSourceResult(None, error.code or "price_source_request_invalid")
    except (DataFetchError, DatabaseError):
        return PublishedPriceSourceResult(None, "price_source_read_unavailable")
    except (TypeError, ValueError, OverflowError):
        return PublishedPriceSourceResult(None, "price_source_evidence_invalid")


@publication_snapshot("equity.price.bar")
def _read_source_snapshot(
    asset_code: str,
    *,
    trade_date: date,
    knowledge_cutoff: datetime,
    publication_key: str,
) -> PublishedPriceSourceResult:
    """Keep current policy, publication members and sealed source inputs in one read boundary."""
    gate = get_current_publication_gate(
        "equity.price.bar", publication_key, as_of=knowledge_cutoff, asset_code=asset_code
    )
    if gate is None or gate.get("must_not_use_for_decision") is not False:
        reason = gate.get("blocked_reason") if gate is not None else None
        return PublishedPriceSourceResult(
            None, reason if isinstance(reason, str) and reason else "canonical_publication_missing"
        )
    publication_repository = get_canonical_publication_repository()
    publication = publication_repository.get_current("equity.price.bar", publication_key)
    freshness = gate.get("freshness_status")
    if (
        publication is None
        or publication.publication_id != gate.get("publication_id")
        or publication.publication_hash != gate.get("publication_hash")
        or publication.dataset_key != "equity.price.bar"
        or publication.publication_key != publication_key
        or not isinstance(freshness, str)
        or not freshness
    ):
        return PublishedPriceSourceResult(None, "price_source_publication_identity_mismatch")
    return ReadPublishedPriceSource(DjangoPublishedPriceSourceRepository()).execute(
        asset_code=asset_code,
        trade_date=trade_date,
        knowledge_cutoff=knowledge_cutoff,
        publication=publication,
        members=tuple(publication_repository.list_members(publication.publication_id)),
        freshness_status=freshness,
    )
