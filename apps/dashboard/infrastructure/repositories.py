"""
Dashboard Infrastructure Repositories

仪表盘数据仓储实现。
"""

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

from apps.dashboard.domain.entities import (
    AlertConfig,
    AlertSeverity,
    CardType,
    DashboardCard,
    DashboardLayout,
    DashboardPreferences,
    DashboardWidget,
    WidgetType,
)
from apps.dashboard.domain.services import LayoutResolutionResult

from .models import (
    AlphaRecommendationRunModel,
    AlphaRecommendationSnapshotModel,
    DashboardAlertModel,
    DashboardCardModel,
    DashboardConfigModel,
    DashboardSnapshotModel,
    DashboardUserConfigModel,
)

logger = logging.getLogger(__name__)

User = get_user_model()


class DashboardAlphaContextRepository:
    """ORM-backed context loader for the Dashboard Alpha homepage view."""

    def load_stock_context(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        if not codes:
            return {}

        from apps.equity.infrastructure.models import StockDailyModel, StockInfoModel
        code_aliases = self._build_code_aliases(codes)
        lookup_codes = sorted({alias for aliases in code_aliases.values() for alias in aliases})
        info_rows = StockInfoModel._default_manager.filter(stock_code__in=lookup_codes).values(
            "stock_code",
            "name",
            "sector",
            "market",
        )
        info_map = {str(row["stock_code"]).upper(): row for row in info_rows}

        daily_rows = (
            StockDailyModel._default_manager.filter(stock_code__in=lookup_codes)
            .order_by("stock_code", "-trade_date")
            .values("stock_code", "trade_date", "close", "volume")
        )
        daily_map: dict[str, dict[str, Any]] = {}
        for row in daily_rows:
            code = str(row["stock_code"]).upper()
            if code not in daily_map:
                daily_map[code] = row

        asset_context = self._load_data_center_asset_context(codes)
        quote_context = self._load_data_center_quote_context(codes, code_aliases)
        missing_codes = [
            code
            for code in codes
            if not self._extract_name_from_rows(code_aliases.get(code, {code}), info_map)
            and not asset_context.get(code, {}).get("name")
        ]
        if missing_codes:
            self._backfill_data_center_assets(missing_codes)
            asset_context.update(self._load_data_center_asset_context(missing_codes))

        context: dict[str, dict[str, Any]] = {}
        for code in codes:
            aliases = code_aliases.get(code, {code})
            info = self._extract_info_row(aliases, info_map)
            latest_daily = self._extract_daily_row(aliases, daily_map)
            master_info = asset_context.get(code, {})
            info.update(
                {
                    "name": info.get("name") or master_info.get("name") or "",
                    "sector": info.get("sector") or master_info.get("sector") or "",
                    "market": info.get("market") or master_info.get("market") or "",
                    "close": float(
                        quote_context.get(code, {}).get("current_price")
                        or latest_daily.get("close")
                        or 0.0
                    ),
                    "volume": float(
                        quote_context.get(code, {}).get("volume")
                        or latest_daily.get("volume")
                        or 0.0
                    ),
                    "trade_date": (
                        latest_daily.get("trade_date").isoformat()
                        if latest_daily.get("trade_date")
                        else None
                    ),
                    "quote_snapshot_at": quote_context.get(code, {}).get("snapshot_at"),
                    "quote_source": quote_context.get(code, {}).get("source", ""),
                }
            )
            context[code] = info
        return context

    @staticmethod
    def _build_code_aliases(codes: list[str]) -> dict[str, set[str]]:
        aliases: dict[str, set[str]] = {}
        for raw_code in codes:
            normalized = str(raw_code or "").strip().upper()
            if not normalized:
                continue
            code_aliases = {normalized}
            base_code = normalized.split(".", 1)[0]
            if base_code:
                code_aliases.add(base_code)
            aliases[normalized] = code_aliases
        return aliases

    @staticmethod
    def _extract_info_row(
        aliases: set[str],
        info_map: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        for alias in aliases:
            row = info_map.get(alias)
            if row:
                return dict(row)
        return {}

    @staticmethod
    def _extract_daily_row(
        aliases: set[str],
        daily_map: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        for alias in aliases:
            row = daily_map.get(alias)
            if row:
                return row
        return {}

    @staticmethod
    def _extract_name_from_rows(
        aliases: set[str],
        info_map: dict[str, dict[str, Any]],
    ) -> str:
        for alias in aliases:
            name = str((info_map.get(alias) or {}).get("name") or "").strip()
            if name:
                return name
        return ""

    def _load_data_center_asset_context(self, codes: list[str]) -> dict[str, dict[str, str]]:
        from apps.data_center.infrastructure.repositories import AssetRepository

        asset_repo = AssetRepository()
        context: dict[str, dict[str, str]] = {}
        for code in codes:
            asset = asset_repo.get_by_code(code)
            if asset is None:
                continue
            context[str(code).strip().upper()] = {
                "name": asset.short_name or asset.name,
                "sector": asset.sector or asset.industry or "",
                "market": asset.exchange.value,
            }
        return context

    def _load_data_center_quote_context(
        self,
        codes: list[str],
        code_aliases: dict[str, set[str]],
    ) -> dict[str, dict[str, Any]]:
        if not codes:
            return {}

        from apps.data_center.infrastructure.models import QuoteSnapshotModel

        lookup_codes = sorted({alias for aliases in code_aliases.values() for alias in aliases})
        rows = (
            QuoteSnapshotModel._default_manager.filter(asset_code__in=lookup_codes)
            .order_by("asset_code", "-snapshot_at")
            .values(
                "asset_code",
                "snapshot_at",
                "current_price",
                "volume",
                "source",
            )
        )
        latest_by_code: dict[str, dict[str, Any]] = {}
        for row in rows:
            code = str(row["asset_code"]).upper()
            latest_by_code.setdefault(code, row)

        context: dict[str, dict[str, Any]] = {}
        for code in codes:
            for alias in code_aliases.get(code, {code}):
                row = latest_by_code.get(str(alias).upper())
                if not row:
                    continue
                snapshot_at = row.get("snapshot_at")
                context[code] = {
                    "current_price": float(row.get("current_price") or 0.0),
                    "volume": float(row.get("volume") or 0.0),
                    "snapshot_at": snapshot_at.isoformat() if snapshot_at else None,
                    "source": row.get("source") or "",
                }
                break
        return context

    def _backfill_data_center_assets(self, codes: list[str]) -> None:
        if not codes:
            return

        from apps.data_center.infrastructure.asset_master_backfill import (
            AssetMasterBackfillService,
        )

        AssetMasterBackfillService().backfill_codes(codes, include_remote=False)

    def load_actionable_map(self) -> dict[str, Any]:
        from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel

        queryset = AlphaCandidateModel._default_manager.filter(status="ACTIONABLE").order_by(
            "-confidence", "-created_at"
        )
        return {str(item.asset_code).upper(): item for item in queryset[:200]}

    def load_pending_map(self) -> dict[str, Any]:
        from apps.decision_rhythm.infrastructure.models import DecisionRequestModel

        queryset = DecisionRequestModel._default_manager.filter(
            response__approved=True, execution_status__in=["PENDING", "FAILED"]
        ).order_by("-requested_at")
        pending_map: dict[str, Any] = {}
        for item in queryset[:200]:
            code = str(item.asset_code or "").upper()
            pending_map.setdefault(code, item)
        return pending_map

    def load_user_account_totals(self, user_id: int) -> dict[str, float] | None:
        """Load simulated account totals for sizing fallback."""

        return DashboardOverviewRepository().get_user_simulated_account_totals(user_id)

    def load_actionable_candidates(self, max_count: int | None) -> list[Any]:
        from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel, AlphaTriggerModel
        from apps.decision_rhythm.infrastructure.models import DecisionRequestModel
        from apps.equity.infrastructure.models import ValuationRepairTrackingModel

        pending_codes = {
            (code or "").upper()
            for code in DecisionRequestModel._default_manager.filter(
                response__approved=True,
                execution_status__in=["PENDING", "FAILED"],
            ).values_list("asset_code", flat=True)
        }
        manual_override_trigger_ids = set(
            AlphaTriggerModel._default_manager.filter(
                trigger_type=AlphaTriggerModel.MANUAL_OVERRIDE,
                status__in=[AlphaTriggerModel.ACTIVE, AlphaTriggerModel.TRIGGERED],
            ).values_list("trigger_id", flat=True)
        )
        candidates = list(
            AlphaCandidateModel._default_manager.filter(status="ACTIONABLE")
            .order_by("-confidence", "-created_at")[:50]
        )

        candidate_codes = [
            (getattr(item, "asset_code", "") or "").upper()
            for item in candidates
        ]
        repair_map = self._load_valuation_repair_map(candidate_codes)

        deduped: list[Any] = []
        seen_codes: set[str] = set()
        for item in candidates:
            code = (getattr(item, "asset_code", "") or "").upper()
            trigger_id = str(getattr(item, "trigger_id", "") or "")
            if (
                not code
                or code in seen_codes
                or code in pending_codes
                or trigger_id in manual_override_trigger_ids
            ):
                continue
            seen_codes.add(code)

            repair_payload = repair_map.get(code)
            item.valuation_repair = repair_payload
            item._valuation_repair = repair_payload
            deduped.append(item)
            if max_count is not None and len(deduped) >= max_count:
                break

        return deduped

    def _load_valuation_repair_map(self, candidate_codes: list[str]) -> dict[str, dict[str, Any]]:
        if not candidate_codes:
            return {}

        from apps.equity.infrastructure.models import ValuationRepairTrackingModel

        try:
            repair_records = ValuationRepairTrackingModel._default_manager.filter(
                stock_code__in=[code for code in candidate_codes if code],
                is_active=True,
            ).values(
                "stock_code",
                "current_phase",
                "signal",
                "composite_percentile",
                "repair_progress",
                "repair_speed_per_30d",
                "estimated_days_to_target",
            )
        except Exception as exc:
            logger.warning("Failed to get valuation repair info: %s", exc)
            return {}

        repair_map: dict[str, dict[str, Any]] = {}
        for record in repair_records:
            stock_code = str(record.get("stock_code") or "").upper()
            if not stock_code:
                continue
            repair_map[stock_code] = {
                "phase": record.get("current_phase"),
                "signal": record.get("signal"),
                "composite_percentile": record.get("composite_percentile"),
                "repair_progress": record.get("repair_progress"),
                "repair_speed_per_30d": record.get("repair_speed_per_30d"),
                "estimated_days_to_target": record.get("estimated_days_to_target"),
            }
        return repair_map

    def load_policy_state(self) -> dict[str, Any]:
        try:
            from apps.policy.infrastructure.models import PolicyLog

            policy = (
                PolicyLog._default_manager.filter(gate_effective=True)
                .exclude(gate_level__isnull=True)
                .order_by("-effective_at", "-event_date")
                .first()
            )
            if policy is None:
                return {"gate_level": "L0", "effective": False}
            return {
                "gate_level": policy.gate_level or "L0",
                "effective": bool(policy.gate_effective),
                "event_date": policy.event_date.isoformat(),
                "title": policy.title,
            }
        except Exception as exc:
            logger.warning("Failed to load policy gate state: %s", exc)
            return {"gate_level": "L0", "effective": False}


class DashboardOverviewRepository:
    """ORM-backed read model for dashboard overview use cases."""

    def get_user_simulated_account_totals(self, user_id: int) -> dict[str, float] | None:
        """Return aggregated totals from the simulated-account system."""

        from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

        accounts = list(SimulatedAccountModel._default_manager.filter(user_id=user_id))
        if not accounts:
            return None

        total_assets = 0.0
        initial_capital = 0.0
        cash_balance = 0.0
        invested_value = 0.0
        for account in accounts:
            total_assets += float(account.total_value or 0.0)
            initial_capital += float(account.initial_capital or 0.0)
            cash_balance += float(account.current_cash or 0.0)
            invested_value += float(account.current_market_value or 0.0)

        total_return = total_assets - initial_capital
        total_return_pct = (total_return / initial_capital * 100) if initial_capital else 0.0
        invested_ratio = (invested_value / total_assets) if total_assets else 0.0

        return {
            "total_assets": total_assets,
            "initial_capital": initial_capital,
            "cash_balance": cash_balance,
            "invested_value": invested_value,
            "invested_ratio": invested_ratio,
            "total_return": total_return,
            "total_return_pct": total_return_pct,
        }

    def get_simulated_positions(self, user_id: int) -> list[dict]:
        """Return holdings from the simulated-account system."""

        from apps.simulated_trading.infrastructure.models import PositionModel

        sim_positions = (
            PositionModel._default_manager.filter(account__user_id=user_id)
            .select_related("account")
            .order_by("-market_value", "asset_code")
        )
        if not sim_positions.exists():
            return []

        return [
            {
                "id": pos.id,
                "asset_code": pos.asset_code,
                "asset_name": pos.asset_name,
                "asset_class": pos.asset_type,
                "shares": float(pos.quantity),
                "avg_cost": float(pos.avg_cost),
                "current_price": float(pos.current_price),
                "market_value": float(pos.market_value),
                "unrealized_pnl": float(pos.unrealized_pnl),
                "unrealized_pnl_pct": pos.unrealized_pnl_pct,
                "opened_at": pos.first_buy_date.strftime("%Y-%m-%d") if pos.first_buy_date else "",
            }
            for pos in sim_positions
        ]

    def get_simulated_positions_for_dashboard(
        self,
        user_id: int,
        account_id: int | None = None,
    ) -> list[dict]:
        """Return simulated-account positions with account metadata for dashboard views."""

        from apps.simulated_trading.infrastructure.models import PositionModel

        qs = PositionModel._default_manager.filter(account__user_id=user_id)
        if account_id:
            qs = qs.filter(account_id=account_id)
        positions = qs.select_related("account").order_by("-market_value", "asset_code")
        return [
            {
                "id": pos.id,
                "asset_code": pos.asset_code,
                "asset_name": pos.asset_name,
                "asset_class": pos.asset_type,
                "asset_class_display": pos.get_asset_type_display(),
                "region": "CN",
                "region_display": "中国",
                "shares": float(pos.quantity),
                "avg_cost": float(pos.avg_cost),
                "current_price": float(pos.current_price),
                "market_value": float(pos.market_value),
                "unrealized_pnl": float(pos.unrealized_pnl),
                "unrealized_pnl_pct": pos.unrealized_pnl_pct,
                "opened_at": pos.first_buy_date.strftime("%Y-%m-%d") if pos.first_buy_date else "",
                "account_id": pos.account_id,
                "account_name": pos.account.account_name if pos.account else "",
            }
            for pos in positions
        ]

    def get_dashboard_accounts(self, user_id: int) -> list[dict]:
        """Return investment account cards for the dashboard homepage."""

        from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

        accounts = (
            SimulatedAccountModel._default_manager
            .filter(user_id=user_id)
            .order_by("account_type", "-total_value", "-created_at")
        )
        return [
            {
                "id": account.id,
                "name": account.account_name,
                "type_code": account.account_type,
                "type_label": "实仓" if account.account_type == "real" else "模拟仓",
                "total_value": float(account.total_value or 0),
                "cash": float(account.current_cash or 0),
                "market_value": float(account.current_market_value or 0),
                "total_return": float(account.total_return or 0),
                "is_active": account.is_active,
            }
            for account in accounts
        ]

    def get_policy_environment(self, user_id: int) -> tuple[str | None, date | None, int, list[dict]]:
        """Return policy environment data for the dashboard."""

        from apps.policy.infrastructure.models import PolicyAuditQueue, PolicyLog
        from apps.policy.infrastructure.repositories import DjangoPolicyRepository

        policy_repo = DjangoPolicyRepository()
        current_policy_level = None
        current_policy_date = None

        try:
            current_level = policy_repo.get_current_policy_level(date.today())
            current_policy_level = current_level.value
            latest_effective = (
                PolicyLog._default_manager.filter(gate_effective=True)
                .order_by("-event_date", "-effective_at")
                .only("event_date")
                .first()
            )
            if latest_effective:
                current_policy_date = latest_effective.event_date
        except Exception:
            pass

        pending_review_count = 0
        try:
            pending_review_count = PolicyAuditQueue._default_manager.filter(
                assigned_to__user_id=user_id,
                status__in=["pending", "in_progress"],
            ).count()
        except Exception:
            pass

        recent_policies: list[dict] = []
        try:
            recent_logs = PolicyLog._default_manager.filter(
                created_at__gte=timezone.now() - timedelta(days=7),
                audit_status__in=["auto_approved", "manual_approved"],
            ).order_by("-created_at")[:5]
            for policy in recent_logs:
                recent_policies.append(
                    {
                        "id": policy.id,
                        "title": policy.title,
                        "level": policy.level,
                        "level_display": policy.get_level_display(),
                        "category": policy.info_category,
                        "category_display": policy.get_info_category_display(),
                        "created_at": policy.created_at.strftime("%Y-%m-%d %H:%M"),
                    }
                )
        except Exception:
            pass

        return current_policy_level, current_policy_date, pending_review_count, recent_policies

    def get_growth_series(
        self,
        indicator_code: str,
        end_date: date,
        *,
        use_pit: bool = False,
        full: bool = False,
    ) -> list[Any]:
        """Return growth indicator series via the regime macro adapter."""

        from apps.regime.infrastructure.macro_data_provider import MacroRepositoryAdapter

        repo = MacroRepositoryAdapter()
        series = (
            repo.get_growth_series_full(
                indicator_code=indicator_code,
                end_date=end_date,
                use_pit=use_pit,
            )
            if full
            else repo.get_growth_series(
                indicator_code=indicator_code,
                end_date=end_date,
                use_pit=use_pit,
            )
        )
        return list(series or [])

    def get_inflation_series(
        self,
        indicator_code: str,
        end_date: date,
        *,
        use_pit: bool = False,
        full: bool = False,
    ) -> list[Any]:
        """Return inflation indicator series via the regime macro adapter."""

        from apps.regime.infrastructure.macro_data_provider import MacroRepositoryAdapter

        repo = MacroRepositoryAdapter()
        series = (
            repo.get_inflation_series_full(
                indicator_code=indicator_code,
                end_date=end_date,
                use_pit=use_pit,
            )
            if full
            else repo.get_inflation_series(
                indicator_code=indicator_code,
                end_date=end_date,
                use_pit=use_pit,
            )
        )
        return list(series or [])

    def get_primary_system_ai_provider_payload(self) -> dict[str, Any] | None:
        """Return the first active configured system AI provider payload."""

        from apps.ai_provider.infrastructure.repositories import AIProviderRepository

        provider_repo = AIProviderRepository()
        provider = next(iter(provider_repo.get_active_configured_system_providers()), None)
        if provider is None:
            return None

        api_key = provider_repo.get_api_key(provider)
        if not api_key:
            return None

        return {
            "name": provider.name,
            "base_url": provider.base_url,
            "provider_type": provider.provider_type,
            "default_model": provider.default_model,
            "api_key": api_key,
        }

    def list_global_investment_rule_payloads(self) -> list[dict[str, Any]]:
        """Return active global investment rule payloads for dashboard hints."""

        from apps.account.infrastructure.models import InvestmentRuleModel

        queryset = (
            InvestmentRuleModel._default_manager.filter(
                is_active=True,
                user__isnull=True,
            )
            .order_by("priority", "id")
            .values("rule_type", "conditions", "advice_template")
        )
        return [
            {
                "rule_type": str(row["rule_type"]),
                "conditions": dict(row.get("conditions") or {}),
                "advice_template": str(row.get("advice_template") or ""),
            }
            for row in queryset
        ]

    def get_portfolio_snapshot_performance_data(self, portfolio_id: int) -> list[dict]:
        """Return performance chart data from legacy portfolio snapshots."""

        from apps.account.infrastructure.models import PortfolioDailySnapshotModel

        snapshots = list(
            PortfolioDailySnapshotModel._default_manager.filter(
                portfolio_id=portfolio_id
            ).order_by("snapshot_date")
        )
        if not snapshots:
            return []

        base_value = float(snapshots[0].total_value) if snapshots[0].total_value else 1.0
        if base_value <= 0:
            base_value = 1.0

        return [
            {
                "date": snapshot.snapshot_date.isoformat(),
                "portfolio_value": float(snapshot.total_value),
                "return_pct": round(
                    ((float(snapshot.total_value) - base_value) / base_value) * 100,
                    2,
                ),
                "cash_balance": float(snapshot.cash_balance),
                "invested_value": float(snapshot.invested_value),
                "position_count": snapshot.position_count,
            }
            for snapshot in snapshots
        ]

    def get_simulated_performance_data(
        self,
        *,
        user_id: int,
        account_id: int | None,
        days: int,
    ) -> list[dict]:
        """Return performance chart data from simulated-account net values."""

        from apps.simulated_trading.infrastructure.models import (
            DailyNetValueModel,
            SimulatedAccountModel,
        )

        if days <= 0:
            return []

        end_date = date.today()
        start_date = end_date - timedelta(days=max(days - 1, 0))

        if account_id:
            records = list(
                DailyNetValueModel._default_manager.filter(
                    account_id=account_id,
                    account__user_id=user_id,
                    record_date__gte=start_date,
                    record_date__lte=end_date,
                ).order_by("record_date")
            )
            if not records:
                return []

            return [
                {
                    "date": record.record_date.isoformat(),
                    "portfolio_value": float(record.net_value),
                    "return_pct": round(record.cumulative_return, 2),
                    "cash_balance": float(record.cash),
                    "invested_value": float(record.market_value),
                    "position_count": record.positions_count,
                }
                for record in records
            ]

        account_ids = list(
            SimulatedAccountModel._default_manager.filter(user_id=user_id).values_list(
                "id",
                flat=True,
            )
        )
        if not account_ids:
            return []

        records = list(
            DailyNetValueModel._default_manager.filter(
                account_id__in=account_ids,
                record_date__gte=start_date,
                record_date__lte=end_date,
            ).order_by("record_date")
        )
        if not records:
            return []

        daily_totals: dict[date, dict] = {}
        for record in records:
            bucket = daily_totals.setdefault(
                record.record_date,
                {
                    "net_value": 0.0,
                    "cash": 0.0,
                    "market_value": 0.0,
                    "positions_count": 0,
                },
            )
            bucket["net_value"] += float(record.net_value)
            bucket["cash"] += float(record.cash)
            bucket["market_value"] += float(record.market_value)
            bucket["positions_count"] += record.positions_count

        total_initial = sum(
            float(account.initial_capital)
            for account in SimulatedAccountModel._default_manager.filter(id__in=account_ids)
        )
        if total_initial <= 0:
            total_initial = next(iter(daily_totals.values()))["net_value"] if daily_totals else 1.0

        performance_data: list[dict] = []
        for record_date in sorted(daily_totals.keys()):
            bucket = daily_totals[record_date]
            return_pct = (
                ((bucket["net_value"] - total_initial) / total_initial) * 100
                if total_initial
                else 0.0
            )
            performance_data.append(
                {
                    "date": record_date.isoformat(),
                    "portfolio_value": bucket["net_value"],
                    "return_pct": round(return_pct, 2),
                    "cash_balance": bucket["cash"],
                    "invested_value": bucket["market_value"],
                    "position_count": bucket["positions_count"],
                }
            )

        return performance_data


class DashboardQueryRepository:
    """ORM-backed query helpers for dashboard application query services."""

    def get_alpha_ic_trends(self, days: int) -> list[dict[str, Any]]:
        """Return Alpha IC/ICIR trend rows for the last N days."""

        from apps.alpha.infrastructure.models import QlibModelRegistryModel

        active_models = QlibModelRegistryModel._default_manager.filter(is_active=True)
        if not active_models.exists():
            return []

        trends: list[dict[str, Any]] = []
        base_date = date.today()
        for i in range(days):
            check_date = base_date - timedelta(days=i)
            model_metrics = QlibModelRegistryModel._default_manager.filter(
                created_at__date=check_date
            ).first()
            if model_metrics:
                trends.append(
                    {
                        "date": check_date.isoformat(),
                        "ic": round(float(model_metrics.ic), 4) if model_metrics.ic else None,
                        "icir": round(float(model_metrics.icir), 4) if model_metrics.icir else None,
                        "rank_ic": (
                            round(float(model_metrics.rank_ic), 4) if model_metrics.rank_ic else None
                        ),
                    }
                )
            else:
                trends.append(
                    {
                        "date": check_date.isoformat(),
                        "ic": None,
                        "icir": None,
                        "rank_ic": None,
                    }
                )
        return list(reversed(trends))

    def get_latest_macro_indicator_value(self, indicator_code: str) -> float | None:
        """Return the latest macro indicator value for one code."""

        from apps.macro.infrastructure.models import MacroIndicator

        latest = (
            MacroIndicator._default_manager.filter(code=indicator_code)
            .order_by("-reporting_period")
            .first()
        )
        return float(latest.value) if latest else None

    def get_position_detail(self, user_id: int, asset_code: str) -> dict[str, Any]:
        """Return one account position and related active signals."""

        from apps.account.infrastructure.models import PositionModel
        from apps.signal.infrastructure.models import InvestmentSignalModel

        position = PositionModel._default_manager.get(
            user_id=user_id,
            asset_code=asset_code,
        )
        related_signals = list(
            InvestmentSignalModel._default_manager.filter(
                asset_code=asset_code,
                status="active",
            ).order_by("-created_at")[:5]
        )
        return {
            "position": position,
            "related_signals": related_signals,
            "asset_code": asset_code,
            "error": None,
        }

    def load_alpha_candidate_generation_context(self) -> dict[str, Any]:
        """Return trigger/candidate context for batch candidate generation."""

        from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel, AlphaTriggerModel

        active_triggers = list(
            AlphaTriggerModel._default_manager.filter(
                status__in=[AlphaTriggerModel.ACTIVE, AlphaTriggerModel.TRIGGERED]
            ).order_by("-created_at")[:50]
        )
        trigger_ids = [trigger.trigger_id for trigger in active_triggers]
        existing_trigger_ids = set(
            AlphaCandidateModel._default_manager.filter(
                trigger_id__in=trigger_ids,
                status__in=["WATCH", "CANDIDATE", "ACTIONABLE"],
            ).values_list("trigger_id", flat=True)
        )
        actionable_count = AlphaCandidateModel._default_manager.filter(
            status="ACTIONABLE"
        ).count()
        return {
            "active_triggers": active_triggers,
            "existing_trigger_ids": existing_trigger_ids,
            "actionable_count": actionable_count,
        }


class DashboardConfigRepository:
    """
    仪表盘配置仓储

    管理仪表盘配置的持久化操作。

    Example:
        >>> repo = DashboardConfigRepository()
        >>> config = repo.get_default_config()
        >>> cards = repo.get_cards_for_config(config.config_id)
    """

    def get_default_config(self) -> DashboardConfigModel | None:
        """
        获取默认配置

        Returns:
            默认配置或 None
        """
        try:
            return DashboardConfigModel._default_manager.filter(
                is_default=True, is_active=True
            ).first()
        except Exception as e:
            logger.error(f"Error getting default config: {e}")
            return None

    def get_config_by_id(self, config_id: str) -> DashboardConfigModel | None:
        """
        按 ID 获取配置

        Args:
            config_id: 配置 ID

        Returns:
            配置或 None
        """
        try:
            return DashboardConfigModel._default_manager.get(config_id=config_id)
        except DashboardConfigModel.DoesNotExist:
            return None

    def get_all_active_configs(self) -> list[DashboardConfigModel]:
        """
        获取所有激活的配置

        Returns:
            配置列表
        """
        return list(DashboardConfigModel._default_manager.filter(is_active=True))

    def create_config(
        self,
        config_id: str,
        name: str,
        layout_config: dict[str, Any],
        card_configs: list[dict[str, Any]],
        is_default: bool = False,
        description: str = "",
    ) -> DashboardConfigModel:
        """
        创建配置

        Args:
            config_id: 配置 ID
            name: 名称
            layout_config: 布局配置
            card_configs: 卡片配置列表
            is_default: 是否默认
            description: 描述

        Returns:
            创建的配置
        """
        if is_default:
            # 取消其他默认配置
            DashboardConfigModel._default_manager.filter(is_default=True).update(is_default=False)

        config = DashboardConfigModel._default_manager.create(
            config_id=config_id,
            name=name,
            description=description,
            layout_config=layout_config,
            card_configs=card_configs,
            is_default=is_default,
        )
        return config

    def update_config(self, config_id: str, **kwargs) -> DashboardConfigModel | None:
        """
        更新配置

        Args:
            config_id: 配置 ID
            **kwargs: 更新字段

        Returns:
            更新后的配置或 None
        """
        try:
            config = DashboardConfigModel._default_manager.get(config_id=config_id)
            for key, value in kwargs.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            config.save()
            return config
        except DashboardConfigModel.DoesNotExist:
            return None


class DashboardPreferencesRepository:
    """
    仪表盘用户偏好仓储

    管理用户仪表盘偏好的持久化操作。

    Example:
        >>> repo = DashboardPreferencesRepository()
        >>> prefs = repo.get_or_create_preferences(user_id)
    """

    def get_preferences(self, user_id: int) -> DashboardPreferences | None:
        """
        获取用户偏好

        Args:
            user_id: 用户 ID

        Returns:
            用户偏好或 None
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)
            return self._to_domain_entity(config_model)
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return None


class AlphaRecommendationHistoryRepository:
    """Alpha 首页候选历史持久化。"""

    def upsert_run(
        self,
        *,
        user_id: int,
        portfolio_id: int | None,
        portfolio_name: str,
        trade_date,
        scope_hash: str,
        scope_label: str,
        scope_metadata: dict[str, Any],
        model_hash: str,
        source: str,
        provider_source: str,
        requested_trade_date,
        effective_asof_date,
        uses_cached_data: bool,
        cache_reason: str,
        fallback_reason: str,
        meta: dict[str, Any],
    ) -> AlphaRecommendationRunModel:
        run, _ = AlphaRecommendationRunModel._default_manager.update_or_create(
            user_id=user_id,
            portfolio_id=portfolio_id,
            trade_date=trade_date,
            scope_hash=scope_hash,
            model_hash=model_hash,
            source=source,
            defaults={
                "portfolio_name": portfolio_name,
                "scope_label": scope_label,
                "scope_metadata": scope_metadata,
                "provider_source": provider_source,
                "requested_trade_date": requested_trade_date,
                "effective_asof_date": effective_asof_date,
                "uses_cached_data": uses_cached_data,
                "cache_reason": cache_reason,
                "fallback_reason": fallback_reason,
                "meta": meta,
            },
        )
        return run

    def replace_snapshots(
        self,
        *,
        run: AlphaRecommendationRunModel,
        snapshots: list[dict[str, Any]],
    ) -> None:
        AlphaRecommendationSnapshotModel._default_manager.filter(run=run).delete()
        AlphaRecommendationSnapshotModel._default_manager.bulk_create(
            [
                AlphaRecommendationSnapshotModel(
                    run=run,
                    stock_code=item["stock_code"],
                    stock_name=item.get("stock_name", ""),
                    stage=item.get("stage", "top_ranked"),
                    gate_status=item.get("gate_status", "blocked"),
                    rank=item.get("rank", 0),
                    alpha_score=item.get("alpha_score", 0.0),
                    confidence=item.get("confidence", 0.0),
                    source=item.get("source", ""),
                    buy_reasons=item.get("buy_reasons", []),
                    no_buy_reasons=item.get("no_buy_reasons", []),
                    invalidation_rule=item.get("invalidation_rule", {}),
                    risk_snapshot=item.get("risk_snapshot", {}),
                    suggested_position_pct=item.get("suggested_position_pct", 0.0),
                    suggested_notional=item.get("suggested_notional", 0.0),
                    suggested_quantity=item.get("suggested_quantity", 0.0),
                    source_candidate_id=item.get("source_candidate_id"),
                    source_recommendation_id=item.get("source_recommendation_id"),
                    extra_payload=item.get("extra_payload", {}),
                )
                for item in snapshots
            ]
        )

    def list_recent_runs(
        self,
        *,
        user_id: int,
        portfolio_id: int | None = None,
        limit: int = 5,
    ) -> list[AlphaRecommendationRunModel]:
        queryset = AlphaRecommendationRunModel._default_manager.filter(user_id=user_id)
        if portfolio_id is not None:
            queryset = queryset.filter(portfolio_id=portfolio_id)
        return list(queryset.order_by("-trade_date", "-created_at")[:limit])

    def filter_runs(
        self,
        *,
        user_id: int,
        portfolio_id: int | None = None,
        stock_code: str | None = None,
        stage: str | None = None,
        source: str | None = None,
        trade_date=None,
        limit: int = 50,
    ) -> list[AlphaRecommendationRunModel]:
        queryset = AlphaRecommendationRunModel._default_manager.filter(user_id=user_id)
        if portfolio_id is not None:
            queryset = queryset.filter(portfolio_id=portfolio_id)
        if source:
            queryset = queryset.filter(source=source)
        if trade_date:
            queryset = queryset.filter(trade_date=trade_date)
        if stock_code or stage:
            queryset = queryset.filter(snapshots__stock_code=stock_code) if stock_code else queryset
            queryset = queryset.filter(snapshots__stage=stage) if stage else queryset
            queryset = queryset.distinct()
        return list(queryset.order_by("-trade_date", "-created_at")[:limit])

    def get_run_detail(self, *, user_id: int, run_id: int) -> AlphaRecommendationRunModel | None:
        try:
            return AlphaRecommendationRunModel._default_manager.prefetch_related("snapshots").get(
                id=run_id, user_id=user_id
            )
        except AlphaRecommendationRunModel.DoesNotExist:
            return None

    def get_or_create_preferences(self, user_id: int) -> DashboardPreferences:
        """
        获取或创建用户偏好

        Args:
            user_id: 用户 ID

        Returns:
            用户偏好
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model, created = DashboardUserConfigModel._default_manager.get_or_create(
                user=user,
                defaults={
                    "dashboard_config": DashboardConfigRepository().get_default_config(),
                },
            )
            return self._to_domain_entity(config_model)
        except User.DoesNotExist:
            # 创建默认偏好
            return DashboardPreferences(
                user_id=user_id,
                layout_id="default",
            )

    def update_preferences(self, user_id: int, **kwargs) -> DashboardPreferences | None:
        """
        更新用户偏好

        Args:
            user_id: 用户 ID
            **kwargs: 更新字段

        Returns:
            更新后的偏好或 None
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)

            for key, value in kwargs.items():
                if hasattr(config_model, key):
                    setattr(config_model, key, value)

            config_model.save()
            return self._to_domain_entity(config_model)
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return None

    def add_hidden_card(self, user_id: int, card_id: str) -> bool:
        """
        添加隐藏卡片

        Args:
            user_id: 用户 ID
            card_id: 卡片 ID

        Returns:
            是否成功
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)

            if card_id not in config_model.hidden_cards:
                config_model.hidden_cards.append(card_id)
                config_model.save()

            return True
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return False

    def remove_hidden_card(self, user_id: int, card_id: str) -> bool:
        """
        移除隐藏卡片

        Args:
            user_id: 用户 ID
            card_id: 卡片 ID

        Returns:
            是否成功
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)

            if card_id in config_model.hidden_cards:
                config_model.hidden_cards.remove(card_id)
                config_model.save()

            return True
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return False

    def add_collapsed_card(self, user_id: int, card_id: str) -> bool:
        """
        添加折叠卡片

        Args:
            user_id: 用户 ID
            card_id: 卡片 ID

        Returns:
            是否成功
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)

            if card_id not in config_model.collapsed_cards:
                config_model.collapsed_cards.append(card_id)
                config_model.save()

            return True
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return False

    def remove_collapsed_card(self, user_id: int, card_id: str) -> bool:
        """
        移除折叠卡片

        Args:
            user_id: 用户 ID
            card_id: 卡片 ID

        Returns:
            是否成功
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)

            if card_id in config_model.collapsed_cards:
                config_model.collapsed_cards.remove(card_id)
                config_model.save()

            return True
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return False

    def update_card_order(self, user_id: int, card_order: list[str]) -> bool:
        """
        更新卡片顺序

        Args:
            user_id: 用户 ID
            card_order: 卡片顺序

        Returns:
            是否成功
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)
            config_model.card_order = card_order
            config_model.save()
            return True
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return False

    def _to_domain_entity(self, model: DashboardUserConfigModel) -> DashboardPreferences:
        """转换为领域实体"""
        return DashboardPreferences(
            user_id=model.user_id,
            layout_id=model.dashboard_config.config_id if model.dashboard_config else "default",
            hidden_cards=model.hidden_cards or [],
            collapsed_cards=model.collapsed_cards or [],
            card_order=model.card_order or [],
            custom_card_config=model.custom_card_config or {},
            theme=model.theme,
            refresh_enabled=model.refresh_enabled,
            refresh_interval=model.refresh_interval,
            last_updated=model.last_updated,
        )


