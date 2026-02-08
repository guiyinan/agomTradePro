"""Initialize default DB-driven position management rules for strategies."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.strategy.infrastructure.models import (
    PositionManagementRuleModel,
    StrategyModel,
)


class Command(BaseCommand):
    help = "初始化仓位管理规则（数据库驱动表达式）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--strategy-id",
            type=int,
            default=None,
            help="仅初始化指定 strategy_id；不传则初始化全部策略。",
        )
        parser.add_argument(
            "--template",
            type=str,
            choices=["atr_risk", "breakout_trend"],
            default="atr_risk",
            help="模板类型。",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="已存在规则时执行覆盖。",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="仅打印将执行的变更，不写入数据库。",
        )

    def handle(self, *args, **options):
        strategy_id = options["strategy_id"]
        template_name = options["template"]
        force = options["force"]
        dry_run = options["dry_run"]

        queryset = StrategyModel._default_manager.all().order_by("id")
        if strategy_id is not None:
            queryset = queryset.filter(id=strategy_id)
            if not queryset.exists():
                raise CommandError(f"未找到策略: strategy_id={strategy_id}")

        template = self._get_template(template_name)
        created = 0
        updated = 0
        skipped = 0

        for strategy in queryset:
            payload = {
                "strategy": strategy,
                "name": f"{strategy.name} - {template['name_suffix']}",
                "description": template["description"],
                "is_active": True,
                "price_precision": template["price_precision"],
                "variables_schema": template["variables_schema"],
                "buy_condition_expr": template["buy_condition_expr"],
                "sell_condition_expr": template["sell_condition_expr"],
                "buy_price_expr": template["buy_price_expr"],
                "sell_price_expr": template["sell_price_expr"],
                "stop_loss_expr": template["stop_loss_expr"],
                "take_profit_expr": template["take_profit_expr"],
                "position_size_expr": template["position_size_expr"],
                "metadata": {"template": template_name},
            }

            existing = PositionManagementRuleModel._default_manager.filter(strategy=strategy).first()
            if existing and not force:
                skipped += 1
                self.stdout.write(f"[SKIP] strategy={strategy.id} 已存在规则（使用 --force 覆盖）")
                continue

            action = "UPDATE" if existing else "CREATE"
            self.stdout.write(f"[{action}] strategy={strategy.id} {strategy.name}")

            if dry_run:
                continue

            if existing:
                for key, value in payload.items():
                    if key == "strategy":
                        continue
                    setattr(existing, key, value)
                existing.save()
                updated += 1
            else:
                PositionManagementRuleModel._default_manager.create(**payload)
                created += 1

        if dry_run:
            self.stdout.write(self.style.WARNING("dry-run 模式：未写入数据库。"))

        self.stdout.write(
            self.style.SUCCESS(
                f"完成：created={created}, updated={updated}, skipped={skipped}, template={template_name}"
            )
        )

    @staticmethod
    def _get_template(template_name: str) -> dict:
        if template_name == "breakout_trend":
            return {
                "name_suffix": "突破趋势仓位规则",
                "description": "突破买入 + 追踪止盈；仓位按风险金额计算。",
                "price_precision": 2,
                "variables_schema": [
                    {"name": "current_price", "type": "number", "required": True},
                    {"name": "breakout_price", "type": "number", "required": True},
                    {"name": "pullback_price", "type": "number", "required": True},
                    {"name": "atr", "type": "number", "required": True},
                    {"name": "account_equity", "type": "number", "required": True},
                    {"name": "risk_per_trade_pct", "type": "number", "required": True},
                    {"name": "slippage_pct", "type": "number", "required": False},
                ],
                "buy_condition_expr": "current_price >= breakout_price",
                "sell_condition_expr": "current_price <= pullback_price",
                "buy_price_expr": "breakout_price * (1 + slippage_pct if slippage_pct else 1)",
                "sell_price_expr": "pullback_price",
                "stop_loss_expr": "buy_price - 2 * atr",
                "take_profit_expr": "buy_price + 3 * atr",
                "position_size_expr": "(account_equity * risk_per_trade_pct) / abs(buy_price - stop_loss_price)",
            }

        return {
            "name_suffix": "ATR风险仓位规则",
            "description": "结构位+ATR 止损；2R 目标止盈；仓位按单笔风险金额计算。",
            "price_precision": 2,
            "variables_schema": [
                {"name": "current_price", "type": "number", "required": True},
                {"name": "support_price", "type": "number", "required": True},
                {"name": "resistance_price", "type": "number", "required": True},
                {"name": "structure_low", "type": "number", "required": True},
                {"name": "atr", "type": "number", "required": True},
                {"name": "account_equity", "type": "number", "required": True},
                {"name": "risk_per_trade_pct", "type": "number", "required": True},
                {"name": "entry_buffer_pct", "type": "number", "required": False},
            ],
            "buy_condition_expr": "current_price <= support_price * (1 + (entry_buffer_pct if entry_buffer_pct else 0))",
            "sell_condition_expr": "current_price >= resistance_price",
            "buy_price_expr": "support_price * (1 + (entry_buffer_pct if entry_buffer_pct else 0))",
            "sell_price_expr": "resistance_price",
            "stop_loss_expr": "min(structure_low, buy_price - 2 * atr)",
            "take_profit_expr": "buy_price + 2 * abs(buy_price - stop_loss_price)",
            "position_size_expr": "(account_equity * risk_per_trade_pct) / abs(buy_price - stop_loss_price)",
        }
