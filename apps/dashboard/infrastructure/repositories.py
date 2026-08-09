"""
Dashboard Infrastructure Repositories

仪表盘数据仓储实现。
"""

import logging
from collections.abc import Mapping
from datetime import date
from typing import Any

from django.contrib.auth import get_user_model
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.dashboard.application.integration_gateways import (
    DashboardApplicationGateway,
)
from apps.dashboard.domain.entities import (
    DashboardPreferences,
)
from apps.dashboard.infrastructure.dashboard_state_repositories import (
    DashboardAlertRepository as DashboardAlertRepository,
)
from apps.dashboard.infrastructure.dashboard_state_repositories import (
    DashboardCardRepository as DashboardCardRepository,
)
from apps.dashboard.infrastructure.dashboard_state_repositories import (
    DashboardSnapshotRepository as DashboardSnapshotRepository,
)
from apps.data_center.application.public import update_asset_display_name
from apps.fund.application.repository_provider import resolve_fund_holding_names

from .models import (
    AlphaRecommendationRunModel,
    AlphaRecommendationSnapshotModel,
    AutoAdvisorNotificationModel,
    AutoAdvisorWeeklyReportModel,
    DashboardConfigModel,
    DashboardUserConfigModel,
)

logger = logging.getLogger(__name__)

User = get_user_model()


def _optional_isoformat(value: object) -> str | None:
    """Serialize date-like values at the dynamic integration boundary."""

    formatter = getattr(value, "isoformat", None)
    return str(formatter()) if callable(formatter) else None


def _asset_context_value(asset: object, key: str) -> object | None:
    """Read an asset field from either a Public Port mapping or a legacy DTO."""

    if isinstance(asset, Mapping):
        return asset.get(key)
    return getattr(asset, key, None)


