"""Canonical sector-membership and capital-flow persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date

from django.db.models import Q

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import CapitalFlowFact, SectorMembershipFact
from apps.data_center.domain.market_time import cn_market_date_start_utc
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
from apps.data_center.infrastructure.models import CapitalFlowFactModel, SectorMembershipFactModel


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

    def list_publication_candidates(
        self, facts: Sequence[SectorMembershipFact]
    ) -> list[PublicationFactReference]:
        """Resolve persisted membership rows to exact publication members."""

        references: list[PublicationFactReference] = []
        seen_fact_pks: set[str] = set()
        for fact in facts:
            row = (
                SectorMembershipFactModel._default_manager.filter(
                    asset_code=fact.asset_code,
                    sector_code=fact.sector_code,
                    effective_date=fact.effective_date,
                )
                .order_by("id")
                .first()
            )
            if row is None or str(row.pk) in seen_fact_pks:
                continue
            fact_pk = str(row.pk)
            seen_fact_pks.add(fact_pk)
            natural_key = f"{row.asset_code}:{row.sector_code}:{row.effective_date.isoformat()}"
            references.append(
                PublicationFactReference(
                    natural_key=natural_key,
                    source=row.source,
                    source_record_id=row.source_record_id or natural_key,
                    fact_table="data_center_sector_membership",
                    fact_pk=fact_pk,
                    observed_at=cn_market_date_start_utc(row.effective_date),
                    raw_payload_hash=row.raw_payload_hash or _sector_membership_payload_hash(row),
                    quality_status=row.quality_status,
                    revision_number=row.revision_number,
                )
            )
        return references


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

    def list_publication_candidates(
        self, facts: Sequence[CapitalFlowFact]
    ) -> list[PublicationFactReference]:
        """Resolve one sync batch to exact capital-flow fact references.

        ``flow_date`` is the source observation boundary for a daily flow.
        ``fetched_at`` is intentionally not used: ingestion time cannot turn
        an old flow into a current observation.
        """

        references: list[PublicationFactReference] = []
        seen_fact_pks: set[str] = set()
        for fact in facts:
            row = (
                CapitalFlowFactModel._default_manager.filter(
                    asset_code=fact.asset_code,
                    flow_date=fact.flow_date,
                    source=fact.source,
                )
                .order_by("id")
                .first()
            )
            if row is None or str(row.pk) in seen_fact_pks:
                continue
            fact_pk = str(row.pk)
            seen_fact_pks.add(fact_pk)
            natural_key = f"{row.asset_code}:{row.flow_date.isoformat()}:{row.source}"
            payload_hash = row.raw_payload_hash or _capital_flow_payload_hash(row)
            references.append(
                PublicationFactReference(
                    natural_key=natural_key,
                    source=row.source,
                    source_record_id=row.source_record_id or natural_key,
                    fact_table="data_center_capital_flow_fact",
                    fact_pk=fact_pk,
                    observed_at=cn_market_date_start_utc(row.flow_date),
                    raw_payload_hash=payload_hash,
                    quality_status=row.quality_status,
                    revision_number=row.revision_number,
                )
            )
        return references


def _capital_flow_payload_hash(row: CapitalFlowFactModel) -> str:
    """Return deterministic evidence for one persisted capital-flow row."""

    payload = {
        "asset_code": row.asset_code,
        "flow_date": row.flow_date.isoformat(),
        "main_net": str(row.main_net) if row.main_net is not None else None,
        "retail_net": str(row.retail_net) if row.retail_net is not None else None,
        "super_large_net": str(row.super_large_net) if row.super_large_net is not None else None,
        "large_net": str(row.large_net) if row.large_net is not None else None,
        "medium_net": str(row.medium_net) if row.medium_net is not None else None,
        "small_net": str(row.small_net) if row.small_net is not None else None,
        "source": row.source,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _sector_membership_payload_hash(row: SectorMembershipFactModel) -> str:
    """Return deterministic evidence for one persisted membership row."""

    payload = {
        "asset_code": row.asset_code,
        "sector_code": row.sector_code,
        "sector_name": row.sector_name,
        "effective_date": row.effective_date.isoformat(),
        "expiry_date": row.expiry_date.isoformat() if row.expiry_date else None,
        "weight": str(row.weight) if row.weight is not None else None,
        "source": row.source,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


__all__ = ["CapitalFlowRepository", "SectorMembershipRepository"]
