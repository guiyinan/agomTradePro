"""Dashboard application-layer gateways for cross-app integrations."""

from __future__ import annotations
from datetime import date, timedelta
from typing import Any

from apps.alpha_trigger.domain.entities import TriggerStatus, TriggerType


class DashboardApplicationGateway:
    """Bridge dashboard repositories to other apps through application APIs."""

    def get_stock_context_map(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        from apps.equity.application.query_services import get_stock_context_map

        return get_stock_context_map(codes)

    def resolve_asset(self, code: str) -> Any | None:
        from apps.data_center.application.dtos import ResolveAssetRequest
        from apps.data_center.application.interface_services import make_resolve_asset_use_case

        return make_resolve_asset_use_case().execute(ResolveAssetRequest(code=code))

    def query_latest_quote(self, asset_code: str) -> Any | None:
        from apps.data_center.application.dtos import LatestQuoteRequest
        from apps.data_center.application.interface_services import make_query_latest_quote_use_case

        return make_query_latest_quote_use_case().execute(LatestQuoteRequest(asset_code=asset_code))

    def list_actionable_alpha_candidates(self, *, limit: int) -> list[Any]:
        from apps.alpha_trigger.application.repository_provider import (
            get_alpha_candidate_repository,
        )

        return list(
            get_alpha_candidate_repository().list_models_by_status(
                "ACTIONABLE",
                limit=limit,
            )
        )

    def list_pending_execution_requests(self, *, limit: int) -> list[Any]:
        from apps.decision_rhythm.application.global_alert_service import (
            get_decision_rhythm_global_alert_service,
        )

        return list(
            get_decision_rhythm_global_alert_service().list_pending_execution_requests(limit=limit)
        )

    def get_manual_override_trigger_ids(self) -> set[str]:
        from apps.alpha_trigger.application.repository_provider import (
            get_alpha_trigger_repository,
        )

        trigger_repo = get_alpha_trigger_repository()
        return {
            str(trigger.trigger_id)
            for trigger in trigger_repo.get_by_type(TriggerType.MANUAL_OVERRIDE)
            if getattr(trigger, "status", None) in {TriggerStatus.ACTIVE, TriggerStatus.TRIGGERED}
        }

    def get_valuation_repair_snapshot_map(
        self,
        candidate_codes: list[str],
    ) -> dict[str, dict[str, Any]]:
        from apps.equity.application.query_services import get_valuation_repair_snapshot_map

        return get_valuation_repair_snapshot_map(candidate_codes)

    def get_policy_state(self) -> dict[str, Any]:
        from apps.policy.application.repository_provider import (
            get_current_policy_repository,
            get_workbench_repository,
        )
        from apps.policy.application.use_cases import GetCurrentPolicyUseCase

        current_policy = GetCurrentPolicyUseCase(get_current_policy_repository()).execute()
        effective_items = get_workbench_repository().list_workbench_items(
            tab="effective",
            limit=1,
            offset=0,
        )
        latest_effective = next(iter(effective_items.get("items", [])), None)
        if latest_effective is None:
            return {"gate_level": "L0", "effective": False}
        return {
            "gate_level": str(latest_effective.get("gate_level") or "L0"),
            "effective": True,
            "event_date": latest_effective.get("event_date"),
            "title": str(latest_effective.get("title") or ""),
            "policy_level": (
                current_policy.policy_level.value
                if current_policy.success and current_policy.policy_level
                else None
            ),
        }

    def get_user_account_totals(self, user_id: int) -> dict[str, float] | None:
        from apps.simulated_trading.application.query_services import get_user_account_totals

        return get_user_account_totals(user_id)

    def list_user_positions(
        self,
        *,
        user_id: int,
        account_id: int | None = None,
        include_account_meta: bool = False,
    ) -> list[dict]:
        from apps.simulated_trading.application.query_services import list_user_position_payloads

        return list_user_position_payloads(
            user_id=user_id,
            account_id=account_id,
            include_account_meta=include_account_meta,
        )

    def list_dashboard_accounts(self, user_id: int) -> list[dict]:
        from apps.simulated_trading.application.query_services import (
            list_dashboard_account_payloads,
        )

        return list_dashboard_account_payloads(user_id)

    def get_policy_environment(
        self,
        user_id: int,
    ) -> tuple[str | None, date | None, int, list[dict]]:
        from apps.policy.application.repository_provider import (
            get_current_policy_repository,
            get_workbench_repository,
        )

        policy_repo = get_current_policy_repository()
        workbench_repo = get_workbench_repository()

        current_policy_level = None
        current_policy_date = None
        current_level = policy_repo.get_current_policy_level(date.today())
        if current_level is not None:
            current_policy_level = current_level.value

        effective_items = workbench_repo.list_workbench_items(
            tab="effective",
            limit=1,
            offset=0,
        )
        latest_effective = next(iter(effective_items.get("items", [])), None)
        if latest_effective and latest_effective.get("event_date"):
            current_policy_date = date.fromisoformat(latest_effective["event_date"])

        pending_review_count = len(
            workbench_repo.list_audit_queue_items(
                assigned_user_id=user_id,
                limit=500,
            )
        )

        recent_policies: list[dict[str, Any]] = []
        recent_items = workbench_repo.list_workbench_items(
            tab="effective",
            start_date=date.today() - timedelta(days=7),
            limit=5,
            offset=0,
        )
        for policy in recent_items.get("items", []):
            recent_policies.append(
                {
                    "id": policy.get("id"),
                    "title": str(policy.get("title") or ""),
                    "level": policy.get("level"),
                    "level_display": str(policy.get("level") or ""),
                    "category": policy.get("event_type"),
                    "category_display": str(policy.get("event_type") or ""),
                    "created_at": str(policy.get("created_at") or ""),
                }
            )

        return current_policy_level, current_policy_date, pending_review_count, recent_policies

    def get_growth_series(
        self,
        *,
        indicator_code: str,
        end_date: date,
        use_pit: bool = False,
        full: bool = False,
    ) -> list[Any]:
        from apps.regime.application.query_services import get_growth_series

        return get_growth_series(
            indicator_code=indicator_code,
            end_date=end_date,
            use_pit=use_pit,
            full=full,
        )

    def get_inflation_series(
        self,
        *,
        indicator_code: str,
        end_date: date,
        use_pit: bool = False,
        full: bool = False,
    ) -> list[Any]:
        from apps.regime.application.query_services import get_inflation_series

        return get_inflation_series(
            indicator_code=indicator_code,
            end_date=end_date,
            use_pit=use_pit,
            full=full,
        )

    def get_primary_system_ai_provider_payload(self) -> dict[str, Any] | None:
        from apps.ai_provider.application.query_services import get_primary_system_provider_payload

        return get_primary_system_provider_payload()

    def list_global_investment_rule_payloads(self) -> list[dict[str, Any]]:
        from apps.account.application.query_services import list_global_investment_rule_payloads

        return list_global_investment_rule_payloads()

    def get_portfolio_snapshot_performance_data(self, portfolio_id: int) -> list[dict]:
        from apps.account.application.query_services import get_portfolio_snapshot_performance_data

        return get_portfolio_snapshot_performance_data(portfolio_id)

    def get_user_performance_payload(
        self,
        *,
        user_id: int,
        account_id: int | None,
        days: int,
    ) -> list[dict]:
        from apps.simulated_trading.application.query_services import get_user_performance_payload

        return get_user_performance_payload(
            user_id=user_id,
            account_id=account_id,
            days=days,
        )

    def get_alpha_ic_trends(self, days: int) -> list[dict[str, Any]]:
        from apps.alpha.application.query_services import get_alpha_ic_trends

        return get_alpha_ic_trends(days)

    def get_latest_macro_indicator_value(self, indicator_code: str) -> float | None:
        from apps.data_center.application.query_services import get_latest_macro_indicator_value

        return get_latest_macro_indicator_value(indicator_code)

    def get_position_detail_payload(self, user_id: int, asset_code: str) -> dict[str, Any] | None:
        from apps.account.application.query_services import get_position_detail_payload

        return get_position_detail_payload(user_id, asset_code)

    def list_active_signal_payloads_by_asset(
        self,
        *,
        asset_code: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        from apps.signal.application.query_services import list_active_signal_payloads_by_asset

        return list_active_signal_payloads_by_asset(
            asset_code=asset_code,
            limit=limit,
        )

    def get_candidate_generation_context(self, *, limit: int) -> dict[str, Any]:
        from apps.alpha_trigger.application.query_services import (
            get_candidate_generation_context,
        )

        return get_candidate_generation_context(limit=limit)


def build_dashboard_application_gateway() -> DashboardApplicationGateway:
    """Build the default dashboard integration gateway."""

    return DashboardApplicationGateway()
