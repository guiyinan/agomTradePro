"""Behavior tests for account initialization orchestration commands."""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import CommandError

from apps.account.management.commands import init_all
from apps.account.management.commands.bootstrap_cold_start import Command as BootstrapCommand
from apps.account.management.commands.bootstrap_mcp_cold_start import Command as McpBootstrapCommand


def test_init_all_executes_required_steps_and_tolerates_optional_failure(monkeypatch) -> None:
    """The wrapper forwards force only where supported and isolates optional sync failure."""
    command = init_all.Command(stdout=StringIO())
    command.init_steps = [
        {
            "name": "Required",
            "command": "init_classification",
            "description": "required",
            "module": "account",
        },
        {
            "name": "Prompt",
            "command": "init_prompt_templates",
            "description": "prompt",
            "module": "prompt",
        },
        {
            "name": "Optional",
            "command": "sync_macro_data",
            "description": "network",
            "module": "macro",
            "optional": True,
        },
    ]
    calls: list[tuple[str, dict[str, object]]] = []

    def _call(name: str, **kwargs: object) -> None:
        calls.append((name, kwargs))
        if name == "sync_macro_data":
            raise RuntimeError("offline")

    monkeypatch.setattr(init_all.management, "call_command", _call)
    result = command._execute_steps({"force": True})
    assert result["success"] == ["Required", "Prompt"]
    assert result["failed"] == []
    assert "failed: offline" in result["skipped"][0]
    assert calls[1] == ("init_prompt_templates", {"force": True})

    skipped = command._execute_steps({"step": "classification", "skip_macro": True})
    assert skipped["success"] == ["Required"]
    assert len(skipped["skipped"]) == 2


def test_init_all_confirmation_database_and_handle_paths(monkeypatch) -> None:
    """Interactive cancellation and non-interactive completion remain deterministic."""
    command = init_all.Command(stdout=StringIO())
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert command._confirm("continue") is True
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert command._confirm("continue") is False

    events: list[str] = []
    monkeypatch.setattr(command, "_show_database_info", lambda: events.append("database"))
    monkeypatch.setattr(command, "_show_plan", lambda options: events.append("plan"))
    monkeypatch.setattr(
        command, "_execute_steps", lambda options: {"success": [], "skipped": [], "failed": []}
    )
    monkeypatch.setattr(command, "_show_summary", lambda results: events.append("summary"))
    monkeypatch.setattr(command, "_show_next_steps", lambda: events.append("next"))
    command.handle(force=False, yes=True, skip_macro=True, step=None)
    assert events == ["database", "plan", "summary", "next"]

    monkeypatch.setattr(command, "_confirm", lambda message: False)
    events.clear()
    command.handle(force=False, yes=False, skip_macro=False, step=None)
    assert events == ["database", "plan"]


def test_bootstrap_helpers_route_environment_commands_and_readiness(monkeypatch) -> None:
    """Cold-start helpers resolve environments and preserve command failure semantics."""
    command = BootstrapCommand(stdout=StringIO())
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.production")
    assert command._resolve_decision_env("auto") == "prod"
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.test")
    assert command._resolve_decision_env("auto") == "test"
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.development")
    assert command._resolve_decision_env("auto") == "dev"
    assert command._resolve_decision_env("prod") == "prod"

    captured: list[tuple[str, dict[str, object]]] = []

    def _call(name: str, stdout: StringIO, stderr: StringIO, **kwargs: object) -> None:
        captured.append((name, kwargs))
        stdout.write("completed")

    monkeypatch.setattr(
        "apps.account.management.commands.bootstrap_cold_start.call_command",
        _call,
    )
    command._run_command("sample", check=True)
    assert captured == [("sample", {"check": True})]

    monkeypatch.setattr(
        command,
        "_run_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(CommandError("missing")),
    )
    assert command._macro_indicator_governance_ready() is False


def test_mcp_bootstrap_normalizes_weights_and_enforces_environment(monkeypatch) -> None:
    """MCP bootstrap normalization is positive, total-preserving, and dev-only."""
    command = McpBootstrapCommand(stdout=StringIO())
    assert command._normalize_weights({}) == {}
    assert command._normalize_weights({"a": 0.0}) == {"a": 0.0}
    normalized = command._normalize_weights({"a": -2.0, "b": 1.0})
    assert normalized["a"] >= 0
    assert normalized["b"] >= 0
    assert sum(normalized.values()) == 1.0

    monkeypatch.setattr(
        "apps.account.management.commands.bootstrap_mcp_cold_start.settings.DEBUG",
        False,
    )
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.production")
    try:
        command._assert_dev_only_environment()
    except CommandError as exc:
        assert "dev-only" in str(exc)
    else:
        raise AssertionError("production-like environment must be rejected")

    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.test")
    command._assert_dev_only_environment()


