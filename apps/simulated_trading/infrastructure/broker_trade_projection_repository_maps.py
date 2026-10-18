"""Position provenance and fact-mirror helpers for broker projection."""

from __future__ import annotations

from decimal import ROUND_HALF_UP
from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction

from apps.simulated_trading.application.broker_trade_projection import (
    BrokerActualFact,
    BrokerPositionExpectation,
    BrokerTradeProjectionResult,
)
from apps.simulated_trading.infrastructure.broker_trade_projection_repository_utils import (
    _PRICE_QUANTUM,
    _ZERO,
    _decimal,
    _money,
    _quantity,
    _required_decimal,
)

if TYPE_CHECKING:
    from apps.simulated_trading.infrastructure.models import (
        LedgerMigrationMapModel,
        PositionModel,
        SimulatedAccountModel,
        SimulatedTradeModel,
    )


class BrokerTradeProjectionMappingMixin:
    """Validate provenance and construct source-linked ledger mirror rows."""

    @staticmethod
    def _fact_fee_amounts_known(fact: BrokerActualFact) -> bool:
        """Return whether all four source fee amounts were explicitly recorded."""
        return all(
            (
                fact.commission_known,
                fact.slippage_known,
                fact.stamp_duty_known,
                fact.transfer_fee_known,
            )
        )

    @staticmethod
    def _fact_basis_cost_known(fact: BrokerActualFact) -> bool:
        """Require all included fees and zero slippage in the preserved basis subtotal.

        The existing broker projection subtotal excludes slippage. Keep its numeric formula
        unchanged and report a partial basis when slippage is missing or nonzero.
        """
        return (
            fact.commission_known
            and fact.stamp_duty_known
            and fact.transfer_fee_known
            and fact.slippage_known
            and fact.slippage == _ZERO
        )

    @staticmethod
    def _blocked(reason_code: str) -> BrokerTradeProjectionResult:
        """Build a typed, non-mutating projection blocker."""

        return BrokerTradeProjectionResult(
            applied=False,
            already_applied=False,
            account_id=None,
            unified_position_id=None,
            simulated_trade_id=None,
            total_shares=None,
            average_cost=None,
            reference_mark=None,
            available_quantity_known=None,
            fully_closed=False,
            reason_code=reason_code,
        )

    def bind_legacy_position_source(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        source_position_id: int,
        unified_position_id: int,
    ) -> bool:
        """Bind one new legacy-facing position to its exact unified row."""

        from apps.simulated_trading.infrastructure.models import (
            LedgerMigrationMapModel,
            PositionModel,
            SimulatedAccountModel,
        )

        with transaction.atomic():
            account_maps = list(
                LedgerMigrationMapModel._default_manager.select_for_update()
                .filter(
                    source_app="account",
                    source_table="portfolio",
                    source_id=portfolio_id,
                    target_table="simulated_account",
                )
                .order_by("pk")
            )
            if len(account_maps) != 1:
                return False
            account_map = account_maps[0]
            account = (
                SimulatedAccountModel._default_manager.select_for_update()
                .filter(
                    pk=account_map.target_id,
                    user_id=owner_user_id,
                    account_type="real",
                )
                .first()
            )
            position = (
                PositionModel._default_manager.select_for_update()
                .filter(
                    pk=unified_position_id,
                    account_id=account.pk if account is not None else None,
                )
                .first()
            )
            if account is None or position is None:
                return False
            source_maps = list(
                LedgerMigrationMapModel._default_manager.select_for_update()
                .filter(
                    source_app="account",
                    source_table="position",
                    source_id=source_position_id,
                )
                .order_by("pk")
            )
            if source_maps:
                if not (
                    len(source_maps) == 1
                    and source_maps[0].target_table == "simulated_position"
                    and source_maps[0].target_id == unified_position_id
                    and not source_maps[0].notes.startswith("broker_fact_projection_retired:")
                ):
                    return False
                reverse_maps = list(
                    LedgerMigrationMapModel._default_manager.select_for_update()
                    .filter(target_table="simulated_position", target_id=unified_position_id)
                    .order_by("pk")
                )
                return len(reverse_maps) == 1 and reverse_maps[0].pk == source_maps[0].pk
            reverse_maps = list(
                LedgerMigrationMapModel._default_manager.select_for_update()
                .filter(target_table="simulated_position", target_id=unified_position_id)
                .order_by("pk")
            )
            if reverse_maps:
                return False
            try:
                with transaction.atomic():
                    LedgerMigrationMapModel._default_manager.create(
                        source_app="account",
                        source_table="position",
                        source_id=source_position_id,
                        target_table="simulated_position",
                        target_id=unified_position_id,
                        notes="broker_fact_projection_position_map",
                    )
            except IntegrityError:
                source_maps = list(
                    LedgerMigrationMapModel._default_manager.filter(
                        source_app="account",
                        source_table="position",
                        source_id=source_position_id,
                    )
                )
                if not (
                    len(source_maps) == 1
                    and source_maps[0].target_table == "simulated_position"
                    and source_maps[0].target_id == unified_position_id
                ):
                    return False
                reverse_maps = list(
                    LedgerMigrationMapModel._default_manager.filter(
                        target_table="simulated_position", target_id=unified_position_id
                    )
                )
                return len(reverse_maps) == 1 and reverse_maps[0].pk == source_maps[0].pk
            return True

    @staticmethod
    def _expectation_matches(
        position: PositionModel | None,
        expectation: BrokerPositionExpectation,
    ) -> bool:
        """Compare locked position fields to the previously shown CAS snapshot."""

        if position is None:
            return (
                expectation.unified_position_id is None
                and expectation.total_shares is None
                and expectation.average_cost is None
                and expectation.reference_mark is None
                and expectation.valuation_known is None
                and expectation.available_quantity is None
                and expectation.available_quantity_known is None
            )
        return (
            expectation.unified_position_id == position.pk
            and expectation.total_shares == _required_decimal(position.quantity)
            and expectation.average_cost == _required_decimal(position.avg_cost)
            and expectation.valuation_known is bool(position.valuation_known)
            and (
                expectation.reference_mark == _required_decimal(position.current_price)
                if position.valuation_known
                else expectation.reference_mark is None
            )
            and expectation.available_quantity == _required_decimal(position.available_quantity)
            and expectation.available_quantity_known is bool(position.available_quantity_known)
        )

    @staticmethod
    def _trade_matches(trade: SimulatedTradeModel, fact: BrokerActualFact) -> bool:
        """Check all mirror economics before treating a source map as idempotent."""

        quantity = _quantity(fact.shares)
        price = fact.price.quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP)
        expected_notional = _money(quantity * price)
        return (
            trade.asset_code == fact.asset_code
            and trade.asset_type == fact.asset_type
            and trade.action == fact.action
            and _required_decimal(trade.quantity) == quantity
            and _required_decimal(trade.price) == price
            and _money(fact.notional) == expected_notional
            and _required_decimal(trade.amount) == expected_notional
            and trade.execution_time == fact.traded_at
        )

    @staticmethod
    def _trade_fee_notes_match(
        notes: str,
        trade: SimulatedTradeModel,
        fact: BrokerActualFact,
    ) -> bool:
        """Verify exact fee knownness separately from the Sim mirror's zero placeholders."""

        expected_flags = {
            "commission_known": fact.commission_known,
            "slippage_known": fact.slippage_known,
            "stamp_duty_known": fact.stamp_duty_known,
            "transfer_fee_known": fact.transfer_fee_known,
        }
        recorded_flags: dict[str, str] = {}
        for segment in notes.split(";"):
            key, separator, value = segment.strip().partition("=")
            if separator:
                recorded_flags[key] = value
        if any(recorded_flags.get(key) != str(value) for key, value in expected_flags.items()):
            return False
        if "fee_amounts_known" in recorded_flags:
            if recorded_flags["fee_amounts_known"] != str(
                BrokerTradeProjectionMappingMixin._fact_fee_amounts_known(fact)
            ) or trade.fee_amounts_known is not BrokerTradeProjectionMappingMixin._fact_fee_amounts_known(
                fact
            ):
                return False
            if recorded_flags.get("cost_basis_known") != str(trade.cost_basis_known):
                return False
        elif trade.fee_amounts_known is not None or trade.cost_basis_known is not None:
            # Existing source maps predate these flags; retain them as unknown on replay.
            return False

        expected_commission = _money(fact.commission if fact.commission_known else _ZERO)
        expected_transfer_fee = _money(fact.transfer_fee) if fact.transfer_fee_known else None
        expected_stamp_duty = _money(fact.stamp_duty) if fact.stamp_duty_known else None
        expected_slippage = _money(fact.slippage if fact.slippage_known else _ZERO)
        known_fees = (
            (fact.commission if fact.commission_known else _ZERO)
            + (fact.transfer_fee if fact.transfer_fee_known else _ZERO)
            + (fact.stamp_duty if fact.stamp_duty_known else _ZERO)
        )
        expected_total_cost = _money(_money(fact.notional) + known_fees)
        return (
            _required_decimal(trade.commission) == expected_commission
            and _decimal(trade.transfer_fee) == expected_transfer_fee
            and _decimal(trade.stamp_duty) == expected_stamp_duty
            and _required_decimal(trade.slippage) == expected_slippage
            and _required_decimal(trade.total_cost) == expected_total_cost
        )

    @staticmethod
    def _position_map_can_bind(
        *,
        LedgerMigrationMapModel: type[LedgerMigrationMapModel],
        source_position_id: int | None,
        existing_position_id: int | None,
    ) -> bool:
        """Check both source and reverse provenance before changing a position."""

        if source_position_id is None:
            if existing_position_id is None:
                return True
            reverse_rows = list(
                LedgerMigrationMapModel._default_manager.select_for_update()
                .filter(
                    target_table="simulated_position",
                    target_id=existing_position_id,
                )
                .order_by("pk")
            )
            return not reverse_rows

        source_rows = list(
            LedgerMigrationMapModel._default_manager.select_for_update()
            .filter(
                source_app="account",
                source_table="position",
                source_id=source_position_id,
            )
            .order_by("pk")
        )
        if len(source_rows) > 1:
            return False
        if source_rows:
            source_row = source_rows[0]
            if not (
                source_row.target_table == "simulated_position"
                and existing_position_id is not None
                and source_row.target_id == existing_position_id
                and not source_row.notes.startswith("broker_fact_projection_retired:")
            ):
                return False
            reverse_rows = list(
                LedgerMigrationMapModel._default_manager.select_for_update()
                .filter(target_table="simulated_position", target_id=existing_position_id)
                .order_by("pk")
            )
            return len(reverse_rows) == 1 and reverse_rows[0].pk == source_row.pk
        if existing_position_id is None:
            return True
        reverse_rows = list(
            LedgerMigrationMapModel._default_manager.select_for_update()
            .filter(
                target_table="simulated_position",
                target_id=existing_position_id,
            )
            .order_by("pk")
        )
        return not reverse_rows

    @staticmethod
    def _create_trade(
        *,
        SimulatedTradeModel: type[SimulatedTradeModel],
        account: SimulatedAccountModel,
        fact: BrokerActualFact,
        cost_basis_known: bool | None,
    ) -> SimulatedTradeModel:
        """Create a mirror without claiming unverified historical realized PnL."""

        known_fees = (
            (fact.commission if fact.commission_known else _ZERO)
            + (fact.stamp_duty if fact.stamp_duty_known else _ZERO)
            + (fact.transfer_fee if fact.transfer_fee_known else _ZERO)
        )
        amount = _money(fact.notional)
        total_cost = _money(amount + known_fees)
        trade = SimulatedTradeModel._default_manager.create(
            account=account,
            asset_code=fact.asset_code,
            asset_name=fact.asset_name,
            asset_type=fact.asset_type,
            action=fact.action,
            quantity=_quantity(fact.shares),
            price=fact.price.quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP),
            amount=amount,
            commission=_money(fact.commission if fact.commission_known else _ZERO),
            transfer_fee=_money(fact.transfer_fee) if fact.transfer_fee_known else None,
            stamp_duty=_money(fact.stamp_duty) if fact.stamp_duty_known else None,
            slippage=_money(fact.slippage if fact.slippage_known else _ZERO),
            total_cost=total_cost,
            fee_amounts_known=BrokerTradeProjectionMappingMixin._fact_fee_amounts_known(fact),
            cost_basis_known=cost_basis_known,
            realized_pnl=None,
            realized_pnl_pct=None,
            reason="券商实际成交事实镜像；费用完整性见来源映射备注",
            order_date=fact.traded_at.date(),
            execution_date=fact.traded_at.date(),
            execution_time=fact.traded_at,
            status="executed",
            # Settlement binding/idempotency fields intentionally remain unset.
        )
        return trade

    @staticmethod
    def _ensure_position_map(
        *,
        LedgerMigrationMapModel: type[LedgerMigrationMapModel],
        source_position_id: int,
        unified_position_id: int,
    ) -> bool:
        """Retain or create the exact legacy-to-unified position provenance."""

        rows = list(
            LedgerMigrationMapModel._default_manager.select_for_update()
            .filter(
                source_app="account",
                source_table="position",
                source_id=source_position_id,
            )
            .order_by("pk")
        )
        if not rows:
            try:
                with transaction.atomic():
                    created = LedgerMigrationMapModel._default_manager.create(
                        source_app="account",
                        source_table="position",
                        source_id=source_position_id,
                        target_table="simulated_position",
                        target_id=unified_position_id,
                        notes="broker_fact_projection_position_map",
                    )
            except IntegrityError:
                return False
            reverse_rows = list(
                LedgerMigrationMapModel._default_manager.select_for_update()
                .filter(target_table="simulated_position", target_id=unified_position_id)
                .order_by("pk")
            )
            return len(reverse_rows) == 1 and reverse_rows[0].pk == created.pk
        if len(rows) != 1:
            return False
        row = rows[0]
        return (
            row.target_table == "simulated_position"
            and row.target_id == unified_position_id
            and not row.notes.startswith("broker_fact_projection_retired:")
        )

    @staticmethod
    def _retire_position_map(
        *,
        LedgerMigrationMapModel: type[LedgerMigrationMapModel],
        source_position_id: int | None,
        unified_position_id: int,
    ) -> None:
        """Remove a closed position's active mapping; the canonical fact retains its IDs."""

        if source_position_id is None:
            return
        rows = list(
            LedgerMigrationMapModel._default_manager.select_for_update()
            .filter(
                source_app="account",
                source_table="position",
                source_id=source_position_id,
            )
            .order_by("pk")
        )
        if len(rows) != 1:
            return
        row = rows[0]
        if row.target_table == "simulated_position" and row.target_id == unified_position_id:
            row.delete()
