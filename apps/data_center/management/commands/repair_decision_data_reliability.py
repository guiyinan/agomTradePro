"""Repair decision-grade data freshness across Data Center, Pulse, and Alpha."""

from __future__ import annotations

import json
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError, call_command

from apps.data_center.application.dtos import DecisionReliabilityRepairRequest
from apps.data_center.application.use_cases import (
    DEFAULT_DECISION_ASSET_CODES,
    DEFAULT_DECISION_MACRO_INDICATORS,
    RepairDecisionDataReliabilityUseCase,
)
from apps.data_center.infrastructure.provider_factory import UnifiedProviderFactory
from apps.data_center.infrastructure.repositories import (
    IndicatorCatalogRepository,
    LegacyMacroSeriesRepository,
    MacroFactRepository,
    PriceBarRepository,
    ProviderConfigRepository,
    QuoteSnapshotRepository,
    RawAuditRepository,
)


def _split_codes(raw: str | None, defaults: tuple[str, ...]) -> list[str]:
    if not raw:
        return list(defaults)
    return [item.strip() for item in raw.split(",") if item.strip()]


class Command(BaseCommand):
    help = "Repair data inputs required for actionable decision outputs."

    def add_arguments(self, parser):
        parser.add_argument("--target-date", dest="target_date", default=None)
        parser.add_argument("--portfolio-id", dest="portfolio_id", type=int, default=366)
        parser.add_argument("--user-id", dest="user_id", type=int, default=None)
        parser.add_argument("--asset-codes", dest="asset_codes", default=None)
        parser.add_argument(
            "--macro-indicator-codes",
            dest="macro_indicator_codes",
            default=None,
        )
        parser.add_argument("--strict", dest="strict", action="store_true", default=False)
        parser.add_argument(
            "--quote-max-age-hours",
            dest="quote_max_age_hours",
            type=float,
            default=4.0,
        )
        parser.add_argument("--skip-pulse", dest="skip_pulse", action="store_true")
        parser.add_argument("--skip-alpha", dest="skip_alpha", action="store_true")

    def handle(self, *args, **options):
        target_date = (
            date.fromisoformat(options["target_date"])
            if options.get("target_date")
            else date.today()
        )
        user = self._resolve_user(options.get("user_id"))
        provider_repo = ProviderConfigRepository()
        use_case = RepairDecisionDataReliabilityUseCase(
            provider_repo=provider_repo,
            provider_factory=UnifiedProviderFactory(provider_repo),
            macro_fact_repo=MacroFactRepository(),
            indicator_catalog_repo=IndicatorCatalogRepository(),
            price_bar_repo=PriceBarRepository(),
            quote_snapshot_repo=QuoteSnapshotRepository(),
            raw_audit_repo=RawAuditRepository(),
            legacy_macro_repo=LegacyMacroSeriesRepository(),
            pulse_refresher=self._build_pulse_refresher(),
            alpha_refresher=self._build_alpha_refresher(user),
            alpha_status_reader=self._build_alpha_status_reader(user),
        )
        report = use_case.execute(
            DecisionReliabilityRepairRequest(
                target_date=target_date,
                portfolio_id=options.get("portfolio_id"),
                asset_codes=_split_codes(
                    options.get("asset_codes"),
                    DEFAULT_DECISION_ASSET_CODES,
                ),
                macro_indicator_codes=_split_codes(
                    options.get("macro_indicator_codes"),
                    DEFAULT_DECISION_MACRO_INDICATORS,
                ),
                strict=bool(options.get("strict")),
                quote_max_age_hours=float(options.get("quote_max_age_hours") or 4.0),
                repair_pulse=not bool(options.get("skip_pulse")),
                repair_alpha=not bool(options.get("skip_alpha")),
            )
        )
        payload = report.to_dict()
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        if options.get("strict") and payload["must_not_use_for_decision"]:
            raise CommandError("Decision data reliability repair completed but remains blocked.")

    def _resolve_user(self, user_id: int | None):
        User = get_user_model()
        if user_id is not None:
            return User.objects.filter(pk=user_id).first()
        return User.objects.filter(is_superuser=True).order_by("id").first()

    @staticmethod
    def _build_pulse_refresher():
        def _refresh(target_date: date):
            from apps.pulse.application.use_cases import CalculatePulseUseCase

            return CalculatePulseUseCase().execute(as_of_date=target_date)

        return _refresh

    @staticmethod
    def _build_alpha_refresher(user):
        def _refresh(target_date: date, portfolio_id: int | None) -> dict:
            if user is None:
                return {"status": "skipped", "message": "No admin user is available."}
            if portfolio_id is None:
                return {"status": "skipped", "message": "portfolio_id is required."}

            from apps.alpha.application.pool_resolver import PortfolioAlphaPoolResolver
            from apps.alpha.application.tasks import qlib_predict_scores

            call_command(
                "build_qlib_data",
                target_date=target_date.isoformat(),
                universes="csi300,csi500,sse50,csi1000",
                lookback_days=400,
                verbosity=0,
            )
            resolved = PortfolioAlphaPoolResolver().resolve(
                user_id=user.id,
                portfolio_id=portfolio_id,
                trade_date=target_date,
                pool_mode="price_covered",
            )
            result = qlib_predict_scores.apply(
                args=[resolved.scope.universe_id, target_date.isoformat(), 30],
                kwargs={"scope_payload": resolved.scope.to_dict()},
            ).get()
            return {
                "status": "completed",
                "scope_hash": resolved.scope.scope_hash,
                "universe_id": resolved.scope.universe_id,
                "qlib_result": result,
            }

        return _refresh

    @staticmethod
    def _build_alpha_status_reader(user):
        def _read(target_date: date, portfolio_id: int | None) -> dict:
            if user is None or portfolio_id is None:
                return {"status": "blocked", "recommendation_ready": False}

            from apps.dashboard.application.alpha_homepage import AlphaHomepageQuery

            data = AlphaHomepageQuery().execute(
                user=user,
                top_n=10,
                portfolio_id=portfolio_id,
                pool_mode="price_covered",
            )
            meta = dict(data.meta or {})
            return {
                "status": "ready" if meta.get("recommendation_ready") else "blocked",
                "recommendation_ready": bool(meta.get("recommendation_ready")),
                "actionable_candidate_count": len(data.actionable_candidates),
                "requested_trade_date": meta.get("requested_trade_date") or target_date.isoformat(),
                "verified_asof_date": meta.get("verified_asof_date"),
                "scope_verification_status": meta.get("scope_verification_status"),
                "scope_hash": meta.get("scope_hash") or data.pool.get("scope_hash"),
                "freshness_status": meta.get("freshness_status"),
                "must_not_use_for_decision": bool(meta.get("must_not_use_for_decision", True)),
                "blocked_reason": meta.get("blocked_reason")
                or meta.get("no_recommendation_reason", ""),
            }

        return _read