class _Query:
    def __init__(
        self,
        *,
        exists: bool = True,
        values: list[object] | None = None,
        rows: list[object] | None = None,
    ) -> None:
        self._exists = exists
        self._values = values or []
        self._rows = rows or []

    def filter(self, **kwargs: object) -> _Query:
        return self

    def exists(self) -> bool:
        return self._exists

    def values_list(self, *args: object, **kwargs: object) -> list[object]:
        return self._values

    def all(self) -> list[object]:
        return self._rows

    def get_or_create(self, **kwargs: object) -> tuple[object, bool]:
        return SimpleNamespace(**kwargs), True


def test_bootstrap_readiness_helpers_cover_configuration_boundaries(monkeypatch) -> None:
    """Readiness checks combine model state without embedding persistence in orchestration."""
    command = BootstrapCommand(stdout=StringIO())
    ready = _Query(exists=True)
    missing = _Query(exists=False)

    monkeypatch.setattr(
        "apps.account.management.commands.bootstrap_cold_start.django_apps.get_model",
        lambda *args: SimpleNamespace(_default_manager=ready),
    )
    assert command._decision_model_params_ready("test") is True

    created: list[str] = []

    class _Weights:
        @staticmethod
        def get_or_create(**kwargs: object) -> tuple[object, bool]:
            created.append(str(kwargs["name"]))
            return object(), True

    monkeypatch.setattr(
        "apps.account.management.commands.bootstrap_cold_start.ScoringWeightConfigModel",
        SimpleNamespace(_default_manager=_Weights()),
    )
    command._bootstrap_scoring_weights()
    assert created == ["默认配置", "成长型配置", "价值型配置"]

    module = "apps.account.management.commands.bootstrap_cold_start"
    monkeypatch.setattr(
        f"{module}.StockScreeningRuleConfigModel", SimpleNamespace(_default_manager=ready)
    )
    monkeypatch.setattr(
        f"{module}.SectorPreferenceConfigModel", SimpleNamespace(_default_manager=ready)
    )
    monkeypatch.setattr(
        f"{module}.FundTypePreferenceConfigModel", SimpleNamespace(_default_manager=ready)
    )
    assert command._equity_config_exists() is True
    monkeypatch.setattr(
        f"{module}.FundTypePreferenceConfigModel", SimpleNamespace(_default_manager=missing)
    )
    assert command._equity_config_exists() is False

    monkeypatch.setattr(f"{module}.StrategyModel", SimpleNamespace(_default_manager=missing))
    assert command._position_rules_ready() is True
    monkeypatch.setattr(f"{module}.StrategyModel", SimpleNamespace(_default_manager=ready))
    monkeypatch.setattr(
        f"{module}.PositionManagementRuleModel", SimpleNamespace(_default_manager=ready)
    )
    assert command._position_rules_ready() is True
    monkeypatch.setattr(
        f"{module}.PositionManagementRuleModel", SimpleNamespace(_default_manager=missing)
    )
    assert command._position_rules_ready() is False

    expected_tasks = [
        "daily-sync-and-calculate",
        "check-data-freshness",
        "high-frequency-generate-signal",
        "high-frequency-recalculate-regime",
        "equity-valuation-daily-sync",
        "equity-valuation-quality-validate",
        "equity-valuation-freshness-check",
        "decision-quote-intraday-refresh",
        "decision-quote-post-close-refresh",
        "decision-quote-pre-readiness-refresh",
        "decision-quote-freshness-check",
        "decision-workspace-nightly-snapshot-refresh",
        "account-check-stop-loss-take-profit-intraday",
        "dashboard-auto-advisor-weekly-report",
        "personal-readiness-daily-evidence",
    ]
    periodic = SimpleNamespace(_default_manager=_Query(values=expected_tasks))
    monkeypatch.setattr(
        "apps.account.management.commands.bootstrap_cold_start.django_apps.get_model",
        lambda *args: periodic,
    )
    assert command._scheduler_defaults_ready() is True


