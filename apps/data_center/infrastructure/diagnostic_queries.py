"""Infrastructure read models for data-center diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import TypedDict, cast

from django.db import models
from django.db.models import Q

from apps.data_center.domain.control_plane import PublicationState
from apps.data_center.domain.entities import ProductionCoverageUniverseConfig
from apps.data_center.domain.market_time import (
    cn_market_date_from_observation,
    latest_closed_cn_market_session,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    DatasetContractRepository,
)
from apps.data_center.infrastructure.models import (
    AssetMasterModel,
    CanonicalPublicationModel,
    FinancialFactModel,
    MacroFactModel,
    PriceBarModel,
    ProviderConfigModel,
    PublicationMemberModel,
    ValuationFactModel,
)
from apps.data_center.infrastructure.repositories import (
    ProductionCoverageUniverseConfigRepository,
)


class _FactDomainSummary(TypedDict):
    """Typed coverage summary for one persisted fact domain."""

    covered_count: int
    missing_count: int
    latest_date: str | None
    status: str


class _PublicationCoverageSummary(TypedDict):
    """Publication/member-bound evidence for one fact domain."""

    dataset_key: str
    publication_key: str
    publication_id: str | None
    state: str | None
    member_count: int
    member_row_count: int
    member_bound_count: int
    member_missing_count: int
    coverage_selected_count: int
    coverage_missing_count: int
    as_of: str | None
    published_at: str | None
    published_latest_date: str | None
    observed_at: str | None
    age_seconds: float | None
    max_age_seconds: int | None
    freshness_status: str
    must_not_use_for_decision: bool
    blocked_reason: str
    status: str


class _UniverseQualitySummary(TypedDict):
    """Typed quality result for the configured production universe."""

    status: str
    minimum_active_a_share_count: int
    minimum_star_market_count: int
    minimum_chinext_count: int
    minimum_bse_count: int
    exchange_counts: dict[str, int]
    board_counts: dict[str, int]
    issues: list[str]


class DataCenterDiagnosticRepository:
    """Read data-center summary counts for operational diagnostics."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def get_summary(self) -> dict[str, int]:
        """Return macro fact and provider configuration counts."""

        return {
            "macro_fact_count": MacroFactModel.objects.count(),
            "provider_config_count": ProviderConfigModel.objects.count(),
            "active_provider_config_count": ProviderConfigModel.objects.filter(
                is_active=True
            ).count(),
        }

    def macro_fact_exists_on_or_before(self, reporting_period: date) -> bool:
        """Return whether a macro fact exists on or before the reporting period."""

        return bool(MacroFactModel.objects.filter(reporting_period__lte=reporting_period).exists())

    def get_active_stock_fact_coverage_summary(self) -> dict[str, object]:
        """Return production data coverage for active stock facts."""

        config = ProductionCoverageUniverseConfigRepository().load()
        universe_queryset = AssetMasterModel.objects.filter(
            asset_type=config.asset_type,
            exchange__in=config.exchanges,
        )
        if not config.include_inactive:
            universe_queryset = universe_queryset.filter(
                Q(is_active=True) | Q(is_active__isnull=True)
            )
        active_codes = [str(code) for code in universe_queryset.values_list("code", flat=True)]
        asset_count = len(active_codes)
        universe_quality = self._active_stock_universe_quality(active_codes, config)
        domain_specs: dict[str, tuple[str, str, type[models.Model], str]] = {
            "price": (
                "equity.price.bar",
                "data_center_price_bar",
                PriceBarModel,
                "bar_date",
            ),
            "valuation": (
                "equity.valuation.fact",
                "data_center_valuation_fact",
                ValuationFactModel,
                "val_date",
            ),
            "financial": (
                "equity.financial.fact",
                "data_center_financial_fact",
                FinancialFactModel,
                "period_end",
            ),
        }
        domains: dict[str, dict[str, object]] = {}
        for name, (dataset_key, fact_table, model, date_field) in domain_specs.items():
            fact_summary = self._fact_domain_summary(
                active_codes,
                model=model,
                date_field=date_field,
            )
            publication_summary = self._publication_domain_summary(
                active_codes,
                dataset_key=dataset_key,
                fact_table=fact_table,
                model=model,
                date_field=date_field,
            )
            # Keep the original fact-table counters unchanged for operators and
            # existing consumers.  The explicit published counters/evidence
            # below prevent those counters from being mistaken for current,
            # member-bound coverage.
            domains[name] = {
                **fact_summary,
                "published_covered_count": publication_summary["member_bound_count"],
                "published_missing_count": publication_summary["member_missing_count"],
                "published_status": publication_summary["status"],
                "publication": publication_summary,
            }
        facts_ready = asset_count > 0 and all(
            domain["covered_count"] == asset_count for domain in domains.values()
        )
        publications_ready = asset_count > 0 and all(
            domain["published_status"] == "ok" for domain in domains.values()
        )
        return {
            "status": (
                "ok"
                if facts_ready and publications_ready and universe_quality["status"] == "ok"
                else "incomplete"
            ),
            "universe": config.universe_id,
            "asset_count": asset_count,
            "universe_config": config.to_dict(),
            "universe_quality": universe_quality,
            "domains": domains,
        }

    def list_active_stock_codes(self) -> list[str]:
        """Return the configured production A-share universe in stable code order."""

        config = ProductionCoverageUniverseConfigRepository().load()
        queryset = AssetMasterModel.objects.filter(
            asset_type=config.asset_type,
            exchange__in=config.exchanges,
        )
        if not config.include_inactive:
            queryset = queryset.filter(Q(is_active=True) | Q(is_active__isnull=True))
        return [str(code) for code in queryset.order_by("code").values_list("code", flat=True)]

    def _active_stock_universe_quality(
        self,
        active_codes: list[str],
        config: ProductionCoverageUniverseConfig,
    ) -> _UniverseQualitySummary:
        board_counts = {
            "star_market": sum(
                code.startswith(("688", "689")) and code.endswith(".SH") for code in active_codes
            ),
            "chinext": sum(
                code.startswith(("300", "301")) and code.endswith(".SZ") for code in active_codes
            ),
            "bse": sum(code.endswith(".BJ") for code in active_codes),
            "sh_main": sum(
                code.startswith(("600", "601", "603", "605")) and code.endswith(".SH")
                for code in active_codes
            ),
            "sz_main": sum(
                code.startswith(("000", "001", "002")) and code.endswith(".SZ")
                for code in active_codes
            ),
        }
        configured_exchanges = list(config.exchanges)
        exchange_counts = dict.fromkeys(configured_exchanges, 0)
        for code in active_codes:
            if code.endswith(".SH"):
                exchange_counts["SSE"] = exchange_counts.get("SSE", 0) + 1
            elif code.endswith(".SZ"):
                exchange_counts["SZSE"] = exchange_counts.get("SZSE", 0) + 1
            elif code.endswith(".BJ"):
                exchange_counts["BSE"] = exchange_counts.get("BSE", 0) + 1

        issues: list[str] = []
        min_active = config.min_active_asset_count
        min_star = config.min_star_market_count
        min_chinext = config.min_chinext_count
        min_bse = config.min_bse_count
        if len(active_codes) < min_active:
            issues.append("active_a_share_universe_too_narrow")
        if board_counts["star_market"] < min_star:
            issues.append("star_market_undercovered")
        if board_counts["chinext"] < min_chinext:
            issues.append("chinext_undercovered")
        if board_counts["bse"] < min_bse:
            issues.append("bse_undercovered")

        return {
            "status": "ok" if not issues else "incomplete",
            "minimum_active_a_share_count": min_active,
            "minimum_star_market_count": min_star,
            "minimum_chinext_count": min_chinext,
            "minimum_bse_count": min_bse,
            "exchange_counts": exchange_counts,
            "board_counts": board_counts,
            "issues": issues,
        }

    def _fact_domain_summary(
        self,
        active_codes: list[str],
        *,
        model: type[models.Model],
        date_field: str,
    ) -> _FactDomainSummary:
        if not active_codes:
            return {
                "covered_count": 0,
                "missing_count": 0,
                "latest_date": None,
                "status": "empty",
            }

        queryset = model._default_manager.filter(asset_code__in=active_codes)
        covered_count = queryset.values("asset_code").distinct().count()
        latest_value: object = (
            queryset.order_by(f"-{date_field}").values_list(date_field, flat=True).first()
        )
        latest_date = latest_value.isoformat() if isinstance(latest_value, date) else None
        missing_count = len(active_codes) - covered_count
        return {
            "covered_count": covered_count,
            "missing_count": missing_count,
            "latest_date": latest_date,
            "status": "ok" if missing_count == 0 and latest_date is not None else "incomplete",
        }

    def _publication_domain_summary(
        self,
        active_codes: list[str],
        *,
        dataset_key: str,
        fact_table: str,
        model: type[models.Model],
        date_field: str,
    ) -> _PublicationCoverageSummary:
        """Return current Publication/member-bound coverage evidence.

        A fact-table row is not current-data evidence by itself.  This query
        resolves the active publication, validates its persisted member set,
        binds member ``fact_pk`` values back to the canonical fact table and
        then applies the Dataset Contract freshness budget to the oldest
        selected source observation.
        """

        empty = self._empty_publication_summary(dataset_key)
        if not active_codes:
            empty["status"] = "empty"
            empty["freshness_status"] = "missing"
            empty["blocked_reason"] = "active_stock_universe_empty"
            return self._typed_publication_summary(empty)

        publication_model = (
            CanonicalPublicationModel._default_manager.filter(
                dataset_key=dataset_key,
                publication_key="current",
                state=PublicationState.PUBLISHED.value,
            )
            .order_by("-published_at", "-created_at")
            .first()
        )
        if publication_model is None:
            publication_model = (
                CanonicalPublicationModel._default_manager.filter(
                    dataset_key=dataset_key,
                    publication_key="current",
                    state__in=[
                        PublicationState.CANDIDATE.value,
                        PublicationState.BLOCKED.value,
                    ],
                )
                .order_by("-created_at")
                .first()
            )
        if publication_model is None:
            return self._typed_publication_summary(empty)

        summary = dict(empty)
        publication_id = str(publication_model.publication_id)
        summary.update(
            publication_id=publication_id,
            state=str(publication_model.state),
            member_count=int(publication_model.member_count),
            coverage_selected_count=int(publication_model.coverage_selected_count),
            coverage_missing_count=int(publication_model.coverage_missing_count),
            as_of=(
                publication_model.as_of.isoformat() if publication_model.as_of is not None else None
            ),
            published_at=(
                publication_model.published_at.isoformat()
                if publication_model.published_at is not None
                else None
            ),
        )
        if publication_model.state != PublicationState.PUBLISHED.value:
            summary.update(
                status="blocked",
                freshness_status="blocked",
                blocked_reason="canonical_publication_not_published",
            )
            return self._typed_publication_summary(summary)
        if publication_model.must_not_use_for_decision:
            summary.update(
                status="blocked",
                freshness_status="blocked",
                blocked_reason=(
                    publication_model.blocked_reason or "canonical_publication_blocked"
                ),
            )
            return self._typed_publication_summary(summary)
        if publication_model.as_of is None:
            summary.update(
                status="blocked",
                freshness_status="missing",
                blocked_reason="publication_as_of_missing",
            )
            return self._typed_publication_summary(summary)
        if publication_model.published_at is None:
            summary.update(
                status="blocked",
                freshness_status="missing",
                blocked_reason="publication_published_at_missing",
            )
            return self._typed_publication_summary(summary)
        if (
            publication_model.as_of.tzinfo is None
            or publication_model.as_of.utcoffset() is None
            or publication_model.published_at.tzinfo is None
            or publication_model.published_at.utcoffset() is None
        ):
            summary.update(
                status="blocked",
                freshness_status="invalid",
                blocked_reason="publication_boundary_naive",
            )
            return self._typed_publication_summary(summary)
        if publication_model.as_of > publication_model.published_at:
            summary.update(
                status="blocked",
                freshness_status="invalid",
                blocked_reason="publication_boundary_invalid",
            )
            return self._typed_publication_summary(summary)

        members = PublicationMemberModel._default_manager.filter(
            publication_id=publication_model.publication_id,
            dataset_key=dataset_key,
            fact_table=fact_table,
        )
        member_row_count = members.count()
        summary["member_row_count"] = member_row_count
        if member_row_count == 0:
            summary.update(
                status="blocked",
                freshness_status="missing",
                blocked_reason="canonical_publication_members_missing",
            )
            return self._typed_publication_summary(summary)
        if member_row_count != int(publication_model.member_count):
            summary.update(
                status="blocked",
                freshness_status="invalid",
                blocked_reason="canonical_publication_members_incomplete",
            )
            return self._typed_publication_summary(summary)
        if (
            int(publication_model.coverage_selected_count) != member_row_count
            or int(publication_model.coverage_missing_count) > 0
        ):
            summary.update(
                status="blocked",
                freshness_status="incomplete",
                blocked_reason="canonical_publication_coverage_incomplete",
            )
            return self._typed_publication_summary(summary)

        fact_pks = list(members.values_list("fact_pk", flat=True))
        bound_codes = {
            str(code)
            for code in model._default_manager.filter(
                pk__in=fact_pks,
                asset_code__in=active_codes,
            ).values_list("asset_code", flat=True)
        }
        member_bound_count = len(bound_codes)
        summary["member_bound_count"] = member_bound_count
        summary["member_missing_count"] = max(len(active_codes) - member_bound_count, 0)
        latest_value: object = (
            model._default_manager.filter(pk__in=fact_pks)
            .order_by(f"-{date_field}")
            .values_list(date_field, flat=True)
            .first()
        )
        if isinstance(latest_value, date):
            summary["published_latest_date"] = latest_value.isoformat()
        if member_bound_count != len(active_codes):
            summary.update(
                status="blocked",
                freshness_status="incomplete",
                blocked_reason="canonical_publication_coverage_incomplete",
            )
            return self._typed_publication_summary(summary)

        observed_values = list(members.values_list("observed_at", flat=True))
        if any(value is None for value in observed_values):
            summary.update(
                status="blocked",
                freshness_status="missing",
                blocked_reason="publication_observation_missing",
            )
            return self._typed_publication_summary(summary)
        aware_observed = [value for value in observed_values if isinstance(value, datetime)]
        if len(aware_observed) != len(observed_values):
            summary.update(
                status="blocked",
                freshness_status="invalid",
                blocked_reason="publication_observation_invalid",
            )
            return self._typed_publication_summary(summary)
        if any(value.tzinfo is None or value.utcoffset() is None for value in aware_observed):
            summary.update(
                status="blocked",
                freshness_status="invalid",
                blocked_reason="publication_observation_naive",
            )
            return self._typed_publication_summary(summary)

        publication_as_of = publication_model.as_of.astimezone(UTC)
        if any(value.astimezone(UTC) > publication_as_of for value in aware_observed):
            summary.update(
                status="blocked",
                freshness_status="invalid",
                blocked_reason="publication_observation_after_as_of",
            )
            return self._typed_publication_summary(summary)

        oldest = min(aware_observed).astimezone(UTC)
        oldest = min(oldest, publication_as_of)
        summary["observed_at"] = oldest.isoformat()
        contract = DatasetContractRepository().get_active(dataset_key)
        max_age_seconds = getattr(contract, "freshness_seconds", None)
        summary["max_age_seconds"] = int(max_age_seconds) if max_age_seconds is not None else None
        if max_age_seconds is None:
            summary.update(
                status="blocked",
                freshness_status="unverified",
                blocked_reason="publication_freshness_policy_missing",
            )
            return self._typed_publication_summary(summary)

        current_time = self._clock()
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            summary.update(
                status="blocked",
                freshness_status="invalid",
                blocked_reason="diagnostic_clock_naive",
            )
            return self._typed_publication_summary(summary)
        age_seconds = max((current_time.astimezone(UTC) - oldest).total_seconds(), 0.0)
        summary["age_seconds"] = age_seconds
        if age_seconds > int(max_age_seconds):
            latest_session = latest_closed_cn_market_session(current_time)
            is_latest_market_session = dataset_key in {
                "equity.price.bar",
                "equity.valuation.fact",
            } and all(
                cn_market_date_from_observation(value) == latest_session for value in aware_observed
            )
            if not is_latest_market_session:
                summary.update(
                    status="blocked",
                    freshness_status="stale",
                    blocked_reason="canonical_publication_stale",
                )
                return self._typed_publication_summary(summary)
            summary.update(
                status="ok",
                freshness_status="latest_completed_session",
                must_not_use_for_decision=False,
                blocked_reason="",
            )
            return self._typed_publication_summary(summary)
        summary.update(
            status="ok",
            freshness_status="fresh",
            must_not_use_for_decision=False,
            blocked_reason="",
        )
        return self._typed_publication_summary(summary)

    @staticmethod
    def _empty_publication_summary(dataset_key: str) -> dict[str, object]:
        """Build a fail-closed publication payload for missing evidence."""

        return {
            "dataset_key": dataset_key,
            "publication_key": "current",
            "publication_id": None,
            "state": None,
            "member_count": 0,
            "member_row_count": 0,
            "member_bound_count": 0,
            "member_missing_count": 0,
            "coverage_selected_count": 0,
            "coverage_missing_count": 0,
            "as_of": None,
            "published_at": None,
            "published_latest_date": None,
            "observed_at": None,
            "age_seconds": None,
            "max_age_seconds": None,
            "freshness_status": "blocked",
            "must_not_use_for_decision": True,
            "blocked_reason": "canonical_publication_missing",
            "status": "blocked",
        }

    @staticmethod
    def _typed_publication_summary(
        summary: dict[str, object],
    ) -> _PublicationCoverageSummary:
        """Normalize an internal evidence map to the public typed shape."""

        return _PublicationCoverageSummary(
            dataset_key=str(summary["dataset_key"]),
            publication_key=str(summary["publication_key"]),
            publication_id=(
                str(summary["publication_id"])
                if summary.get("publication_id") is not None
                else None
            ),
            state=(str(summary["state"]) if summary.get("state") is not None else None),
            member_count=int(cast(int, summary["member_count"])),
            member_row_count=int(cast(int, summary["member_row_count"])),
            member_bound_count=int(cast(int, summary["member_bound_count"])),
            member_missing_count=int(cast(int, summary["member_missing_count"])),
            coverage_selected_count=int(cast(int, summary["coverage_selected_count"])),
            coverage_missing_count=int(cast(int, summary["coverage_missing_count"])),
            as_of=str(summary["as_of"]) if summary.get("as_of") is not None else None,
            published_at=(
                str(summary["published_at"]) if summary.get("published_at") is not None else None
            ),
            published_latest_date=(
                str(summary["published_latest_date"])
                if summary.get("published_latest_date") is not None
                else None
            ),
            observed_at=(
                str(summary["observed_at"]) if summary.get("observed_at") is not None else None
            ),
            age_seconds=(
                float(cast(float, summary["age_seconds"]))
                if summary.get("age_seconds") is not None
                else None
            ),
            max_age_seconds=(
                int(cast(int, summary["max_age_seconds"]))
                if summary.get("max_age_seconds") is not None
                else None
            ),
            freshness_status=str(summary["freshness_status"]),
            must_not_use_for_decision=bool(summary["must_not_use_for_decision"]),
            blocked_reason=str(summary["blocked_reason"]),
            status=str(summary["status"]),
        )