class DashboardCardRepository:
    """
    仪表盘卡片仓储

    管理仪表盘卡片的持久化操作。

    Example:
        >>> repo = DashboardCardRepository()
        >>> card = repo.get_card_by_id("portfolio_summary")
    """

    def get_card_by_id(self, card_id: str) -> DashboardCardModel | None:
        """
        按 ID 获取卡片

        Args:
            card_id: 卡片 ID

        Returns:
            卡片或 None
        """
        try:
            return DashboardCardModel._default_manager.get(card_id=card_id)
        except DashboardCardModel.DoesNotExist:
            return None

    def get_all_visible_cards(self) -> list[DashboardCardModel]:
        """
        获取所有可见卡片

        Returns:
            卡片列表
        """
        return list(DashboardCardModel._default_manager.filter(is_visible=True))

    def get_cards_by_type(self, card_type: CardType) -> list[DashboardCardModel]:
        """
        按类型获取卡片

        Args:
            card_type: 卡片类型

        Returns:
            卡片列表
        """
        return list(
            DashboardCardModel._default_manager.filter(card_type=card_type.value, is_visible=True)
        )

    def create_card(
        self, card_id: str, card_type: CardType, title: str = "", **kwargs
    ) -> DashboardCardModel:
        """
        创建卡片

        Args:
            card_id: 卡片 ID
            card_type: 卡片类型
            title: 标题
            **kwargs: 其他字段

        Returns:
            创建的卡片
        """
        card = DashboardCardModel._default_manager.create(
            card_id=card_id, card_type=card_type.value, title=title, **kwargs
        )
        return card

    def update_card_visibility(self, card_id: str, is_visible: bool) -> bool:
        """
        更新卡片可见性

        Args:
            card_id: 卡片 ID
            is_visible: 是否可见

        Returns:
            是否成功
        """
        try:
            card = DashboardCardModel._default_manager.get(card_id=card_id)
            card.is_visible = is_visible
            card.save()
            return True
        except DashboardCardModel.DoesNotExist:
            return False


