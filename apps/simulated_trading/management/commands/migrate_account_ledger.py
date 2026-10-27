"""
Management command: migrate_account_ledger

将 apps/account 的旧账本数据迁移至 apps/simulated_trading 统一账本表：
  PortfolioModel     → SimulatedAccountModel (account_type='real')
  account.PositionModel → simulated_trading.PositionModel
  TransactionModel   → SimulatedTradeModel

幂等性保证：
  每条记录迁移前先查 LedgerMigrationMapModel，已存在则跳过。

用法：
  # 模拟运行（只报告，不写入）
  python manage.py migrate_account_ledger --dry-run

  # 实际执行
  python manage.py migrate_account_ledger

  # 只迁移指定用户（测试用）
  python manage.py migrate_account_ledger --user-id=3

⚠️  执行前请先备份数据库。
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, TypedDict

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import Sum

from core.integration.account_ledger import (
    get_account_position_model,
    get_account_transaction_model,
    get_capital_flow_model,
    get_portfolio_model,
)

SIMULATED_TRADE_PRICE_MAX = Decimal("999999.9999")
SIMULATED_TRADE_AMOUNT_MAX = Decimal("9999999999999.99")
SIMULATED_TRADE_QUANTITY_MAX = Decimal("99999999999999.999999")


class MigrationStats(TypedDict):
    """Counters and warnings emitted by one ledger migration run."""

    portfolios_skipped: int
    portfolios_migrated: int
    positions_skipped: int
    positions_migrated: int
    transactions_skipped: int
    transactions_skipped_unknown_costs: int
    transactions_migrated: int
    errors: list[str]


class Command(BaseCommand):
    help = "将 apps/account 账本数据迁移至 simulated_trading 统一账本（幂等）"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="模拟运行，不实际写入数据",
        )
        parser.add_argument(
            "--user-id",
            type=int,
            default=None,
            help="只迁移指定用户（不填则迁移所有用户）",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Validate migration options and orchestrate the requested ledger migration."""
        dry_run = options["dry_run"]
        user_id = options.get("user_id")
        if not isinstance(dry_run, bool):
            raise CommandError("dry_run 必须是布尔值")
        if user_id is not None and (
            isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0
        ):
            raise CommandError("user_id 必须是正整数")

        self.stdout.write(self.style.WARNING("=" * 70))
        self.stdout.write(self.style.WARNING("账本迁移工具  apps/account → simulated_trading"))
        if dry_run:
            self.stdout.write(self.style.WARNING("【模拟运行模式 — 不写入数据库】"))
        self.stdout.write(self.style.WARNING("=" * 70))

        if not dry_run:
            confirm = input("确认已备份数据库？输入 'yes' 继续: ")
            if confirm.strip().lower() != "yes":
                self.stdout.write(self.style.ERROR("已取消"))
                return

        stats: MigrationStats = {
            "portfolios_skipped": 0,
            "portfolios_migrated": 0,
            "positions_skipped": 0,
            "positions_migrated": 0,
            "transactions_skipped": 0,
            "transactions_skipped_unknown_costs": 0,
            "transactions_migrated": 0,
            "errors": [],
        }

        self._migrate_portfolios(user_id, dry_run, stats)
        self._migrate_positions(user_id, dry_run, stats)
        self._migrate_transactions(user_id, dry_run, stats)

        self._print_summary(stats)

    # ── Step 1: PortfolioModel → SimulatedAccountModel ──────────────────

    def _migrate_portfolios(
        self,
        user_id: int | None,
        dry_run: bool,
        stats: MigrationStats,
    ) -> None:
        from apps.simulated_trading.infrastructure.models import (
            LedgerMigrationMapModel,
            SimulatedAccountModel,
        )

        CapitalFlowModel = get_capital_flow_model()
        PortfolioModel = get_portfolio_model()
        qs = PortfolioModel._default_manager.select_related("user")
        if user_id is not None:
            qs = qs.filter(user_id=user_id)

        self.stdout.write(f"\n[1/3] 迁移投资组合 → SimulatedAccountModel ({qs.count()} 条)")

        for portfolio in qs.iterator():
            # Idempotency check
            if LedgerMigrationMapModel._default_manager.filter(
                source_app="account",
                source_table="portfolio",
                source_id=portfolio.id,
            ).exists():
                stats["portfolios_skipped"] += 1
                continue

            # Compute initial_capital from capital flows
            deposit_total = CapitalFlowModel._default_manager.filter(
                portfolio=portfolio,
                flow_type="deposit",
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

            # Compute current totals from positions
            positions_qs = portfolio.positions.filter(is_closed=False)
            market_value_total = sum(float(p.market_value or 0) for p in positions_qs)

            # current_cash approximation: initial capital - invested value
            invested = sum(float(p.shares * float(p.avg_cost)) for p in positions_qs)
            cash = max(float(deposit_total) - invested, 0)
            total_value = cash + market_value_total

            if not dry_run:
                with transaction.atomic():
                    # Always create a dedicated SimulatedAccountModel for each portfolio
                    # (one-to-one mapping required — never reuse another portfolio's account).
                    new_account = SimulatedAccountModel._default_manager.create(
                        user=portfolio.user,
                        account_name=portfolio.name,
                        account_type="real",
                        initial_capital=max(float(deposit_total), 0),
                        current_cash=max(cash, 0),
                        cash_known=False,
                        cash_reconciliation_status="unverified",
                        current_market_value=market_value_total,
                        total_value=max(total_value, 0),
                        is_active=portfolio.is_active,
                        auto_trading_enabled=False,
                    )
                    target_id = new_account.id

                    LedgerMigrationMapModel._default_manager.create(
                        source_app="account",
                        source_table="portfolio",
                        source_id=portfolio.id,
                        target_table="simulated_account",
                        target_id=target_id,
                    )

            stats["portfolios_migrated"] += 1
            label = "[dry-run]" if dry_run else str(target_id)
            self.stdout.write(
                f"  ✓ Portfolio {portfolio.id} ({portfolio.name}) → SimulatedAccount {label}"
            )

    # ── Step 2: account.PositionModel → simulated_trading.PositionModel ─

    def _migrate_positions(
        self,
        user_id: int | None,
        dry_run: bool,
        stats: MigrationStats,
    ) -> None:
        from apps.simulated_trading.domain.execution_settlement_primitives import (
            SimulatedTradeIntentValidationError,
            validate_ledger_price,
        )
        from apps.simulated_trading.infrastructure import models as simulated_models
        from shared.domain.position_calculations import recalculate_derived_fields

        LedgerMigrationMapModel = simulated_models.LedgerMigrationMapModel
        SimPositionModel = simulated_models.PositionModel
        SimulatedAccountModel = simulated_models.SimulatedAccountModel
        AccountPositionModel = get_account_position_model()
        PortfolioModel = get_portfolio_model()
        qs = AccountPositionModel._default_manager.all()
        if user_id is not None:
            qs = qs.filter(portfolio__user_id=user_id)

        self.stdout.write(f"\n[2/3] 迁移持仓 → simulated_trading.PositionModel ({qs.count()} 条)")

        processed_asset_keys: set[tuple[int, str]] = set()
        for iterator_position in qs.iterator():
            source_position_id = iterator_position.pk
            iterator_portfolio_id = iterator_position.portfolio_id
            with transaction.atomic():
                source_portfolio = (
                    PortfolioModel._default_manager.select_for_update()
                    .filter(pk=iterator_portfolio_id)
                    .first()
                )
                if source_portfolio is None:
                    self._record_position_migration_error(
                        stats,
                        source_position_id,
                        "来源 portfolio 已不存在",
                    )
                    continue

                pos = (
                    AccountPositionModel._default_manager.select_for_update()
                    .filter(pk=source_position_id)
                    .first()
                )
                if pos is None:
                    self._record_position_migration_error(
                        stats,
                        source_position_id,
                        "来源 position 已不存在",
                    )
                    continue
                if pos.portfolio_id != source_portfolio.pk:
                    self._record_position_migration_error(
                        stats,
                        source_position_id,
                        "来源 position 的 portfolio 已变化",
                    )
                    continue
                if user_id is not None and source_portfolio.user_id != user_id:
                    self._record_position_migration_error(
                        stats,
                        source_position_id,
                        "来源 portfolio 的所有者已变化",
                    )
                    continue
                if pos.is_closed:
                    stats["positions_skipped"] += 1
                    continue

                candidate_portfolio_map = (
                    LedgerMigrationMapModel._default_manager.filter(
                        source_table="portfolio",
                        source_id=source_portfolio.pk,
                    )
                    .order_by("pk")
                    .first()
                )
                if candidate_portfolio_map is None:
                    self._record_position_migration_error(
                        stats,
                        pos.pk,
                        f"portfolio {source_portfolio.pk} 缺少迁移映射",
                    )
                    continue
                if candidate_portfolio_map.target_table != "simulated_account":
                    self._record_position_migration_error(
                        stats,
                        pos.pk,
                        "portfolio 映射目标表不是 simulated_account",
                    )
                    continue

                target_account = (
                    SimulatedAccountModel._default_manager.select_for_update()
                    .filter(pk=candidate_portfolio_map.target_id)
                    .first()
                )
                if target_account is None:
                    self._record_position_migration_error(
                        stats,
                        pos.pk,
                        "portfolio 映射指向不存在的账户",
                    )
                    continue

                portfolio_maps = list(
                    LedgerMigrationMapModel._default_manager.select_for_update()
                    .filter(
                        source_table="portfolio",
                        source_id=source_portfolio.pk,
                    )
                    .order_by("pk")
                )
                if (
                    len(portfolio_maps) != 1
                    or portfolio_maps[0].pk != candidate_portfolio_map.pk
                    or portfolio_maps[0].source_app != "account"
                    or portfolio_maps[0].target_table != "simulated_account"
                    or portfolio_maps[0].target_id != target_account.pk
                ):
                    self._record_position_migration_error(
                        stats,
                        pos.pk,
                        "portfolio 映射缺失、歧义或与目标账户不匹配",
                    )
                    continue

                if (
                    target_account.account_type != "real"
                    or target_account.user_id != source_portfolio.user_id
                ):
                    self._record_position_migration_error(
                        stats,
                        pos.pk,
                        "目标账户必须属于同一用户且类型为 real",
                    )
                    continue

                account_maps = list(
                    LedgerMigrationMapModel._default_manager.select_for_update()
                    .filter(
                        target_table="simulated_account",
                        target_id=target_account.pk,
                    )
                    .order_by("pk")
                )
                if (
                    len(account_maps) != 1
                    or account_maps[0].source_app != "account"
                    or account_maps[0].source_table != "portfolio"
                    or account_maps[0].source_id != source_portfolio.pk
                    or account_maps[0].pk != portfolio_maps[0].pk
                ):
                    self._record_position_migration_error(
                        stats,
                        pos.pk,
                        "目标账户的反向 portfolio 映射缺失、歧义或不匹配",
                    )
                    continue

                position_maps = list(
                    LedgerMigrationMapModel._default_manager.select_for_update()
                    .filter(source_table="position", source_id=pos.pk)
                    .order_by("pk")
                )
                if position_maps:
                    position_map = position_maps[0]
                    if (
                        len(position_maps) != 1
                        or position_map.source_app != "account"
                        or position_map.target_table != "simulated_position"
                    ):
                        self._record_position_migration_error(
                            stats,
                            pos.pk,
                            "已有 position 映射不唯一或目标表不匹配",
                        )
                        continue

                    mapped_position = (
                        SimPositionModel._default_manager.select_for_update()
                        .filter(pk=position_map.target_id)
                        .first()
                    )
                    reverse_position_maps = list(
                        LedgerMigrationMapModel._default_manager.select_for_update()
                        .filter(
                            target_table="simulated_position",
                            target_id=position_map.target_id,
                        )
                        .order_by("pk")
                    )
                    if (
                        mapped_position is None
                        or mapped_position.account_id != target_account.pk
                        or mapped_position.asset_code != pos.asset_code
                        or len(reverse_position_maps) != 1
                        or reverse_position_maps[0].pk != position_map.pk
                    ):
                        self._record_position_migration_error(
                            stats,
                            pos.pk,
                            "已有 position 映射对应的目标持仓不匹配",
                        )
                        continue

                    stats["positions_skipped"] += 1
                    continue

                quantity = Decimal(str(pos.shares)).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_UP
                )
                if quantity <= 0:
                    stats["positions_skipped"] += 1
                    continue

                asset_key = (target_account.pk, pos.asset_code)
                existing_position = (
                    SimPositionModel._default_manager.select_for_update()
                    .filter(account_id=target_account.pk, asset_code=pos.asset_code)
                    .first()
                )
                if existing_position is not None or asset_key in processed_asset_keys:
                    self._record_position_migration_error(
                        stats,
                        pos.pk,
                        "目标账户已有同资产未映射持仓或本次迁移已处理该资产，拒绝合并",
                    )
                    continue

                avg_cost = Decimal(str(pos.avg_cost)).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
                current_price = Decimal("0.0000")
                valuation_known = False
                if pos.current_price is not None:
                    try:
                        current_price = validate_ledger_price(
                            pos.current_price,
                            "position.current_price",
                            allow_zero=False,
                        )
                    except SimulatedTradeIntentValidationError:
                        pass
                    else:
                        valuation_known = True

                if valuation_known:
                    market_value_float, pnl_float, pnl_pct = recalculate_derived_fields(
                        float(quantity), float(avg_cost), float(current_price)
                    )
                    market_value = Decimal(str(market_value_float)).quantize(Decimal("0.01"))
                    unrealized_pnl = Decimal(str(pnl_float)).quantize(Decimal("0.01"))
                else:
                    market_value = Decimal("0.00")
                    unrealized_pnl = Decimal("0.00")
                    pnl_pct = 0.0

                target_position_id: int | None = None
                if not dry_run:
                    new_position = SimPositionModel._default_manager.create(
                        account_id=target_account.pk,
                        asset_code=pos.asset_code,
                        asset_name=pos.asset_code,  # account model lacks asset_name
                        asset_type=_map_asset_type(pos.asset_class),
                        quantity=quantity,
                        available_quantity=Decimal("0.000000"),
                        available_quantity_known=False,
                        avg_cost=avg_cost,
                        total_cost=(avg_cost * quantity).quantize(Decimal("0.01")),
                        current_price=current_price,
                        market_value=market_value,
                        valuation_known=valuation_known,
                        unrealized_pnl=unrealized_pnl,
                        unrealized_pnl_pct=pnl_pct,
                        first_buy_date=pos.opened_at.date() if pos.opened_at else date.today(),
                        first_buy_date_known=False,
                        signal_id=pos.source_id if pos.source == "signal" else None,
                        entry_reason=f"migrated from account.position:{pos.pk}",
                    )
                    LedgerMigrationMapModel._default_manager.create(
                        source_app="account",
                        source_table="position",
                        source_id=pos.pk,
                        target_table="simulated_position",
                        target_id=new_position.pk,
                    )
                    target_position_id = new_position.pk

                processed_asset_keys.add(asset_key)
                stats["positions_migrated"] += 1
                label = "[dry-run]" if target_position_id is None else str(target_position_id)
                self.stdout.write(
                    f"  ✓ Position {pos.pk} ({pos.asset_code}) → SimulatedPosition {label}"
                )

        self.stdout.write(
            f"  迁移 {stats['positions_migrated']} 条，跳过 {stats['positions_skipped']} 条"
        )

    def _record_position_migration_error(
        self,
        stats: MigrationStats,
        source_position_id: int,
        reason: str,
    ) -> None:
        """Record one stable, non-mutating position migration refusal."""

        message = f"  ⚠ Position {source_position_id}: {reason}, skipping"
        self.stdout.write(self.style.WARNING(message))
        stats["errors"].append(message)
        stats["positions_skipped"] += 1

    # ── Step 3: TransactionModel → SimulatedTradeModel ───────────────────

    def _migrate_transactions(
        self,
        user_id: int | None,
        dry_run: bool,
        stats: MigrationStats,
    ) -> None:
        from apps.simulated_trading.infrastructure.models import (
            LedgerMigrationMapModel,
            SimulatedTradeModel,
        )

        TransactionModel = get_account_transaction_model()
        qs = TransactionModel._default_manager.select_related("portfolio__user")
        if user_id is not None:
            qs = qs.filter(portfolio__user_id=user_id)

        self.stdout.write(f"\n[3/3] 迁移交易记录 → SimulatedTradeModel ({qs.count()} 条)")

        for txn in qs.iterator():
            if LedgerMigrationMapModel._default_manager.filter(
                source_app="account",
                source_table="transaction",
                source_id=txn.id,
            ).exists():
                stats["transactions_skipped"] += 1
                continue

            fee_state_fields = (
                txn.commission_known,
                txn.slippage_known,
                txn.stamp_duty_known,
                txn.transfer_fee_known,
            )
            if any(state is not True for state in fee_state_fields):
                stats["transactions_skipped"] += 1
                stats["transactions_skipped_unknown_costs"] += 1
                continue

            try:
                source_quantity = Decimal(str(txn.shares))
                if not source_quantity.is_finite() or source_quantity <= 0:
                    raise ValueError("交易数量必须为正有限值")
                # Preserve the existing six-place ROUND_HALF_UP migration rule.
                quantity = source_quantity.quantize(
                    Decimal("0.000001"),
                    rounding=ROUND_HALF_UP,
                )
            except (InvalidOperation, ValueError) as exc:
                stats["errors"].append(f"交易 {txn.id} 的交易数量无效: {exc}")
                stats["transactions_skipped"] += 1
                continue

            if not quantity.is_finite() or quantity <= 0:
                stats["errors"].append(f"交易 {txn.id} 的交易数量按六位小数舍入后必须仍为正有限值")
                stats["transactions_skipped"] += 1
                continue
            if quantity > SIMULATED_TRADE_QUANTITY_MAX:
                stats["errors"].append(
                    f"交易 {txn.id} 的交易数量超出目标 SimulatedTrade(20,6) 上限"
                )
                stats["transactions_skipped"] += 1
                continue

            try:
                commission = _quantize_migration_fee(txn.commission)
                slippage = _quantize_migration_fee(txn.slippage)
                stamp_duty = _quantize_migration_fee(txn.stamp_duty)
                transfer_fee = _quantize_migration_fee(txn.transfer_fee)
                price = txn.price.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                # Retain the existing zero-notional fallback; it is a legacy repair
                # heuristic, not evidence that the source notional was complete.
                amount = (txn.notional or txn.price * Decimal(str(txn.shares))).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                )
                fee_total = commission + slippage + stamp_duty + transfer_fee
                total_cost = amount + fee_total if txn.action == "buy" else fee_total
            except (InvalidOperation, ValueError) as exc:
                stats["errors"].append(f"交易 {txn.id} 的金额或成本无效: {exc}")
                stats["transactions_skipped"] += 1
                continue

            # The target model fields are narrower than the account ledger fields:
            # price(10,4), amount/total_cost(15,2). Reject rows that cannot fit
            # before resolving target mappings so dry-run and write counts agree.
            if (
                not price.is_finite()
                or price <= 0
                or price > SIMULATED_TRADE_PRICE_MAX
                or not amount.is_finite()
                or amount < 0
                or amount > SIMULATED_TRADE_AMOUNT_MAX
                or not total_cost.is_finite()
                or total_cost < 0
                or total_cost > SIMULATED_TRADE_AMOUNT_MAX
            ):
                stats["errors"].append(f"交易 {txn.id} 超出目标 SimulatedTrade 的字段范围")
                stats["transactions_skipped"] += 1
                continue

            # Resolve target account after source cost validation so dry-run and
            # write runs count unknown, malformed, and unrepresentable costs alike.
            try:
                mapping = LedgerMigrationMapModel._default_manager.get(
                    source_app="account",
                    source_table="portfolio",
                    source_id=txn.portfolio_id,
                )
                target_account_id = mapping.target_id
            except LedgerMigrationMapModel.DoesNotExist:
                stats["transactions_skipped"] += 1
                continue

            traded_at = txn.traded_at

            if not dry_run:
                with transaction.atomic():
                    new_trade = SimulatedTradeModel._default_manager.create(
                        account_id=target_account_id,
                        asset_code=txn.asset_code,
                        asset_name=txn.asset_code,
                        asset_type="equity",  # default; account model lacks asset_type
                        action=txn.action,
                        quantity=quantity,
                        price=price,
                        amount=amount,
                        commission=commission,
                        slippage=slippage,
                        stamp_duty=stamp_duty,
                        transfer_fee=transfer_fee,
                        total_cost=total_cost,
                        realized_pnl=None,
                        realized_pnl_pct=None,
                        reason=txn.notes or "migrated",
                        order_date=traded_at.date(),
                        execution_date=traded_at.date(),
                        status="executed",
                    )

                    SimulatedTradeModel._default_manager.filter(id=new_trade.id).update(
                        execution_time=traded_at
                    )

                    LedgerMigrationMapModel._default_manager.create(
                        source_app="account",
                        source_table="transaction",
                        source_id=txn.id,
                        target_table="simulated_trade",
                        target_id=new_trade.id,
                    )

            stats["transactions_migrated"] += 1

        self.stdout.write(
            f"  迁移 {stats['transactions_migrated']} 条，跳过 {stats['transactions_skipped']} 条"
        )
        self.stdout.write(f"  因实际成本未知跳过 {stats['transactions_skipped_unknown_costs']} 条")

    # ── Summary ───────────────────────────────────────────────────────────

    def _print_summary(self, stats: MigrationStats) -> None:
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("迁移摘要"))
        self.stdout.write(
            f"  投资组合: 迁移 {stats['portfolios_migrated']}，跳过 {stats['portfolios_skipped']}"
        )
        self.stdout.write(
            f"  持仓记录: 迁移 {stats['positions_migrated']}，跳过 {stats['positions_skipped']}"
        )
        self.stdout.write(
            f"  交易记录: 迁移 {stats['transactions_migrated']}，跳过 {stats['transactions_skipped']}"
        )
        self.stdout.write(
            f"  其中因实际成本未知跳过 {stats['transactions_skipped_unknown_costs']} 条"
        )
        if stats["errors"]:
            self.stdout.write(self.style.WARNING(f"\n警告 ({len(stats['errors'])} 条):"))
            for e in stats["errors"]:
                self.stdout.write(f"  {e}")
        self.stdout.write("=" * 70)
        if not stats["errors"]:
            self.stdout.write(self.style.SUCCESS("✓ 迁移完成，无错误"))
        else:
            self.stdout.write(self.style.WARNING("⚠ 迁移完成，有警告，请检查上方日志"))


# ── helpers ───────────────────────────────────────────────────────────────


def _quantize_migration_fee(value: Decimal | None) -> Decimal:
    """Validate and quantize one source fee without a float/string round trip."""
    if value is None or not value.is_finite() or value < 0:
        raise ValueError("fee must be a finite, non-negative Decimal")
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _map_asset_type(asset_class: str) -> str:
    """Map account.PositionModel.asset_class to simulated_trading asset_type."""
    mapping = {
        "equity": "equity",
        "fund": "fund",
        "fixed_income": "bond",
        "commodity": "equity",  # closest available type
        "currency": "fund",
        "cash": "fund",
        "derivative": "equity",
        "other": "equity",
    }
    return mapping.get(asset_class, "equity")
