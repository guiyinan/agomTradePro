from __future__ import annotations

import os
from dataclasses import dataclass
from io import StringIO

from django.apps import apps as django_apps
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.account.infrastructure.models import (
    AssetCategoryModel,
    CurrencyModel,
    DocumentationModel,
    InvestmentRuleModel,
)
from apps.audit.infrastructure.models import ConfidenceConfigModel, IndicatorThresholdConfigModel
from apps.equity.infrastructure.models import (
    ScoringWeightConfigModel,
    StockInfoModel,
    StockScreeningRuleConfigModel,
)
from apps.factor.infrastructure.models import FactorDefinitionModel, FactorPortfolioConfigModel
from apps.fund.infrastructure.models import FundTypePreferenceConfigModel
from apps.hedge.infrastructure.models import HedgePairModel
from apps.prompt.infrastructure.models import ChainConfigORM, PromptTemplateORM
from apps.regime.infrastructure.models import RegimeThresholdConfig
from apps.rotation.infrastructure.models import (
    AssetClassModel,
    RotationConfigModel,
    RotationTemplateModel,
)
from apps.sector.infrastructure.models import SectorPreferenceConfigModel
from apps.strategy.infrastructure.models import PositionManagementRuleModel, StrategyModel


@dataclass(frozen=True)
class BootstrapStep:
    name: str
    check: callable
    run: callable


