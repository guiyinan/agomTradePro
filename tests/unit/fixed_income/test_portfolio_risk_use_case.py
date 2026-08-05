"""Application tests for fixed-income portfolio risk evidence collection."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.fixed_income.application.portfolio_risk import (
    AssessFixedIncomePortfolioRisk,
    AssessFixedIncomePortfolioRiskCommand,
)
from apps.fixed_income.domain.portfolio_risk import (
    FixedIncomeRiskBudgetPolicy,
    PortfolioRiskBlockerCode,
    PortfolioRiskInputBundle,
    PortfolioRiskStatus,
)
from tests.unit.fixed_income.test_portfolio_risk import _bundle, _policy

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


class _BundleProvider:
    def __init__(self, bundle: PortfolioRiskInputBundle | None) -> None:
        self._bundle = bundle

    def get_bundle(
        self,
        bundle_id: str,
        *,
        evaluated_at: datetime,
    ) -> PortfolioRiskInputBundle | None:
        assert bundle_id == "fixed-income-risk-bundle-1"
        assert evaluated_at == NOW
        return self._bundle


class _PolicyProvider:
    def __init__(self, policy: FixedIncomeRiskBudgetPolicy | None) -> None:
        self._policy = policy

    def get_policy(
        self,
        policy_version: str,
        *,
        evaluated_at: datetime,
    ) -> FixedIncomeRiskBudgetPolicy | None:
        assert policy_version == "r5-risk-budget-v1"
        assert evaluated_at == NOW
        return self._policy


def _command() -> AssessFixedIncomePortfolioRiskCommand:
    return AssessFixedIncomePortfolioRiskCommand(
        bundle_id="fixed-income-risk-bundle-1",
        budget_policy_version="r5-risk-budget-v1",
        evaluated_at=NOW,
    )


def test_application_assesses_only_canonical_provider_inputs() -> None:
    report = AssessFixedIncomePortfolioRisk(
        bundle_provider=_BundleProvider(_bundle()),
        policy_provider=_PolicyProvider(_policy()),
    ).execute(_command())

    assert report.status is PortfolioRiskStatus.AVAILABLE
    assert report.blockers == ()
    assert report.research_only is True
    assert report.must_not_use_for_decision is True
    assert report.must_not_execute is True


def test_missing_bundle_fails_closed_without_default_inputs() -> None:
    report = AssessFixedIncomePortfolioRisk(
        bundle_provider=_BundleProvider(None),
        policy_provider=_PolicyProvider(_policy()),
    ).execute(_command())

    assert report.status is PortfolioRiskStatus.BLOCKED
    assert tuple(item.code for item in report.blockers) == (
        PortfolioRiskBlockerCode.CANONICAL_BUNDLE_MISSING,
    )
    assert report.totals is None
    assert report.input_hash is None


def test_missing_policy_fails_closed_without_default_thresholds() -> None:
    report = AssessFixedIncomePortfolioRisk(
        bundle_provider=_BundleProvider(_bundle()),
        policy_provider=_PolicyProvider(None),
    ).execute(_command())

    assert report.status is PortfolioRiskStatus.BLOCKED
    assert tuple(item.code for item in report.blockers) == (
        PortfolioRiskBlockerCode.BUDGET_POLICY_MISSING,
    )
    assert report.totals is None


def test_command_requires_aware_time_and_non_blank_versions() -> None:
    try:
        AssessFixedIncomePortfolioRiskCommand(
            bundle_id="",
            budget_policy_version="r5-risk-budget-v1",
            evaluated_at=NOW,
        )
    except ValueError as exc:
        assert "bundle_id" in str(exc)
    else:
        raise AssertionError("blank bundle_id must be rejected")

    try:
        AssessFixedIncomePortfolioRiskCommand(
            bundle_id="fixed-income-risk-bundle-1",
            budget_policy_version="r5-risk-budget-v1",
            evaluated_at=datetime(2026, 8, 5, 12),
        )
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive evaluated_at must be rejected")