class DashboardAlertRepository:
    """
    仪表盘告警仓储

    管理仪表盘告警的持久化操作。

    Example:
        >>> repo = DashboardAlertRepository()
        >>> alerts = repo.get_enabled_alerts()
    """

    def get_alert_by_id(self, alert_id: str) -> DashboardAlertModel | None:
        """
        按 ID 获取告警

        Args:
            alert_id: 告警 ID

        Returns:
            告警或 None
        """
        try:
            return DashboardAlertModel._default_manager.get(alert_id=alert_id)
        except DashboardAlertModel.DoesNotExist:
            return None

    def get_enabled_alerts(self) -> list[DashboardAlertModel]:
        """
        获取所有启用的告警

        Returns:
            告警列表
        """
        return list(DashboardAlertModel._default_manager.filter(is_enabled=True))

    def get_alerts_by_severity(self, severity: AlertSeverity) -> list[DashboardAlertModel]:
        """
        按严重级别获取告警

        Args:
            severity: 告警级别

        Returns:
            告警列表
        """
        return list(
            DashboardAlertModel._default_manager.filter(severity=severity.value, is_enabled=True)
        )

    def create_alert(
        self,
        alert_id: str,
        name: str,
        metric: str,
        threshold: float,
        severity: AlertSeverity = AlertSeverity.WARNING,
        **kwargs,
    ) -> DashboardAlertModel:
        """
        创建告警

        Args:
            alert_id: 告警 ID
            name: 名称
            metric: 监控指标
            threshold: 阈值
            severity: 告警级别
            **kwargs: 其他字段

        Returns:
            创建的告警
        """
        alert = DashboardAlertModel._default_manager.create(
            alert_id=alert_id,
            name=name,
            metric=metric,
            threshold=threshold,
            severity=severity.value,
            **kwargs,
        )
        return alert

    def update_trigger_time(self, alert_id: str) -> bool:
        """
        更新告警触发时间

        Args:
            alert_id: 告警 ID

        Returns:
            是否成功
        """
        try:
            alert = DashboardAlertModel._default_manager.get(alert_id=alert_id)
            alert.update_trigger()
            return True
        except DashboardAlertModel.DoesNotExist:
            return False


