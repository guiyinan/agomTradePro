"""Pure scope contracts for the TUX09 task actions.

This module narrows task parameters before an executor is allowed to bind an
endpoint.  It does not identify the authenticated actor or perform access
checks; owner services remain responsible for those decisions.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Literal, cast

from core.exceptions import InvalidInputError

TuiTaskActionKey = Literal[
    "today-focus.market-context",
    "today-focus.account-selector",
    "today-focus.queue",
    "portfolio-check.portfolios",
    "portfolio-check.recorded-facts",
    "account.portfolio-recorded-facts",
    "account-inspection.run",
    "rebalance-plan.accounts",
    "rebalance-plan.account-detail",
    "rebalance-plan.positions",
    "rebalance-plan.account-risk",
    "rebalance-plan.list",
    "rebalance-plan.create",
    "rebalance-plan.read",
    "rebalance-plan.orders",
    "rebalance-plan.reconcile",
    "rebalance-plan.preview-order",
    "rebalance-plan.review",
    "rebalance-plan.successor",
]

_KNOWN_ACTION_KEYS: frozenset[str] = frozenset(
    {
        "today-focus.market-context",
        "today-focus.account-selector",
        "today-focus.queue",
        "portfolio-check.portfolios",
        "portfolio-check.recorded-facts",
        "account.portfolio-recorded-facts",
        "account-inspection.run",
        "rebalance-plan.accounts",
        "rebalance-plan.account-detail",
        "rebalance-plan.positions",
        "rebalance-plan.account-risk",
        "rebalance-plan.list",
        "rebalance-plan.create",
        "rebalance-plan.read",
        "rebalance-plan.orders",
        "rebalance-plan.reconcile",
        "rebalance-plan.preview-order",
        "rebalance-plan.review",
        "rebalance-plan.successor",
    }
)
_NO_PARAMS: frozenset[str] = frozenset(
    {"today-focus.market-context", "today-focus.account-selector"}
)
_ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "today-focus.market-context": frozenset(),
    "today-focus.account-selector": frozenset(),
    "today-focus.queue": frozenset({"account_id"}),
    "portfolio-check.portfolios": frozenset({"page"}),
    "portfolio-check.recorded-facts": frozenset({"pk", "page", "page_size"}),
    "account.portfolio-recorded-facts": frozenset({"pk", "page", "page_size"}),
    "account-inspection.run": frozenset(
        {"account_id", "temporary_target_weights", "reference_price_basis"}
    ),
    "rebalance-plan.accounts": frozenset(),
    "rebalance-plan.account-detail": frozenset({"account_id"}),
    "rebalance-plan.positions": frozenset({"account_id"}),
    "rebalance-plan.account-risk": frozenset({"account_id"}),
    "rebalance-plan.list": frozenset({"account_id"}),
    "rebalance-plan.create": frozenset({"account_id", "target_weights", "reference_price_basis"}),
    "rebalance-plan.read": frozenset({"account_id", "plan_id", "plan_version", "revision_hash"}),
    "rebalance-plan.orders": frozenset({"account_id", "plan_id", "plan_version", "revision_hash"}),
    "rebalance-plan.preview-order": frozenset(
        {
            "account_id",
            "plan_id",
            "plan_version",
            "revision_hash",
            "order_ordinal",
            "order_content_hash",
            "plan_order_binding_id",
            "quantity",
            "limit_price",
            "reason",
        }
    ),
    "rebalance-plan.reconcile": frozenset(
        {"account_id", "plan_id", "plan_version", "revision_hash"}
    ),
    "rebalance-plan.review": frozenset(
        {"account_id", "plan_id", "plan_version", "revision_hash", "confirmed"}
    ),
    "rebalance-plan.successor": frozenset(
        {
            "account_id",
            "plan_id",
            "plan_version",
            "revision_hash",
            "confirmed",
            "target_weights",
        }
    ),
}


class TuiTaskScopeError(InvalidInputError):
    """Identify a task-scope input that cannot be safely bound to an owner call."""

    default_message = "任务参数无效，请重新选择账户或组合"
    default_code = "TUI_TASK_SCOPE_INVALID"


@dataclass(frozen=True, slots=True)
class TuiTaskScope:
    """The only endpoint parameters a known TUX09 action may receive."""

    action_key: TuiTaskActionKey
    params: Mapping[str, int | str | bool]
    temporary_target_weights: str | None = None
    reference_price_basis: Literal["market", "published_close"] | None = None

    def to_params(self) -> dict[str, int | str | bool]:
        """Return the narrow account-inspection body and integer scope values."""

        values: dict[str, int | str | bool] = dict(self.params)
        if self.temporary_target_weights is not None:
            values["temporary_target_weights"] = self.temporary_target_weights
        if self.reference_price_basis is not None:
            values["reference_price_basis"] = self.reference_price_basis
        return values


def _invalid(message: str) -> TuiTaskScopeError:
    """Create the stable user-facing scope error without exposing raw values."""

    return TuiTaskScopeError(message=message, code="TUI_TASK_SCOPE_INVALID")


def _positive_integer(value: object, field_name: str) -> int:
    """Normalize one strict positive integer parameter."""

    if type(value) is int:
        number = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        try:
            number = int(value)
        except (ValueError, OverflowError) as error:
            raise _invalid(f"{field_name}必须是正整数") from error
    else:
        raise _invalid(f"{field_name}必须是正整数")

    if number < 1:
        raise _invalid(f"{field_name}必须是正整数")
    return number


def _copy_params(params: Mapping[str, object] | None) -> dict[str, object]:
    """Copy a parameter mapping while rejecting non-mapping input."""

    if params is None:
        return {}
    if not isinstance(params, Mapping):
        raise _invalid("任务参数必须是对象")
    return dict(params)


def _require_fields(action_key: str, values: Mapping[str, object]) -> dict[str, int | str | bool]:
    """Validate a known action's declared fields and return normalized values."""

    allowed = _ALLOWED_FIELDS[action_key]
    unknown = set(values).difference(allowed)
    if unknown:
        raise _invalid("任务参数包含未声明字段")

    normalized: dict[str, int | str | bool] = {}
    if action_key == "today-focus.queue":
        if "account_id" not in values:
            raise _invalid("账户待办必须先选择账户")
        normalized["account_id"] = _positive_integer(values["account_id"], "账户编号")
        return normalized

    if action_key == "account-inspection.run":
        if "account_id" not in values:
            raise _invalid("请先选择本人账户")
        normalized["account_id"] = _positive_integer(values["account_id"], "账户编号")
        return normalized

    if action_key in {
        "portfolio-check.recorded-facts",
        "account.portfolio-recorded-facts",
    }:
        if "pk" not in values:
            raise _invalid("组合记录事实必须先选择组合")
        normalized["pk"] = _positive_integer(values["pk"], "组合编号")
        page = values.get("page", 1)
        page_size = values.get("page_size", 20)
        normalized["page"] = _positive_integer(page, "页码")
        normalized_page_size = _positive_integer(page_size, "每页持仓数")
        normalized["page_size"] = normalized_page_size
        if normalized_page_size > 100:
            raise _invalid("每页持仓数不能超过100")
        return normalized

    if action_key == "portfolio-check.portfolios":
        normalized["page"] = _positive_integer(values.get("page", 1), "页码")
        return normalized

    if action_key.startswith("rebalance-plan."):
        return _require_rebalance_fields(action_key, values)

    if action_key in _NO_PARAMS:
        return normalized

    raise _invalid("任务参数无法识别")


