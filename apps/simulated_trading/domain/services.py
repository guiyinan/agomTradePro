"""
模拟盘领域服务

Domain层:
- 封装不依赖 Django 的持仓成本算法
- 统一买入成本和持仓成本摊销逻辑
"""
from decimal import Decimal


def _to_decimal(value: float | int | str | Decimal) -> Decimal:
    """统一 Decimal 转换，避免二进制浮点误差。"""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class PositionCostBasisService:
    """持仓成本服务。"""

    @staticmethod
    def calculate_lot_cost(
        quantity: int,
        price: float,
        commission: float,
        slippage: float,
    ) -> tuple[float, float]:
        """
        计算单笔买入的总成本与摊薄成本价。

        Returns:
            (avg_cost, total_cost)
        """
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        gross_amount = _to_decimal(quantity) * _to_decimal(price)
        total_cost = gross_amount + _to_decimal(commission) + _to_decimal(slippage)
        avg_cost = total_cost / _to_decimal(quantity)
        return float(avg_cost), float(total_cost)

    @staticmethod
    def merge_position_cost(
        existing_quantity: int,
        existing_total_cost: float,
        added_quantity: int,
        added_total_cost: float,
    ) -> tuple[float, float]:
        """
        合并现有持仓和新增买入批次的成本。

        Returns:
            (avg_cost, total_cost)
        """
        new_quantity = existing_quantity + added_quantity
        if new_quantity <= 0:
            raise ValueError("merged quantity must be positive")

        new_total_cost = _to_decimal(existing_total_cost) + _to_decimal(added_total_cost)
        new_avg_cost = new_total_cost / _to_decimal(new_quantity)
        return float(new_avg_cost), float(new_total_cost)
