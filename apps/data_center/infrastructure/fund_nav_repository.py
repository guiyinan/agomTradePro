"""Canonical fund NAV fact persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date

from django.db.models import Max

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import FundNavFact
from apps.data_center.domain.market_time import cn_market_date_start_utc
from apps.data_center.infrastructure.models import FundNavFactModel


class FundNavRepository:
    """ORM-backed repository for fund NAV facts."""

    @staticmethod
    def _from_model(m: FundNavFactModel) -> FundNavFact:
        return FundNavFact(
            fund_code=m.fund_code,
            nav_date=m.nav_date,
            nav=float(m.nav),
            acc_nav=float(m.acc_nav) if m.acc_nav is not None else None,
            daily_return=float(m.daily_return) if m.daily_return is not None else None,
            source=m.source,
            fetched_at=m.fetched_at,
            extra=m.extra or {},
        )

    def get_series(
        self,
        fund_code: str,
        start: date | None = None,
        end: date | None = None,
        fact_pks: Sequence[str] | None = None,
    ) -> list[FundNavFact]:
        qs = FundNavFactModel.objects.filter(fund_code=fund_code)
        if fact_pks is not None:
            qs = qs.filter(pk__in=list(fact_pks))
        if start:
            qs = qs.filter(nav_date__gte=start)
        if end:
            qs = qs.filter(nav_date__lte=end)
        return [self._from_model(m) for m in qs.order_by("-nav_date")]

    def get_latest(self, fund_code: str) -> FundNavFact | None:
        m = FundNavFactModel.objects.filter(fund_code=fund_code).order_by("-nav_date").first()
        return self._from_model(m) if m else None

    def get_latest_date(self) -> date | None:
        """Return the newest canonical NAV date across the fund universe."""

        value = FundNavFactModel._default_manager.aggregate(latest=Max("nav_date"))["latest"]
        return value if isinstance(value, date) else None

    def bulk_upsert(self, facts: list[FundNavFact]) -> int:
        count = 0
        for f in facts:
            FundNavFactModel.objects.update_or_create(
                fund_code=f.fund_code,
                nav_date=f.nav_date,
                source=f.source,
                defaults={
                    "nav": f.nav,
                    "acc_nav": f.acc_nav,
                    "daily_return": f.daily_return,
                    "extra": f.extra,
                },
            )
            count += 1
        return count

    def list_publication_candidates(
        self, facts: Sequence[FundNavFact]
    ) -> list[PublicationFactReference]:
        """Resolve persisted NAV rows to exact publication member references."""

        references: list[PublicationFactReference] = []
        seen_fact_pks: set[str] = set()
        for fact in facts:
            row = (
                FundNavFactModel._default_manager.filter(
                    fund_code=fact.fund_code,
                    nav_date=fact.nav_date,
                    source=fact.source,
                )
                .order_by("id")
                .first()
            )
            if row is None or str(row.pk) in seen_fact_pks:
                continue
            fact_pk = str(row.pk)
            seen_fact_pks.add(fact_pk)
            natural_key = f"{row.fund_code}:{row.nav_date.isoformat()}:{row.source}"
            references.append(
                PublicationFactReference(
                    natural_key=natural_key,
                    source=row.source,
                    source_record_id=row.source_record_id or natural_key,
                    fact_table="data_center_fund_nav_fact",
                    fact_pk=fact_pk,
                    observed_at=cn_market_date_start_utc(row.nav_date),
                    raw_payload_hash=row.raw_payload_hash or _fund_nav_payload_hash(row),
                    quality_status=row.quality_status,
                    revision_number=row.revision_number,
                )
            )
        return references


def _fund_nav_payload_hash(row: FundNavFactModel) -> str:
    """Return deterministic evidence for one persisted NAV fact."""

    payload = {
        "fund_code": row.fund_code,
        "nav_date": row.nav_date.isoformat(),
        "nav": str(row.nav),
        "acc_nav": str(row.acc_nav) if row.acc_nav is not None else None,
        "daily_return": str(row.daily_return) if row.daily_return is not None else None,
        "source": row.source,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


__all__ = ["FundNavRepository"]