def _require_rebalance_fields(
    action_key: str, values: Mapping[str, object]
) -> dict[str, int | str | bool]:
    """Normalize exact plan pins and explicit target intent for known actions."""

    normalized: dict[str, int | str | bool] = {}
    if action_key == "rebalance-plan.accounts":
        if values:
            raise _invalid("模拟账户列表不接受参数")
        return normalized
    if action_key in {
        "rebalance-plan.account-detail",
        "rebalance-plan.positions",
        "rebalance-plan.account-risk",
        "rebalance-plan.list",
    }:
        if "account_id" not in values:
            raise _invalid("请先选择本人模拟账户")
        normalized["account_id"] = _positive_integer(values["account_id"], "账户编号")
        return normalized
    if "account_id" not in values:
        raise _invalid("请先选择本人模拟账户")
    normalized["account_id"] = _positive_integer(values["account_id"], "账户编号")
    if action_key == "rebalance-plan.create":
        target = values.get("target_weights")
        if type(target) is not str or not target.strip() or len(target) > 2048:
            raise _invalid("请填写有效证券目标文本")
        normalized["target_weights"] = target
        basis = values.get("reference_price_basis")
        if type(basis) is not str or basis not in {"market", "published_close"}:
            raise _invalid("请选择有效的计划参考价格口径")
        normalized["reference_price_basis"] = basis
        return normalized
    plan_id = values.get("plan_id")
    if type(plan_id) is not str or not plan_id or len(plan_id) > 64 or plan_id.strip() != plan_id:
        raise _invalid("请从计划列表选择一个已保存版本")
    normalized["plan_id"] = plan_id
    normalized["plan_version"] = _positive_integer(values.get("plan_version"), "计划版本")
    revision_hash = values.get("revision_hash")
    if (
        type(revision_hash) is not str
        or len(revision_hash) != 64
        or any(character not in "0123456789abcdef" for character in revision_hash)
    ):
        raise _invalid("计划版本无法核对，请重新读取计划列表")
    normalized["revision_hash"] = revision_hash
    if action_key in {"rebalance-plan.review", "rebalance-plan.successor"}:
        if values.get("confirmed") is not True:
            raise _invalid("请明确确认本次计划操作")
        normalized["confirmed"] = True
    if action_key == "rebalance-plan.review":
        return normalized
    if action_key == "rebalance-plan.successor":
        target = values.get("target_weights")
        if target is not None:
            if type(target) is not str or not target.strip() or len(target) > 2048:
                raise _invalid("后继目标必须是有效证券目标文本")
            normalized["target_weights"] = target
        return normalized
    if action_key in {"rebalance-plan.read", "rebalance-plan.orders", "rebalance-plan.reconcile"}:
        return normalized
    if action_key == "rebalance-plan.preview-order":
        normalized["order_ordinal"] = _nonnegative_integer(
            values.get("order_ordinal"), "计划订单序号"
        )
        for field_name in ("order_content_hash", "plan_order_binding_id"):
            value = values.get(field_name)
            if (
                type(value) is not str
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise _invalid("计划订单无法核对，请重新读取")
            normalized[field_name] = value
        normalized["quantity"] = _positive_decimal_text(values.get("quantity"), "数量", whole=True)
        normalized["limit_price"] = _positive_decimal_text(
            values.get("limit_price"), "限价", whole=False
        )
        reason = values.get("reason")
        if reason is not None:
            if type(reason) is not str or len(reason) > 200:
                raise _invalid("本次说明不能超过200个字符")
            normalized["reason"] = reason
        return normalized
    raise _invalid("调仓计划任务无法识别")


def _nonnegative_integer(value: object, field_name: str) -> int:
    """Normalize a strict zero-based order ordinal."""

    if type(value) is int:
        number = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        try:
            number = int(value)
        except (ValueError, OverflowError) as error:
            raise _invalid(f"{field_name}无效") from error
    else:
        raise _invalid(f"{field_name}无效")
    if number < 0:
        raise _invalid(f"{field_name}无效")
    return number


_DECIMAL_TEXT = re.compile(r"^(?:0|[1-9]\d{0,15})(?:\.\d{1,6})?$")


def _positive_decimal_text(value: object, field_name: str, *, whole: bool) -> str:
    """Accept exact positive decimal text without coercing through float."""

    if type(value) is not str or not _DECIMAL_TEXT.fullmatch(value):
        raise _invalid(f"{field_name}格式无效")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise _invalid(f"{field_name}格式无效") from error
    if not parsed.is_finite() or parsed <= 0 or (whole and parsed != parsed.to_integral_value()):
        raise _invalid(f"{field_name}必须为正数")
    return value


def validate_task_action_scope(
    action_key: str, params: Mapping[str, object] | None = None
) -> TuiTaskScope | None:
    """Validate and narrow one known task action's parameters.

    Unknown action keys return ``None`` so existing professional actions keep
    their prior execution semantics.  Known TUX09 actions reject undeclared
    parameters, including actor overrides such as ``user_id``.
    """

    if not isinstance(action_key, str) or action_key not in _KNOWN_ACTION_KEYS:
        return None

    values = _copy_params(params)
    temporary_target_weights: str | None = None
    reference_price_basis: Literal["market", "published_close"] | None = None
    if action_key == "account-inspection.run":
        if "reference_price_basis" in values:
            raw_basis = values.pop("reference_price_basis")
            if type(raw_basis) is not str or raw_basis not in ("market", "published_close"):
                raise _invalid("请选择有效的预览价格口径")
            reference_price_basis = cast(Literal["market", "published_close"], raw_basis)
        raw_targets = values.pop("temporary_target_weights", None)
        if raw_targets is not None:
            if type(raw_targets) is not str or len(raw_targets) > 2048:
                raise _invalid("临时目标必须是有效的证券比例文本")
            if raw_targets.strip():
                temporary_target_weights = raw_targets
    normalized = _require_fields(action_key, values)
    typed_action_key = cast(TuiTaskActionKey, action_key)
    return TuiTaskScope(
        action_key=typed_action_key,
        params=MappingProxyType(normalized),
        temporary_target_weights=temporary_target_weights,
        reference_price_basis=reference_price_basis,
    )


__all__ = [
    "TuiTaskActionKey",
    "TuiTaskScope",
    "TuiTaskScopeError",
    "validate_task_action_scope",
]