def test_mcp_readiness_detects_invalid_factor_weights(monkeypatch) -> None:
    """MCP readiness rejects negative or non-normalized factor portfolios."""
    command = BootstrapCommand(stdout=StringIO())
    module = "apps.account.management.commands.bootstrap_cold_start"
    valid_rows = [SimpleNamespace(factor_weights={"momentum": 0.6, "value": 0.4})]
    invalid_rows = [SimpleNamespace(factor_weights={"momentum": -0.5, "value": 0.5})]
    manager = _Query(exists=True, rows=valid_rows)
    monkeypatch.setattr(f"{module}.RotationConfigModel", SimpleNamespace(_default_manager=manager))
    monkeypatch.setattr(f"{module}.StockInfoModel", SimpleNamespace(_default_manager=manager))
    monkeypatch.setattr(
        f"{module}.FactorPortfolioConfigModel",
        SimpleNamespace(_default_manager=manager),
    )
    monkeypatch.setattr(
        command,
        "_macro_indicator_model",
        lambda: SimpleNamespace(_default_manager=manager),
    )
    assert command._mcp_cold_start_ready() is True

    monkeypatch.setattr(
        f"{module}.FactorPortfolioConfigModel",
        SimpleNamespace(_default_manager=_Query(exists=True, rows=invalid_rows)),
    )
    assert command._mcp_cold_start_ready() is False


def test_cold_start_handle_runs_optional_work_and_is_idempotent(monkeypatch) -> None:
    """The complete orchestration skips ready seeds and runs explicitly requested repairs."""
    command = BootstrapCommand(stdout=StringIO())
    module = "apps.account.management.commands.bootstrap_cold_start"
    ready_model = SimpleNamespace(_default_manager=_Query(exists=True))
    model_names = [
        "CurrencyModel",
        "AssetCategoryModel",
        "InvestmentRuleModel",
        "DocumentationModel",
        "RegimeThresholdConfig",
        "IndicatorThresholdConfigModel",
        "ConfidenceConfigModel",
        "ScoringWeightConfigModel",
        "StockScreeningRuleConfigModel",
        "SectorPreferenceConfigModel",
        "FundTypePreferenceConfigModel",
        "PromptTemplateORM",
        "ChainConfigORM",
        "AssetClassModel",
        "RotationConfigModel",
        "RotationTemplateModel",
        "HedgePairModel",
        "FactorDefinitionModel",
        "FactorPortfolioConfigModel",
        "StrategyModel",
        "PositionManagementRuleModel",
    ]
    for name in model_names:
        monkeypatch.setattr(f"{module}.{name}", ready_model)
    monkeypatch.setattr(command, "_scheduler_defaults_ready", lambda: True)
    monkeypatch.setattr(command, "_authoritative_rss_sources_ready", lambda: True)
    monkeypatch.setattr(command, "_macro_indicator_governance_ready", lambda: True)
    monkeypatch.setattr(command, "_mcp_cold_start_ready", lambda: True)
    monkeypatch.setattr(command, "_decision_model_params_ready", lambda env: True)
    invoked: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        command,
        "_run_command",
        lambda name, **kwargs: invoked.append((name, kwargs)),
    )

    command.handle(
        decision_env="test",
        with_macro_sync=True,
        with_alpha=True,
        with_decision_repair=True,
        decision_asset_codes="000001.SZ,600000.SH",
        decision_quote_max_age_hours=2,
        skip_pulse=True,
        skip_alpha=False,
        alpha_universes="csi300",
        alpha_top_n=12,
    )
    assert [name for name, _ in invoked] == [
        "sync_macro_data",
        "bootstrap_alpha_cold_start",
        "repair_decision_data_reliability",
    ]
    assert invoked[-1][1]["asset_codes"] == "000001.SZ,600000.SH"
    assert "applied=3, skipped=18" in command.stdout.getvalue()


