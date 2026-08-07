"""Canonical valuation fact persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, time

from django.db.models import Max

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import ValuationFact
from apps.data_center.infrastructure._repository_helpers import _resolve_asset_code_candidates
from apps.data_center.infrastructure.models import ValuationFactModel


class ValuationFactRepository:
    """ORM-backed repository for daily valuation multiples."""

    @staticmethod
    def _from_model(m: ValuationFactModel) -> ValuationFact:
        return ValuationFact(
            asset_code=m.asset_code,
            val_date=m.val_date,
            pe_ttm=float(m.pe_ttm) if m.pe_ttm is not None else None,
            pe_static=float(m.pe_static) if m.pe_static is not None else None,
            pb=float(m.pb) if m.pb is not None else None,
            ps_ttm=float(m.ps_ttm) if m.ps_ttm is not None else None,
            market_cap=float(m.market_cap) if m.market_cap is not None else None,
            float_market_cap=float(m.float_market_cap) if m.float_market_cap is not None else None,
            dv_ratio=float(m.dv_ratio) if m.dv_ratio is not None else None,
            source=m.source,
            available_at=m.available_at,
            fetched_at=m.fetched_at,
            extra=m.extra or {},
        )

    def get_series(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
        fact_pks: Sequence[str] | None = None,
    ) -> list[ValuationFact]:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = ValuationFactModel.objects.filter(asset_code=candidate)
            if fact_pks is not None:
                qs = qs.filter(pk__in=list(fact_pks))
            if start:
                qs = qs.filter(val_date__gte=start)
            if end:
                qs = qs.filter(val_date__lte=end)
            rows = list(qs.order_by("-val_date"))
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def get_latest(self, asset_code: str) -> ValuationFact | None:
        for candidate in _resolve_asset_code_candidates(asset_code):
            m = (
                ValuationFactModel.objects.filter(asset_code=candidate)
                .order_by("-val_date")
                .first()
            )
            if m is not None:
                return self._from_model(m)
        return None

    def get_latest_date(self) -> date | None:
        """Return the newest canonical valuation date across all assets."""

        value = ValuationFactModel._default_manager.aggregate(latest=Max("val_date"))["latest"]
        return value if isinstance(value, date) else None

    def list_by_date(self, as_of_date: date) -> list[ValuationFact]:
        """Return canonical valuation facts for one date in deterministic order."""

        rows = ValuationFactModel._default_manager.filter(val_date=as_of_date).order_by(
            "asset_code"
        )
        return [self._from_model(row) for row in rows]

    def list_asset_codes(self, as_of: date | None = None) -> list[str]:
        """Return assets with canonical valuation facts through ``as_of``."""

        queryset = ValuationFactModel.objects.all()
        if as_of is not None:
            queryset = queryset.filter(val_date__lte=as_of)
        return list(queryset.order_by("asset_code").values_list("asset_code", flat=True).distinct())

    def bulk_upsert(self, facts: list[ValuationFact]) -> int:
        if not facts:
            return 0
        models = [
            ValuationFactModel(
                asset_code=fact.asset_code,
                val_date=fact.val_date,
                pe_ttm=fact.pe_ttm,
                pe_static=fact.pe_static,
                pb=fact.pb,
                ps_ttm=fact.ps_ttm,
                market_cap=fact.market_cap,
                float_market_cap=fact.float_market_cap,
                dv_ratio=fact.dv_ratio,
                source=fact.source,
                available_at=fact.available_at,
                extra=fact.extra,
            )
            for fact in facts
        ]
        ValuationFactModel._default_manager.bulk_create(
            models,
            batch_size=1_000,
            update_conflicts=True,
            update_fields=[
                "pe_ttm",
                "pe_static",
                "pb",
                "ps_ttm",
                "market_cap",
                "float_market_cap",
                "dv_ratio",
                "available_at",
                "extra",
            ],
            unique_fields=["asset_code", "val_date", "source"],
        )
        return len(models)

    def list_publication_candidates(
        self, facts: Sequence[ValuationFact]
    ) -> list[PublicationFactReference]:
        """Resolve exact valuation rows without substituting fetch time.

        ``val_date`` is the observed market date. Optional ``available_at`` is
        retained as a safety check only; missing availability is marked as an
        unverified quality state rather than fabricated from ``fetched_at``.
        """

        references: list[PublicationFactReference] = []
        seen_fact_pks: set[str] = set()
        now = datetime.now(UTC)
        for fact in facts:
            row = (
                ValuationFactModel._default_manager.filter(
                    asset_code=fact.asset_code,
                    val_date=fact.val_date,
                    source=fact.source,
                )
                .order_by("id")
                .first()
            )
            if row is None or str(row.pk) in seen_fact_pks:
                continue
            if row.available_at is not None:
                if row.available_at.tzinfo is None or row.available_at.utcoffset() is None:
                    raise ValueError("valuation available_at must be timezone-aware")
                if row.available_at > now:
                    raise ValueError("valuation available_at cannot be in the future")
            fact_pk = str(row.pk)
            seen_fact_pks.add(fact_pk)
            natural_key = f"{row.asset_code}:{row.val_date.isoformat()}:{row.source}"
            references.append(
                PublicationFactReference(
                    natural_key=natural_key,
                    source=row.source,
                    source_record_id=row.source_record_id or natural_key,
                    fact_table="data_center_valuation_fact",
                    fact_pk=fact_pk,
                    observed_at=datetime.combine(row.val_date, time.min, tzinfo=UTC),
                    raw_payload_hash=row.raw_payload_hash or _valuation_payload_hash(row),
                    quality_status=(
                        row.quality_status
                        if row.available_at is not None
                        else "available_at_unverified"
                    ),
                    revision_number=row.revision_number,
                )
            )
        return references


def _valuation_payload_hash(row: ValuationFactModel) -> str:
    """Return deterministic evidence for one persisted valuation fact."""

    payload = {
        "asset_code": row.asset_code,
        "val_date": row.val_date.isoformat(),
        "pe_ttm": str(row.pe_ttm) if row.pe_ttm is not None else None,
        "pe_static": str(row.pe_static) if row.pe_static is not None else None,
        "pb": str(row.pb) if row.pb is not None else None,
        "ps_ttm": str(row.ps_ttm) if row.ps_ttm is not None else None,
        "market_cap": str(row.market_cap) if row.market_cap is not None else None,
        "float_market_cap": str(row.float_market_cap) if row.float_market_cap is not None else None,
        "dv_ratio": str(row.dv_ratio) if row.dv_ratio is not None else None,
        "source": row.source,
        "available_at": row.available_at.isoformat() if row.available_at else None,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


__all__ = ["ValuationFactRepository"]
