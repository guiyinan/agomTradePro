"""Volatility adjustment application boundary tests."""

from datetime import date
from decimal import Decimal

import pytest

from apps.account.application.volatility_use_cases import (
    UpdateTargetVolatilityUseCase,
    VolatilityAdjustmentUseCase,
    VolatilityAnalysisOutput,
    VolatilityAnalysisUseCase,
)
from apps.account.domain.services import (
    VolatilityAdjustmentResult,
)


class FakeAnalysisUseCase:
    """Return a deterministic reduction assessment."""

    def analyze_portfolio_volatility(
        self,
        portfolio_id: int,
        user_id: int,
    ) -> VolatilityAnalysisOutput:
        return VolatilityAnalysisOutput(
            portfolio_id=portfolio_id,
            current_volatility_30d=0.3,
            current_volatility_60d=0.3,
            current_volatility_90d=0.3,
            target_volatility=0.15,
            adjustment_result=VolatilityAdjustmentResult(
                current_volatility=0.3,
                target_volatility=0.15,
                volatility_ratio=2.0,
                should_reduce=True,
                suggested_position_multiplier=0.5,
                reduction_reason="test reduction",
            ),
            volatility_history=[],
            as_of_date=date(2026, 7, 24),
        )


class FakePositionRepository:
    """Capture the atomic batch call made by the use case."""

    def __init__(self, price: Decimal, status: str = "executed") -> None:
        self.price = price
        self.status = status
        self.calls = []

    def list_open_positions_for_adjustment(self, portfolio_id: int):
        return [
            {
                "id": 7,
                "asset_code": "600000.SH",
                "shares": 100.0,
                "current_price": self.price,
                "avg_cost": Decimal("10"),
            }
        ]

    def execute_volatility_reduction(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": self.status,
            "reduced_positions": (
                []
                if self.status == "already_executed"
                else [{"asset_code": "600000.SH", "shares_reduced": 50.0}]
            ),
        }


class FakePortfolioRepository:
    """Control ownership for analysis boundary tests."""

    def __init__(self, owns: bool = True) -> None:
        self.owns = owns

    def user_owns_portfolio(self, portfolio_id: int, user_id: int) -> bool:
        return self.owns


class FakeAccountRepository:
    """Provide and capture volatility settings."""

    def __init__(self, settings=None, updated=None) -> None:
        self.settings = settings
        self.updated = updated
        self.calls = []

    def get_volatility_settings(self, user_id: int):
        return self.settings

    def update_volatility_settings(self, user_id: int, **kwargs):
        self.calls.append((user_id, kwargs))
        return self.updated


class FakeSnapshotRepository:
    """Return deterministic portfolio snapshots."""

    def __init__(self, snapshots) -> None:
        self.snapshots = snapshots

    def get_snapshots_for_volatility(self, portfolio_id: int, days: int):
        assert days == 90
        return self.snapshots


def test_invalid_execution_price_stops_before_repository_write() -> None:
    repository = FakePositionRepository(Decimal("0"))
    use_case = VolatilityAdjustmentUseCase(
        position_repo=repository,
        analysis_use_case=FakeAnalysisUseCase(),
    )

    with pytest.raises(ValueError, match="数量或价格无效"):
        use_case.execute_volatility_adjustment(portfolio_id=1, user_id=2)

    assert repository.calls == []


def test_repeated_batch_is_reported_without_claiming_reductions() -> None:
    repository = FakePositionRepository(Decimal("12"), status="already_executed")
    use_case = VolatilityAdjustmentUseCase(
        position_repo=repository,
        analysis_use_case=FakeAnalysisUseCase(),
    )

    first_result = use_case.execute_volatility_adjustment(portfolio_id=1, user_id=2)
    second_result = use_case.execute_volatility_adjustment(portfolio_id=1, user_id=2)

    assert first_result["status"] == "already_executed"
    assert first_result["reduced_positions"] == []
    assert repository.calls[0]["idempotency_key"] == repository.calls[1]["idempotency_key"]
    assert second_result["status"] == "already_executed"


def test_analysis_rejects_cross_user_portfolio_before_snapshot_read() -> None:
    """Ownership is checked before any account or snapshot data is consumed."""
    use_case = VolatilityAnalysisUseCase(
        portfolio_repo=FakePortfolioRepository(owns=False),
        account_repo=FakeAccountRepository(),
        snapshot_repo=FakeSnapshotRepository([]),
    )

    with pytest.raises(ValueError, match="不存在或无权限"):
        use_case.analyze_portfolio_volatility(portfolio_id=1, user_id=2)