def test_cold_start_handle_applies_missing_steps_and_skips_command_errors(monkeypatch) -> None:
    """Only the explicitly optional dev seed may fail without aborting bootstrap."""
    command = BootstrapCommand(stdout=StringIO())
    module = "apps.account.management.commands.bootstrap_cold_start"
    missing_model = SimpleNamespace(_default_manager=_Query(exists=False))
    model_names = [
        "CurrencyModel",
        "AssetCategoryModel",
        "InvestmentRuleModel",
        "DocumentationModel",
        "RegimeThresholdConfig",
        "IndicatorThresholdConfigModel",
        "ConfidenceConfigModel",
        "ScoringWeightConfigModel",
        "StockScreeningRuleConfigModel",
        "SectorPreferenceConfigModel",
        "FundTypePreferenceConfigModel",
        "PromptTemplateORM",
        "ChainConfigORM",
        "AssetClassModel",
        "RotationConfigModel",
        "RotationTemplateModel",
        "HedgePairModel",
        "FactorDefinitionModel",
        "FactorPortfolioConfigModel",
        "StrategyModel",
        "PositionManagementRuleModel",
    ]
    for name in model_names:
        monkeypatch.setattr(f"{module}.{name}", missing_model)
    monkeypatch.setattr(command, "_scheduler_defaults_ready", lambda: False)
    monkeypatch.setattr(command, "_authoritative_rss_sources_ready", lambda: False)
    monkeypatch.setattr(command, "_macro_indicator_governance_ready", lambda: False)
    monkeypatch.setattr(command, "_mcp_cold_start_ready", lambda: False)
    monkeypatch.setattr(command, "_decision_model_params_ready", lambda env: False)
    monkeypatch.setattr(command, "_position_rules_ready", lambda: False)
    called: list[str] = []

    def _run(name: str, **kwargs: object) -> None:
        called.append(name)
        if name == "bootstrap_mcp_cold_start":
            raise CommandError("dev only")

    monkeypatch.setattr(command, "_run_command", _run)
    command.handle(
        decision_env="dev",
        with_macro_sync=False,
        with_alpha=False,
        with_decision_repair=False,
        decision_asset_codes="",
        decision_quote_max_age_hours=4,
        skip_pulse=False,
        skip_alpha=False,
        alpha_universes="csi300",
        alpha_top_n=30,
    )
    assert "init_classification" in called
    assert "init_decision_model_params" in called
    assert "applied=17, skipped=1" in command.stdout.getvalue()

    def _required_failure(name: str, **kwargs: object) -> None:
        if name == "init_classification":
            raise CommandError("classification seed failed")

    monkeypatch.setattr(command, "_run_command", _required_failure)
    with pytest.raises(
        CommandError,
        match="Required cold-start step failed: account_classification",
    ):
        command.handle(
            decision_env="dev",
            with_macro_sync=False,
            with_alpha=False,
            with_decision_repair=False,
            decision_asset_codes="",
            decision_quote_max_age_hours=4,
            skip_pulse=False,
            skip_alpha=False,
            alpha_universes="csi300",
            alpha_top_n=30,
        )


def test_cold_start_rejects_invalid_operational_options() -> None:
    command = BootstrapCommand(stdout=StringIO())

    with pytest.raises(CommandError, match="decision-env"):
        command._resolve_decision_env("staging")
    for value in (True, 0, -1):
        with pytest.raises(CommandError, match="positive integer"):
            command._require_positive_int(value, "--alpha-top-n")
    for value in (True, 0, -1.0, float("nan"), float("inf")):
        with pytest.raises(CommandError, match="positive finite"):
            command._require_positive_float(value, "--decision-quote-max-age-hours")


def test_mcp_handle_reports_each_seed_count(monkeypatch) -> None:
    """MCP bootstrap reports the result of each independent, idempotent seed."""
    command = McpBootstrapCommand(stdout=StringIO())
    monkeypatch.setattr(command, "_assert_dev_only_environment", lambda: None)
    monkeypatch.setattr(command, "_repair_factor_configs", lambda: 2)
    monkeypatch.setattr(command, "_ensure_stock_universe", lambda: 10)
    monkeypatch.setattr(command, "_ensure_factor_cold_start_config", lambda: 1)
    monkeypatch.setattr(command, "_ensure_rotation_aliases", lambda: 1)
    monkeypatch.setattr(command, "_ensure_macro_smoke_indicator", lambda: 24)
    command.handle()
    assert (
        "factor_fixed=2, stock_seeded=10, factor_seeded=1, rotation_seeded=1, macro_seeded=24"
        in command.stdout.getvalue()
    )


def test_init_all_renders_plan_summary_database_and_next_steps() -> None:
    """Human-readable initialization output includes every execution outcome."""
    command = init_all.Command(stdout=StringIO())
    command.init_steps = [
        {
            "name": "Required",
            "command": "init_required",
            "description": "required",
            "module": "account",
        },
        {
            "name": "Optional",
            "command": "sync_macro_data",
            "description": "network",
            "module": "macro",
            "optional": True,
        },
    ]
    command._show_database_info()
    command._show_plan({"skip_macro": True, "step": None})
    command._show_plan({"skip_macro": False, "step": "required"})
    command._show_summary(
        {
            "success": ["Required"],
            "skipped": ["Optional"],
            "failed": ["Broken"],
        }
    )
    command._show_next_steps()
    output = command.stdout.getvalue()
    assert "Database Status" in output
    assert "[EXECUTE] Required" in output
    assert "[SKIP] Optional" in output
    assert "Success (1)" in output
    assert "Skipped (1)" in output
    assert "Failed (1)" in output
    assert "Recommended Next Steps" in output


