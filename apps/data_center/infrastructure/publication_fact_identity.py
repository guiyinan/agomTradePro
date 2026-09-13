"""Canonical publication identities for the normalized fact tables."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from django.db import models

from apps.data_center.domain.market_time import cn_market_date_start_utc

from .models import (
    CapitalFlowFactModel,
    FinancialFactModel,
    FundNavFactModel,
    MacroFactModel,
    NewsFactModel,
    PriceBarModel,
    QuoteSnapshotModel,
    SectorMembershipFactModel,
    ValuationFactModel,
)
from .publication_fact_legacy_payload import (
    canonical_news_payload_hash,
    capital_flow_payload_hash,
    financial_payload_hash,
    fund_nav_payload_hash,
    macro_payload_hash,
    price_bar_payload_hash,
    quote_snapshot_payload_hash,
    sector_membership_payload_hash,
    valuation_payload_hash,
)


@dataclass(frozen=True, slots=True)
class PublicationFactIdentity:
    """Canonical identity and fallback evidence for one normalized fact row."""

    natural_key: str
    source: str
    observed_at: datetime
    source_record_id: str
    raw_payload_hash: str
    quality_status: str
    revision_number: int

    def __post_init__(self) -> None:
        """Reject incomplete identity values before they cross the boundary."""

        field_values: tuple[tuple[str, str], ...] = (
            ("natural_key", self.natural_key),
            ("source", self.source),
            ("source_record_id", self.source_record_id),
            ("raw_payload_hash", self.raw_payload_hash),
        )
        for field_name, value in field_values:
            if not isinstance(value, str) or not value:
                raise ValueError(f"PublicationFactIdentity.{field_name} cannot be empty")
        if not isinstance(self.quality_status, str):
            raise ValueError("PublicationFactIdentity.quality_status must be text")
        if not isinstance(self.observed_at, datetime):
            raise ValueError("PublicationFactIdentity.observed_at must be a datetime")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("PublicationFactIdentity.observed_at must be timezone-aware")
        if not isinstance(self.revision_number, int) or isinstance(self.revision_number, bool):
            raise ValueError("PublicationFactIdentity.revision_number must be an integer")
        if self.revision_number < 1:
            raise ValueError("PublicationFactIdentity.revision_number must be positive")


_DATASET_FACT_MODELS: Mapping[str, type[models.Model]] = MappingProxyType(
    {
        "market.capital_flow": CapitalFlowFactModel,
        "equity.financial.fact": FinancialFactModel,
        "fund.nav": FundNavFactModel,
        "macro.fact": MacroFactModel,
        "market.news": NewsFactModel,
        "equity.price.bar": PriceBarModel,
        "equity.quote.snapshot": QuoteSnapshotModel,
        "sector.membership": SectorMembershipFactModel,
        "equity.valuation.fact": ValuationFactModel,
    }
)


def publication_fact_model_registry() -> Mapping[str, type[models.Model]]:
    """Return the immutable dataset-to-normalized-fact model registry."""

    return _DATASET_FACT_MODELS


def build_publication_fact_identity(
    dataset_key: str,
    row: models.Model,
) -> PublicationFactIdentity:
    """Build the exact identity emitted by the selected fact repository.

    This dispatcher intentionally contains no database access.  It mirrors
    the nine repository reference producers so a frozen publication member
    can be checked against the row that produced it without importing a
    repository back into the infrastructure store.
    """

    expected_model = _DATASET_FACT_MODELS.get(dataset_key)
    if expected_model is None or not isinstance(row, expected_model):
        raise ValueError("Publication fact dataset and row model do not match")
    if dataset_key == "market.capital_flow":
        if not isinstance(row, CapitalFlowFactModel):
            raise ValueError("Publication fact row model is not capital flow")
        return _capital_flow_identity(row)
    if dataset_key == "equity.financial.fact":
        if not isinstance(row, FinancialFactModel):
            raise ValueError("Publication fact row model is not financial")
        return _financial_identity(row)
    if dataset_key == "fund.nav":
        if not isinstance(row, FundNavFactModel):
            raise ValueError("Publication fact row model is not fund NAV")
        return _fund_nav_identity(row)
    if dataset_key == "macro.fact":
        if not isinstance(row, MacroFactModel):
            raise ValueError("Publication fact row model is not macro")
        return _macro_identity(row)
    if dataset_key == "market.news":
        if not isinstance(row, NewsFactModel):
            raise ValueError("Publication fact row model is not news")
        return _news_identity(row)
    if dataset_key == "equity.price.bar":
        if not isinstance(row, PriceBarModel):
            raise ValueError("Publication fact row model is not price bar")
        return _price_bar_identity(row)
    if dataset_key == "equity.quote.snapshot":
        if not isinstance(row, QuoteSnapshotModel):
            raise ValueError("Publication fact row model is not quote snapshot")
        return _quote_snapshot_identity(row)
    if dataset_key == "sector.membership":
        if not isinstance(row, SectorMembershipFactModel):
            raise ValueError("Publication fact row model is not sector membership")
        return _sector_membership_identity(row)
    if dataset_key == "equity.valuation.fact":
        if not isinstance(row, ValuationFactModel):
            raise ValueError("Publication fact row model is not valuation")
        return _valuation_identity(row)
    raise ValueError("Publication fact dataset is not registered")


def _capital_flow_identity(row: CapitalFlowFactModel) -> PublicationFactIdentity:
    """Build the capital-flow repository identity."""

    natural_key = f"{row.asset_code}:{row.flow_date.isoformat()}:{row.source}"
    return _identity(
        natural_key=natural_key,
        source=row.source,
        observed_at=cn_market_date_start_utc(row.flow_date),
        source_record_id=row.source_record_id or natural_key,
        raw_payload_hash=row.raw_payload_hash or capital_flow_payload_hash(row),
        quality_status=row.quality_status,
        revision_number=row.revision_number,
    )


def _financial_identity(row: FinancialFactModel) -> PublicationFactIdentity:
    """Build the financial-fact repository identity."""

    if row.available_at is None:
        raise ValueError("financial publication candidate requires available_at")
    natural_key = (
        f"{row.asset_code}:{row.period_end.isoformat()}:{row.period_type}:"
        f"{row.metric_code}:{row.source}"
    )
    return _identity(
        natural_key=natural_key,
        source=row.source,
        observed_at=row.available_at,
        source_record_id=row.source_record_id or natural_key,
        raw_payload_hash=row.raw_payload_hash or financial_payload_hash(row),
        quality_status=row.quality_status,
        revision_number=row.revision_number,
    )


def _fund_nav_identity(row: FundNavFactModel) -> PublicationFactIdentity:
    """Build the fund-NAV repository identity."""

    natural_key = f"{row.fund_code}:{row.nav_date.isoformat()}:{row.source}"
    return _identity(
        natural_key=natural_key,
        source=row.source,
        observed_at=cn_market_date_start_utc(row.nav_date),
        source_record_id=row.source_record_id or natural_key,
        raw_payload_hash=row.raw_payload_hash or fund_nav_payload_hash(row),
        quality_status=row.quality_status,
        revision_number=row.revision_number,
    )


def _macro_identity(row: MacroFactModel) -> PublicationFactIdentity:
    """Build the macro-fact repository identity with its one-based revision."""

    if row.published_at is None:
        raise ValueError("macro publication candidate requires published_at")
    natural_key = (
        f"{row.indicator_code}:{row.reporting_period.isoformat()}:{row.source}:"
        f"{row.revision_number}"
    )
    return _identity(
        natural_key=natural_key,
        source=row.source,
        observed_at=cn_market_date_start_utc(row.published_at),
        source_record_id=row.source_record_id or natural_key,
        raw_payload_hash=row.raw_payload_hash or macro_payload_hash(row),
        quality_status=row.quality_status,
        revision_number=row.revision_number + 1,
    )


def _news_identity(row: NewsFactModel) -> PublicationFactIdentity:
    """Build the market-news repository identity."""

    natural_key = f"{row.source}:{row.external_id}"
    return _identity(
        natural_key=natural_key,
        source=row.source,
        observed_at=row.published_at,
        source_record_id=row.source_record_id or row.external_id or natural_key,
        raw_payload_hash=row.raw_payload_hash
        or canonical_news_payload_hash(
            asset_code=row.asset_code,
            title=row.title,
            summary=row.summary,
            url=row.url,
            published_at=row.published_at,
            source=row.source,
            external_id=row.external_id,
        ),
        quality_status=row.quality_status,
        revision_number=row.revision_number,
    )


def _price_bar_identity(row: PriceBarModel) -> PublicationFactIdentity:
    """Build the price-bar repository identity."""

    natural_key = (
        f"{row.asset_code}:{row.bar_date.isoformat()}:{row.freq}:" f"{row.adjustment}:{row.source}"
    )
    return _identity(
        natural_key=natural_key,
        source=row.source,
        observed_at=cn_market_date_start_utc(row.bar_date),
        source_record_id=row.source_record_id or natural_key,
        raw_payload_hash=row.raw_payload_hash or price_bar_payload_hash(row),
        quality_status=row.quality_status,
        revision_number=row.revision_number,
    )


def _quote_snapshot_identity(row: QuoteSnapshotModel) -> PublicationFactIdentity:
    """Build the quote-snapshot repository identity."""

    natural_key = f"{row.asset_code}:{row.snapshot_at.isoformat()}:{row.source}"
    return _identity(
        natural_key=natural_key,
        source=row.source,
        observed_at=row.snapshot_at,
        source_record_id=row.source_record_id or natural_key,
        raw_payload_hash=row.raw_payload_hash or quote_snapshot_payload_hash(row),
        quality_status=row.quality_status,
        revision_number=row.revision_number,
    )


def _sector_membership_identity(row: SectorMembershipFactModel) -> PublicationFactIdentity:
    """Build the sector-membership repository identity."""

    natural_key = f"{row.asset_code}:{row.sector_code}:{row.effective_date.isoformat()}"
    return _identity(
        natural_key=natural_key,
        source=row.source,
        observed_at=cn_market_date_start_utc(row.effective_date),
        source_record_id=row.source_record_id or natural_key,
        raw_payload_hash=row.raw_payload_hash or sector_membership_payload_hash(row),
        quality_status=row.quality_status,
        revision_number=row.revision_number,
    )


def _valuation_identity(row: ValuationFactModel) -> PublicationFactIdentity:
    """Build the valuation repository identity."""

    if row.observed_at is None:
        raise ValueError("valuation publication candidate requires observed_at")
    natural_key = f"{row.asset_code}:{row.val_date.isoformat()}:{row.source}"
    return _identity(
        natural_key=natural_key,
        source=row.source,
        observed_at=row.observed_at,
        source_record_id=row.source_record_id or natural_key,
        raw_payload_hash=row.raw_payload_hash or valuation_payload_hash(row),
        quality_status=(
            row.quality_status if row.available_at is not None else "available_at_unverified"
        ),
        revision_number=row.revision_number,
    )


def _identity(
    *,
    natural_key: str,
    source: str,
    observed_at: datetime,
    source_record_id: str,
    raw_payload_hash: str,
    quality_status: str,
    revision_number: int,
) -> PublicationFactIdentity:
    """Construct one validated identity from an existing producer rule."""

    return PublicationFactIdentity(
        natural_key=natural_key,
        source=source,
        observed_at=observed_at,
        source_record_id=source_record_id,
        raw_payload_hash=raw_payload_hash,
        quality_status=quality_status,
        revision_number=revision_number,
    )


__all__ = [
    "PublicationFactIdentity",
    "build_publication_fact_identity",
    "canonical_news_payload_hash",
    "publication_fact_model_registry",
]
