"""Structural contracts for the Decision Rhythm repository split."""

from __future__ import annotations

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
