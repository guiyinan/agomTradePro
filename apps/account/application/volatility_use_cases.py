"""Application orchestration for account volatility controls."""

import hashlib
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, TypedDict, cast

from apps.account.application.repository_provider import (
    get_account_position_repository,
    get_account_repository,
    get_portfolio_repository,
    get_portfolio_snapshot_repository,
)
from apps.account.domain.interfaces import (
    AccountRepositoryProtocol,
    PortfolioRepositoryProtocol,
    PortfolioSnapshotRepositoryProtocol,
    PositionRepositoryProtocol,
    VolatilityReductionInstruction,
    VolatilityReductionItem,
    VolatilitySettings,
)
from apps.account.domain.services import (
    VolatilityAdjustmentResult,
    VolatilityCalculator,
    VolatilityMetrics,
    VolatilitySeriesPoint,
    VolatilityTargetService,
)


@dataclass(frozen=True)
class VolatilityAnalysisOutput:
    """Volatility analysis output for one portfolio."""

    portfolio_id: int
    current_volatility_30d: float
    current_volatility_60d: float
    current_volatility_90d: float
    target_volatility: float
    adjustment_result: VolatilityAdjustmentResult
    volatility_history: list[VolatilityMetrics]
    as_of_date: date | None


class VolatilityAdjustmentOutput(TypedDict, total=False):
    """Public result returned by the volatility adjustment use case."""

    status: Literal["no_action", "executed", "already_executed"]
    message: str
    current_volatility: float
    target_volatility: float
    position_multiplier: float
    reduced_positions: list[VolatilityReductionItem]
    idempotency_key: str


class VolatilityAnalysisUseCase:
    """Analyze portfolio volatility and assess whether exposure must be reduced."""

    def __init__(
        self,
        portfolio_repo: PortfolioRepositoryProtocol | None = None,
        account_repo: AccountRepositoryProtocol | None = None,
        snapshot_repo: PortfolioSnapshotRepositoryProtocol | None = None,
    ) -> None:
        self.portfolio_repo = portfolio_repo or cast(
            PortfolioRepositoryProtocol,
            get_portfolio_repository(),
        )
        self.account_repo = account_repo or cast(
            AccountRepositoryProtocol,
            get_account_repository(),
        )
        self.snapshot_repo = snapshot_repo or cast(
            PortfolioSnapshotRepositoryProtocol,
            get_portfolio_snapshot_repository(),
        )

    def analyze_portfolio_volatility(
        self,
        portfolio_id: int,
        user_id: int,
    ) -> VolatilityAnalysisOutput:
        """Analyze historical snapshots after verifying portfolio ownership."""

        if not self.portfolio_repo.user_owns_portfolio(portfolio_id, user_id):
            raise ValueError(f"投资组合 {portfolio_id} 不存在或无权限")

        profile = self.account_repo.get_volatility_settings(user_id)
        target_volatility = profile["target_volatility"] if profile else 0.15
        tolerance = profile["volatility_tolerance"] if profile else 0.2
        max_reduction = profile["max_volatility_reduction"] if profile else 0.5

        snapshots = self.snapshot_repo.get_snapshots_for_volatility(
            portfolio_id=portfolio_id,
            days=90,
        )
        snapshot_data: list[VolatilitySeriesPoint] = []
        for snapshot in snapshots:
            total_value = float(snapshot["total_value"])
            if not math.isfinite(total_value) or total_value <= 0:
                raise ValueError("投资组合快照总值必须是大于0的有限数")
            snapshot_data.append(
                {
                    "date": snapshot["snapshot_date"],
                    "total_value": total_value,
                }
            )

        vol_30d = self._calculate_volatility_for_window(snapshot_data, 30)
        vol_60d = self._calculate_volatility_for_window(snapshot_data, 60)
        vol_90d = self._calculate_volatility_for_window(snapshot_data, 90)
        adjustment_result = VolatilityTargetService.assess_volatility_adjustment(
            current_volatility=vol_30d,
            target_volatility=target_volatility,
            tolerance=tolerance,
            max_reduction=max_reduction,
        )

        return VolatilityAnalysisOutput(
            portfolio_id=portfolio_id,
            current_volatility_30d=vol_30d,
            current_volatility_60d=vol_60d,
            current_volatility_90d=vol_90d,
            target_volatility=target_volatility,
            adjustment_result=adjustment_result,
            volatility_history=VolatilityCalculator.calculate_portfolio_volatility(
                daily_snapshots=snapshot_data,
                window_days=30,
            ),
            as_of_date=snapshots[-1]["snapshot_date"] if snapshots else None,
        )

    @staticmethod
    def _calculate_volatility_for_window(
        snapshots: list[VolatilitySeriesPoint],
        window_days: int,
    ) -> float:
        """Calculate annualized volatility for a trailing window."""

        if len(snapshots) < 2:
            return 0.0
        returns = [
            (snapshots[index]["total_value"] - snapshots[index - 1]["total_value"])
            / snapshots[index - 1]["total_value"]
            for index in range(1, len(snapshots))
        ]
        if len(returns) < 2:
            return 0.0
        metrics = VolatilityCalculator.calculate_volatility(
            returns=returns[-window_days:],
            window_days=window_days,
            annualize=True,
        )
        return metrics.annualized_volatility


