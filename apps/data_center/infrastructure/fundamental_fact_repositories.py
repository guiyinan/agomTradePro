"""Fund NAV, financial statement, and valuation fact persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from django.db.models import Max

from apps.data_center.domain.entities import FinancialFact, FundNavFact, ValuationFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.infrastructure._repository_helpers import _resolve_asset_code_candidates
from apps.data_center.infrastructure.models import (
    FinancialFactModel,
    FundNavFactModel,
    ValuationFactModel,
)


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
    ) -> list[FundNavFact]:
        qs = FundNavFactModel.objects.filter(fund_code=fund_code)
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


class FinancialFactRepository:
    """ORM-backed repository for financial statement facts."""

    @staticmethod
    def _from_model(m: FinancialFactModel) -> FinancialFact:
        return FinancialFact(
            asset_code=m.asset_code,
            period_end=m.period_end,
            period_type=FinancialPeriodType(m.period_type),
            metric_code=m.metric_code,
            value=float(m.value),
            unit=m.unit,
            source=m.source,
            report_date=m.report_date,
            fetched_at=m.fetched_at,
            extra=m.extra or {},
        )

    def get_facts(
        self,
        asset_code: str,
        period_type: FinancialPeriodType | None = None,
        limit: int = 20,
        end: date | None = None,
        fact_pks: Sequence[str] | None = None,
    ) -> list[FinancialFact]:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = FinancialFactModel.objects.filter(asset_code=candidate)
            if fact_pks is not None:
                qs = qs.filter(pk__in=list(fact_pks))
            if period_type:
                qs = qs.filter(period_type=period_type.value)
            if end is not None:
                qs = qs.filter(period_end__lte=end)
            rows = list(qs.order_by("-period_end")[:limit])
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def get_latest(
        self, asset_code: str, period_type: FinancialPeriodType | None = None
    ) -> FinancialFact | None:
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = FinancialFactModel.objects.filter(asset_code=candidate)
            if period_type:
                qs = qs.filter(period_type=period_type.value)
            m = qs.order_by("-period_end").first()
            if m is not None:
                return self._from_model(m)
        return None

    def bulk_upsert(self, facts: list[FinancialFact]) -> int:
        if not facts:
            return 0
        models = [
            FinancialFactModel(
                asset_code=fact.asset_code,
                period_end=fact.period_end,
                period_type=fact.period_type.value,
                metric_code=fact.metric_code,
                value=fact.value,
                unit=fact.unit,
                source=fact.source,
                report_date=fact.report_date,
                extra=fact.extra,
            )
            for fact in facts
        ]
        FinancialFactModel._default_manager.bulk_create(
            models,
            batch_size=1_000,
            update_conflicts=True,
            update_fields=["value", "unit", "report_date", "extra"],
            unique_fields=["asset_code", "period_end", "period_type", "metric_code", "source"],
        )
        return len(models)


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
                "extra",
            ],
            unique_fields=["asset_code", "val_date", "source"],
        )
        return len(models)