class AutoAdvisorReportRepository:
    """Persist weekly auto-advisor reports, diary snapshots, and notifications."""

    def upsert_weekly_report(
        self,
        *,
        user_id: int,
        account_id: int,
        account_name: str,
        report_date: date,
        week_start: date,
        week_end: date,
        payload: dict[str, Any],
        investment_diary: dict[str, Any],
        status: str = AutoAdvisorWeeklyReportModel.STATUS_READY,
        audit_log_id: str = "",
    ) -> dict[str, Any]:
        """Create or update one weekly report snapshot."""

        report, _ = AutoAdvisorWeeklyReportModel._default_manager.update_or_create(
            user_id=user_id,
            account_id=account_id,
            report_date=report_date,
            defaults={
                "account_name": account_name,
                "week_start": week_start,
                "week_end": week_end,
                "status": status,
                "payload": payload,
                "investment_diary": investment_diary,
                "audit_log_id": audit_log_id,
            },
        )
        return self._serialize_report(report)

    def update_report_audit_log(
        self, *, report_id: int, audit_log_id: str
    ) -> dict[str, Any] | None:
        """Attach an audit operation log id to a persisted report."""

        updated = AutoAdvisorWeeklyReportModel._default_manager.filter(id=report_id).update(
            audit_log_id=audit_log_id
        )
        if not updated:
            return None
        report = AutoAdvisorWeeklyReportModel._default_manager.get(id=report_id)
        return self._serialize_report(report)

    def create_notification(
        self,
        *,
        user_id: int,
        account_id: int,
        report_id: int,
        title: str,
        message: str,
        payload: dict[str, Any],
        channel: str = AutoAdvisorNotificationModel.CHANNEL_DASHBOARD,
        delivery_status: str = AutoAdvisorNotificationModel.STATUS_DELIVERED,
    ) -> dict[str, Any]:
        """Create one stored dashboard notification/output item."""

        delivered_at = (
            timezone.now()
            if delivery_status == AutoAdvisorNotificationModel.STATUS_DELIVERED
            else None
        )
        notification = AutoAdvisorNotificationModel._default_manager.create(
            user_id=user_id,
            account_id=account_id,
            report_id=report_id,
            channel=channel,
            title=title,
            message=message,
            payload=payload,
            delivery_status=delivery_status,
            delivered_at=delivered_at,
        )
        return self._serialize_notification(notification)

    def list_recent_reports(
        self,
        *,
        user_id: int,
        account_id: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return recent persisted weekly reports."""

        queryset = AutoAdvisorWeeklyReportModel._default_manager.filter(user_id=user_id)
        if account_id is not None:
            queryset = queryset.filter(account_id=account_id)
        return [
            self._serialize_report(report)
            for report in queryset.order_by("-report_date", "-created_at")[: max(limit, 0)]
        ]

    def list_recent_notifications(
        self,
        *,
        user_id: int,
        account_id: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return recent auto-advisor notification/output items."""

        queryset = AutoAdvisorNotificationModel._default_manager.filter(user_id=user_id)
        if account_id is not None:
            queryset = queryset.filter(account_id=account_id)
        return [
            self._serialize_notification(notification)
            for notification in queryset.order_by("-created_at")[: max(limit, 0)]
        ]

    @staticmethod
    def _serialize_report(report: AutoAdvisorWeeklyReportModel) -> dict[str, Any]:
        return {
            "id": report.id,
            "user_id": report.user_id,
            "account_id": report.account_id,
            "account_name": report.account_name,
            "report_date": report.report_date.isoformat(),
            "week_start": report.week_start.isoformat(),
            "week_end": report.week_end.isoformat(),
            "status": report.status,
            "payload": report.payload,
            "investment_diary": report.investment_diary,
            "audit_log_id": report.audit_log_id,
            "created_at": report.created_at.isoformat() if report.created_at else None,
            "updated_at": report.updated_at.isoformat() if report.updated_at else None,
        }

    @staticmethod
    def _serialize_notification(notification: AutoAdvisorNotificationModel) -> dict[str, Any]:
        return {
            "id": notification.id,
            "user_id": notification.user_id,
            "account_id": notification.account_id,
            "report_id": notification.report_id,
            "channel": notification.channel,
            "title": notification.title,
            "message": notification.message,
            "payload": notification.payload,
            "delivery_status": notification.delivery_status,
            "delivered_at": (
                notification.delivered_at.isoformat() if notification.delivered_at else None
            ),
            "read_at": notification.read_at.isoformat() if notification.read_at else None,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
        }


class DashboardAlphaContextRepository:
    """ORM-backed context loader for the Dashboard Alpha homepage view."""

    def __init__(self, integration_gateway: DashboardApplicationGateway) -> None:
        self._integration_gateway = integration_gateway

    def load_stock_context(
        self,
        codes: list[str],
        *,
        persist_names: bool = True,
    ) -> dict[str, dict[str, Any]]:
        if not codes:
            return {}

        code_aliases = self._build_code_aliases(codes)
        if persist_names:
            local_context = self._integration_gateway.get_stock_context_map(codes)
        else:
            local_context = {}

        asset_context = self._load_data_center_asset_context(codes, code_aliases)
        legacy_holding_context = self._load_legacy_holding_asset_context(
            [
                code
                for code in codes
                if not (
                    (local_context.get(code, {}) or {}).get("name")
                    or (asset_context.get(code, {}) or {}).get("name")
                )
            ],
            code_aliases,
            persist_asset_names=persist_names,
        )
        quote_context = self._load_data_center_quote_context(codes, code_aliases)

        context: dict[str, dict[str, Any]] = {}
        for code in codes:
            latest_daily = local_context.get(code, {})
            info: dict[str, Any] = {
                "name": str(latest_daily.get("name") or ""),
                "sector": str(latest_daily.get("sector") or ""),
                "market": str(latest_daily.get("market") or ""),
            }
            master_info = asset_context.get(code, {})
            legacy_info = legacy_holding_context.get(code, {})
            info.update(
                {
                    "name": info.get("name")
                    or master_info.get("name")
                    or legacy_info.get("name")
                    or "",
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
                    "trade_date": _optional_isoformat(latest_daily.get("trade_date")),
                    "report_date": _optional_isoformat(latest_daily.get("report_date")),
                    "roe": latest_daily.get("roe"),
                    "debt_ratio": latest_daily.get("debt_ratio"),
                    "revenue_growth": latest_daily.get("revenue_growth"),
                    "profit_growth": latest_daily.get("profit_growth"),
                    "valuation_trade_date": _optional_isoformat(
                        latest_daily.get("valuation_trade_date")
                    ),
                    "pe": latest_daily.get("pe"),
                    "pb": latest_daily.get("pb"),
                    "ps": latest_daily.get("ps"),
                    "dividend_yield": latest_daily.get("dividend_yield"),
                    "must_not_use_for_decision": bool(
                        latest_daily.get("must_not_use_for_decision")
                    ),
                    "blocked_reason": latest_daily.get("blocked_reason"),
                    "publication_gates": latest_daily.get("publication_gates", {}),
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

    def _load_data_center_asset_context(
        self,
        codes: list[str],
        code_aliases: dict[str, set[str]],
    ) -> dict[str, dict[str, str]]:
        context: dict[str, dict[str, str]] = {}
        for code in codes:
            normalized_code = str(code).strip().upper()
            for alias in code_aliases.get(normalized_code, {normalized_code}):
                asset = self._integration_gateway.resolve_asset(alias)
                if asset is None:
                    continue
                short_name = str(_asset_context_value(asset, "short_name") or "")
                name = str(_asset_context_value(asset, "name") or "")
                sector = str(_asset_context_value(asset, "sector") or "")
                industry = str(_asset_context_value(asset, "industry") or "")
                exchange = str(_asset_context_value(asset, "exchange") or "")
                context[normalized_code] = {
                    "name": short_name or name,
                    "sector": sector or industry,
                    "market": exchange,
                }
                break
        return context

    def _load_legacy_holding_asset_context(
        self,
        codes: list[str],
        code_aliases: dict[str, set[str]],
        *,
        persist_asset_names: bool,
    ) -> dict[str, dict[str, str]]:
        lookup_codes = sorted(
            {
                alias.upper()
                for code in codes
                for alias in code_aliases.get(str(code).strip().upper(), {str(code).upper()})
                if alias
            }
        )
        if not lookup_codes:
            return {}
        try:
            holding_names = resolve_fund_holding_names(lookup_codes)
        except Exception as exc:
            logger.warning(
                "Fund holding name lookup failed through application port: %s",
                type(exc).__name__,
            )
            return {}

        context: dict[str, dict[str, str]] = {}
        for code in codes:
            normalized_code = str(code).strip().upper()
            for alias in code_aliases.get(normalized_code, {normalized_code}):
                stock_name = str(holding_names.get(alias.upper()) or "").strip()
                if not stock_name:
                    continue

                context[normalized_code] = {"name": stock_name}
                if persist_asset_names:
                    update_asset_display_name(normalized_code, stock_name)
                break
        return context

    def _load_data_center_quote_context(
        self,
        codes: list[str],
        code_aliases: dict[str, set[str]],
    ) -> dict[str, dict[str, Any]]:
        if not codes:
            return {}

        context: dict[str, dict[str, Any]] = {}
        for code in codes:
            for alias in code_aliases.get(code, {code}):
                quote = self._integration_gateway.query_latest_quote(str(alias).upper())
                if quote is None:
                    continue
                if isinstance(quote, Mapping):
                    snapshot_at = quote.get("snapshot_at")
                    current_price = quote.get("current_price")
                    volume = quote.get("volume")
                    source = quote.get("source")
                else:
                    snapshot_at = quote.snapshot_at
                    current_price = quote.current_price
                    volume = quote.volume
                    source = quote.source
                snapshot_text = (
                    snapshot_at.isoformat()
                    if isinstance(snapshot_at, date)
                    else str(snapshot_at or "")
                )
                context[code] = {
                    "current_price": (float(current_price) if current_price is not None else None),
                    "volume": float(volume) if volume is not None else None,
                    "snapshot_at": snapshot_text or None,
                    "source": str(source or ""),
                }
                break
        return context

    def load_actionable_map(self) -> dict[str, Any]:
        candidates = self._integration_gateway.list_actionable_alpha_candidates(limit=200)
        return {str(item.asset_code).upper(): item for item in candidates}

    def load_pending_map(self) -> dict[str, Any]:
        queryset = self._integration_gateway.list_pending_execution_requests(limit=200)
        pending_map: dict[str, Any] = {}
        for item in queryset:
            code = str(item.asset_code or "").upper()
            pending_map.setdefault(code, item)
        return pending_map

    def load_user_account_totals(self, user_id: int) -> dict[str, float] | None:
        """Load simulated account totals for sizing fallback."""

        return self._integration_gateway.get_user_account_totals(user_id)

    def load_actionable_candidates(self, max_count: int | None) -> list[Any]:
        pending_codes = {
            str(getattr(item, "asset_code", "") or "").upper()
            for item in self._integration_gateway.list_pending_execution_requests(limit=200)
            if getattr(item, "asset_code", None)
        }
        manual_override_trigger_ids = self._integration_gateway.get_manual_override_trigger_ids()
        candidates = list(self._integration_gateway.list_actionable_alpha_candidates(limit=50))

        candidate_codes = [(getattr(item, "asset_code", "") or "").upper() for item in candidates]
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

        try:
            repair_map = self._integration_gateway.get_valuation_repair_snapshot_map(
                [code for code in candidate_codes if code]
            )
        except Exception as exc:
            logger.warning("Failed to get valuation repair info: %s", exc)
            return {}

        return {
            str(stock_code).upper(): payload
            for stock_code, payload in repair_map.items()
            if stock_code
        }

    def load_policy_state(self) -> dict[str, Any]:
        try:
            return self._integration_gateway.get_policy_state()
        except Exception as exc:
            logger.warning("Failed to load policy gate state: %s", exc)
            return {"gate_level": "L0", "effective": False}


class DashboardOverviewRepository:
    """ORM-backed read model for dashboard overview use cases."""

    def __init__(self, integration_gateway: DashboardApplicationGateway) -> None:
        self._integration_gateway = integration_gateway

    def get_user_simulated_account_totals(self, user_id: int) -> dict[str, float] | None:
        """Return aggregated totals from the simulated-account system."""
        return self._integration_gateway.get_user_account_totals(user_id)

    def get_simulated_positions(self, user_id: int) -> list[dict[str, Any]]:
        """Return holdings from the simulated-account system."""
        return self._integration_gateway.list_user_positions(user_id=user_id)

    def get_simulated_positions_for_dashboard(
        self,
        user_id: int,
        account_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return simulated-account positions with account metadata for dashboard views."""
        return self._integration_gateway.list_user_positions(
            user_id=user_id,
            account_id=account_id,
            include_account_meta=True,
        )

    def get_dashboard_accounts(self, user_id: int) -> list[dict[str, Any]]:
        """Return investment account cards for the dashboard homepage."""
        return self._integration_gateway.list_dashboard_accounts(user_id)

    def get_policy_environment(
        self, user_id: int
    ) -> tuple[str | None, date | None, int, list[dict[str, Any]]]:
        """Return policy environment data for the dashboard."""
        return self._integration_gateway.get_policy_environment(user_id)

    def get_growth_series(
        self,
        indicator_code: str,
        end_date: date,
        *,
        use_pit: bool = False,
        full: bool = False,
    ) -> list[Any]:
        """Return growth indicator series via the regime macro adapter."""
        return self._integration_gateway.get_growth_series(
            indicator_code=indicator_code,
            end_date=end_date,
            use_pit=use_pit,
            full=full,
        )

    def get_inflation_series(
        self,
        indicator_code: str,
        end_date: date,
        *,
        use_pit: bool = False,
        full: bool = False,
    ) -> list[Any]:
        """Return inflation indicator series via the regime macro adapter."""
        return self._integration_gateway.get_inflation_series(
            indicator_code=indicator_code,
            end_date=end_date,
            use_pit=use_pit,
            full=full,
        )

    def get_primary_system_ai_provider_payload(self) -> dict[str, Any] | None:
        """Return the first active configured system AI provider payload."""
        return self._integration_gateway.get_primary_system_ai_provider_payload()

    def list_global_investment_rule_payloads(self) -> list[dict[str, Any]]:
        """Return active global investment rule payloads for dashboard hints."""
        return self._integration_gateway.list_global_investment_rule_payloads()

    def get_portfolio_snapshot_performance_data(self, portfolio_id: int) -> list[dict[str, Any]]:
        """Return performance chart data from legacy portfolio snapshots."""
        return self._integration_gateway.get_portfolio_snapshot_performance_data(portfolio_id)

    def get_simulated_performance_data(
        self,
        *,
        user_id: int,
        account_id: int | None,
        days: int,
    ) -> list[dict[str, Any]]:
        """Return performance chart data from simulated-account net values."""
        return self._integration_gateway.get_user_performance_payload(
            user_id=user_id,
            account_id=account_id,
            days=days,
        )


class DashboardQueryRepository:
    """ORM-backed query helpers for dashboard application query services."""

    def __init__(self, integration_gateway: DashboardApplicationGateway) -> None:
        self._integration_gateway = integration_gateway

    def get_alpha_ic_trends(self, days: int) -> list[dict[str, Any]]:
        """Return Alpha IC/ICIR trend rows for the last N days."""
        return self._integration_gateway.get_alpha_ic_trends(days)

    def get_latest_macro_indicator_value(self, indicator_code: str) -> float | None:
        """Return the latest macro indicator value for one code."""
        return self._integration_gateway.get_latest_macro_indicator_value(indicator_code)

    def get_position_detail(self, user_id: int, asset_code: str) -> dict[str, Any]:
        """Return one account position and related active signals."""
        position = self._integration_gateway.get_position_detail_payload(user_id, asset_code)
        if position is None:
            raise ValueError(f"Position not found: user_id={user_id}, asset_code={asset_code}")
        related_signals = self._integration_gateway.list_active_signal_payloads_by_asset(
            asset_code=asset_code,
            limit=5,
        )
        return {
            "position": position,
            "related_signals": related_signals,
            "asset_code": asset_code,
            "error": None,
        }

    def load_alpha_candidate_generation_context(self) -> dict[str, Any]:
        """Return trigger/candidate context for batch candidate generation."""
        return self._integration_gateway.get_candidate_generation_context(limit=50)


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
        except DatabaseError as e:
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

    def update_config(self, config_id: str, **kwargs: Any) -> DashboardConfigModel | None:
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

    def get_or_create_preferences(self, user_id: int) -> DashboardPreferences:
        """Get or create a user's dashboard preferences."""

        try:
            user = User._default_manager.get(id=user_id)
            config_model, _ = DashboardUserConfigModel._default_manager.get_or_create(
                user=user,
                defaults={
                    "dashboard_config": DashboardConfigRepository().get_default_config(),
                },
            )
            return self._to_domain_entity(config_model)
        except User.DoesNotExist:
            return DashboardPreferences(user_id=user_id, layout_id="default")

    def update_preferences(self, user_id: int, **kwargs: Any) -> DashboardPreferences | None:
        """Update a user's persisted dashboard preferences."""

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
        """Add a card to the user's hidden-card collection."""

        return self._update_card_membership(
            user_id=user_id,
            field_name="hidden_cards",
            card_id=card_id,
            should_include=True,
        )

    def remove_hidden_card(self, user_id: int, card_id: str) -> bool:
        """Remove a card from the user's hidden-card collection."""

        return self._update_card_membership(
            user_id=user_id,
            field_name="hidden_cards",
            card_id=card_id,
            should_include=False,
        )

    def add_collapsed_card(self, user_id: int, card_id: str) -> bool:
        """Add a card to the user's collapsed-card collection."""

        return self._update_card_membership(
            user_id=user_id,
            field_name="collapsed_cards",
            card_id=card_id,
            should_include=True,
        )

    def remove_collapsed_card(self, user_id: int, card_id: str) -> bool:
        """Remove a card from the user's collapsed-card collection."""

        return self._update_card_membership(
            user_id=user_id,
            field_name="collapsed_cards",
            card_id=card_id,
            should_include=False,
        )

    def update_card_order(self, user_id: int, card_order: list[str]) -> bool:
        """Replace the user's preferred dashboard card order."""

        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)
            config_model.card_order = list(card_order)
            config_model.save(update_fields=["card_order", "last_updated"])
            return True
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return False

    @staticmethod
    def _update_card_membership(
        *,
        user_id: int,
        field_name: str,
        card_id: str,
        should_include: bool,
    ) -> bool:
        """Update one list-backed card preference."""

        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)
            card_ids = list(getattr(config_model, field_name) or [])
            if should_include and card_id not in card_ids:
                card_ids.append(card_id)
            elif not should_include and card_id in card_ids:
                card_ids.remove(card_id)
            else:
                return True
            setattr(config_model, field_name, card_ids)
            config_model.save(update_fields=[field_name, "last_updated"])
            return True
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return False

    @staticmethod
    def _to_domain_entity(
        model: DashboardUserConfigModel,
    ) -> DashboardPreferences:
        """Convert a persisted preference model to its domain entity."""

        return DashboardPreferences(
            user_id=model.user_id,
            layout_id=(model.dashboard_config.config_id if model.dashboard_config else "default"),
            hidden_cards=model.hidden_cards or [],
            collapsed_cards=model.collapsed_cards or [],
            card_order=model.card_order or [],
            custom_card_config=model.custom_card_config or {},
            theme=model.theme,
            refresh_enabled=model.refresh_enabled,
            refresh_interval=model.refresh_interval,
            last_updated=model.last_updated,
        )


class AlphaRecommendationHistoryRepository:
    """Alpha 首页候选历史持久化。"""

    def upsert_run(
        self,
        *,
        user_id: int,
        portfolio_id: int | None,
        portfolio_name: str,
        trade_date: date,
        scope_hash: str,
        scope_label: str,
        scope_metadata: dict[str, Any],
        model_hash: str,
        source: str,
        provider_source: str,
        requested_trade_date: date | None,
        effective_asof_date: date | None,
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

    @transaction.atomic
    def replace_snapshots(
        self,
        *,
        run: AlphaRecommendationRunModel,
        snapshots: list[dict[str, Any]],
    ) -> None:
        """Replace one run's snapshots atomically.

        The savepoint keeps a failed bulk insert from poisoning a surrounding
        dashboard request or test transaction, and preserves the prior snapshot
        set when any new row violates the persistence contract.
        """

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
        trade_date: date | None = None,
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
