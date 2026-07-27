"""Seed database-backed equity, sector, and fund preferences atomically."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError, transaction

from apps.equity.infrastructure.config_repositories import (
    BootstrapWriteStatus,
    EquityBootstrapConfigRepository,
)

STOCK_SCREENING_RULES: tuple[Mapping[str, object], ...] = (
    {
        "regime": "Recovery",
        "rule_name": "复苏期成长股",
        "min_roe": 15.0,
        "min_revenue_growth": 20.0,
        "min_profit_growth": 15.0,
        "max_pe": 35.0,
        "max_pb": 5.0,
        "min_market_cap": Decimal("5000000000"),
        "sector_preference": ["证券", "建筑材料", "化工", "汽车", "电子"],
        "max_count": 30,
        "priority": 1,
    },
    {
        "regime": "Overheat",
        "rule_name": "过热期商品股",
        "min_roe": 12.0,
        "min_revenue_growth": 15.0,
        "max_pe": 25.0,
        "max_pb": 3.0,
        "min_market_cap": Decimal("10000000000"),
        "sector_preference": ["煤炭", "有色金属", "石油石化", "钢铁"],
        "max_count": 30,
        "priority": 1,
    },
    {
        "regime": "Stagflation",
        "rule_name": "滞胀期防御股",
        "min_roe": 10.0,
        "min_revenue_growth": 5.0,
        "max_pe": 20.0,
        "max_pb": 2.5,
        "min_market_cap": Decimal("10000000000"),
        "sector_preference": ["医药生物", "食品饮料", "公用事业", "农林牧渔"],
        "max_count": 30,
        "priority": 1,
    },
    {
        "regime": "Deflation",
        "rule_name": "通缩期价值股",
        "min_roe": 8.0,
        "max_debt_ratio": 60.0,
        "max_pe": 15.0,
        "max_pb": 2.0,
        "min_market_cap": Decimal("20000000000"),
        "sector_preference": ["银行", "保险", "房地产"],
        "max_count": 30,
        "priority": 1,
    },
)

SECTOR_PREFERENCES: tuple[Mapping[str, object], ...] = (
    {"regime": "Recovery", "sector_name": "证券", "weight": 1.0},
    {"regime": "Recovery", "sector_name": "建筑材料", "weight": 0.9},
    {"regime": "Recovery", "sector_name": "化工", "weight": 0.9},
    {"regime": "Recovery", "sector_name": "汽车", "weight": 0.8},
    {"regime": "Recovery", "sector_name": "电子", "weight": 0.8},
    {"regime": "Overheat", "sector_name": "煤炭", "weight": 1.0},
    {"regime": "Overheat", "sector_name": "有色金属", "weight": 0.9},
    {"regime": "Overheat", "sector_name": "石油石化", "weight": 0.9},
    {"regime": "Stagflation", "sector_name": "医药生物", "weight": 1.0},
    {"regime": "Stagflation", "sector_name": "食品饮料", "weight": 0.9},
    {"regime": "Stagflation", "sector_name": "公用事业", "weight": 0.8},
    {"regime": "Deflation", "sector_name": "银行", "weight": 1.0},
    {"regime": "Deflation", "sector_name": "保险", "weight": 0.9},
)

FUND_TYPE_PREFERENCES: tuple[Mapping[str, object], ...] = (
    {"regime": "Recovery", "fund_type": "股票型", "style": "成长", "priority": 2},
    {"regime": "Recovery", "fund_type": "混合型", "style": "平衡", "priority": 1},
    {"regime": "Overheat", "fund_type": "商品型", "style": "商品", "priority": 2},
    {"regime": "Overheat", "fund_type": "QDII", "style": "商品", "priority": 1},
    {"regime": "Stagflation", "fund_type": "货币型", "style": "稳健", "priority": 2},
    {"regime": "Stagflation", "fund_type": "短债型", "style": "稳健", "priority": 1},
    {"regime": "Deflation", "fund_type": "债券型", "style": "纯债", "priority": 1},
)


class Command(BaseCommand):
    """Create missing bootstrap rows and overwrite them only on explicit request."""

    help = "Initialize database-backed equity, sector, and fund configuration"

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the explicit destructive-overwrite switch."""

        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite matching database rows with bootstrap defaults.",
        )

    def handle(self, *args: object, **options: object) -> None:
        """Persist all defaults in one transaction and report each outcome class."""

        del args
        force = options.get("force", False)
        if not isinstance(force, bool):
            raise CommandError("--force must be a boolean")

        repository = self._get_repository()
        statuses: Counter[BootstrapWriteStatus] = Counter()
        self.stdout.write("开始初始化个股/板块/基金配置...")
        try:
            with transaction.atomic():
                for rule in STOCK_SCREENING_RULES:
                    statuses[
                        repository.upsert_stock_screening_rule(
                            dict(rule),
                            overwrite=force,
                        )
                    ] += 1
                for preference in SECTOR_PREFERENCES:
                    statuses[
                        repository.upsert_sector_preference(
                            dict(preference),
                            overwrite=force,
                        )
                    ] += 1
                for preference in FUND_TYPE_PREFERENCES:
                    statuses[
                        repository.upsert_fund_type_preference(
                            dict(preference),
                            overwrite=force,
                        )
                    ] += 1
        except DatabaseError as exc:
            raise CommandError(f"配置初始化失败: {type(exc).__name__}") from exc

        total = sum(statuses.values())
        self.stdout.write(
            self.style.SUCCESS(
                "配置初始化完成: "
                f"total={total}, created={statuses['created']}, "
                f"updated={statuses['updated']}, preserved={statuses['preserved']}"
            )
        )

    @staticmethod
    def _get_repository() -> EquityBootstrapConfigRepository:
        """Return the concrete bootstrap repository at the command composition root."""

        return EquityBootstrapConfigRepository()
