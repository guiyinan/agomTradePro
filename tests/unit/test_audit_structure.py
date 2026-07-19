"""Structure contracts for the split audit large files.

Covers three remediations:
- apps.audit.domain.services          -> 4 pure-Python owner modules + facade
- apps.audit.infrastructure.repositories -> 4 mixin owner modules + facade
- apps.audit.application.use_cases    -> 3 owner modules + facade
"""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

from apps.audit.application import use_cases
from apps.audit.domain import services
from apps.audit.infrastructure import repositories

REPO_ROOT = Path(__file__).resolve().parents[2]

DOMAIN_FACADE = "apps.audit.domain.services"
DOMAIN_OWNERS = (
    "apps.audit.domain.attribution_services",
    "apps.audit.domain.brinson_services",
    "apps.audit.domain.performance_services",
    "apps.audit.domain.operation_log_services",
)
REPOSITORY_FACADE = "apps.audit.infrastructure.repositories"
REPOSITORY_OWNERS = (
    "apps.audit.infrastructure.attribution_repositories",
    "apps.audit.infrastructure.indicator_repositories",
    "apps.audit.infrastructure.validation_repositories",
    "apps.audit.infrastructure.operation_log_repositories",
)
USE_CASE_FACADE = "apps.audit.application.use_cases"
USE_CASE_OWNERS = (
    "apps.audit.application.attribution_use_cases",
    "apps.audit.application.indicator_use_cases",
    "apps.audit.application.operation_log_use_cases",
)

# Names that stayed importable from the legacy domain services module even
# though they are defined in entities.py or are private helpers.
DOMAIN_ENTITY_RE_EXPORTS = (
    "AttributionConfig",
    "AttributionResult",
    "BrinsonAttributionResult",
    "IndicatorPerformanceReport",
    "IndicatorThresholdConfig",
    "LossSource",
    "OperationLog",
    "PeriodPerformance",
    "RecommendedAction",
    "RegimePeriod",
    "RegimeSnapshot",
    "SignalEvent",
)
DOMAIN_PRIVATE_HELPERS = (
    "_build_period_attributions",
    "_build_regime_periods",
    "_calculate_average_return",
    "_calculate_average_weight",
    "_calculate_period_performances",
    "_calculate_total_transaction_cost",
    "_calculate_weighted_return",
    "_generate_brinson_period_breakdown",
    "_generate_lessons",
    "_heuristic_pnl_decomposition",
    "_identify_loss_source",
)

REPOSITORY_MIXINS = (
    "AttributionRepositoryMixin",
    "IndicatorRepositoryMixin",
    "ValidationRepositoryMixin",
    "OperationLogRepositoryMixin",
)
REPOSITORY_LEGACY_METHODS = (
    # attribution reports
    "get_database_health",
    "save_attribution_report",
    "save_loss_analysis",
    "save_experience_summary",
    "get_attribution_report",
    "list_attribution_report_records",
    "count_attribution_reports",
    "get_reported_backtest_ids",
    "get_attribution_report_record",
    "get_reports_by_backtest",
    "get_reports_by_date_range",
    "get_loss_analyses",
    "get_loss_analysis_records",
    "get_experience_summaries",
    "get_experience_summary_records",
    "_serialize_report",
    # indicator performance and threshold configs
    "get_indicator_performance",
    "get_latest_indicator_performance",
    "get_latest_indicator_performance_detail",
    "get_active_threshold_configs",
    "get_threshold_config_by_indicator",
    "save_indicator_performance_record",
    "get_indicator_performance_reports",
    "get_indicator_performance_records_by_period",
    "get_recent_indicator_performance_records",
    "get_macro_indicator_values",
    "get_regime_log_values",
    "get_active_threshold_configs_by_codes",
    "count_active_threshold_configs",
    "get_performance_reports_by_date_range",
    "update_threshold_config_weight",
    "update_threshold_config_levels",
    "get_indicator_performance_by_date_range",
    # validation summaries
    "get_validation_summary",
    "get_recent_validations",
    "save_validation_summary_record",
    "get_validation_summary_by_id",
    "get_validation_summary_record_by_id",
    "get_latest_validation_summary_model",
    "get_latest_validation_summary_record",
    "create_validation_summary_record",
    "update_validation_summary_status",
    "get_validation_summary_by_run_id",
    # operation logs and decision traces
    "count_operation_logs",
    "save_operation_log",
    "query_operation_logs",
    "get_operation_log_by_id",
    "get_operation_stats",
    "cleanup_old_operation_logs",
    "list_decision_traces",
    "get_decision_trace",
    "_build_decision_trace_summary",
    "_build_step_summary",
)

FORBIDDEN_DOMAIN_IMPORT_ROOTS = {"django", "pandas", "numpy", "requests"}


