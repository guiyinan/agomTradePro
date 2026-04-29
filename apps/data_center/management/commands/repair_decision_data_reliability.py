"""Repair decision-grade data freshness across Data Center, Pulse, and Alpha."""

from __future__ import annotations

import json
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError, call_command
from core.integration.alpha_runtime import (
    queue_alpha_score_prediction,
    resolve_portfolio_alpha_scope,
    run_alpha_score_prediction_now,
)
from core.integration.alpha_homepage import load_alpha_homepage_data
from core.integration.pulse_refresh import refresh_pulse_snapshot

from apps.data_center.application.dtos import DecisionReliabilityRepairRequest
from apps.data_center.application.dtos import SyncQuoteRequest
from apps.data_center.application.use_cases import (
    DEFAULT_DECISION_ASSET_CODES,
    DEFAULT_DECISION_MACRO_INDICATORS,
    RepairDecisionDataReliabilityUseCase,
    SyncQuoteUseCase,
)
from apps.data_center.infrastructure.provider_factory import UnifiedProviderFactory
from apps.data_center.infrastructure.repositories import (
    IndicatorCatalogRepository,
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
        parser.add_argument(
            "--sync-alpha",
            dest="sync_alpha",
            action="store_true",
            help="Run scoped Alpha inference synchronously. Default queues it to avoid blocking repair.",
        )

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
            pulse_refresher=self._build_pulse_refresher(),
            alpha_refresher=self._build_alpha_refresher(
                user,
                sync_alpha=bool(options.get("sync_alpha")),
            ),
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
            return refresh_pulse_snapshot(target_date=target_date)

        return _refresh

    @staticmethod
    def _build_alpha_refresher(user, *, sync_alpha: bool = False):
        def _refresh(target_date: date, portfolio_id: int | None) -> dict:
            if user is None:
                return {"status": "skipped", "message": "No admin user is available."}
            if portfolio_id is None:
                return {"status": "skipped", "message": "portfolio_id is required."}

            try:
                call_command(
                    "build_qlib_data",
                    check_only=True,
                    target_date=target_date.isoformat(),
                    verbosity=0,
                )
            except CommandError:
                call_command(
                    "build_qlib_data",
                    target_date=target_date.isoformat(),
                    universes="csi300,csi500,sse50,csi1000",
                    lookback_days=400,
                    verbosity=0,
                )
            resolved = resolve_portfolio_alpha_scope(
                user_id=user.id,
                portfolio_id=portfolio_id,
                trade_date=target_date,
            )
            quote_sync_result = Command._sync_scope_quotes(
                list(getattr(resolved.scope, "instrument_codes", ()) or ())
            )
            task_kwargs = {"scope_payload": resolved.scope.to_dict()}
            if sync_alpha:
                result = run_alpha_score_prediction_now(
                    universe_id=resolved.scope.universe_id,
                    trade_date=target_date,
                    scope_payload=task_kwargs["scope_payload"],
                )
                status = "completed"
                task_id = ""
            else:
                from kombu.exceptions import OperationalError as KombuOperationalError

                try:
                    task = queue_alpha_score_prediction(
                        universe_id=resolved.scope.universe_id,
                        trade_date=target_date,
                        scope_payload=task_kwargs["scope_payload"],
                    )
                except (KombuOperationalError, ConnectionError, OSError, TimeoutError) as exc:
                    return {
                        "status": "queue_failed",
                        "scope_hash": resolved.scope.scope_hash,
                        "universe_id": resolved.scope.universe_id,
                        "task_id": "",
                        "qlib_result": {
                            "message": "Scoped Alpha inference queue is unavailable.",
                            "error_message": str(exc),
                        },
                        "quote_sync": quote_sync_result,
                    }
                result = {
                    "message": "Scoped Alpha inference queued.",
                    "task_id": getattr(task, "id", ""),
                }
                status = "queued"
                task_id = getattr(task, "id", "")
            return {
                "status": status,
                "scope_hash": resolved.scope.scope_hash,
                "universe_id": resolved.scope.universe_id,
                "task_id": task_id,
                "qlib_result": result,
                "quote_sync": quote_sync_result,
            }

        return _refresh

    @staticmethod
    def _sync_scope_quotes(asset_codes: list[str]) -> dict:
        normalized_codes = [str(code or "").strip().upper() for code in asset_codes if code]
        if not normalized_codes:
            return {"status": "skipped", "message": "No scoped instruments to sync."}

        provider_repo = ProviderConfigRepository()
        source_priority = {"akshare": 0, "eastmoney": 1, "tushare": 2}
        providers = [
            item
            for item in provider_repo.list_all()
            if item.is_active and item.id is not None and item.source_type in source_priority
        ]
        providers.sort(key=lambda item: (source_priority[item.source_type], item.priority))
        provider = providers[0] if providers else None
        if provider is None or provider.id is None:
            return {"status": "skipped", "message": "No realtime quote provider is available."}

        try:
            result = SyncQuoteUseCase(
                provider_repo=provider_repo,
                provider_factory=UnifiedProviderFactory(provider_repo),
                fact_repo=QuoteSnapshotRepository(),
                raw_audit_repo=RawAuditRepository(),
            ).execute(
                SyncQuoteRequest(
                    provider_id=provider.id,
                    asset_codes=normalized_codes,
                )
            )
        except Exception as exc:
            return {"status": "failed", "error_message": str(exc)}
        return result.to_dict()

    @staticmethod
    def _build_alpha_status_reader(user):
        def _read(target_date: date, portfolio_id: int | None) -> dict:
            if user is None or portfolio_id is None:
                return {"status": "blocked", "recommendation_ready": False}

            data = load_alpha_homepage_data(
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
                "latest_completed_session_result": bool(
                    meta.get("latest_completed_session_result", False)
                ),
                "must_not_use_for_decision": bool(meta.get("must_not_use_for_decision", True)),
                "blocked_reason": meta.get("blocked_reason")
                or meta.get("no_recommendation_reason", ""),
            }

        return _read