class Command(BaseCommand):
    help = "Bootstrap idempotent cold-start configuration data for a fresh deployment"

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-macro-sync",
            action="store_true",
            help="Also run sync_macro_data after config bootstrap (network-dependent).",
        )
        parser.add_argument(
            "--with-alpha",
            action="store_true",
            help="Also bootstrap Alpha caches using real Qlib assets when available.",
        )
        parser.add_argument(
            "--with-decision-repair",
            action="store_true",
            help="Also repair decision-grade macro/quote/pulse/alpha readiness after bootstrap.",
        )
        parser.add_argument(
            "--decision-asset-codes",
            default="",
            help="Comma-separated asset codes for decision reliability repair.",
        )
        parser.add_argument(
            "--decision-quote-max-age-hours",
            type=float,
            default=4.0,
            help="Max quote age accepted by decision reliability repair.",
        )
        parser.add_argument(
            "--skip-pulse",
            action="store_true",
            help="Skip Pulse refresh when --with-decision-repair is used.",
        )
        parser.add_argument(
            "--skip-alpha",
            action="store_true",
            help="Skip Alpha refresh when --with-decision-repair is used.",
        )
        parser.add_argument(
            "--alpha-universes",
            default="csi300",
            help="Comma-separated universes for alpha bootstrap (default: csi300).",
        )
        parser.add_argument(
            "--alpha-top-n",
            type=int,
            default=30,
            help="Top N alpha scores to bootstrap per universe (default: 30).",
        )
        parser.add_argument(
            "--decision-env",
            choices=["auto", "dev", "test", "prod"],
            default="auto",
            help="Environment to use for init_decision_model_params.",
        )

    def handle(self, *args, **options):
        decision_env = self._resolve_decision_env(options["decision_env"])
        self.stdout.write(self.style.SUCCESS("Cold-start bootstrap begin"))

        steps = [
            BootstrapStep(
                name="account_classification",
                check=lambda: CurrencyModel._default_manager.exists() and AssetCategoryModel._default_manager.exists(),
                run=lambda: self._run_command("init_classification"),
            ),
            BootstrapStep(
                name="investment_rules",
                check=lambda: InvestmentRuleModel._default_manager.filter(user__isnull=True).exists(),
                run=lambda: self._run_command("init_enhanced_rules"),
            ),
            BootstrapStep(
                name="system_docs",
                check=lambda: DocumentationModel._default_manager.exists(),
                run=lambda: self._run_command("init_docs"),
            ),
            BootstrapStep(
                name="regime_thresholds",
                check=lambda: RegimeThresholdConfig._default_manager.filter(is_active=True).exists(),
                run=lambda: self._run_command("init_regime_thresholds"),
            ),
            BootstrapStep(
                name="audit_indicator_thresholds",
                check=lambda: IndicatorThresholdConfigModel._default_manager.exists(),
                run=lambda: self._run_command("init_indicator_thresholds"),
            ),
            BootstrapStep(
                name="audit_confidence_config",
                check=lambda: ConfidenceConfigModel._default_manager.exists(),
                run=lambda: self._run_command("init_confidence_config"),
            ),
            BootstrapStep(
                name="equity_scoring_weights",
                check=lambda: ScoringWeightConfigModel._default_manager.exists(),
                run=self._bootstrap_scoring_weights,
            ),
            BootstrapStep(
                name="equity_config",
                check=self._equity_config_exists,
                run=lambda: self._run_command("init_equity_config"),
            ),
            BootstrapStep(
                name="prompt_templates",
                check=lambda: PromptTemplateORM._default_manager.exists() and ChainConfigORM._default_manager.exists(),
                run=lambda: self._run_command("init_prompt_templates"),
            ),
            BootstrapStep(
                name="scheduler_defaults",
                check=self._scheduler_defaults_ready,
                run=lambda: self._run_command("init_scheduler_defaults"),
            ),
            BootstrapStep(
                name="authoritative_rss_sources",
                check=self._authoritative_rss_sources_ready,
                run=lambda: self._run_command("init_authoritative_rss_sources"),
            ),
            BootstrapStep(
                name="rotation_config",
                check=lambda: AssetClassModel._default_manager.exists()
                and RotationConfigModel._default_manager.exists()
                and RotationTemplateModel._default_manager.exists(),
                run=lambda: self._run_command("init_rotation"),
            ),
            BootstrapStep(
                name="hedge_pairs",
                check=lambda: HedgePairModel._default_manager.exists(),
                run=lambda: self._run_command("init_hedge"),
            ),
            BootstrapStep(
                name="factor_config",
                check=lambda: FactorDefinitionModel._default_manager.exists()
                and FactorPortfolioConfigModel._default_manager.exists(),
                run=lambda: self._run_command("init_factors"),
            ),
            BootstrapStep(
                name="mcp_cold_start_defaults",
                check=self._mcp_cold_start_ready,
                run=lambda: self._run_command("bootstrap_mcp_cold_start"),
            ),
            BootstrapStep(
                name="decision_model_params",
                check=lambda: self._decision_model_params_ready(decision_env),
                run=lambda: self._run_command("init_decision_model_params", env=decision_env),
            ),
            BootstrapStep(
                name="position_rules",
                check=self._position_rules_ready,
                run=lambda: self._run_command("init_position_rules"),
            ),
        ]

        applied = 0
        skipped = 0
        for step in steps:
            if step.check():
                skipped += 1
                self.stdout.write(f"[skip] {step.name}")
                continue
            self.stdout.write(f"[apply] {step.name}")
            try:
                step.run()
            except CommandError:
                self.stdout.write(f"[skip] {step.name} (CommandError, likely dev-only)")
                skipped += 1
                continue
            applied += 1

        if options.get("with_macro_sync"):
            self.stdout.write("[apply] macro_sync")
            self._run_command("sync_macro_data")
            applied += 1

        if options.get("with_alpha"):
            self.stdout.write("[apply] alpha_bootstrap")
            self._run_command(
                "bootstrap_alpha_cold_start",
                universes=options["alpha_universes"],
                top_n=options["alpha_top_n"],
            )

        if options.get("with_decision_repair"):
            self.stdout.write("[apply] decision_repair")
            repair_kwargs = {
                "quote_max_age_hours": float(
                    options.get("decision_quote_max_age_hours") or 4.0
                ),
                "skip_pulse": bool(options.get("skip_pulse")),
                "skip_alpha": bool(options.get("skip_alpha")),
            }
            raw_asset_codes = str(options.get("decision_asset_codes") or "").strip()
            if raw_asset_codes:
                repair_kwargs["asset_codes"] = raw_asset_codes
            self._run_command("repair_decision_data_reliability", **repair_kwargs)
            applied += 1

        self.stdout.write(self.style.SUCCESS(f"Cold-start bootstrap complete: applied={applied}, skipped={skipped}"))

    def _resolve_decision_env(self, raw_env: str) -> str:
        if raw_env != "auto":
            return raw_env
        settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
        if "production" in settings_module:
            return "prod"
        if "test" in settings_module:
            return "test"
        return "dev"

    def _run_command(self, command_name: str, **kwargs):
        buffer = StringIO()
        call_command(command_name, stdout=buffer, stderr=buffer, **kwargs)
        output = buffer.getvalue().strip()
        if output:
            self.stdout.write(output)

    def _decision_model_params_ready(self, env: str) -> bool:
        model = django_apps.get_model(
            "decision_rhythm",
            "DecisionModelParamConfigModel",
        )
        return model._default_manager.filter(env=env).exists()

    def _bootstrap_scoring_weights(self):
        default_configs = [
            {
                "name": "默认配置",
                "description": "系统默认评分权重配置：成长性40%、盈利能力40%、估值20%",
                "is_active": True,
                "growth_weight": 0.4,
                "profitability_weight": 0.4,
                "valuation_weight": 0.2,
                "revenue_growth_weight": 0.5,
                "profit_growth_weight": 0.5,
            },
            {
                "name": "成长型配置",
                "description": "偏向成长性的配置：成长性50%、盈利能力35%、估值15%",
                "is_active": False,
                "growth_weight": 0.5,
                "profitability_weight": 0.35,
                "valuation_weight": 0.15,
                "revenue_growth_weight": 0.6,
                "profit_growth_weight": 0.4,
            },
            {
                "name": "价值型配置",
                "description": "偏向价值的配置：成长性30%、盈利能力35%、估值35%",
                "is_active": False,
                "growth_weight": 0.3,
                "profitability_weight": 0.35,
                "valuation_weight": 0.35,
                "revenue_growth_weight": 0.4,
                "profit_growth_weight": 0.6,
            },
        ]
        for config in default_configs:
            ScoringWeightConfigModel._default_manager.get_or_create(name=config["name"], defaults=config)
        self.stdout.write("Created default scoring weights when missing.")

    def _equity_config_exists(self) -> bool:
        return (
            StockScreeningRuleConfigModel._default_manager.exists()
            and SectorPreferenceConfigModel._default_manager.exists()
            and FundTypePreferenceConfigModel._default_manager.exists()
        )

    def _position_rules_ready(self) -> bool:
        if not StrategyModel._default_manager.exists():
            return True
        return PositionManagementRuleModel._default_manager.exists()

    def _scheduler_defaults_ready(self) -> bool:
        periodic_task_model = django_apps.get_model("django_celery_beat", "PeriodicTask")
        existing_names = set(
            periodic_task_model._default_manager.values_list("name", flat=True)
        )
        expected_names = {
            "daily-sync-and-calculate",
            "check-data-freshness",
            "high-frequency-generate-signal",
            "high-frequency-recalculate-regime",
            "equity-valuation-daily-sync",
            "equity-valuation-quality-validate",
            "equity-valuation-freshness-check",
            "decision-quote-intraday-refresh",
            "decision-quote-post-close-refresh",
            "decision-quote-freshness-check",
            "decision-workspace-nightly-snapshot-refresh",
            "account-check-stop-loss-take-profit-intraday",
        }
        return expected_names.issubset(existing_names)

    def _authoritative_rss_sources_ready(self) -> bool:
        from apps.policy.management.commands.init_authoritative_rss_sources import (
            AUTHORITATIVE_RSS_SOURCES,
        )

        rsshub_config_model = django_apps.get_model("policy", "RSSHubGlobalConfig")
        rss_source_model = django_apps.get_model("policy", "RSSSourceConfigModel")
        config = rsshub_config_model._default_manager.filter(singleton_id=1).first()
        if config is None or not config.enabled:
            return False

        expected_routes = {source.route_path for source in AUTHORITATIVE_RSS_SOURCES}
        active_routes = set(
            rss_source_model._default_manager.filter(
                is_active=True,
                rsshub_enabled=True,
                rsshub_route_path__in=expected_routes,
            ).values_list("rsshub_route_path", flat=True)
        )
        return expected_routes.issubset(active_routes)

    def _mcp_cold_start_ready(self) -> bool:
        rotation_ready = RotationConfigModel._default_manager.filter(name="动量轮动配置").exists()
        macro_ready = self._macro_indicator_model()._default_manager.filter(
            indicator_code="MCP_TEST_IND"
        ).exists()
        stock_ready = StockInfoModel._default_manager.exists()
        factor_seed_ready = FactorPortfolioConfigModel._default_manager.filter(name="MCP冷启动动量组合").exists()
        factor_ready = True
        for config in FactorPortfolioConfigModel._default_manager.all():
            weights = config.factor_weights or {}
            if not weights:
                continue
            abs_sum = sum(abs(weight) for weight in weights.values())
            if abs(abs_sum - 1.0) > 0.01 or any(weight < 0 for weight in weights.values()):
                factor_ready = False
                break
        return rotation_ready and macro_ready and stock_ready and factor_seed_ready and factor_ready

    @staticmethod
    def _macro_indicator_model():
        from apps.data_center.infrastructure.models import MacroFactModel

        return MacroFactModel