class DashboardSnapshotRepository:
    """
    仪表盘快照仓储

    管理仪表盘快照的持久化操作。

    Example:
        >>> repo = DashboardSnapshotRepository()
        >>> repo.create_snapshot(user_id, snapshot_data)
    """

    def create_snapshot(
        self, user_id: int, snapshot_data: dict[str, Any]
    ) -> DashboardSnapshotModel | None:
        """
        创建快照

        Args:
            user_id: 用户 ID
            snapshot_data: 快照数据

        Returns:
            创建的快照或 None
        """
        try:
            user = User._default_manager.get(id=user_id)
            snapshot = DashboardSnapshotModel._default_manager.create(
                user=user, snapshot_data=snapshot_data
            )
            return snapshot
        except User.DoesNotExist:
            return None

    def get_recent_snapshots(self, user_id: int, limit: int = 10) -> list[DashboardSnapshotModel]:
        """
        获取最近的快照

        Args:
            user_id: 用户 ID
            limit: 数量限制

        Returns:
            快照列表
        """
        try:
            user = User._default_manager.get(id=user_id)
            return list(
                DashboardSnapshotModel._default_manager.filter(user=user).order_by("-captured_at")[
                    :limit
                ]
            )
        except User.DoesNotExist:
            return []

    def delete_old_snapshots(self, user_id: int, keep_count: int = 100) -> int:
        """
        删除旧快照

        Args:
            user_id: 用户 ID
            keep_count: 保留数量

        Returns:
            删除的数量
        """
        try:
            user = User._default_manager.get(id=user_id)
            snapshots = DashboardSnapshotModel._default_manager.filter(user=user).order_by(
                "-captured_at"
            )

            total = snapshots.count()
            if total > keep_count:
                to_delete = snapshots[keep_count:]
                count = len(to_delete)
                to_delete.delete()
                return count
            return 0
        except User.DoesNotExist:
            return 0