def test_mcp_seed_helpers_normalize_create_and_missing_source_paths(monkeypatch) -> None:
    """MCP seeds repair invalid factors and report idempotent create decisions."""
    command = McpBootstrapCommand(stdout=StringIO())
    saved: list[tuple[list[str], dict[str, float]]] = []
    invalid = SimpleNamespace(
        name="invalid",
        factor_weights={"momentum": -2.0, "value": 1.0},
        is_active=False,
        save=lambda update_fields: saved.append((update_fields, invalid.factor_weights)),
    )

    class _Factors:
        def all(self) -> list[object]:
            return [invalid, SimpleNamespace(name="empty", factor_weights={})]

        def update_or_create(self, **kwargs: object) -> tuple[object, bool]:
            return object(), True

    module = "apps.account.management.commands.bootstrap_mcp_cold_start"
    monkeypatch.setattr(
        f"{module}.FactorPortfolioConfigModel",
        SimpleNamespace(_default_manager=_Factors()),
    )
    assert command._repair_factor_configs() == 1
    assert sum(invalid.factor_weights.values()) == 1.0
    assert saved[0][0] == ["factor_weights", "is_active", "updated_at"]
    assert command._ensure_factor_cold_start_config() == 1

    class _Stocks:
        def __init__(self) -> None:
            self.calls = 0

        def get_or_create(self, **kwargs: object) -> tuple[object, bool]:
            self.calls += 1
            return object(), self.calls % 2 == 1

    stocks = _Stocks()
    monkeypatch.setattr(
        f"{module}.StockInfoModel",
        SimpleNamespace(_default_manager=stocks),
    )
    assert command._ensure_stock_universe() == 5

    class _RotationQuery:
        def __init__(self, exists: bool = False, first: object | None = None) -> None:
            self._exists = exists
            self._first = first

        def exists(self) -> bool:
            return self._exists

        def first(self) -> object | None:
            return self._first

    source = SimpleNamespace(
        description="source",
        strategy_type="momentum",
        asset_universe=["equity"],
        params={"lookback": 20},
        rebalance_frequency="monthly",
        min_weight=0,
        max_weight=1,
        max_turnover=0.5,
        lookback_period=20,
        regime_allocations={},
        momentum_periods=[20],
        top_n=5,
    )
    created: list[dict[str, object]] = []

    class _Rotations:
        def filter(self, **kwargs: object) -> _RotationQuery:
            if kwargs["name"] == "动量轮动策略":
                return _RotationQuery(first=source)
            return _RotationQuery(exists=False)

        def create(self, **kwargs: object) -> object:
            created.append(kwargs)
            return object()

    monkeypatch.setattr(
        f"{module}.RotationConfigModel",
        SimpleNamespace(_default_manager=_Rotations()),
    )
    assert command._ensure_rotation_aliases() == 1
    assert created[0]["name"] == "动量轮动配置"


def test_mcp_macro_seed_handles_absent_and_present_source(monkeypatch) -> None:
    """Macro smoke rows are only synthesized from an available canonical source."""
    command = McpBootstrapCommand(stdout=StringIO())
    module = "apps.account.management.commands.bootstrap_mcp_cold_start"

    class _QuerySet:
        def __init__(self, rows: list[object]) -> None:
            self.rows = rows

        def exists(self) -> bool:
            return False

        def order_by(self, *args: object) -> _QuerySet:
            return self

        def __getitem__(self, key: slice) -> list[object]:
            return self.rows[key]

    class _MacroManager:
        def __init__(self, rows: list[object]) -> None:
            self.rows = rows
            self.created = 0

        def filter(self, **kwargs: object) -> _QuerySet:
            if kwargs["indicator_code"] == "CN_PMI":
                return _QuerySet(self.rows)
            return _QuerySet([])

        def get_or_create(self, **kwargs: object) -> tuple[object, bool]:
            self.created += 1
            return object(), True

    empty = _MacroManager([])
    monkeypatch.setattr(
        f"{module}.MacroFactModel",
        SimpleNamespace(_default_manager=empty),
    )
    assert command._ensure_macro_smoke_indicator() == 0

    row = SimpleNamespace(
        reporting_period=__import__("datetime").date(2026, 6, 30),
        revision_number=0,
        value=50.2,
        unit="index",
        published_at=None,
        quality="verified",
        extra={"original_unit": "index"},
    )
    populated = _MacroManager([row])
    monkeypatch.setattr(
        f"{module}.MacroFactModel",
        SimpleNamespace(_default_manager=populated),
    )
    assert command._ensure_macro_smoke_indicator() == 1
    assert populated.created == 1
