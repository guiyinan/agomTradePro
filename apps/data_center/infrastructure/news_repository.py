"""Canonical market-news persistence and daily metrics."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, cast

from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import MarketNewsDailyMetrics, NewsFact
from apps.data_center.infrastructure._market_breadth_helpers import (
    validate_date_range as _validate_date_range,
)
from apps.data_center.infrastructure._market_breadth_helpers import (
    validated_code as _validated_code,
)
from apps.data_center.infrastructure._market_breadth_helpers import (
    validated_limit as _validated_limit,
)
from apps.data_center.infrastructure._repository_helpers import (
    _resolve_asset_code_candidates,
)
from apps.data_center.infrastructure.models import NewsFactModel

from .publication_fact_evidence import publication_fact_reference_for_dataset
from .publication_fact_identity import canonical_news_payload_hash


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
            references.append(
                publication_fact_reference_for_dataset(
                    row,
                    dataset_key="market.news",
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


def _stable_news_external_id(article: NewsFact) -> str:
    """Use provider id when present, otherwise a content-derived id."""

    if article.external_id.strip():
        return article.external_id.strip()
    return "content-" + canonical_news_payload_hash(
        asset_code=article.asset_code,
        title=article.title,
        summary=article.summary,
        url=article.url,
        published_at=article.published_at,
        source=article.source,
        external_id="",
    )


__all__ = ["NewsRepository"]
