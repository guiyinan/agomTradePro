"""Position management rule evaluation service."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any


class PositionRuleError(ValueError):
    """Raised when position rule expression is invalid."""


@dataclass(frozen=True)
class PositionManagementEvaluation:
    """Output of evaluating a position management rule."""

    should_buy: bool
    should_sell: bool
    buy_price: float
    sell_price: float
    stop_loss_price: float
    take_profit_price: float
    position_size: float
    risk_reward_ratio: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_buy": self.should_buy,
            "should_sell": self.should_sell,
            "buy_price": self.buy_price,
            "sell_price": self.sell_price,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "position_size": self.position_size,
            "risk_reward_ratio": self.risk_reward_ratio,
        }


class _SafeExpressionValidator(ast.NodeVisitor):
    """AST validator for a restricted expression grammar."""

    _ALLOWED_BIN_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)
    _ALLOWED_UNARY_OPS = (ast.UAdd, ast.USub, ast.Not)
    _ALLOWED_BOOL_OPS = (ast.And, ast.Or)
    _ALLOWED_COMPARE_OPS = (
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
    )
    _ALLOWED_FUNC_NAMES = {"min", "max", "abs", "round", "pow"}

    def visit(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return self.visit(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, bool)):
                return
            raise PositionRuleError("仅允许数字和布尔常量")
        if isinstance(node, ast.Name):
            return
        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, self._ALLOWED_BIN_OPS):
                raise PositionRuleError("表达式包含不支持的二元运算符")
            self.visit(node.left)
            self.visit(node.right)
            return
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, self._ALLOWED_UNARY_OPS):
                raise PositionRuleError("表达式包含不支持的一元运算符")
            self.visit(node.operand)
            return
        if isinstance(node, ast.BoolOp):
            if not isinstance(node.op, self._ALLOWED_BOOL_OPS):
                raise PositionRuleError("表达式包含不支持的逻辑运算符")
            for value in node.values:
                self.visit(value)
            return
        if isinstance(node, ast.Compare):
            self.visit(node.left)
            for op in node.ops:
                if not isinstance(op, self._ALLOWED_COMPARE_OPS):
                    raise PositionRuleError("表达式包含不支持的比较运算符")
            for comparator in node.comparators:
                self.visit(comparator)
            return
        if isinstance(node, ast.IfExp):
            self.visit(node.test)
            self.visit(node.body)
            self.visit(node.orelse)
            return
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in self._ALLOWED_FUNC_NAMES:
                raise PositionRuleError("表达式调用了不允许的函数")
            for arg in node.args:
                self.visit(arg)
            for kw in node.keywords:
                self.visit(kw.value)
            return
        raise PositionRuleError(f"表达式包含不支持的语法: {node.__class__.__name__}")


class PositionManagementService:
    """Evaluate position management rules with DB-defined expressions."""

    _FUNCTIONS = {
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
        "pow": pow,
    }

    @classmethod
    def validate_expression(cls, expression: str) -> None:
        if not expression or not expression.strip():
            raise PositionRuleError("表达式不能为空")
        try:
            parsed = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise PositionRuleError(f"表达式语法错误: {exc.msg}") from exc
        _SafeExpressionValidator().visit(parsed)

    @classmethod
    def _safe_eval(cls, expression: str, context: dict[str, Any]) -> Any:
        cls.validate_expression(expression)
        compiled = compile(ast.parse(expression, mode="eval"), "<position-rule>", "eval")
        safe_locals = {**cls._FUNCTIONS, **context}
        try:
            return eval(compiled, {"__builtins__": {}}, safe_locals)  # noqa: S307
        except NameError as exc:
            raise PositionRuleError(f"表达式变量未提供: {exc}") from exc
        except ZeroDivisionError as exc:
            raise PositionRuleError("表达式出现除零错误") from exc
        except Exception as exc:  # pragma: no cover
            raise PositionRuleError(f"表达式计算失败: {exc}") from exc

    @classmethod
    def evaluate(
        cls,
        rule: Any,
        context: dict[str, Any],
    ) -> PositionManagementEvaluation:
        buy_price = float(cls._safe_eval(rule.buy_price_expr, context))
        sell_price = float(cls._safe_eval(rule.sell_price_expr, context))

        stop_ctx = {
            **context,
            "buy_price": buy_price,
            "sell_price": sell_price,
        }
        stop_loss_price = float(cls._safe_eval(rule.stop_loss_expr, stop_ctx))
        take_profit_price = float(cls._safe_eval(rule.take_profit_expr, {**stop_ctx, "stop_loss_price": stop_loss_price}))

        position_ctx = {
            **stop_ctx,
            "stop_loss_price": stop_loss_price,
            "take_profit_price": take_profit_price,
        }
        position_size = float(cls._safe_eval(rule.position_size_expr, position_ctx))
        if position_size < 0:
            raise PositionRuleError("仓位结果不能为负数")

        if rule.buy_condition_expr.strip():
            should_buy = bool(cls._safe_eval(rule.buy_condition_expr, position_ctx))
        else:
            current_price = context.get("current_price", buy_price)
            should_buy = float(current_price) <= buy_price

        if rule.sell_condition_expr.strip():
            should_sell = bool(cls._safe_eval(rule.sell_condition_expr, position_ctx))
        else:
            current_price = context.get("current_price", sell_price)
            should_sell = float(current_price) >= sell_price

        entry_price = float(context.get("entry_price", context.get("current_price", buy_price)))
        risk = abs(entry_price - stop_loss_price)
        reward = abs(take_profit_price - entry_price)
        risk_reward_ratio = None if risk == 0 else reward / risk

        precision = int(getattr(rule, "price_precision", 2))
        buy_price = round(buy_price, precision)
        sell_price = round(sell_price, precision)
        stop_loss_price = round(stop_loss_price, precision)
        take_profit_price = round(take_profit_price, precision)
        position_size = round(position_size, 6)
        if risk_reward_ratio is not None:
            risk_reward_ratio = round(risk_reward_ratio, 6)

        return PositionManagementEvaluation(
            should_buy=should_buy,
            should_sell=should_sell,
            buy_price=buy_price,
            sell_price=sell_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            position_size=position_size,
            risk_reward_ratio=risk_reward_ratio,
        )
