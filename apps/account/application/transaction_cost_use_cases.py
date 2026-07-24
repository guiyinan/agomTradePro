"""Application use cases for estimating and analyzing transaction costs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.account.application.repository_provider import (
    get_asset_metadata_repository,
    get_transaction_cost_config_repository,
    get_transaction_cost_repository,
)
from apps.account.domain.transaction_cost_contracts import (
    AssetMetadataLookupProtocol,
    AssetMetadataRecord,
    HighCostTransaction,
    TransactionCostConfigRecord,
    TransactionCostConfigRepositoryProtocol,
    TransactionCostRecord,
    TransactionCostRepositoryProtocol,
)

ZERO = Decimal("0")


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
    total_actual_cost: Decimal
    total_estimated_cost: Decimal
    cost_variance: Decimal
    cost_variance_pct: float
    estimation_accuracy: float
    avg_cost_ratio: float
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
        transaction_id: int,
        actual_commission: Decimal,
        actual_slippage: Decimal | None = None,
        actual_stamp_duty: Decimal | None = None,
        actual_transfer_fee: Decimal | None = None,
    ) -> TransactionCostRecord:
        """Persist actual costs and return the refreshed transaction record."""

        transaction = self.transaction_repo.update_transaction_costs(
            transaction_id,
            commission=actual_commission,
            slippage=actual_slippage,
            stamp_duty=actual_stamp_duty,
            transfer_fee=actual_transfer_fee,
        )
        if transaction is None:
            raise ValueError(f"交易 {transaction_id} 不存在")
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

        since_date = timezone.now() - timedelta(days=days)
        transactions = self.transaction_repo.list_user_transaction_costs(
            user_id,
            portfolio_id=portfolio_id,
            since_date=since_date,
        )
        if not transactions:
            return self._empty_analysis()

        total_traded_value = sum((transaction["notional"] for transaction in transactions), ZERO)
        total_actual_cost = sum(
            (self._actual_cost(transaction) for transaction in transactions), ZERO
        )

        estimated_transactions: list[TransactionCostRecord] = []
        total_estimated_cost = ZERO
        for transaction in transactions:
            estimated_cost = transaction["estimated_cost"]
            if estimated_cost is not None:
                estimated_transactions.append(transaction)
                total_estimated_cost += estimated_cost

        cost_variance = total_actual_cost - total_estimated_cost
        cost_variance_pct = (
            float(cost_variance / total_estimated_cost) if total_estimated_cost > ZERO else 0.0
        )

        accurate_count = sum(
            1
            for transaction in estimated_transactions
            if transaction["cost_variance_pct"] is not None
            and abs(transaction["cost_variance_pct"]) < 0.2
        )
        estimation_accuracy = (
            accurate_count / len(estimated_transactions) if estimated_transactions else 0.0
        )

        positive_notional_transactions = [
            transaction for transaction in transactions if transaction["notional"] > ZERO
        ]
        avg_cost_ratio = (
            sum(
                (
                    float(self._actual_cost(transaction) / transaction["notional"])
                    for transaction in positive_notional_transactions
                ),
                0.0,
            )
            / len(positive_notional_transactions)
            if positive_notional_transactions
            else 0.0
        )

        high_cost_transactions: list[HighCostTransaction] = []
        for transaction in positive_notional_transactions:
            cost_ratio = float(self._actual_cost(transaction) / transaction["notional"])
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
            total_estimated_cost=total_estimated_cost,
            cost_variance=cost_variance,
            cost_variance_pct=cost_variance_pct,
            estimation_accuracy=estimation_accuracy,
            avg_cost_ratio=avg_cost_ratio,
            high_cost_transactions=high_cost_transactions,
        )

    @staticmethod
    def _actual_cost(transaction: TransactionCostRecord) -> Decimal:
        """Return a transaction's complete actual cost."""

        return (
            transaction["commission"]
            + (transaction["slippage"] or ZERO)
            + (transaction["stamp_duty"] or ZERO)
            + (transaction["transfer_fee"] or ZERO)
        )

    @staticmethod
    def _empty_analysis() -> TransactionCostAnalysis:
        """Return the zero-value analysis for an empty transaction set."""

        return TransactionCostAnalysis(
            total_transactions=0,
            total_traded_value=ZERO,
            total_actual_cost=ZERO,
            total_estimated_cost=ZERO,
            cost_variance=ZERO,
            cost_variance_pct=0.0,
            estimation_accuracy=0.0,
            avg_cost_ratio=0.0,
            high_cost_transactions=[],
        )
