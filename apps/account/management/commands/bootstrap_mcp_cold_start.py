from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from apps.equity.infrastructure.models import StockInfoModel
from apps.factor.infrastructure.models import FactorPortfolioConfigModel
from apps.macro.infrastructure.models import MacroIndicator
from apps.rotation.infrastructure.models import RotationConfigModel


class Command(BaseCommand):
    help = "Bootstrap MCP-friendly cold-start defaults for local/dev environments"

    STOCK_SEEDS = [
        ("000001.SZ", "平安银行", "银行", "SZ"),
        ("000333.SZ", "美的集团", "家电", "SZ"),
        ("000651.SZ", "格力电器", "家电", "SZ"),
        ("000858.SZ", "五粮液", "食品饮料", "SZ"),
        ("002594.SZ", "比亚迪", "汽车", "SZ"),
        ("300750.SZ", "宁德时代", "电力设备", "SZ"),
        ("600000.SH", "浦发银行", "银行", "SH"),
        ("600036.SH", "招商银行", "银行", "SH"),
        ("600519.SH", "贵州茅台", "食品饮料", "SH"),
        ("601318.SH", "中国平安", "非银金融", "SH"),
    ]

    ROTATION_ALIASES = {
        "动量轮动配置": "动量轮动策略",
    }

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("MCP cold-start bootstrap begin"))

        factor_fixed = self._repair_factor_configs()
        stock_seeded = self._ensure_stock_universe()
        factor_seeded = self._ensure_factor_cold_start_config()
        rotation_seeded = self._ensure_rotation_aliases()
        macro_seeded = self._ensure_macro_smoke_indicator()

        self.stdout.write(
            self.style.SUCCESS(
                f"MCP cold-start bootstrap complete: factor_fixed={factor_fixed}, "
                f"stock_seeded={stock_seeded}, factor_seeded={factor_seeded}, "
                f"rotation_seeded={rotation_seeded}, macro_seeded={macro_seeded}"
            )
        )

    def _repair_factor_configs(self) -> int:
        updated = 0
        for config in FactorPortfolioConfigModel._default_manager.all():
            weights = dict(config.factor_weights or {})
            if not weights:
                continue
            abs_sum = sum(abs(weight) for weight in weights.values())
            if abs(abs_sum - 1.0) <= 0.01 and all(weight >= 0 for weight in weights.values()):
                continue

            normalized = self._normalize_weights(weights)
            if normalized == weights:
                continue

            config.factor_weights = normalized
            config.is_active = True
            config.save(update_fields=["factor_weights", "is_active", "updated_at"])
            updated += 1
            self.stdout.write(f"[factor] normalized {config.name}")
        return updated

    def _ensure_stock_universe(self) -> int:
        created = 0
        for stock_code, name, sector, market in self.STOCK_SEEDS:
            _, was_created = StockInfoModel._default_manager.get_or_create(
                stock_code=stock_code,
                defaults={
                    "name": name,
                    "sector": sector,
                    "market": market,
                    "list_date": date(2010, 1, 1),
                    "is_active": True,
                },
            )
            if was_created:
                created += 1

        if created:
            self.stdout.write(f"[equity] seeded stock universe rows={created}")
        return created

    def _ensure_factor_cold_start_config(self) -> int:
        _, created = FactorPortfolioConfigModel._default_manager.update_or_create(
            name="MCP冷启动动量组合",
            defaults={
                "description": "用于 MCP/SDK 冷启动验证的最小可运行因子组合",
                "factor_weights": {
                    "momentum_1m": 0.2,
                    "momentum_3m": 0.35,
                    "momentum_6m": 0.25,
                    "volatility_20d": 0.1,
                    "volume_ratio": 0.1,
                },
                "universe": "all_a",
                "top_n": 10,
                "rebalance_frequency": "monthly",
                "weight_method": "equal_weight",
                "is_active": True,
            },
        )
        if created:
            self.stdout.write("[factor] created MCP冷启动动量组合")
            return 1
        return 0

    def _ensure_rotation_aliases(self) -> int:
        created = 0
        for alias_name, source_name in self.ROTATION_ALIASES.items():
            if RotationConfigModel._default_manager.filter(name=alias_name).exists():
                continue

            source = RotationConfigModel._default_manager.filter(name=source_name).first()
            if source is None:
                self.stdout.write(self.style.WARNING(f"[rotation] source missing: {source_name}"))
                continue

            RotationConfigModel._default_manager.create(
                name=alias_name,
                description=f"{source.description or source_name}（MCP 冷启动别名）",
                strategy_type=source.strategy_type,
                asset_universe=deepcopy(source.asset_universe),
                params=deepcopy(source.params),
                rebalance_frequency=source.rebalance_frequency,
                min_weight=source.min_weight,
                max_weight=source.max_weight,
                max_turnover=source.max_turnover,
                lookback_period=source.lookback_period,
                regime_allocations=deepcopy(source.regime_allocations),
                momentum_periods=deepcopy(source.momentum_periods),
                top_n=source.top_n,
                is_active=True,
            )
            created += 1
            self.stdout.write(f"[rotation] created alias {alias_name} -> {source_name}")
        return created

    def _ensure_macro_smoke_indicator(self) -> int:
        if MacroIndicator._default_manager.filter(code="MCP_TEST_IND").exists():
            return 0

        source_rows = list(
            MacroIndicator._default_manager.filter(code="CN_PMI").order_by("-reporting_period")[:24]
        )
        if not source_rows:
            self.stdout.write(self.style.WARNING("[macro] source missing: CN_PMI"))
            return 0

        created = 0
        for row in source_rows:
            MacroIndicator._default_manager.get_or_create(
                code="MCP_TEST_IND",
                reporting_period=row.reporting_period,
                revision_number=row.revision_number,
                defaults={
                    "value": row.value,
                    "unit": row.unit,
                    "original_unit": row.original_unit,
                    "period_type": row.period_type,
                    "published_at": row.published_at or (row.reporting_period + timedelta(days=1)),
                    "publication_lag_days": row.publication_lag_days,
                    "source": "bootstrap_mcp_cold_start",
                },
            )
            created += 1

        self.stdout.write(f"[macro] created MCP_TEST_IND from CN_PMI, rows={created}")
        return created

    @staticmethod
    def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
        total = sum(abs(weight) for weight in weights.values())
        if total <= 0:
            return weights
        normalized = {code: round(abs(weight) / total, 6) for code, weight in weights.items()}
        diff = round(1.0 - sum(normalized.values()), 6)
        if diff != 0:
            first_key = next(iter(normalized))
            normalized[first_key] = round(normalized[first_key] + diff, 6)
        return normalized
