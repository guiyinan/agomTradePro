"""Sector membership, market news, and capital-flow fact persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from typing import Any, cast

from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import (
    CapitalFlowFact,
    MarketNewsDailyMetrics,
    NewsFact,
    SectorMembershipFact,
)
from apps.data_center.infrastructure._repository_helpers import _resolve_asset_code_candidates
from apps.data_center.infrastructure.models import (
    CapitalFlowFactModel,
    NewsFactModel,
    SectorMembershipFactModel,
)


class SectorMembershipRepository:
    """ORM-backed repository for sector / index constituent membership."""

    @staticmethod
    def _from_model(m: SectorMembershipFactModel) -> SectorMembershipFact:
        return SectorMembershipFact(
            asset_code=m.asset_code,
            sector_code=m.sector_code,
            sector_name=m.sector_name,
            effective_date=m.effective_date,
            expiry_date=m.expiry_date,
            weight=float(m.weight) if m.weight is not None else None,
            source=m.source,
            fetched_at=m.fetched_at,
        )

    def get_members(
        self,
        sector_code: str,
        as_of: date | None = None,
        fact_pks: Sequence[str] | None = None,
    ) -> list[SectorMembershipFact]:
        sector_code = _validated_code(sector_code, field_name="sector_code")
        qs = SectorMembershipFactModel.objects.filter(sector_code=sector_code)
        if fact_pks is not None:
            qs = qs.filter(pk__in=list(fact_pks))
        if as_of:
            qs = qs.filter(effective_date__lte=as_of).filter(expiry_date__isnull=True) | qs.filter(
                effective_date__lte=as_of, expiry_date__gte=as_of
            )
        return [self._from_model(m) for m in qs]

    def get_sectors_for_asset(
        self, asset_code: str, as_of: date | None = None
    ) -> list[SectorMembershipFact]:
        asset_code = _validated_code(asset_code, field_name="asset_code")
        qs = SectorMembershipFactModel.objects.filter(asset_code=asset_code)
        if as_of:
            qs = qs.filter(effective_date__lte=as_of).filter(expiry_date__isnull=True) | qs.filter(
                effective_date__lte=as_of, expiry_date__gte=as_of
            )
        return [self._from_model(m) for m in qs]

    def list_current(
        self,
        as_of: date | None = None,
        fact_pks: Sequence[str] | None = None,
    ) -> list[SectorMembershipFact]:
        """Return all canonical membership facts active at an optional date."""

        qs = SectorMembershipFactModel.objects.all()
        if fact_pks is not None:
            qs = qs.filter(pk__in=list(fact_pks))
        if as_of is not None:
            qs = qs.filter(effective_date__lte=as_of).filter(
                Q(expiry_date__isnull=True) | Q(expiry_date__gte=as_of)
            )
        return [self._from_model(model) for model in qs]

    def bulk_upsert(self, facts: list[SectorMembershipFact]) -> int:
        count = 0
        for f in facts:
            SectorMembershipFactModel.objects.update_or_create(
                asset_code=f.asset_code,
                sector_code=f.sector_code,
                effective_date=f.effective_date,
                defaults={
                    "sector_name": f.sector_name,
                    "expiry_date": f.expiry_date,
                    "weight": f.weight,
                    "source": f.source,
                },
            )
            count += 1
        return count


class NewsRepository:
    """ORM-backed repository for news articles."""

    @staticmethod
    def _from_model(m: NewsFactModel) -> NewsFact:
        return NewsFact(
            asset_code=m.asset_code,
            title=m.title,
            summary=m.summary,
            url=m.url,
            published_at=m.published_at,
            source=m.source,
            external_id=m.external_id,
            sentiment_score=m.sentiment_score,
            extra=dict(m.extra or {}),
            fetched_at=m.fetched_at,
        )

    def get_recent(
        self,
        asset_code: str | None = None,
        limit: int = 50,
        end: date | None = None,
        fact_pks: Sequence[str] | None = None,
    ) -> list[NewsFact]:
        limit = _validated_limit(limit)
        if asset_code is not None:
            asset_code = _validated_code(asset_code, field_name="asset_code")
        qs = NewsFactModel.objects.all()
        if fact_pks is not None:
            qs = qs.filter(pk__in=list(fact_pks))
        if end is not None:
            qs = qs.filter(published_at__date__lte=end)
        if not asset_code:
            return [self._from_model(m) for m in qs.order_by("-published_at")[:limit]]

        for candidate in _resolve_asset_code_candidates(asset_code):
            rows = list(qs.filter(asset_code=candidate).order_by("-published_at")[:limit])
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def list_market_news_for_date(
        self,
        target_date: date,
        limit: int = 50,
        fact_pks: Sequence[str] | None = None,
    ) -> list[NewsFact]:
        """Return market-wide news published on one date."""

        limit = _validated_limit(limit)

        queryset = NewsFactModel.objects.filter(asset_code="", published_at__date=target_date)
        if fact_pks is not None:
            queryset = queryset.filter(pk__in=list(fact_pks))
        rows = queryset.order_by("-published_at", "-id")[:limit]
        return [self._from_model(m) for m in rows]

    def bulk_insert(self, articles: list[NewsFact]) -> int:
        count = 0
        for a in articles:
            external_id = _stable_news_external_id(a)
            _, created = NewsFactModel.objects.get_or_create(
                source=a.source,
                external_id=external_id,
                defaults={
                    "asset_code": a.asset_code,
                    "title": a.title,
                    "summary": a.summary,
                    "url": a.url,
                    "published_at": a.published_at,
                    "sentiment_score": a.sentiment_score,
                    "extra": a.extra,
                },
            )
            if created:
                count += 1
        return count

    def list_publication_candidates(
        self, articles: Sequence[NewsFact]
    ) -> list[PublicationFactReference]:
        """Resolve persisted news rows into publication-safe fact references.

        The lookup is restricted to the exact source/natural key written by
        the sync batch. This prevents a publication retry from accidentally
        selecting an unrelated article while still supporting legacy rows that
        were ingested before stable content identifiers were introduced.
        """

        references: list[PublicationFactReference] = []
        seen_fact_pks: set[str] = set()
        for article in articles:
            external_id = _stable_news_external_id(article)
            row = (
                NewsFactModel._default_manager.filter(
                    source=article.source,
                    external_id=external_id,
                )
                .order_by("id")
                .first()
            )
            if row is None and not article.external_id:
                row = (
                    NewsFactModel._default_manager.filter(
                        source=article.source,
                        title=article.title,
                        published_at=article.published_at,
                    )
                    .order_by("id")
                    .first()
                )
            if row is None or str(row.pk) in seen_fact_pks:
                continue
            fact_pk = str(row.pk)
            seen_fact_pks.add(fact_pk)
            payload_hash = row.raw_payload_hash or _news_payload_hash(
                asset_code=row.asset_code,
                title=row.title,
                summary=row.summary,
                url=row.url,
                published_at=row.published_at,
                source=row.source,
                external_id=row.external_id,
            )
            references.append(
                PublicationFactReference(
                    natural_key=f"{row.source}:{row.external_id}",
                    source=row.source,
                    source_record_id=row.source_record_id or row.external_id,
                    fact_table="data_center_news_fact",
                    fact_pk=fact_pk,
                    observed_at=row.published_at,
                    raw_payload_hash=payload_hash,
                    quality_status=row.quality_status,
                    revision_number=row.revision_number,
                )
            )
        return references

    def aggregate_market_daily(
        self,
        start: date | None = None,
        end: date | None = None,
    ) -> list[MarketNewsDailyMetrics]:
        _validate_date_range(start, end)
        qs = NewsFactModel.objects.filter(asset_code="")
        if start:
            qs = qs.filter(published_at__date__gte=start)
        if end:
            qs = qs.filter(published_at__date__lte=end)

        rows = (
            cast(Any, qs)
            .annotate(observed_date=TruncDate("published_at"))
            .values("observed_date")
            .annotate(
                news_count=Count("id"),
                avg_sentiment=Avg("sentiment_score"),
                positive_count=Count("id", filter=Q(sentiment_score__gt=0)),
            )
            .order_by("-observed_date")
        )

        metrics: list[MarketNewsDailyMetrics] = []
        for row in rows:
            observed_date = row.get("observed_date")
            if observed_date is None:
                continue
            news_count = int(row.get("news_count") or 0)
            positive_count = int(row.get("positive_count") or 0)
            positive_ratio = (positive_count / news_count) if news_count > 0 else None
            avg_sentiment = row.get("avg_sentiment")
            metrics.append(
                MarketNewsDailyMetrics(
                    observed_date=observed_date,
                    news_count=news_count,
                    avg_sentiment=float(avg_sentiment) if avg_sentiment is not None else None,
                    positive_ratio=positive_ratio,
                )
            )
        return metrics


class CapitalFlowRepository:
    """ORM-backed repository for capital-flow facts."""

    @staticmethod
    def _from_model(m: CapitalFlowFactModel) -> CapitalFlowFact:
        return CapitalFlowFact(
            asset_code=m.asset_code,
            flow_date=m.flow_date,
            main_net=float(m.main_net) if m.main_net is not None else None,
            retail_net=float(m.retail_net) if m.retail_net is not None else None,
            super_large_net=float(m.super_large_net) if m.super_large_net is not None else None,
            large_net=float(m.large_net) if m.large_net is not None else None,
            medium_net=float(m.medium_net) if m.medium_net is not None else None,
            small_net=float(m.small_net) if m.small_net is not None else None,
            source=m.source,
            fetched_at=m.fetched_at,
            extra=dict(m.extra or {}),
        )

    def get_series(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
        fact_pks: Sequence[str] | None = None,
    ) -> list[CapitalFlowFact]:
        asset_code = _validated_code(asset_code, field_name="asset_code")
        _validate_date_range(start, end)
        if limit is not None:
            limit = _validated_limit(limit)
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = CapitalFlowFactModel.objects.filter(asset_code=candidate)
            if fact_pks is not None:
                qs = qs.filter(pk__in=list(fact_pks))
            if start:
                qs = qs.filter(flow_date__gte=start)
            if end:
                qs = qs.filter(flow_date__lte=end)
            rows = list(
                qs.order_by("-flow_date") if limit is None else qs.order_by("-flow_date")[:limit]
            )
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def get_latest(self, asset_code: str) -> CapitalFlowFact | None:
        asset_code = _validated_code(asset_code, field_name="asset_code")
        for candidate in _resolve_asset_code_candidates(asset_code):
            m = (
                CapitalFlowFactModel.objects.filter(asset_code=candidate)
                .order_by("-flow_date")
                .first()
            )
            if m is not None:
                return self._from_model(m)
        return None

    def bulk_upsert(self, facts: list[CapitalFlowFact]) -> int:
        count = 0
        for f in facts:
            CapitalFlowFactModel.objects.update_or_create(
                asset_code=f.asset_code,
                flow_date=f.flow_date,
                source=f.source,
                defaults={
                    "main_net": f.main_net,
                    "retail_net": f.retail_net,
                    "super_large_net": f.super_large_net,
                    "large_net": f.large_net,
                    "medium_net": f.medium_net,
                    "small_net": f.small_net,
                    "extra": f.extra,
                },
            )
            count += 1
        return count


def _validated_code(value: str, *, field_name: str) -> str:
    """Validate a bounded lookup code before building an ORM query."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    normalized = value.strip()
    if not normalized or len(normalized) > 64:
        raise ValueError(f"{field_name} must contain 1 to 64 characters.")
    return normalized


def _news_payload_hash(
    *,
    asset_code: str,
    title: str,
    summary: str,
    url: str,
    published_at: Any,
    source: str,
    external_id: str,
) -> str:
    """Return a deterministic digest for publication evidence."""

    payload = {
        "asset_code": asset_code,
        "title": title,
        "summary": summary,
        "url": url,
        "published_at": str(published_at),
        "source": source,
        "external_id": external_id,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _stable_news_external_id(article: NewsFact) -> str:
    """Use provider id when present, otherwise a content-derived id."""

    if article.external_id.strip():
        return article.external_id.strip()
    return "content-" + _news_payload_hash(
        asset_code=article.asset_code,
        title=article.title,
        summary=article.summary,
        url=article.url,
        published_at=article.published_at,
        source=article.source,
        external_id="",
    )


def _validated_limit(limit: int) -> int:
    """Reject unbounded, boolean, and non-positive query limits."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer between 1 and 1000.")
    return limit


def _validate_date_range(start: date | None, end: date | None) -> None:
    """Reject inverted date ranges before querying storage."""
    if start is not None and end is not None and start > end:
        raise ValueError("start cannot be after end.")
