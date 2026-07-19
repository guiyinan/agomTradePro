"""Structural contracts for the Decision Rhythm repository split."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from apps.decision_rhythm.infrastructure import repositories

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_repository_split_preserves_exports_dependencies_and_size_budgets() -> None:
    """Keep the compatibility facade thin and owner modules independently bounded."""

    owners = {
        "apps.decision_rhythm.infrastructure.rhythm_repositories": {
            "QuotaRepository": repositories.QuotaRepository,
            "CooldownRepository": repositories.CooldownRepository,
            "DecisionRequestRepository": repositories.DecisionRequestRepository,
        },
        "apps.decision_rhythm.infrastructure.recommendation_repositories": {
            "ValuationSnapshotRepository": repositories.ValuationSnapshotRepository,
            "InvestmentRecommendationRepository": repositories.InvestmentRecommendationRepository,
            "PortfolioTransitionPlanRepository": repositories.PortfolioTransitionPlanRepository,
            "ExecutionApprovalRequestRepository": repositories.ExecutionApprovalRequestRepository,
        },
        "apps.decision_rhythm.infrastructure.unified_repositories": {
            "UnifiedRecommendationRepository": repositories.UnifiedRecommendationRepository,
            "DecisionModelParamConfigRepository": repositories.DecisionModelParamConfigRepository,
        },
    }
    for module_name, exported_symbols in owners.items():
        owner = importlib.import_module(module_name)
        for symbol_name, facade_symbol in exported_symbols.items():
            assert getattr(owner, symbol_name) is facade_symbol
        source = Path(owner.__file__).read_text(encoding="utf-8")
        assert "infrastructure.repositories import" not in source

    budgets = {
        "apps/decision_rhythm/infrastructure/repositories.py": 100,
        "apps/decision_rhythm/infrastructure/rhythm_repositories.py": 600,
        "apps/decision_rhythm/infrastructure/recommendation_repositories.py": 800,
        "apps/decision_rhythm/infrastructure/unified_repositories.py": 700,
    }
    for relative_path, budget in budgets.items():
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        non_empty_lines = sum(bool(line.strip()) for line in source.splitlines())
        assert non_empty_lines <= budget, (
            f"{relative_path} has {non_empty_lines} non-empty lines; budget is {budget}"
        )


DOMAIN_SERVICES_AGGREGATOR = "apps.decision_rhythm.domain.services"
DOMAIN_SERVICES_OWNERS = (
    "apps.decision_rhythm.domain.rhythm_services",
    "apps.decision_rhythm.domain.workflow_services",
    "apps.decision_rhythm.domain.valuation_services",
    "apps.decision_rhythm.domain.unified_services",
)
DOMAIN_BANNED_IMPORT_ROOTS = {"django", "pandas", "numpy", "requests"}


def _imports_module(source: str, module_name: str) -> bool:
    """Return whether source imports one exact module, absolute or relative."""
    leaf = module_name.rsplit(".", 1)[-1]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(alias.name == module_name for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == module_name:
                return True
            if node.level > 0 and node.module == leaf:
                return True
    return False


def _imports_banned_roots(source: str, roots: set[str]) -> list[str]:
    """Return banned top-level import roots found in source."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append(node.module.split(".")[0])
    return sorted({name for name in found if name in roots})


def test_domain_services_split_preserves_exports_dependencies_and_size_budgets() -> None:
    """Keep the domain services facade thin and owner modules bounded and pure."""

    from apps.decision_rhythm.domain import services

    owners = {
        "apps.decision_rhythm.domain.rhythm_services": {
            "QuotaCheckResult": services.QuotaCheckResult,
            "CooldownCheckResult": services.CooldownCheckResult,
            "QuotaManager": services.QuotaManager,
            "CooldownManager": services.CooldownManager,
            "RhythmManager": services.RhythmManager,
            "DecisionScheduler": services.DecisionScheduler,
            "submit_decision_request": services.submit_decision_request,
            "check_quota_status": services.check_quota_status,
            "check_cooldown_status": services.check_cooldown_status,
        },
        "apps.decision_rhythm.domain.workflow_services": {
            "PrecheckResult": services.PrecheckResult,
            "ExecutionResult": services.ExecutionResult,
            "ExecutionStatusStateMachine": services.ExecutionStatusStateMachine,
            "CandidateStatusStateMachine": services.CandidateStatusStateMachine,
            "ApprovalStatusStateMachine": services.ApprovalStatusStateMachine,
        },
        "apps.decision_rhythm.domain.valuation_services": {
            "ValuationSnapshotService": services.ValuationSnapshotService,
            "RecommendationConsolidationService": services.RecommendationConsolidationService,
            "ExecutionApprovalService": services.ExecutionApprovalService,
        },
        "apps.decision_rhythm.domain.unified_services": {
            "DEFAULT_MODEL_PARAMS": services.DEFAULT_MODEL_PARAMS,
            "ModelWeights": services.ModelWeights,
            "GatePenalties": services.GatePenalties,
            "CompositeScoreCalculator": services.CompositeScoreCalculator,
            "RecommendationAggregator": services.RecommendationAggregator,
            "ConflictPair": services.ConflictPair,
        },
    }
    assert set(owners) == set(DOMAIN_SERVICES_OWNERS)

    owner_exports: set[str] = set()
    for module_name, exported_symbols in owners.items():
        owner = importlib.import_module(module_name)
        assert set(exported_symbols) == set(owner.__all__)
        owner_exports.update(owner.__all__)
        for symbol_name, facade_symbol in exported_symbols.items():
            assert getattr(owner, symbol_name) is facade_symbol
    assert owner_exports == set(services.__all__)

    budgets = {
        DOMAIN_SERVICES_AGGREGATOR: 150,
        "apps.decision_rhythm.domain.rhythm_services": 700,
        "apps.decision_rhythm.domain.workflow_services": 400,
        "apps.decision_rhythm.domain.valuation_services": 700,
        "apps.decision_rhythm.domain.unified_services": 500,
    }
    for module_name, budget in budgets.items():
        relative_path = Path(*module_name.split(".")).with_suffix(".py")
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        non_empty_lines = sum(bool(line.strip()) for line in source.splitlines())
        assert non_empty_lines <= budget, (
            f"{relative_path} has {non_empty_lines} non-empty lines; budget is {budget}"
        )
        if module_name != DOMAIN_SERVICES_AGGREGATOR:
            assert not _imports_module(source, DOMAIN_SERVICES_AGGREGATOR), (
                f"{relative_path} must not import the compatibility facade"
            )
        banned = _imports_banned_roots(source, DOMAIN_BANNED_IMPORT_ROOTS)
        assert not banned, f"{relative_path} must stay pure Python; banned imports: {banned}"