@pytest.mark.parametrize("invalid_total", [0, -1, float("nan"), float("inf")])
def test_analysis_rejects_non_positive_or_non_finite_snapshot_values(
    invalid_total: float,
) -> None:
    """Corrupt portfolio history cannot enter volatility calculations."""
    use_case = VolatilityAnalysisUseCase(
        portfolio_repo=FakePortfolioRepository(),
        account_repo=FakeAccountRepository(),
        snapshot_repo=FakeSnapshotRepository(
            [
                {
                    "snapshot_date": date(2026, 7, 24),
                    "total_value": invalid_total,
                }
            ]
        ),
    )

    with pytest.raises(ValueError, match="快照总值"):
        use_case.analyze_portfolio_volatility(portfolio_id=1, user_id=2)


def test_analysis_uses_defaults_for_empty_history() -> None:
    """A new portfolio has zero observed volatility and the governed default target."""
    use_case = VolatilityAnalysisUseCase(
        portfolio_repo=FakePortfolioRepository(),
        account_repo=FakeAccountRepository(settings=None),
        snapshot_repo=FakeSnapshotRepository([]),
    )

    output = use_case.analyze_portfolio_volatility(portfolio_id=1, user_id=2)

    assert output.current_volatility_30d == 0.0
    assert output.current_volatility_60d == 0.0
    assert output.current_volatility_90d == 0.0
    assert output.target_volatility == 0.15
    assert output.as_of_date is None
    assert output.adjustment_result.should_reduce is False


class FakeNoActionAnalysisUseCase:
    """Return a deterministic assessment that requires no position mutation."""

    def analyze_portfolio_volatility(
        self,
        portfolio_id: int,
        user_id: int,
    ) -> VolatilityAnalysisOutput:
        return VolatilityAnalysisOutput(
            portfolio_id=portfolio_id,
            current_volatility_30d=0.1,
            current_volatility_60d=0.1,
            current_volatility_90d=0.1,
            target_volatility=0.15,
            adjustment_result=VolatilityAdjustmentResult(
                current_volatility=0.1,
                target_volatility=0.15,
                volatility_ratio=2 / 3,
                should_reduce=False,
                suggested_position_multiplier=1.0,
                reduction_reason="",
            ),
            volatility_history=[],
            as_of_date=date(2026, 7, 24),
        )


def test_adjustment_no_action_does_not_read_or_write_positions() -> None:
    """Normal volatility ends before the repository mutation boundary."""
    repository = FakePositionRepository(Decimal("12"))
    use_case = VolatilityAdjustmentUseCase(
        position_repo=repository,
        analysis_use_case=FakeNoActionAnalysisUseCase(),
    )

    result = use_case.execute_volatility_adjustment(portfolio_id=1, user_id=2)

    assert result["status"] == "no_action"
    assert result["current_volatility"] == 0.1
    assert repository.calls == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"target_volatility": 0}, "target_volatility"),
        ({"target_volatility": float("nan")}, "target_volatility"),
        ({"volatility_tolerance": -0.1}, "volatility_tolerance"),
        ({"volatility_tolerance": float("inf")}, "volatility_tolerance"),
        ({"max_volatility_reduction": -0.1}, "max_volatility_reduction"),
        ({"max_volatility_reduction": 1.1}, "max_volatility_reduction"),
    ],
)
def test_update_settings_rejects_invalid_boundaries(kwargs, message: str) -> None:
    """Invalid risk settings never reach persistence."""
    repository = FakeAccountRepository(updated={})
    use_case = UpdateTargetVolatilityUseCase(account_repo=repository)

    with pytest.raises(ValueError, match=message):
        use_case.execute(user_id=2, **kwargs)

    assert repository.calls == []


def test_update_settings_requires_existing_profile() -> None:
    """A missing account profile is explicit after a valid repository call."""
    repository = FakeAccountRepository(updated=None)
    use_case = UpdateTargetVolatilityUseCase(account_repo=repository)

    with pytest.raises(ValueError, match="账户配置不存在"):
        use_case.execute(user_id=2, target_volatility=0.12)

    assert repository.calls == [
        (
            2,
            {
                "target_volatility": 0.12,
                "volatility_tolerance": None,
                "max_volatility_reduction": None,
            },
        )
    ]