class VolatilityAdjustmentUseCase:
    """Execute an assessed portfolio reduction as one idempotent transaction."""

    def __init__(
        self,
        position_repo: PositionRepositoryProtocol | None = None,
        analysis_use_case: VolatilityAnalysisUseCase | None = None,
    ) -> None:
        self.position_repo = position_repo or cast(
            PositionRepositoryProtocol,
            get_account_position_repository(),
        )
        self.analysis_use_case = analysis_use_case or VolatilityAnalysisUseCase()

    def execute_volatility_adjustment(
        self,
        portfolio_id: int,
        user_id: int,
    ) -> VolatilityAdjustmentOutput:
        """Analyze and, when required, atomically reduce every open position."""

        analysis = self.analysis_use_case.analyze_portfolio_volatility(
            portfolio_id=portfolio_id,
            user_id=user_id,
        )
        adjustment = analysis.adjustment_result
        if not adjustment.should_reduce:
            return {
                "status": "no_action",
                "message": "波动率正常，无需调整",
                "current_volatility": adjustment.current_volatility,
                "target_volatility": adjustment.target_volatility,
            }

        multiplier = adjustment.suggested_position_multiplier
        if not math.isfinite(multiplier) or not 0 <= multiplier < 1:
            raise ValueError(f"无效的波动率仓位乘数: {multiplier}")

        positions = self.position_repo.list_open_positions_for_adjustment(portfolio_id)
        instructions: list[VolatilityReductionInstruction] = []
        for position in positions:
            shares_to_reduce = position["shares"] * (1 - multiplier)
            price = (
                position["current_price"]
                if position["current_price"] is not None
                else position["avg_cost"]
            )
            if (
                not math.isfinite(position["shares"])
                or position["shares"] <= 0
                or not math.isfinite(shares_to_reduce)
                or shares_to_reduce <= 0
                or not price.is_finite()
                or price <= Decimal("0")
            ):
                raise ValueError(f"持仓 {position['asset_code']} 的数量或价格无效")
            instructions.append(
                {
                    "position_id": position["id"],
                    "asset_code": position["asset_code"],
                    "shares": shares_to_reduce,
                    "price": price,
                }
            )

        if not instructions:
            return {
                "status": "no_action",
                "message": "无可调整持仓",
                "current_volatility": adjustment.current_volatility,
                "target_volatility": adjustment.target_volatility,
            }

        idempotency_key = self._build_idempotency_key(
            portfolio_id=portfolio_id,
            as_of_date=analysis.as_of_date,
            adjustment=adjustment,
        )
        batch = self.position_repo.execute_volatility_reduction(
            portfolio_id=portfolio_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
            reason=adjustment.reduction_reason,
            instructions=instructions,
        )
        return {
            "status": batch["status"],
            "message": (
                "该波动率调整批次已执行"
                if batch["status"] == "already_executed"
                else adjustment.reduction_reason
            ),
            "current_volatility": adjustment.current_volatility,
            "target_volatility": adjustment.target_volatility,
            "position_multiplier": multiplier,
            "reduced_positions": batch["reduced_positions"],
            "idempotency_key": idempotency_key,
        }

    @staticmethod
    def _build_idempotency_key(
        *,
        portfolio_id: int,
        as_of_date: date | None,
        adjustment: VolatilityAdjustmentResult,
    ) -> str:
        """Build a stable key for one portfolio analysis snapshot."""

        payload = "|".join(
            (
                str(portfolio_id),
                as_of_date.isoformat() if as_of_date else "no-snapshot",
                adjustment.current_volatility.hex(),
                adjustment.target_volatility.hex(),
                adjustment.suggested_position_multiplier.hex(),
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class UpdateTargetVolatilityUseCase:
    """Update validated volatility-control settings for one user."""

    def __init__(self, account_repo: AccountRepositoryProtocol | None = None) -> None:
        self.account_repo = account_repo or cast(
            AccountRepositoryProtocol,
            get_account_repository(),
        )

    def execute(
        self,
        user_id: int,
        target_volatility: float | None = None,
        volatility_tolerance: float | None = None,
        max_volatility_reduction: float | None = None,
    ) -> VolatilitySettings:
        """Validate and persist supplied volatility settings."""

        if target_volatility is not None and (
            not math.isfinite(target_volatility) or target_volatility <= 0
        ):
            raise ValueError("target_volatility 必须是大于0的有限数")
        if volatility_tolerance is not None and (
            not math.isfinite(volatility_tolerance) or volatility_tolerance < 0
        ):
            raise ValueError("volatility_tolerance 必须是非负有限数")
        if max_volatility_reduction is not None and (
            not math.isfinite(max_volatility_reduction) or not 0 <= max_volatility_reduction <= 1
        ):
            raise ValueError("max_volatility_reduction 必须在 0 到 1 之间")

        profile = self.account_repo.update_volatility_settings(
            user_id,
            target_volatility=target_volatility,
            volatility_tolerance=volatility_tolerance,
            max_volatility_reduction=max_volatility_reduction,
        )
        if profile is None:
            raise ValueError(f"用户 {user_id} 账户配置不存在")
        return profile
