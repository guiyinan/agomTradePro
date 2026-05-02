"""
Dashboard Infrastructure Repositories

仪表盘数据仓储实现。
"""

import logging
from datetime import date, datetime
from typing import Any

from django.contrib.auth import get_user_model
from django.db import DatabaseError, models
from django.utils import timezone

from apps.data_center.infrastructure.models import AssetMasterModel
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
from apps.fund.infrastructure.models import FundHoldingModel

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

    def __init__(self, integration_gateway: Any) -> None:
        self._integration_gateway = integration_gateway

    def load_stock_context(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        if not codes:
            return {}

        code_aliases = self._build_code_aliases(codes)
        local_context = self._integration_gateway.get_stock_context_map(codes)

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
        )
        quote_context = self._load_data_center_quote_context(codes, code_aliases)

        context: dict[str, dict[str, Any]] = {}
        for code in codes:
            latest_daily = local_context.get(code, {})
            info = {
                "name": str(latest_daily.get("name") or ""),
                "sector": str(latest_daily.get("sector") or ""),
                "market": str(latest_daily.get("market") or ""),
            }
            master_info = asset_context.get(code, {})
            legacy_info = legacy_holding_context.get(code, {})
            info.update(
                {
                    "name": info.get("name") or master_info.get("name") or legacy_info.get("name") or "",
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
                context[normalized_code] = {
                    "name": asset.short_name or asset.name,
                    "sector": asset.sector or asset.industry or "",
                    "market": asset.exchange,
                }
                break
        return context

    def _load_legacy_holding_asset_context(
        self,
        codes: list[str],
        code_aliases: dict[str, set[str]],
    ) -> dict[str, dict[str, str]]:
        context: dict[str, dict[str, str]] = {}
        for code in codes:
            normalized_code = str(code).strip().upper()
            for alias in code_aliases.get(normalized_code, {normalized_code}):
                holding = (
                    FundHoldingModel._default_manager.filter(stock_code=alias)
                    .exclude(stock_name__exact="")
                    .order_by("-report_date", "-id")
                    .first()
                )
                if holding is None:
                    continue

                stock_name = str(holding.stock_name or "").strip()
                if not stock_name:
                    continue

                context[normalized_code] = {"name": stock_name}
                AssetMasterModel._default_manager.update_or_create(
                    code=normalized_code,
                    defaults={"name": stock_name},
                )
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
                snapshot_at = quote.snapshot_at
                context[code] = {
                    "current_price": float(quote.current_price or 0.0),
                    "volume": float(quote.volume or 0.0),
                    "snapshot_at": snapshot_at.isoformat() if snapshot_at else None,
                    "source": quote.source or "",
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

    def __init__(self, integration_gateway: Any) -> None:
        self._integration_gateway = integration_gateway

    def get_user_simulated_account_totals(self, user_id: int) -> dict[str, float] | None:
        """Return aggregated totals from the simulated-account system."""
        return self._integration_gateway.get_user_account_totals(user_id)

    def get_simulated_positions(self, user_id: int) -> list[dict]:
        """Return holdings from the simulated-account system."""
        return self._integration_gateway.list_user_positions(user_id=user_id)

    def get_simulated_positions_for_dashboard(
        self,
        user_id: int,
        account_id: int | None = None,
    ) -> list[dict]:
        """Return simulated-account positions with account metadata for dashboard views."""
        return self._integration_gateway.list_user_positions(
            user_id=user_id,
            account_id=account_id,
            include_account_meta=True,
        )

    def get_dashboard_accounts(self, user_id: int) -> list[dict]:
        """Return investment account cards for the dashboard homepage."""
        return self._integration_gateway.list_dashboard_accounts(user_id)

    def get_policy_environment(
        self, user_id: int
    ) -> tuple[str | None, date | None, int, list[dict]]:
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

    def get_portfolio_snapshot_performance_data(self, portfolio_id: int) -> list[dict]:
        """Return performance chart data from legacy portfolio snapshots."""
        return self._integration_gateway.get_portfolio_snapshot_performance_data(portfolio_id)

    def get_simulated_performance_data(
        self,
        *,
        user_id: int,
        account_id: int | None,
        days: int,
    ) -> list[dict]:
        """Return performance chart data from simulated-account net values."""
        return self._integration_gateway.get_user_performance_payload(
            user_id=user_id,
            account_id=account_id,
            days=days,
        )


class DashboardQueryRepository:
    """ORM-backed query helpers for dashboard application query services."""

    def __init__(self, integration_gateway: Any) -> None:
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
