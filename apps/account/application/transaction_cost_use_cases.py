"""Application use cases for estimating and analyzing transaction costs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import cast

from django.utils import timezone

from apps.account.application.repository_provider import (
    get_asset_metadata_repository,
    get_transaction_cost_config_repository,
    get_transaction_cost_repository,
)
from apps.account.domain.transaction_cost_calculations import complete_actual_cost
from apps.account.domain.transaction_cost_contracts import (
    AssetMetadataLookupProtocol,
    AssetMetadataRecord,
    HighCostTransaction,
    TransactionCostConfigRecord,
    TransactionCostConfigRepositoryProtocol,
    TransactionCostRecord,
    TransactionCostRepositoryProtocol,
)
from core.exceptions import AuthorizationError, InvalidInputError

ZERO = Decimal("0")
CENT = Decimal("0.01")
MAX_ACTUAL_FEE = Decimal("99999999.99")


def normalize_actual_fee(value: Decimal | None, *, field_name: str) -> Decimal | None:
    """Validate and quantize one optional actual fee to the stored scale."""

    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite() or value < ZERO:
        raise InvalidInputError("实际费用必须为非负有限金额", details={"field": field_name})
    try:
        normalized = value.quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise InvalidInputError("实际费用超出允许范围", details={"field": field_name}) from exc
    if normalized > MAX_ACTUAL_FEE:
        raise InvalidInputError("实际费用超出允许范围", details={"field": field_name})
    return normalized


@dataclass(frozen=True)
class TransactionCostEstimate:
    """Transaction-cost estimate returned before trade execution."""

    market: str
    asset_class: str
    trade_value: Decimal
    is_buy: bool
    commission: Decimal
    slippage: Decimal
    stamp_duty: Decimal
    transfer_fee: Decimal
    total_cost: Decimal
    cost_ratio: float
    exceeds_threshold: bool
    warning_message: str


@dataclass(frozen=True)
class TransactionCostAnalysis:
    """Aggregate comparison of actual and estimated transaction costs."""

    total_transactions: int
    total_traded_value: Decimal
    total_actual_cost: Decimal | None
    actual_sample_count: int
    paired_actual_cost: Decimal | None
    paired_sample_count: int
    total_estimated_cost: Decimal | None
    cost_variance: Decimal | None
    cost_variance_pct: float | None
    estimation_accuracy: float | None
    accuracy_sample_count: int
    avg_cost_ratio: float | None
    cost_ratio_sample_count: int
    high_cost_transactions: list[HighCostTransaction]


@dataclass(frozen=True)
class _TransactionCostBreakdown:
    """Strongly typed intermediate result for one cost calculation."""

    commission: Decimal
    slippage: Decimal
    stamp_duty: Decimal
    transfer_fee: Decimal
    total_cost: Decimal
    cost_ratio: float


class TransactionCostEstimationUseCase:
    """Estimate transaction costs before trade execution."""

    def __init__(
        self,
        asset_meta_repo: AssetMetadataLookupProtocol | None = None,
        transaction_cost_config_repo: TransactionCostConfigRepositoryProtocol | None = None,
    ) -> None:
        self.asset_meta_repo = asset_meta_repo or get_asset_metadata_repository()
        self.transaction_cost_config_repo = (
            transaction_cost_config_repo or get_transaction_cost_config_repository()
        )

    def estimate_transaction_cost(
        self,
        asset_code: str,
        shares: float,
        price: Decimal,
        action: str,
        user_id: int,
    ) -> TransactionCostEstimate:
        """Estimate costs for a buy or sell transaction."""

        if action not in {"buy", "sell"}:
            raise ValueError(f"不支持的交易方向: {action}")

        notional = Decimal(str(shares)) * price
        asset_meta = self.asset_meta_repo.get_asset_by_code(asset_code)
        if asset_meta is None:
            market = "CN_A_SHARE"
            asset_class = "equity"
        else:
            market = self._infer_market(asset_meta)
            asset_class = asset_meta["asset_class"]

        cost_config = self._get_cost_config(market, asset_class)
        is_buy = action == "buy"
        cost_detail = self._calculate_total_cost(cost_config, notional, is_buy)

        threshold = cost_config["cost_warning_threshold"]
        exceeds_threshold = cost_detail.cost_ratio > threshold
        warning_message = ""
        if exceeds_threshold:
            warning_message = (
                f"⚠️ 交易成本过高：{cost_detail.cost_ratio:.2%} " f"（超过阈值 {threshold:.2%}）"
            )
            if notional < Decimal("1000"):
                warning_message += "，建议：小额交易可考虑合并以降低成本"

        return TransactionCostEstimate(
            market=market,
            asset_class=asset_class,
            trade_value=notional,
            is_buy=is_buy,
            commission=cost_detail.commission,
            slippage=cost_detail.slippage,
            stamp_duty=cost_detail.stamp_duty,
            transfer_fee=cost_detail.transfer_fee,
            total_cost=cost_detail.total_cost,
            cost_ratio=cost_detail.cost_ratio,
            exceeds_threshold=exceeds_threshold,
            warning_message=warning_message,
        )

    @staticmethod
    def _infer_market(asset_meta: AssetMetadataRecord) -> str:
        """Infer the trading market from normalized asset metadata."""

        code = asset_meta["asset_code"].upper()
        if "SH" in code or "SZ" in code:
            return "CN_A_SHARE"
        if "HK" in code:
            return "CN_HK_STOCK"
        if "US" in code:
            return "US_STOCK"
        return "CN_A_SHARE"

    def _get_cost_config(self, market: str, asset_class: str) -> TransactionCostConfigRecord:
        """Return the active explicit configuration or fail closed."""

        configured = self.transaction_cost_config_repo.get_cost_config(market, asset_class)
        if configured is None:
            raise ValueError(f"未配置启用的交易成本费率: {market}/{asset_class}")
        return configured

    @staticmethod
    def _calculate_total_cost(
        config: TransactionCostConfigRecord,
        notional: Decimal,
        is_buy: bool,
    ) -> _TransactionCostBreakdown:
        """Calculate a strongly typed cost breakdown from normalized config."""

        commission = max(notional * config["commission_rate"], config["min_commission"])
        slippage = notional * config["slippage_rate"]
        stamp_duty = ZERO if is_buy else notional * config["stamp_duty_rate"]
        transfer_fee = notional * config["transfer_fee_rate"]
        total_cost = commission + slippage + stamp_duty + transfer_fee
        cost_ratio = float(total_cost / notional) if notional > ZERO else 0.0
        return _TransactionCostBreakdown(
            commission=commission,
            slippage=slippage,
            stamp_duty=stamp_duty,
            transfer_fee=transfer_fee,
            total_cost=total_cost,
            cost_ratio=cost_ratio,
        )


class RecordTransactionCostUseCase:
    """Record actual transaction costs after execution."""

    def __init__(self, transaction_repo: TransactionCostRepositoryProtocol | None = None) -> None:
        self.transaction_repo = transaction_repo or get_transaction_cost_repository()

    def record_actual_cost(
        self,
        actor_user_id: int,
        transaction_id: int,
        *,
        actual_commission: Decimal | None = None,
        actual_slippage: Decimal | None = None,
        actual_stamp_duty: Decimal | None = None,
        actual_transfer_fee: Decimal | None = None,
    ) -> TransactionCostRecord:
        """Persist actual costs and return the refreshed transaction record."""
        if (
            isinstance(actor_user_id, bool)
            or not isinstance(actor_user_id, int)
            or actor_user_id <= 0
        ):
            raise InvalidInputError("用户编号必须为正整数", details={"field": "actor_user_id"})
        if (
            isinstance(transaction_id, bool)
            or not isinstance(transaction_id, int)
            or transaction_id <= 0
        ):
            raise InvalidInputError("交易记录编号必须为正整数", details={"field": "transaction_id"})
        patch = (
            actual_commission,
            actual_slippage,
            actual_stamp_duty,
            actual_transfer_fee,
        )
        if all(value is None for value in patch):
            raise InvalidInputError("至少需要提交一项实际费用")
        normalized_patch = (
            normalize_actual_fee(actual_commission, field_name="commission"),
            normalize_actual_fee(actual_slippage, field_name="slippage"),
            normalize_actual_fee(actual_stamp_duty, field_name="stamp_duty"),
            normalize_actual_fee(actual_transfer_fee, field_name="transfer_fee"),
        )
        transaction = self.transaction_repo.update_transaction_costs(
            transaction_id,
            actor_user_id=actor_user_id,
            commission=normalized_patch[0],
            slippage=normalized_patch[1],
            stamp_duty=normalized_patch[2],
            transfer_fee=normalized_patch[3],
        )
        if transaction is None:
            raise AuthorizationError("交易记录不存在或无权修改")
        return transaction


class TransactionCostAnalysisUseCase:
    """Analyze historical actual and estimated transaction costs."""

    def __init__(self, transaction_repo: TransactionCostRepositoryProtocol | None = None) -> None:
        self.transaction_repo = transaction_repo or get_transaction_cost_repository()

    def analyze_user_transaction_costs(
        self,
        user_id: int,
        portfolio_id: int | None = None,
        days: int = 90,
    ) -> TransactionCostAnalysis:
        """Analyze transaction costs for a user and optional portfolio."""

        as_of = timezone.now()
        since_date = as_of - timedelta(days=days)
        transactions = self.transaction_repo.list_user_transaction_costs(
            user_id,
            portfolio_id=portfolio_id,
            since_date=since_date,
            until_date=as_of,
        )
        if not transactions:
            return self._empty_analysis()

        total_traded_value = sum((transaction["notional"] for transaction in transactions), ZERO)
        actual_transactions = [
            (transaction, self._actual_cost(transaction)) for transaction in transactions
        ]
        complete_actual = [
            (transaction, actual)
            for transaction, actual in actual_transactions
            if actual is not None
        ]
        actual_sample_count = len(complete_actual)
        total_actual_cost = (
            sum((actual for _, actual in complete_actual if actual is not None), ZERO)
            if complete_actual
            else None
        )

        paired = [
            (transaction, actual)
            for transaction, actual in complete_actual
            if transaction["estimated_cost"] is not None
        ]
        paired_sample_count = len(paired)
        paired_actual_cost = (
            sum((actual for _, actual in paired if actual is not None), ZERO) if paired else None
        )
        total_estimated_cost = (
            sum(
                (cast(Decimal, transaction["estimated_cost"]) for transaction, _ in paired),
                ZERO,
            )
            if paired
            else None
        )
        cost_variance = (
            paired_actual_cost - total_estimated_cost
            if paired_actual_cost is not None and total_estimated_cost is not None
            else None
        )
        cost_variance_pct = (
            float(cost_variance / total_estimated_cost)
            if cost_variance is not None
            and total_estimated_cost is not None
            and total_estimated_cost > ZERO
            else None
        )

        accuracy_pairs = [
            (transaction, actual)
            for transaction, actual in paired
            if transaction["estimated_cost"] is not None
            and transaction["estimated_cost"] > ZERO
            and actual is not None
        ]
        accuracy_sample_count = len(accuracy_pairs)
        accurate_count = sum(
            1
            for transaction, actual in accuracy_pairs
            if actual is not None
            and transaction["estimated_cost"] is not None
            and abs((actual - transaction["estimated_cost"]) / transaction["estimated_cost"])
            < Decimal("0.2")
        )
        estimation_accuracy = (
            accurate_count / accuracy_sample_count if accuracy_sample_count else None
        )

        positive_notional_transactions = [
            (transaction, actual)
            for transaction, actual in complete_actual
            if transaction["notional"] > ZERO and actual is not None
        ]
        cost_ratio_sample_count = len(positive_notional_transactions)
        avg_cost_ratio = (
            sum(
                (
                    float(actual / transaction["notional"])
                    for transaction, actual in positive_notional_transactions
                    if actual is not None
                ),
                0.0,
            )
            / cost_ratio_sample_count
            if cost_ratio_sample_count
            else None
        )

        high_cost_transactions: list[HighCostTransaction] = []
        for transaction, actual in positive_notional_transactions:
            if actual is None:
                continue
            cost_ratio = float(actual / transaction["notional"])
            if cost_ratio > 0.01:
                high_cost_transactions.append(
                    {
                        "id": transaction["id"],
                        "asset_code": transaction["asset_code"],
                        "action": transaction["action"],
                        "notional": float(transaction["notional"]),
                        "cost_ratio": cost_ratio,
                        "traded_at": transaction["traded_at"],
                    }
                )

        return TransactionCostAnalysis(
            total_transactions=len(transactions),
            total_traded_value=total_traded_value,
            total_actual_cost=total_actual_cost,
            actual_sample_count=actual_sample_count,
            paired_actual_cost=paired_actual_cost,
            paired_sample_count=paired_sample_count,
            total_estimated_cost=total_estimated_cost,
            cost_variance=cost_variance,
            cost_variance_pct=cost_variance_pct,
            estimation_accuracy=estimation_accuracy,
            accuracy_sample_count=accuracy_sample_count,
            avg_cost_ratio=avg_cost_ratio,
            cost_ratio_sample_count=cost_ratio_sample_count,
            high_cost_transactions=high_cost_transactions,
        )

    @staticmethod
    def _actual_cost(transaction: TransactionCostRecord) -> Decimal | None:
        """Return actual cost only when all four components are explicitly known."""
        return complete_actual_cost(transaction)

    @staticmethod
    def _empty_analysis() -> TransactionCostAnalysis:
        """Return the zero-value analysis for an empty transaction set."""

        return TransactionCostAnalysis(
            total_transactions=0,
            total_traded_value=ZERO,
            total_actual_cost=None,
            actual_sample_count=0,
            paired_actual_cost=None,
            paired_sample_count=0,
            total_estimated_cost=None,
            cost_variance=None,
            cost_variance_pct=None,
            estimation_accuracy=None,
            accuracy_sample_count=0,
            avg_cost_ratio=None,
            cost_ratio_sample_count=0,
            high_cost_transactions=[],
        )
