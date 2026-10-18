"""Owner-scoped infrastructure for applying actual broker execution facts."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP
from typing import TYPE_CHECKING, cast

from django.db import IntegrityError, transaction

from apps.simulated_trading.application.broker_trade_projection import (
    BrokerPositionMapState,
    BrokerTradeProjectionCommand,
    BrokerTradeProjectionConflict,
    BrokerTradeProjectionRepository,
    BrokerTradeProjectionResult,
    BrokerUnifiedPositionSnapshot,
)
from apps.simulated_trading.infrastructure.broker_trade_projection_repository_maps import (
    BrokerTradeProjectionMappingMixin,
)
from apps.simulated_trading.infrastructure.broker_trade_projection_repository_utils import (
    _PRICE_QUANTUM,
    _ZERO,
    _asset_type_is_supported,
    _fits_decimal_field,
    _money,
    _quantity,
    _required_decimal,
)

if TYPE_CHECKING:
    pass


class DjangoBrokerTradeProjectionRepository(
    BrokerTradeProjectionMappingMixin, BrokerTradeProjectionRepository
):
    """Apply actual broker facts inside Simulated Trading's ledger boundary."""

    def get_existing_real_account_id(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
    ) -> int | None:
        """Return only a unique, exact owner-scoped existing real account."""

        from apps.simulated_trading.infrastructure.models import (
            LedgerMigrationMapModel,
            SimulatedAccountModel,
        )

        mappings = list(
            LedgerMigrationMapModel._default_manager.filter(
                source_app="account",
                source_table="portfolio",
                source_id=portfolio_id,
            ).order_by("pk")
        )
        if len(mappings) != 1:
            return None
        mapping = mappings[0]
        if mapping.target_table != "simulated_account":
            return None
        account = SimulatedAccountModel._default_manager.filter(
            pk=mapping.target_id,
            user_id=owner_user_id,
            account_type="real",
        ).first()
        if account is None:
            return None
        reverse = list(
            LedgerMigrationMapModel._default_manager.filter(
                target_table="simulated_account", target_id=account.pk
            ).order_by("pk")
        )
        if len(reverse) != 1 or reverse[0].pk != mapping.pk:
            return None
        return int(account.pk)

    def capture_position_snapshots(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        portfolio_name: str,
        asset_codes: tuple[str, ...],
        legacy_position_ids: Mapping[str, int | None],
    ) -> tuple[BrokerUnifiedPositionSnapshot, ...]:
        """Read mapped positions without creating accounts or changing balances."""

        from apps.simulated_trading.infrastructure.models import (
            LedgerMigrationMapModel,
            PositionModel,
            SimulatedAccountModel,
        )

        mapping_rows = list(
            LedgerMigrationMapModel._default_manager.filter(
                source_app="account",
                source_table="portfolio",
                source_id=portfolio_id,
            ).order_by("pk")
        )
        account = None
        account_mapping = None
        reason: str | None = None
        if len(mapping_rows) > 1:
            reason = "REAL_ACCOUNT_MAPPING_MISSING_OR_AMBIGUOUS"
        elif mapping_rows:
            account_mapping = mapping_rows[0]
            if account_mapping.target_table != "simulated_account":
                reason = "REAL_ACCOUNT_MAPPING_TARGET_MISMATCH"
            else:
                account = SimulatedAccountModel._default_manager.filter(
                    pk=account_mapping.target_id,
                    user_id=owner_user_id,
                    account_type="real",
                ).first()
                if account is None:
                    reason = "REAL_ACCOUNT_OWNER_OR_TYPE_MISMATCH"
                else:
                    reverse = list(
                        LedgerMigrationMapModel._default_manager.filter(
                            target_table="simulated_account", target_id=account.pk
                        ).order_by("pk")
                    )
                    if len(reverse) != 1 or reverse[0].pk != account_mapping.pk:
                        reason = "REAL_ACCOUNT_REVERSE_MAPPING_AMBIGUOUS"

        snapshots: list[BrokerUnifiedPositionSnapshot] = []
        for asset_code in sorted(set(asset_codes)):
            positions = []
            if account is not None:
                positions = list(
                    PositionModel._default_manager.filter(
                        account_id=account.pk, asset_code=asset_code
                    ).order_by("pk")
                )
            position = positions[0] if len(positions) == 1 else None
            position_reason = reason
            if len(positions) > 1:
                position_reason = "UNIFIED_POSITION_AMBIGUOUS"
            legacy_id = legacy_position_ids.get(asset_code)
            position_maps = []
            if legacy_id is not None:
                position_maps = list(
                    LedgerMigrationMapModel._default_manager.filter(
                        source_app="account",
                        source_table="position",
                        source_id=legacy_id,
                    ).order_by("pk")
                )
            map_state = "missing"
            map_row = position_maps[0] if len(position_maps) == 1 else None
            if position is not None and legacy_id is None:
                reverse_position_maps = list(
                    LedgerMigrationMapModel._default_manager.filter(
                        source_app="account",
                        source_table="position",
                        target_table="simulated_position",
                        target_id=position.pk,
                    ).order_by("pk")
                )
                if len(reverse_position_maps) > 1:
                    map_state = "ambiguous"
                    position_reason = position_reason or "POSITION_REVERSE_MAPPING_AMBIGUOUS"
                elif reverse_position_maps:
                    map_row = reverse_position_maps[0]
                    if map_row.notes.startswith("broker_fact_projection_retired:"):
                        map_state = "mismatch"
                        position_reason = position_reason or "POSITION_MAPPING_RETIRED"
                    else:
                        map_state = "valid"
            if len(position_maps) > 1:
                map_state = "ambiguous"
                position_reason = position_reason or "POSITION_SOURCE_MAPPING_AMBIGUOUS"
            elif map_row is not None:
                if map_row.notes.startswith("broker_fact_projection_retired:"):
                    map_state = "mismatch"
                    position_reason = position_reason or "POSITION_MAPPING_RETIRED"
                elif (
                    map_row.target_table == "simulated_position"
                    and position is not None
                    and map_row.target_id == position.pk
                ):
                    reverse_position_maps = list(
                        LedgerMigrationMapModel._default_manager.filter(
                            target_table="simulated_position", target_id=position.pk
                        ).order_by("pk")
                    )
                    if (
                        len(reverse_position_maps) == 1
                        and reverse_position_maps[0].pk == map_row.pk
                    ):
                        map_state = "valid"
                    else:
                        map_state = "ambiguous"
                        position_reason = position_reason or "POSITION_REVERSE_MAPPING_AMBIGUOUS"
                else:
                    map_state = "mismatch"
                    position_reason = position_reason or "POSITION_MAPPING_TARGET_MISMATCH"
            elif position is not None and legacy_id is not None:
                reverse_position_maps = list(
                    LedgerMigrationMapModel._default_manager.filter(
                        target_table="simulated_position", target_id=position.pk
                    ).order_by("pk")
                )
                if reverse_position_maps:
                    map_state = "mismatch"
                    position_reason = position_reason or "POSITION_SOURCE_MAPPING_MISSING"

            snapshots.append(
                BrokerUnifiedPositionSnapshot(
                    owner_user_id=owner_user_id,
                    portfolio_id=portfolio_id,
                    asset_code=asset_code,
                    account_id=int(account.pk) if account is not None else None,
                    account_mapping_id=(
                        int(account_mapping.pk) if account_mapping is not None else None
                    ),
                    account_mapping_count=len(mapping_rows),
                    unified_position_id=int(position.pk) if position is not None else None,
                    position_map_source_id=(
                        legacy_id
                        if legacy_id is not None
                        else (int(map_row.source_id) if map_row else None)
                    ),
                    position_map_target_id=int(map_row.target_id) if map_row is not None else None,
                    position_map_state=cast(BrokerPositionMapState, map_state),
                    total_shares=(
                        _required_decimal(position.quantity) if position is not None else None
                    ),
                    available_quantity=(
                        _required_decimal(position.available_quantity)
                        if position is not None
                        else None
                    ),
                    available_quantity_known=(
                        bool(position.available_quantity_known) if position is not None else None
                    ),
                    average_cost=(
                        _required_decimal(position.avg_cost) if position is not None else None
                    ),
                    reference_mark=(
                        _required_decimal(position.current_price)
                        if position is not None and position.valuation_known
                        else None
                    ),
                    valuation_known=(
                        bool(position.valuation_known) if position is not None else None
                    ),
                    source_updated_at=position.updated_at if position is not None else None,
                    first_buy_date=position.first_buy_date if position is not None else None,
                    first_buy_date_known=(
                        bool(position.first_buy_date_known) if position is not None else None
                    ),
                    asset_name=position.asset_name if position is not None else portfolio_name,
                    asset_type=position.asset_type if position is not None else None,
                    blocked_reason_code=position_reason,
                )
            )
        return tuple(snapshots)

    def apply_actual_broker_fact(
        self,
        command: BrokerTradeProjectionCommand,
    ) -> BrokerTradeProjectionResult:
        """Apply one actual fact without simulated order or sellability gates."""

        from apps.simulated_trading.infrastructure.models import (
            LedgerMigrationMapModel,
            PositionModel,
            SimulatedAccountModel,
            SimulatedTradeModel,
        )

        with transaction.atomic():
            portfolio_map_rows = list(
                LedgerMigrationMapModel._default_manager.select_for_update()
                .filter(
                    source_app="account",
                    source_table="portfolio",
                    source_id=command.portfolio_id,
                )
                .order_by("pk")
            )
            if len(portfolio_map_rows) > 1:
                return self._blocked("REAL_ACCOUNT_MAPPING_MISSING_OR_AMBIGUOUS")
            portfolio_map = portfolio_map_rows[0] if portfolio_map_rows else None
            account = None
            if portfolio_map is not None:
                account = (
                    SimulatedAccountModel._default_manager.select_for_update()
                    .filter(
                        pk=portfolio_map.target_id,
                        user_id=command.owner_user_id,
                        account_type="real",
                    )
                    .first()
                )
                if account is None or portfolio_map.target_table != "simulated_account":
                    return self._blocked("REAL_ACCOUNT_OWNER_OR_TYPE_MISMATCH")
                reverse_account_maps = list(
                    LedgerMigrationMapModel._default_manager.select_for_update()
                    .filter(target_table="simulated_account", target_id=account.pk)
                    .order_by("pk")
                )
                if len(reverse_account_maps) != 1 or reverse_account_maps[0].pk != portfolio_map.pk:
                    return self._blocked("REAL_ACCOUNT_REVERSE_MAPPING_AMBIGUOUS")
            if not command.portfolio_is_active:
                return self._blocked("REAL_ACCOUNT_INACTIVE")
            expectation = command.expectation
            if command.fact.action not in {"buy", "sell"}:
                return self._blocked("FACT_ACTION_INVALID")
            if command.fact.shares <= _ZERO or command.fact.price <= _ZERO:
                return self._blocked("FACT_QUANTITY_OR_PRICE_INVALID")
            if not _fits_decimal_field(
                command.fact.shares, max_digits=20, decimal_places=6
            ) or not _fits_decimal_field(command.fact.price, max_digits=10, decimal_places=4):
                return self._blocked("FACT_PRICE_OR_QUANTITY_OUT_OF_RANGE")
            if any(
                value < _ZERO
                for value, known in (
                    (command.fact.commission, command.fact.commission_known),
                    (command.fact.slippage, command.fact.slippage_known),
                    (command.fact.stamp_duty, command.fact.stamp_duty_known),
                    (command.fact.transfer_fee, command.fact.transfer_fee_known),
                )
                if known
            ):
                return self._blocked("FACT_FEE_NEGATIVE")
            if any(
                known and not _fits_decimal_field(value, max_digits=10, decimal_places=2)
                for value, known in (
                    (command.fact.commission, command.fact.commission_known),
                    (command.fact.slippage, command.fact.slippage_known),
                    (command.fact.stamp_duty, command.fact.stamp_duty_known),
                    (command.fact.transfer_fee, command.fact.transfer_fee_known),
                )
            ):
                return self._blocked("FACT_FEE_OUT_OF_RANGE")
            expected_notional = _money(
                _quantity(command.fact.shares)
                * command.fact.price.quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP)
            )
            if _money(command.fact.notional) != expected_notional:
                return self._blocked("FACT_NOTIONAL_INCONSISTENT")
            created_account_mapping = False
            if portfolio_map is None:
                if (
                    expectation.account_id is not None
                    or expectation.account_mapping_id is not None
                    or expectation.account_mapping_count != 0
                    or expectation.unified_position_id is not None
                    or command.legacy_position is not None
                    or expectation.position_map_state != "missing"
                    or command.fact.action != "buy"
                ):
                    return self._blocked("BROKER_BALANCE_PREVIEW_CHANGED")
                if not _asset_type_is_supported(command.fact.asset_type):
                    return self._blocked("ASSET_TYPE_UNSUPPORTED")

            transaction_maps = list(
                LedgerMigrationMapModel._default_manager.select_for_update()
                .filter(
                    source_app="account",
                    source_table="transaction",
                    source_id=command.fact.transaction_id,
                )
                .order_by("pk")
            )
            if transaction_maps:
                if account is None:
                    return self._blocked("TRANSACTION_MIRROR_WITHOUT_ACCOUNT_MAPPING")
                if len(transaction_maps) != 1:
                    return self._blocked("TRANSACTION_MIRROR_MAPPING_AMBIGUOUS")
                mapping = transaction_maps[0]
                if mapping.target_table != "simulated_trade":
                    return self._blocked("TRANSACTION_MIRROR_TARGET_MISMATCH")
                trade = SimulatedTradeModel._default_manager.filter(pk=mapping.target_id).first()
                if trade is None or trade.account_id != account.pk:
                    return self._blocked("TRANSACTION_MIRROR_TARGET_MISSING")
                if not self._trade_matches(trade, command.fact):
                    return self._blocked("TRANSACTION_MIRROR_ECONOMICS_MISMATCH")
                if not mapping.notes.startswith("broker_actual_fact;"):
                    return self._blocked("TRANSACTION_MIRROR_PROVENANCE_MISMATCH")
                if not self._trade_fee_notes_match(mapping.notes, trade, command.fact):
                    return self._blocked("TRANSACTION_MIRROR_FEE_KNOWNNESS_MISMATCH")
                position = PositionModel._default_manager.filter(
                    account_id=account.pk, asset_code=command.fact.asset_code
                ).first()
                return BrokerTradeProjectionResult(
                    applied=True,
                    already_applied=True,
                    account_id=int(account.pk),
                    unified_position_id=int(position.pk) if position is not None else None,
                    simulated_trade_id=int(trade.pk),
                    total_shares=(
                        _required_decimal(position.quantity) if position is not None else _ZERO
                    ),
                    average_cost=(
                        _required_decimal(position.avg_cost) if position is not None else None
                    ),
                    reference_mark=(
                        _required_decimal(position.current_price)
                        if position is not None and position.valuation_known
                        else None
                    ),
                    available_quantity_known=(
                        bool(position.available_quantity_known) if position is not None else False
                    ),
                    fully_closed=position is None,
                    reason_code=None,
                )

            if account is None:
                account = SimulatedAccountModel._default_manager.create(
                    user_id=command.owner_user_id,
                    account_name=command.portfolio_name,
                    account_type="real",
                    initial_capital=_ZERO,
                    current_cash=_ZERO,
                    cash_known=False,
                    cash_reconciliation_status="quantity_only",
                    current_market_value=_ZERO,
                    total_value=_ZERO,
                    is_active=command.portfolio_is_active,
                    auto_trading_enabled=False,
                )
                portfolio_map = LedgerMigrationMapModel._default_manager.create(
                    source_app="account",
                    source_table="portfolio",
                    source_id=command.portfolio_id,
                    target_table="simulated_account",
                    target_id=account.pk,
                    notes="broker_fact_projection_real_account",
                )
                created_account_mapping = True
            assert portfolio_map is not None
            if not command.portfolio_is_active or not account.is_active:
                return self._blocked("REAL_ACCOUNT_INACTIVE")
            if not created_account_mapping and (
                expectation.account_id != account.pk
                or expectation.account_mapping_id != portfolio_map.pk
                or expectation.account_mapping_count not in {0, 1}
            ):
                return self._blocked("BROKER_BALANCE_PREVIEW_CHANGED")

            position_rows = list(
                PositionModel._default_manager.select_for_update()
                .filter(account_id=account.pk, asset_code=command.fact.asset_code)
                .order_by("pk")
            )
            if len(position_rows) > 1:
                return self._blocked("UNIFIED_POSITION_AMBIGUOUS")
            position = position_rows[0] if position_rows else None
            if not self._expectation_matches(position, expectation):
                return self._blocked("BROKER_BALANCE_PREVIEW_CHANGED")
            if expectation.position_map_state in {"ambiguous", "mismatch"}:
                return self._blocked("POSITION_MAPPING_AMBIGUOUS_OR_MISMATCH")
            if position is not None and expectation.position_map_state == "missing":
                return self._blocked("POSITION_MAPPING_MISSING")
            if not self._position_map_can_bind(
                LedgerMigrationMapModel=LedgerMigrationMapModel,
                source_position_id=expectation.position_map_source_id,
                existing_position_id=int(position.pk) if position is not None else None,
            ):
                return self._blocked("POSITION_MAPPING_CONFLICT")
            if (
                position is None
                and command.legacy_position is None
                and command.fact.action == "sell"
            ):
                return self._blocked("SELL_POSITION_MISSING")
            if not _asset_type_is_supported(command.fact.asset_type):
                return self._blocked("ASSET_TYPE_UNSUPPORTED")
            possible_existing_trades = SimulatedTradeModel._default_manager.filter(
                account_id=account.pk,
                asset_code=command.fact.asset_code,
                action=command.fact.action,
                quantity=_quantity(command.fact.shares),
                price=command.fact.price.quantize(_PRICE_QUANTUM),
                execution_time=command.fact.traded_at,
            )
            if possible_existing_trades.exists():
                return self._blocked("UNMAPPED_EXISTING_TRADE_REQUIRES_REVIEW")

            current_quantity = (
                _required_decimal(position.quantity) if position is not None else _ZERO
            )
            current_average = (
                _required_decimal(position.avg_cost) if position is not None else _ZERO
            )
            valuation_known = bool(position.valuation_known) if position is not None else False
            current_mark = (
                _required_decimal(position.current_price)
                if position is not None and valuation_known
                else None
            )
            first_buy_date = position.first_buy_date if position is not None else None
            first_buy_date_known = (
                bool(position.first_buy_date_known) if position is not None else True
            )
            available_quantity = (
                _required_decimal(position.available_quantity) if position is not None else _ZERO
            )
            asset_name = position.asset_name if position is not None else command.fact.asset_name

            if position is None and command.legacy_position is not None:
                seed = command.legacy_position
                if seed.source_position_id != expectation.position_map_source_id:
                    return self._blocked("LEGACY_POSITION_ID_CHANGED")
                if seed.asset_code != command.fact.asset_code:
                    return self._blocked("LEGACY_POSITION_ASSET_MISMATCH")
                current_quantity = _quantity(seed.total_shares)
                current_average = seed.average_cost
                current_mark = seed.reference_mark if seed.valuation_known else None
                valuation_known = seed.valuation_known
                first_buy_date = seed.first_buy_date
                first_buy_date_known = False
                available_quantity = _ZERO
                asset_name = seed.asset_name

            if position is not None:
                current_total_cost = _required_decimal(position.total_cost)
                current_cost_basis_known = position.cost_basis_known
            elif command.legacy_position is not None:
                current_total_cost = _money(current_quantity * current_average)
                current_cost_basis_known = None
            else:
                current_total_cost = _ZERO
                current_cost_basis_known = True

            if current_mark is None:
                current_mark = _ZERO
                valuation_known = False
            shares = _quantity(command.fact.shares)
            if shares <= _ZERO:
                return self._blocked("FACT_QUANTITY_INVALID")
            if command.fact.action == "sell":
                if shares > current_quantity:
                    return self._blocked("TOTAL_HOLDINGS_INSUFFICIENT")
                next_quantity = _quantity(current_quantity - shares)
                next_available = min(available_quantity, next_quantity)
                fully_closed = next_quantity == _ZERO
                next_total_cost = (
                    _money(current_total_cost * next_quantity / current_quantity)
                    if next_quantity > _ZERO
                    else _ZERO
                )
                next_cost_basis_known = current_cost_basis_known
            else:
                next_quantity = _quantity(current_quantity + shares)
                known_fees = (
                    (command.fact.commission if command.fact.commission_known else _ZERO)
                    + (command.fact.stamp_duty if command.fact.stamp_duty_known else _ZERO)
                    + (command.fact.transfer_fee if command.fact.transfer_fee_known else _ZERO)
                )
                next_total_cost = _money(
                    current_total_cost + _money(command.fact.notional + known_fees)
                )
                if not self._fact_basis_cost_known(command.fact):
                    next_cost_basis_known = False
                else:
                    next_cost_basis_known = current_cost_basis_known
                next_available = available_quantity
                fully_closed = False
                if first_buy_date is None or command.fact.traded_at.date() < first_buy_date:
                    first_buy_date = command.fact.traded_at.date()

            next_average = (
                (next_total_cost / next_quantity).quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP)
                if next_quantity > _ZERO
                else _ZERO
            )
            if valuation_known:
                next_market_value = _money(next_quantity * current_mark)
                next_unrealized_pnl = _money(next_market_value - next_total_cost)
                next_unrealized_pnl_pct = float(
                    (next_unrealized_pnl / next_total_cost * 100) if next_total_cost else _ZERO
                )
            else:
                next_market_value = _ZERO
                next_unrealized_pnl = _ZERO
                next_unrealized_pnl_pct = 0.0
            if not _fits_decimal_field(next_quantity, max_digits=20, decimal_places=6):
                return self._blocked("POSITION_QUANTITY_OUT_OF_RANGE")
            if not _fits_decimal_field(next_average, max_digits=10, decimal_places=4):
                return self._blocked("POSITION_AVERAGE_COST_OUT_OF_RANGE")
            if not _fits_decimal_field(command.fact.price, max_digits=10, decimal_places=4):
                return self._blocked("FACT_PRICE_OUT_OF_RANGE")
            if not _fits_decimal_field(command.fact.notional, max_digits=15, decimal_places=2):
                return self._blocked("FACT_NOTIONAL_OUT_OF_RANGE")
            if not _fits_decimal_field(next_total_cost, max_digits=15, decimal_places=2):
                return self._blocked("POSITION_COST_OUT_OF_RANGE")

            if position is not None and position.asset_type != command.fact.asset_type:
                return self._blocked("ASSET_TYPE_CHANGED")
            trade = self._create_trade(
                SimulatedTradeModel=SimulatedTradeModel,
                account=account,
                fact=command.fact,
                cost_basis_known=(
                    self._fact_basis_cost_known(command.fact)
                    if command.fact.action == "buy"
                    else current_cost_basis_known
                ),
            )
            if fully_closed:
                if position is not None:
                    position_id = int(position.pk)
                    position.delete()
                    self._retire_position_map(
                        LedgerMigrationMapModel=LedgerMigrationMapModel,
                        source_position_id=expectation.position_map_source_id,
                        unified_position_id=position_id,
                    )
                unified_position_id = None
            else:
                if position is None:
                    position = PositionModel._default_manager.create(
                        account=account,
                        asset_code=command.fact.asset_code,
                        asset_name=asset_name,
                        asset_type=command.fact.asset_type,
                        quantity=next_quantity,
                        available_quantity=next_available,
                        available_quantity_known=False,
                        avg_cost=next_average,
                        total_cost=next_total_cost,
                        cost_basis_known=next_cost_basis_known,
                        current_price=current_mark.quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP),
                        valuation_known=valuation_known,
                        market_value=next_market_value,
                        unrealized_pnl=next_unrealized_pnl,
                        unrealized_pnl_pct=next_unrealized_pnl_pct,
                        first_buy_date=first_buy_date or command.fact.traded_at.date(),
                        first_buy_date_known=first_buy_date_known,
                    )
                else:
                    position.quantity = next_quantity
                    position.available_quantity = next_available
                    position.available_quantity_known = False
                    position.avg_cost = next_average
                    position.total_cost = next_total_cost
                    position.cost_basis_known = next_cost_basis_known
                    # current_price is a local mark; historical fill price never replaces it.
                    position.market_value = next_market_value
                    position.unrealized_pnl = next_unrealized_pnl
                    position.unrealized_pnl_pct = next_unrealized_pnl_pct
                    position.save(
                        update_fields=[
                            "quantity",
                            "available_quantity",
                            "available_quantity_known",
                            "avg_cost",
                            "total_cost",
                            "cost_basis_known",
                            "market_value",
                            "unrealized_pnl",
                            "unrealized_pnl_pct",
                            "last_update_date",
                            "updated_at",
                        ]
                    )
                unified_position_id = int(position.pk)
                if expectation.position_map_source_id is not None:
                    map_result = self._ensure_position_map(
                        LedgerMigrationMapModel=LedgerMigrationMapModel,
                        source_position_id=expectation.position_map_source_id,
                        unified_position_id=unified_position_id,
                    )
                    if not map_result:
                        raise BrokerTradeProjectionConflict("POSITION_MAPPING_CONFLICT")

            try:
                with transaction.atomic():
                    LedgerMigrationMapModel._default_manager.create(
                        source_app="account",
                        source_table="transaction",
                        source_id=command.fact.transaction_id,
                        target_table="simulated_trade",
                        target_id=trade.pk,
                        notes=(
                            "broker_actual_fact; canonical_account_fact=true; "
                            f"commission_known={command.fact.commission_known}; "
                            f"slippage_known={command.fact.slippage_known}; "
                            f"stamp_duty_known={command.fact.stamp_duty_known}; "
                            f"transfer_fee_known={command.fact.transfer_fee_known}; "
                            f"fee_amounts_known={trade.fee_amounts_known}; "
                            f"cost_basis_known={trade.cost_basis_known}"
                        ),
                    )
            except IntegrityError as error:
                raise BrokerTradeProjectionConflict(
                    "TRANSACTION_MIRROR_MAPPING_CONFLICT"
                ) from error
            account.total_trades += 1
            account.last_trade_date = command.fact.traded_at.date()
            account.cash_known = False
            account.cash_reconciliation_status = "quantity_only"
            account.save(
                update_fields=[
                    "cash_known",
                    "cash_reconciliation_status",
                    "total_trades",
                    "last_trade_date",
                    "updated_at",
                ]
            )
            position_after = None
            if unified_position_id is not None:
                position_after = PositionModel._default_manager.filter(
                    pk=unified_position_id
                ).first()
            return BrokerTradeProjectionResult(
                applied=True,
                already_applied=False,
                account_id=int(account.pk),
                unified_position_id=unified_position_id,
                simulated_trade_id=int(trade.pk),
                total_shares=(
                    _required_decimal(position_after.quantity)
                    if position_after is not None
                    else _ZERO
                ),
                average_cost=(
                    _required_decimal(position_after.avg_cost)
                    if position_after is not None
                    else None
                ),
                reference_mark=(
                    _required_decimal(position_after.current_price)
                    if position_after is not None and position_after.valuation_known
                    else None
                ),
                available_quantity_known=False,
                fully_closed=fully_closed,
                reason_code=None,
            )