def _imports_module(source: str, module_name: str) -> bool:
    """Return whether source imports one exact module (absolute or relative)."""
    short_name = module_name.rsplit(".", 1)[-1]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(alias.name == module_name for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == module_name:
                return True
            if node.level and (node.module or "") == short_name:
                return True
            if node.level and node.module is None:
                if any(alias.name == short_name for alias in node.names):
                    return True
    return False


def _imported_roots(source: str) -> set[str]:
    """Collect top-level roots of every absolute import in source."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _non_empty_lines(module_name: str) -> int:
    relative_path = Path(*module_name.split(".")).with_suffix(".py")
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    return sum(bool(line.strip()) for line in source.splitlines())


def test_audit_domain_legacy_exports_resolve_to_owner_modules() -> None:
    """Keep moved domain services available from the established module path."""
    owner_exports: set[str] = set()
    for module_name in DOMAIN_OWNERS:
        owner_module = import_module(module_name)
        exports = set(owner_module.__all__)
        owner_exports.update(exports)
        for export_name in exports:
            assert getattr(services, export_name) is getattr(owner_module, export_name)

    assert owner_exports <= set(services.__all__)
    for entity_name in DOMAIN_ENTITY_RE_EXPORTS:
        assert entity_name in services.__all__
        assert getattr(services, entity_name) is not None
    for helper_name in DOMAIN_PRIVATE_HELPERS:
        assert callable(getattr(services, helper_name))


def test_audit_domain_services_stay_pure_python() -> None:
    """Domain facade and owners must not import django/pandas/numpy/requests."""
    for module_name in (DOMAIN_FACADE, *DOMAIN_OWNERS):
        relative_path = Path(*module_name.split(".")).with_suffix(".py")
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        offending = _imported_roots(source) & FORBIDDEN_DOMAIN_IMPORT_ROOTS
        assert not offending, f"{relative_path} imports forbidden roots: {offending}"


def test_audit_repository_composition_and_legacy_method_surface() -> None:
    """Keep the legacy repository class path, composition, and method surface."""
    assert set(repositories.__all__) == {"DjangoAuditRepository"}
    for module_name in REPOSITORY_OWNERS:
        owner_module = import_module(module_name)
        assert len(owner_module.__all__) == 1
        mixin = getattr(owner_module, owner_module.__all__[0])
        assert issubclass(repositories.DjangoAuditRepository, mixin)
    assert [mixin.__name__ for mixin in repositories.DjangoAuditRepository.__mro__[1:5]] == [
        "AttributionRepositoryMixin",
        "IndicatorRepositoryMixin",
        "ValidationRepositoryMixin",
        "OperationLogRepositoryMixin",
    ]
    for method_name in REPOSITORY_LEGACY_METHODS:
        assert callable(
            getattr(repositories.DjangoAuditRepository, method_name, None)
        ), f"DjangoAuditRepository lost legacy method {method_name}"


def test_audit_use_case_legacy_exports_resolve_to_owner_modules() -> None:
    """Keep moved use cases available from the established module path."""
    owner_exports: set[str] = set()
    for module_name in USE_CASE_OWNERS:
        owner_module = import_module(module_name)
        exports = set(owner_module.__all__)
        owner_exports.update(exports)
        for export_name in exports:
            assert getattr(use_cases, export_name) is getattr(owner_module, export_name)

    assert owner_exports == set(use_cases.__all__)
    assert "RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS" in use_cases.__all__


def test_audit_split_modules_stay_bounded_and_one_way() -> None:
    """Prevent owner modules from regrowing or importing their facades."""
    budgets = {
        DOMAIN_FACADE: 150,
        "apps.audit.domain.attribution_services": 450,
        "apps.audit.domain.brinson_services": 300,
        "apps.audit.domain.performance_services": 650,
        "apps.audit.domain.operation_log_services": 300,
        REPOSITORY_FACADE: 150,
        "apps.audit.infrastructure.attribution_repositories": 300,
        "apps.audit.infrastructure.indicator_repositories": 600,
        "apps.audit.infrastructure.validation_repositories": 350,
        "apps.audit.infrastructure.operation_log_repositories": 600,
        USE_CASE_FACADE: 150,
        "apps.audit.application.attribution_use_cases": 650,
        "apps.audit.application.indicator_use_cases": 600,
        "apps.audit.application.operation_log_use_cases": 600,
    }
    facades = {DOMAIN_FACADE, REPOSITORY_FACADE, USE_CASE_FACADE}
    facade_by_owner = {
        **dict.fromkeys(DOMAIN_OWNERS, DOMAIN_FACADE),
        **dict.fromkeys(REPOSITORY_OWNERS, REPOSITORY_FACADE),
        **dict.fromkeys(USE_CASE_OWNERS, USE_CASE_FACADE),
    }
    for module_name, budget in budgets.items():
        relative_path = Path(*module_name.split(".")).with_suffix(".py")
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        non_empty_lines = sum(bool(line.strip()) for line in source.splitlines())
        assert (
            non_empty_lines <= budget
        ), f"{relative_path} has {non_empty_lines} non-empty lines; budget is {budget}"
        if module_name not in facades:
            facade = facade_by_owner[module_name]
            assert not _imports_module(
                source, facade
            ), f"{relative_path} must not import the compatibility facade {facade}"
