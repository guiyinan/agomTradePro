"""Pure scope contracts for the TUX09 task actions.

This module narrows task parameters before an executor is allowed to bind an
endpoint.  It does not identify the authenticated actor or perform access
checks; owner services remain responsible for those decisions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
}


class TuiTaskScopeError(InvalidInputError):
    """Identify a task-scope input that cannot be safely bound to an owner call."""

    default_message = "任务参数无效，请重新选择账户或组合"
    default_code = "TUI_TASK_SCOPE_INVALID"


@dataclass(frozen=True, slots=True)
class TuiTaskScope:
    """The only endpoint parameters a known TUX09 action may receive."""

    action_key: TuiTaskActionKey
    params: Mapping[str, int]
    temporary_target_weights: str | None = None
    reference_price_basis: Literal["market", "published_close"] | None = None

    def to_params(self) -> dict[str, int | str]:
        """Return the narrow account-inspection body and integer scope values."""

        values: dict[str, int | str] = dict(self.params)
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


def _require_fields(action_key: str, values: Mapping[str, object]) -> dict[str, int]:
    """Validate a known action's declared fields and return normalized values."""

    allowed = _ALLOWED_FIELDS[action_key]
    unknown = set(values).difference(allowed)
    if unknown:
        raise _invalid("任务参数包含未声明字段")

    normalized: dict[str, int] = {}
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
        normalized["page_size"] = _positive_integer(page_size, "每页持仓数")
        if normalized["page_size"] > 100:
            raise _invalid("每页持仓数不能超过100")
        return normalized

    if action_key == "portfolio-check.portfolios":
        normalized["page"] = _positive_integer(values.get("page", 1), "页码")
        return normalized

    if action_key in _NO_PARAMS:
        return normalized

    raise _invalid("任务参数无法识别")


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
