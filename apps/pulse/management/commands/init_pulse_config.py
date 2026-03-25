"""
初始化 Pulse 指标配置 和 Navigator 资产配置到数据库。

Usage:
    python manage.py init_pulse_config
    python manage.py init_pulse_config --force  # 覆盖已有配置
"""

from django.core.management.base import BaseCommand

from apps.pulse.infrastructure.data_provider import DEFAULT_PULSE_INDICATORS
from apps.pulse.infrastructure.models import NavigatorAssetConfigModel, PulseIndicatorConfigModel


# Navigator 资产配置默认值
NAVIGATOR_ASSET_DEFAULTS = [
    {
        "regime_name": "Recovery",
        "asset_weight_ranges": {
            "equity": [0.50, 0.70],
            "bond": [0.15, 0.30],
            "commodity": [0.05, 0.15],
            "cash": [0.05, 0.15],
        },
        "risk_budget": 0.85,
        "recommended_sectors": ["消费", "科技", "金融"],
        "benefiting_styles": ["成长", "中小盘"],
    },
    {
        "regime_name": "Overheat",
        "asset_weight_ranges": {
            "equity": [0.20, 0.40],
            "bond": [0.10, 0.25],
            "commodity": [0.25, 0.40],
            "cash": [0.10, 0.20],
        },
        "risk_budget": 0.70,
        "recommended_sectors": ["能源", "材料", "公用事业"],
        "benefiting_styles": ["价值", "周期"],
    },
    {
        "regime_name": "Stagflation",
        "asset_weight_ranges": {
            "equity": [0.05, 0.20],
            "bond": [0.20, 0.35],
            "commodity": [0.15, 0.30],
            "cash": [0.25, 0.40],
        },
        "risk_budget": 0.50,
        "recommended_sectors": ["公用事业", "医药", "必选消费"],
        "benefiting_styles": ["防御", "红利"],
    },
    {
        "regime_name": "Deflation",
        "asset_weight_ranges": {
            "equity": [0.10, 0.25],
            "bond": [0.40, 0.60],
            "commodity": [0.00, 0.10],
            "cash": [0.15, 0.30],
        },
        "risk_budget": 0.60,
        "recommended_sectors": ["债券ETF", "货币基金", "高股息"],
        "benefiting_styles": ["债券", "红利", "低波"],
    },
]


class Command(BaseCommand):
    help = "Initialize Pulse indicator configs and Navigator asset configs in DB"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Override existing configurations",
        )

    def handle(self, *args, **options):
        force = options["force"]

        # 1. Pulse Indicator Configs
        self.stdout.write(self.style.NOTICE("Initializing Pulse indicator configs..."))
        created_count = 0
        updated_count = 0

        for ind_def in DEFAULT_PULSE_INDICATORS:
            defaults = {
                "indicator_name": ind_def.name,
                "dimension": ind_def.dimension,
                "frequency": ind_def.frequency,
                "weight": ind_def.weight,
                "signal_type": ind_def.signal_type,
                "bullish_threshold": ind_def.bullish_threshold,
                "bearish_threshold": ind_def.bearish_threshold,
                "neutral_band": ind_def.neutral_band,
                "signal_multiplier": ind_def.signal_multiplier,
                "is_active": True,
            }

            if force:
                _, created = PulseIndicatorConfigModel.objects.update_or_create(
                    indicator_code=ind_def.code,
                    defaults=defaults,
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1
            else:
                _, created = PulseIndicatorConfigModel.objects.get_or_create(
                    indicator_code=ind_def.code,
                    defaults=defaults,
                )
                if created:
                    created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"  Pulse indicators: {created_count} created, {updated_count} updated"
            )
        )

        # 2. Navigator Asset Configs
        self.stdout.write(self.style.NOTICE("Initializing Navigator asset configs..."))
        nav_created = 0
        nav_updated = 0

        for cfg in NAVIGATOR_ASSET_DEFAULTS:
            defaults = {
                "asset_weight_ranges": cfg["asset_weight_ranges"],
                "risk_budget": cfg["risk_budget"],
                "recommended_sectors": cfg["recommended_sectors"],
                "benefiting_styles": cfg["benefiting_styles"],
                "is_active": True,
            }

            if force:
                _, created = NavigatorAssetConfigModel.objects.update_or_create(
                    regime_name=cfg["regime_name"],
                    defaults=defaults,
                )
                if created:
                    nav_created += 1
                else:
                    nav_updated += 1
            else:
                _, created = NavigatorAssetConfigModel.objects.get_or_create(
                    regime_name=cfg["regime_name"],
                    defaults=defaults,
                )
                if created:
                    nav_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"  Navigator configs: {nav_created} created, {nav_updated} updated"
            )
        )

        self.stdout.write(self.style.SUCCESS("Done!"))
