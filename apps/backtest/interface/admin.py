"""
Django Admin for Backtest.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from django.contrib import admin
from django.db.models import Model
from django.http import HttpRequest

from apps.backtest.models import BacktestResultModel, BacktestTradeModel
from shared.infrastructure.django_admin import TypedModelAdmin

BacktestEvidenceModelT = TypeVar("BacktestEvidenceModelT", bound=Model)


class ImmutableBacktestEvidenceAdmin(
    TypedModelAdmin[BacktestEvidenceModelT],
    Generic[BacktestEvidenceModelT],
):
    """Expose generated backtest evidence without mutation controls."""

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Require backtest evidence to originate from execution workflows."""

        del request
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: BacktestEvidenceModelT | None = None,
    ) -> bool:
        """Keep persisted backtest evidence immutable."""

        del request, obj
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: BacktestEvidenceModelT | None = None,
    ) -> bool:
        """Route deletion through owner-scoped or retention repositories."""

        del request, obj
        return False


@admin.register(BacktestResultModel)
class BacktestResultAdmin(ImmutableBacktestEvidenceAdmin[BacktestResultModel]):
    """Admin interface for BacktestResult"""

    list_display = [
        "id",
        "name",
        "status",
        "trust_status",
        "use_pit_data",
        "start_date",
        "end_date",
        "total_return",
        "annualized_return",
        "max_drawdown",
        "sharpe_ratio",
        "created_at",
        "completed_at",
    ]
    list_filter = [
        "status",
        "trust_status",
        "use_pit_data",
        "start_date",
        "end_date",
        "rebalance_frequency",
    ]
    search_fields = ["name"]
    date_hierarchy = "start_date"
    readonly_fields = [field.name for field in BacktestResultModel._meta.fields] + ["used_signals"]

    fieldsets = (
        ("基本信息", {"fields": ("user", "name", "status", "error_message")}),
        (
            "回测配置",
            {
                "fields": (
                    "start_date",
                    "end_date",
                    "initial_capital",
                    "rebalance_frequency",
                    "use_pit_data",
                    "transaction_cost_bps",
                )
            },
        ),
        (
            "可复现性证据",
            {
                "fields": (
                    "trust_status",
                    "data_manifest_id",
                    "pit_coverage",
                    "config_hash",
                    "code_commit",
                    "engine_version",
                    "research_trial_id",
                    "decision_snapshot_id",
                    "signal_configs",
                    "used_signals",
                )
            },
        ),
        (
            "回测结果",
            {
                "fields": (
                    "final_capital",
                    "total_return",
                    "annualized_return",
                    "max_drawdown",
                    "sharpe_ratio",
                )
            },
        ),
        (
            "详细数据",
            {
                "fields": ("equity_curve", "regime_history", "trades", "warnings"),
                "classes": ("collapse",),
            },
        ),
        (
            "元数据",
            {"fields": ("created_at", "updated_at", "completed_at"), "classes": ("collapse",)},
        ),
    )


@admin.register(BacktestTradeModel)
class BacktestTradeAdmin(ImmutableBacktestEvidenceAdmin[BacktestTradeModel]):
    """Admin interface for BacktestTrade"""

    list_display = [
        "id",
        "backtest",
        "trade_date",
        "asset_class",
        "action",
        "shares",
        "price",
        "notional",
        "cost",
    ]
    list_filter = ["action", "asset_class", "trade_date"]
    search_fields = ["backtest__name", "asset_class"]
    date_hierarchy = "trade_date"
    readonly_fields = [field.name for field in BacktestTradeModel._meta.fields]
