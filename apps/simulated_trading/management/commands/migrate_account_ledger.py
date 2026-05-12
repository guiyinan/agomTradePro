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
from decimal import ROUND_HALF_UP, Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.integration.account_ledger import (
    get_account_position_model,
    get_account_transaction_model,
    get_capital_flow_model,
    get_portfolio_model,
)


class Command(BaseCommand):
    help = "将 apps/account 账本数据迁移至 simulated_trading 统一账本（幂等）"

    def add_arguments(self, parser):
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

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        user_id: int | None = options.get("user_id")

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

        stats = {
            "portfolios_skipped": 0,
            "portfolios_migrated": 0,
            "positions_skipped": 0,
            "positions_migrated": 0,
            "transactions_skipped": 0,
            "transactions_migrated": 0,
            "errors": [],
        }

        self._migrate_portfolios(user_id, dry_run, stats)
        self._migrate_positions(user_id, dry_run, stats)
        self._migrate_transactions(user_id, dry_run, stats)

        self._print_summary(stats)

    # ── Step 1: PortfolioModel → SimulatedAccountModel ──────────────────

    def _migrate_portfolios(self, user_id, dry_run, stats):
        from apps.simulated_trading.infrastructure.models import (
            LedgerMigrationMapModel,
            SimulatedAccountModel,
        )

        CapitalFlowModel = get_capital_flow_model()
        PortfolioModel = get_portfolio_model()
        qs = PortfolioModel._default_manager.select_related("user")
        if user_id:
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
            deposit_total = (
                CapitalFlowModel._default_manager.filter(
                    portfolio=portfolio,
                    flow_type="deposit",
                ).aggregate(total=__import__("django.db.models", fromlist=["Sum"]).Sum("amount"))["total"]
                or Decimal("0")
            )

            # Compute current totals from positions
            positions_qs = portfolio.positions.filter(is_closed=False)
            market_value_total = sum(
                float(p.market_value or 0) for p in positions_qs
            )

            # current_cash approximation: initial capital - invested value
            invested = sum(
                float(p.shares * float(p.avg_cost)) for p in positions_qs
            )
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

    def _migrate_positions(self, user_id, dry_run, stats):
        from apps.simulated_trading.infrastructure.models import (
            LedgerMigrationMapModel,
        )
        from apps.simulated_trading.infrastructure.models import (
            PositionModel as SimPositionModel,
        )
        from shared.domain.position_calculations import recalculate_derived_fields

        AccountPositionModel = get_account_position_model()
        qs = AccountPositionModel._default_manager.select_related("portfolio__user")
        if user_id:
            qs = qs.filter(portfolio__user_id=user_id)

        self.stdout.write(f"\n[2/3] 迁移持仓 → simulated_trading.PositionModel ({qs.count()} 条)")

        for pos in qs.iterator():
            if LedgerMigrationMapModel._default_manager.filter(
                source_app="account",
                source_table="position",
                source_id=pos.id,
            ).exists():
                stats["positions_skipped"] += 1
                continue

            # Skip closed positions — they are historical; their trades will be migrated
            if pos.is_closed:
                stats["positions_skipped"] += 1
                continue

            # Resolve target account ID
            try:
                mapping = LedgerMigrationMapModel._default_manager.get(
                    source_app="account",
                    source_table="portfolio",
                    source_id=pos.portfolio_id,
                )
                target_account_id = mapping.target_id
            except LedgerMigrationMapModel.DoesNotExist:
                msg = f"  ⚠ Position {pos.id}: portfolio {pos.portfolio_id} not yet migrated, skipping"
                self.stdout.write(self.style.WARNING(msg))
                stats["errors"].append(msg)
                stats["positions_skipped"] += 1
                continue

            # Preserve float precision from account.PositionModel.shares
            quantity = Decimal(str(pos.shares)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            if quantity <= 0:
                stats["positions_skipped"] += 1
                continue

            avg_cost = Decimal(str(pos.avg_cost)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            current_price = float(pos.current_price or pos.avg_cost)
            mv, pnl, pnl_pct = recalculate_derived_fields(float(quantity), float(avg_cost), current_price)

            # Determine asset_type from asset_class
            asset_type = _map_asset_type(pos.asset_class)

            if not dry_run:
                with transaction.atomic():
                    # Check unique_together conflict
                    existing = SimPositionModel._default_manager.filter(
                        account_id=target_account_id,
                        asset_code=pos.asset_code,
                    ).first()

                    if existing:
                        # Merge: take the higher quantity, blend avg_cost
                        combined_qty = existing.quantity + quantity
                        blended_cost = (
                            (existing.avg_cost * existing.quantity + avg_cost * quantity)
                            / combined_qty
                        ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                        mv2, pnl2, pnl_pct2 = recalculate_derived_fields(
                            combined_qty, float(blended_cost), current_price
                        )
                        SimPositionModel._default_manager.filter(pk=existing.pk).update(
                            quantity=combined_qty,
                            available_quantity=combined_qty,
                            avg_cost=blended_cost,
                            total_cost=blended_cost * combined_qty,
                            current_price=current_price,
                            market_value=Decimal(str(mv2)).quantize(Decimal("0.01")),
                            unrealized_pnl=Decimal(str(pnl2)).quantize(Decimal("0.01")),
                            unrealized_pnl_pct=pnl_pct2,
                        )
                        target_id = existing.id
                    else:
                        new_pos = SimPositionModel._default_manager.create(
                            account_id=target_account_id,
                            asset_code=pos.asset_code,
                            asset_name=pos.asset_code,  # account model lacks asset_name
                            asset_type=asset_type,
                            quantity=quantity,
                            available_quantity=quantity,
                            avg_cost=avg_cost,
                            total_cost=(avg_cost * quantity).quantize(Decimal("0.01")),
                            current_price=Decimal(str(current_price)).quantize(Decimal("0.0001")),
                            market_value=Decimal(str(mv)).quantize(Decimal("0.01")),
                            unrealized_pnl=Decimal(str(pnl)).quantize(Decimal("0.01")),
                            unrealized_pnl_pct=pnl_pct,
                            first_buy_date=pos.opened_at.date() if pos.opened_at else date.today(),
                            signal_id=pos.source_id if pos.source == "signal" else None,
                            entry_reason=f"migrated from account.position:{pos.id}",
                        )
                        target_id = new_pos.id

                    LedgerMigrationMapModel._default_manager.create(
                        source_app="account",
                        source_table="position",
                        source_id=pos.id,
                        target_table="simulated_position",
                        target_id=target_id,
                    )

            stats["positions_migrated"] += 1

        self.stdout.write(
            f"  迁移 {stats['positions_migrated']} 条，跳过 {stats['positions_skipped']} 条"
        )

    # ── Step 3: TransactionModel → SimulatedTradeModel ───────────────────

    def _migrate_transactions(self, user_id, dry_run, stats):
        from apps.simulated_trading.infrastructure.models import (
            LedgerMigrationMapModel,
            SimulatedTradeModel,
        )

        TransactionModel = get_account_transaction_model()
        qs = TransactionModel._default_manager.select_related("portfolio__user")
        if user_id:
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

            # Resolve target account
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

            quantity = Decimal(str(txn.shares)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            price = float(txn.price)
            amount = float(txn.notional or txn.price * txn.shares)
            commission = float(txn.commission or 0)
            traded_at = txn.traded_at or timezone.now()

            if not dry_run:
                with transaction.atomic():
                    new_trade = SimulatedTradeModel._default_manager.create(
                        account_id=target_account_id,
                        asset_code=txn.asset_code,
                        asset_name=txn.asset_code,
                        asset_type="equity",  # default; account model lacks asset_type
                        action=txn.action,
                        quantity=quantity,
                        price=Decimal(str(price)).quantize(Decimal("0.0001")),
                        amount=Decimal(str(amount)).quantize(Decimal("0.01")),
                        commission=Decimal(str(commission)).quantize(Decimal("0.01")),
                        slippage=Decimal("0"),
                        total_cost=Decimal(str(commission)).quantize(Decimal("0.01")),
                        realized_pnl=None,
                        realized_pnl_pct=None,
                        reason=txn.notes or "migrated",
                        order_date=traded_at.date(),
                        execution_date=traded_at.date(),
                        execution_time=traded_at,
                        status="executed",
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

    # ── Summary ───────────────────────────────────────────────────────────

    def _print_summary(self, stats):
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
