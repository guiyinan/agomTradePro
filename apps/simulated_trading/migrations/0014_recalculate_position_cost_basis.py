from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db import migrations

AVG_COST_QUANT = Decimal("0.0001")
MONEY_QUANT = Decimal("0.01")


def _recalculate_position_cost_basis(apps, schema_editor):
    PositionModel = apps.get_model("simulated_trading", "PositionModel")
    SimulatedTradeModel = apps.get_model("simulated_trading", "SimulatedTradeModel")

    positions = {
        (position.account_id, position.asset_code): position
        for position in PositionModel.objects.all()
    }
    cost_state: dict[tuple[int, str], dict[str, Decimal | int]] = defaultdict(
        lambda: {
            "quantity": 0,
            "total_cost": Decimal("0"),
        }
    )

    trades = SimulatedTradeModel.objects.filter(
        status="executed",
    ).order_by("account_id", "asset_code", "execution_date", "execution_time", "id")

    for trade in trades.iterator():
        key = (trade.account_id, trade.asset_code)
        state = cost_state[key]
        quantity = int(trade.quantity)

        if trade.action == "buy":
            state["quantity"] += quantity
            state["total_cost"] += Decimal(str(trade.total_cost))
            continue

        if trade.action != "sell" or state["quantity"] <= 0:
            continue

        sell_quantity = min(quantity, int(state["quantity"]))
        if sell_quantity <= 0:
            continue

        avg_cost = state["total_cost"] / Decimal(state["quantity"])
        state["total_cost"] -= avg_cost * Decimal(sell_quantity)
        state["quantity"] -= sell_quantity

        if state["quantity"] == 0:
            state["total_cost"] = Decimal("0")

    for key, position in positions.items():
        state = cost_state.get(key)
        if not state:
            continue

        state_quantity = int(state["quantity"])
        if state_quantity <= 0 or state_quantity != position.quantity:
            continue

        raw_total_cost = Decimal(state["total_cost"])
        avg_cost = (raw_total_cost / Decimal(state_quantity)).quantize(
            AVG_COST_QUANT,
            rounding=ROUND_HALF_UP,
        )
        total_cost = raw_total_cost.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        market_value = Decimal(str(position.market_value))
        unrealized_pnl = (market_value - total_cost).quantize(
            MONEY_QUANT,
            rounding=ROUND_HALF_UP,
        )
        unrealized_pnl_pct = (
            float((unrealized_pnl / total_cost) * Decimal("100"))
            if total_cost > 0
            else 0.0
        )

        PositionModel.objects.filter(pk=position.pk).update(
            avg_cost=avg_cost,
            total_cost=total_cost,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("simulated_trading", "0013_assign_default_user_to_accounts"),
    ]

    operations = [
        migrations.RunPython(
            _recalculate_position_cost_basis,
            migrations.RunPython.noop,
        ),
    ]
