"""Repair decision-grade data freshness across Data Center, Pulse, and Alpha."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from math import isfinite
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError, call_command
from django.core.management.base import CommandParser
from django.utils import timezone

from apps.data_center.application.dtos import DecisionReliabilityRepairRequest, SyncQuoteRequest
from apps.data_center.application.interface_services import (
    load_alpha_homepage_data,
    queue_alpha_score_prediction,
    refresh_pulse_snapshot,
    resolve_portfolio_alpha_scope,
    run_alpha_score_prediction_now,
)
from apps.data_center.application.sync_use_cases import RECOVERABLE_DATA_CENTER_EXCEPTIONS
from apps.data_center.application.use_cases import (
    DEFAULT_DECISION_ASSET_CODES,
    DEFAULT_DECISION_MACRO_INDICATORS,
    RepairDecisionDataReliabilityUseCase,
)
from apps.data_center.composition import (
    build_provider_registry_for_repo,
    make_publication_decision_read_recorder,
    make_repair_run_audit_dependencies,
    make_system_audited_sync_macro_use_case,
    make_system_audited_sync_price_use_case,
    make_system_audited_sync_quote_use_case,
)
from apps.data_center.infrastructure.repositories import (
    IndicatorCatalogRepository,
    IndicatorUnitRuleRepository,
    MacroFactRepository,
    PriceBarRepository,
    ProviderConfigRepository,
    QuoteSnapshotRepository,
)

ALPHA_POOL_MODE_STRICT_VALUATION = "strict_valuation"
MAX_REPAIR_CODES = 200
CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,63}$")


def _split_codes(
    raw: object,
    defaults: tuple[str, ...],
    *,
    option_name: str,
) -> list[str]:
    """Normalize, deduplicate, and bound one comma-separated code option."""

    if raw is None:
        return list(defaults)
    if not isinstance(raw, str) or not raw.strip():
        raise CommandError(f"{option_name} must be a non-empty comma-separated string")
    codes = list(dict.fromkeys(item.strip().upper() for item in raw.split(",") if item.strip()))
    if not codes:
        raise CommandError(f"{option_name} must contain at least one code")
    if len(codes) > MAX_REPAIR_CODES:
        raise CommandError(f"{option_name} accepts at most {MAX_REPAIR_CODES} unique codes")
    invalid_codes = [code for code in codes if CODE_PATTERN.fullmatch(code) is None]
    if invalid_codes:
        raise CommandError(f"{option_name} contains invalid code: {invalid_codes[0]}")
    return codes


class Command(BaseCommand):
    help = "Repair data inputs required for actionable decision outputs."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--target-date", dest="target_date", default=None)
        parser.add_argument("--portfolio-id", dest="portfolio_id", type=int, default=None)
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

    def handle(self, *args: object, **options: Any) -> None:
        raw_target_date = options.get("target_date")
        if raw_target_date is not None and (
            not isinstance(raw_target_date, str) or not raw_target_date.strip()
        ):
            raise CommandError("--target-date must use YYYY-MM-DD")
        try:
            target_date = (
                date.fromisoformat(raw_target_date.strip())
                if isinstance(raw_target_date, str)
                else timezone.localdate()
            )
        except ValueError as exc:
            raise CommandError("--target-date must use YYYY-MM-DD") from exc
        if target_date > timezone.localdate():
            raise CommandError("--target-date cannot be in the future")

        user_id = self._optional_positive_id(options.get("user_id"), "--user-id")
        portfolio_id = self._optional_positive_id(
            options.get("portfolio_id"),
            "--portfolio-id",
        )
        quote_max_age_hours = self._positive_finite_float(
            options.get("quote_max_age_hours"),
            "--quote-max-age-hours",
        )
        user = self._resolve_user(user_id)
        if not options.get("skip_alpha") and user is None:
            raise CommandError(
                "Alpha repair requires an active user; pass --user-id or create an active superuser"
            )
        if portfolio_id is None:
            portfolio_id = self._resolve_default_portfolio_id(user, target_date)
        provider_repo = ProviderConfigRepository()
        macro_repository = MacroFactRepository()
        price_repository = PriceBarRepository()
        quote_repository = QuoteSnapshotRepository()
        provider_registry = build_provider_registry_for_repo(provider_repo)
        repair_audit = make_repair_run_audit_dependencies()
        use_case = RepairDecisionDataReliabilityUseCase(
            provider_repo=provider_repo,
            provider_registry=provider_registry,
            macro_fact_repo=macro_repository,
            indicator_catalog_repo=IndicatorCatalogRepository(),
            indicator_unit_rule_repo=IndicatorUnitRuleRepository(),
            price_bar_repo=price_repository,
            quote_snapshot_repo=quote_repository,
            macro_sync_use_case=make_system_audited_sync_macro_use_case(
                provider_repository=provider_repo,
                provider_registry=provider_registry,
            ),
            price_sync_use_case=make_system_audited_sync_price_use_case(
                provider_repository=provider_repo,
                provider_registry=provider_registry,
                publish_current=False,
            ),
            quote_sync_use_case=make_system_audited_sync_quote_use_case(
                provider_repository=provider_repo,
                provider_registry=provider_registry,
                publish_current=False,
            ),
            decision_read_recorder=make_publication_decision_read_recorder(),
            sync_identity_issuer=repair_audit.identity_issuer,
            repair_run_identity_unit_of_work=repair_audit.identity_unit_of_work,
            data_repair_audit_writer=repair_audit.audit_writer,
            clock=repair_audit.clock,
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
                portfolio_id=portfolio_id,
                asset_codes=_split_codes(
                    options.get("asset_codes"),
                    DEFAULT_DECISION_ASSET_CODES,
                    option_name="--asset-codes",
                ),
                macro_indicator_codes=_split_codes(
                    options.get("macro_indicator_codes"),
                    DEFAULT_DECISION_MACRO_INDICATORS,
                    option_name="--macro-indicator-codes",
                ),
                strict=bool(options.get("strict")),
                quote_max_age_hours=quote_max_age_hours,
                repair_pulse=not bool(options.get("skip_pulse")),
                repair_alpha=not bool(options.get("skip_alpha")),
            )
        )
        payload = report.to_dict()
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        if options.get("strict") and payload["must_not_use_for_decision"]:
            raise CommandError("Decision data reliability repair completed but remains blocked.")

    @staticmethod
    def _optional_positive_id(raw_value: object, option_name: str) -> int | None:
        if raw_value is None:
            return None
        if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value <= 0:
            raise CommandError(f"{option_name} must be a positive integer")
        return raw_value

    @staticmethod
    def _positive_finite_float(raw_value: object, option_name: str) -> float:
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise CommandError(f"{option_name} must be a positive finite number")
        value = float(raw_value)
        if not isfinite(value) or value <= 0:
            raise CommandError(f"{option_name} must be a positive finite number")
        return value

    def _resolve_user(self, user_id: int | None) -> Any | None:
        User = get_user_model()
        if user_id is not None:
            user = User._default_manager.filter(pk=user_id, is_active=True).first()
            if user is None:
                raise CommandError(f"Active user not found: {user_id}")
            return user
        return (
            User._default_manager.filter(is_superuser=True, is_active=True).order_by("id").first()
        )

    @staticmethod
    def _build_pulse_refresher() -> Callable[[date], Any]:
        def _refresh(target_date: date) -> Any:
            return refresh_pulse_snapshot(target_date=target_date)

        return _refresh

    @staticmethod
    def _build_alpha_refresher(
        user: Any | None,
        *,
        sync_alpha: bool = False,
    ) -> Callable[[date, int | None], dict[str, Any]]:
        def _refresh(target_date: date, portfolio_id: int | None) -> dict[str, Any]:
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
                pool_mode=ALPHA_POOL_MODE_STRICT_VALUATION,
            )
            quote_sync_result = Command._sync_scope_quotes(
                list(getattr(resolved.scope, "instrument_codes", ()) or ())
            )
            task_kwargs: dict[str, Any] = {"scope_payload": resolved.scope.to_dict()}
            if sync_alpha:
                result = run_alpha_score_prediction_now(
                    universe_id=resolved.scope.universe_id,
                    trade_date=target_date,
                    scope_payload=task_kwargs["scope_payload"],
                )
                status = "completed"
                task_id = ""
            else:
                import kombu.exceptions as kombu_exceptions  # type: ignore[import-untyped]

                try:
                    task = queue_alpha_score_prediction(
                        universe_id=resolved.scope.universe_id,
                        trade_date=target_date,
                        scope_payload=task_kwargs["scope_payload"],
                    )
                except (
                    kombu_exceptions.OperationalError,
                    ConnectionError,
                    OSError,
                    TimeoutError,
                ) as exc:
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
                task_id = str(getattr(task, "id", "") or "")
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
    def _sync_scope_quotes(asset_codes: list[str]) -> dict[str, Any]:
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
            result = make_system_audited_sync_quote_use_case(
                provider_repository=provider_repo,
                provider_registry=build_provider_registry_for_repo(provider_repo),
                publish_current=False,
            ).execute(
                SyncQuoteRequest(
                    provider_id=provider.id,
                    asset_codes=normalized_codes,
                )
            )
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            return {"status": "failed", "error_class": type(exc).__name__}
        return result.to_dict()

    @staticmethod
    def _build_alpha_status_reader(
        user: Any | None,
    ) -> Callable[[date, int | None], dict[str, Any]]:
        def _read(target_date: date, portfolio_id: int | None) -> dict[str, Any]:
            if user is None or portfolio_id is None:
                return {"status": "blocked", "recommendation_ready": False}

            data = load_alpha_homepage_data(
                user=user,
                top_n=10,
                portfolio_id=portfolio_id,
                pool_mode=ALPHA_POOL_MODE_STRICT_VALUATION,
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

    @staticmethod
    def _resolve_default_portfolio_id(user: Any | None, target_date: date) -> int | None:
        if user is None:
            return None
        resolved = resolve_portfolio_alpha_scope(
            user_id=user.id,
            portfolio_id=None,
            trade_date=target_date,
        )
        return resolved.portfolio_id
