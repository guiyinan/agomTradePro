"""Runtime owner actions for simulated-trade fee evidence and confirmation."""

from __future__ import annotations

from typing import Any

from apps.simulated_trading.application.fee_correction_evidence import MAX_UPLOAD_BYTES

_SCREEN = "execution.accounts"
_MODULE = "daily-decisions"
_SOURCE = "approved:runtime-simulated-fee-correction"
_POLICY = "simulated-trading.fee-correction-policy"
_POLICY_SAVE = "simulated-trading.fee-correction-policy-save"
_POLICY_DISABLE = "simulated-trading.fee-correction-policy-disable"
_PREVIEW = "simulated-trading.fee-correction-preview"
_CONFIRM = "simulated-trading.fee-correction-confirm"
_HEAD = "simulated-trading.fee-correction-head"


def _action(
    *,
    key: str,
    label: str,
    endpoint: str,
    method: str,
    intent: str,
    description: str,
    sequence: int,
    fields: list[dict[str, Any]],
    risk: str = "read",
    effect: str = "read",
    confirmation_required: bool = False,
    task_tier: str = "support",
    result_continuation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded owner action for the existing account screen."""

    action: dict[str, Any] = {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "intent": intent,
        "risk": risk,
        "audience": "authenticated",
        "effect": effect,
        "confirmation_required": confirmation_required,
        "audit_required": risk == "write",
        "requires_password": False,
        "session_auth_required": True,
        "sensitive_level": "high" if risk == "write" else "none",
        "raw_debug": False,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": description,
        "source": _SOURCE,
        "task_group": "06 模拟交易记录",
        "sequence": sequence,
        "task_tier": task_tier,
        "submit_label": label,
        "fields": fields,
        "view_model": {"kind": "detail"},
    }
    if result_continuation is not None:
        action["result_continuation"] = result_continuation
    return action


def _account_field(*, hidden: bool = False) -> dict[str, Any]:
    """Describe the account path parameter or its continuation-bound form."""

    field: dict[str, Any] = {
        "key": "account_id",
        "label": "账户编号",
        "binding": "body" if hidden else "path",
        "input_type": "hidden" if hidden else "number",
        "value_type": "string" if hidden else "integer",
        "required": True,
        **({"presentation_semantic": "api_token"} if hidden else {}),
    }
    if not hidden:
        field["min"] = 1
    return field


def _trade_field(*, hidden: bool = False) -> dict[str, Any]:
    """Describe the selected trade path parameter or its hidden scope copy."""

    field: dict[str, Any] = {
        "key": "trade_id",
        "label": "成交编号",
        "binding": "body" if hidden else "path",
        "input_type": "hidden" if hidden else "number",
        "value_type": "string" if hidden else "integer",
        "required": True,
        **({"presentation_semantic": "api_token"} if hidden else {}),
    }
    if not hidden:
        field["min"] = 1
    return field


def _hidden_body_field(
    key: str,
    *,
    value_type: str = "string",
    default: object | None = None,
) -> dict[str, Any]:
    """Describe one non-visible owner request field without a displayed default."""

    field: dict[str, Any] = {
        "key": key,
        "label": key,
        "binding": "body",
        "input_type": "hidden",
        "value_type": value_type,
        "required": True,
    }
    if value_type == "string":
        field["presentation_semantic"] = "api_token"
    if default is not None:
        field["default"] = default
    return field


def _boolean_choice_field(key: str, label: str, *, description: str) -> dict[str, Any]:
    """Require the owner to choose a boolean explicitly instead of defaulting it."""

    return {
        "key": key,
        "label": label,
        "binding": "body",
        "input_type": "select",
        "value_type": "boolean",
        "required": True,
        "options": [
            {"value": "", "label": "请选择"},
            {"value": "true", "label": "是"},
            {"value": "false", "label": "否"},
        ],
        "placeholder": description,
    }


def _policy_endpoint() -> str:
    """Return the current policy route shared by read, update and disable actions."""

    return "/api/simulated-trading/accounts/<int:account_id>/fee-correction-policy/"


RUNTIME_FEE_CORRECTION_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        key=_POLICY,
        label="查看费用材料策略",
        endpoint=_policy_endpoint(),
        method="GET",
        intent="read_owned_simulated_fee_correction_policy",
        description="查看本人账户的费用材料使用状态和有效期。新账户默认停用。",
        sequence=815,
        task_tier="operation",
        fields=[_account_field()],
    ),
    _action(
        key=_POLICY_SAVE,
        label="设置费用材料策略",
        endpoint=_policy_endpoint(),
        method="PUT",
        intent="save_owned_simulated_fee_correction_policy",
        description=(
            "明示选择是否启用及是否允许账户所有者声明材料。启用时必须填写账本币种；"
            "材料声明不代表券商或发行方认证。"
        ),
        sequence=816,
        task_tier="operation",
        fields=[
            _account_field(hidden=True),
            _hidden_body_field("expected_version", value_type="integer"),
            _boolean_choice_field("enabled", "启用费用材料策略", description="必须明确选择。"),
            _boolean_choice_field(
                "allow_operator_attested_upload",
                "允许所有者声明费用材料",
                description="允许上传时仍须明确确认材料未经券商或发行方认证。",
            ),
            {
                "key": "ledger_currency",
                "label": "账本币种",
                "binding": "body",
                "input_type": "text",
                "value_type": "string",
                "required": True,
                "placeholder": "启用策略时填写已有账本使用的三位币种代码",
            },
            {
                "key": "valid_from",
                "label": "策略开始时间",
                "binding": "body",
                "input_type": "hidden",
                "value_type": "datetime",
                "required": False,
            },
            {
                "key": "valid_until",
                "label": "策略结束时间",
                "binding": "body",
                "input_type": "hidden",
                "value_type": "datetime",
                "required": False,
            },
            _boolean_choice_field(
                "attestation_acknowledged",
                "确认材料声明范围",
                description="确认费用材料是账户所有者声明，不是券商或发行方认证。",
            ),
        ],
        risk="write",
        effect="update",
        confirmation_required=True,
    ),
    _action(
        key=_POLICY_DISABLE,
        label="停用费用材料策略",
        endpoint=_policy_endpoint(),
        method="PUT",
        intent="disable_owned_simulated_fee_correction_policy",
        description="停用费用材料资格，并保留当前币种和有效期。提交前还需确认。",
        sequence=817,
        fields=[
            _account_field(hidden=True),
            _hidden_body_field("expected_version", value_type="integer"),
            _hidden_body_field("enabled", value_type="boolean", default=False),
            _hidden_body_field(
                "allow_operator_attested_upload", value_type="boolean", default=False
            ),
            {
                "key": "ledger_currency",
                "label": "当前账本币种",
                "binding": "body",
                "input_type": "hidden",
                "value_type": "string",
                "required": False,
            },
            {
                "key": "valid_from",
                "label": "当前策略开始时间",
                "binding": "body",
                "input_type": "hidden",
                "value_type": "datetime",
                "required": False,
            },
            {
                "key": "valid_until",
                "label": "当前策略结束时间",
                "binding": "body",
                "input_type": "hidden",
                "value_type": "datetime",
                "required": False,
            },
            _hidden_body_field("attestation_acknowledged", value_type="boolean", default=False),
        ],
        risk="write",
        effect="update",
        confirmation_required=True,
    ),
    _action(
        key=_PREVIEW,
        label="预览成交费用更正",
        endpoint=(
            "/api/simulated-trading/accounts/<int:account_id>/trades/"
            "<int:trade_id>/fee-correction-preview/"
        ),
        method="POST",
        intent="preview_owner_attested_simulated_fee_correction",
        description=(
            "选择本人账户中的成交并上传受支持的 UTF-8 费用 CSV。预览仅保存和核对材料，"
            "不会修改现金或成交费用。仅接受表头为 schema_version、currency_code、"
            "source_account_ref、source_trade_ref、asset_code、side、quantity、price、amount、"
            "execution_at、source_observed_at、commission、transfer_fee、stamp_duty 的系统费用表；"
            "schema_version 固定为 operator-fee-evidence.v2，source_observed_at 保留材料来源时点。"
            "材料为账户所有者声明，未经券商或发行方认证。"
        ),
        sequence=818,
        fields=[
            _account_field(),
            _trade_field(),
            {
                "key": "csv_text",
                "label": "费用 CSV 文件（UTF-8）",
                "binding": "body",
                "input_type": "file",
                "value_type": "string",
                "required": True,
                "accept": ".csv,text/csv",
                "file_name_field": "original_filename",
                "max_bytes": MAX_UPLOAD_BYTES,
            },
            _hidden_body_field("original_filename"),
            _boolean_choice_field(
                "attestation_acknowledged",
                "确认费用材料声明",
                description="请明确确认材料是账户所有者声明，不代表券商或发行方认证。",
            ),
        ],
        risk="write",
        effect="create",
        confirmation_required=True,
        result_continuation={
            "target_action_key": _CONFIRM,
            "field_map": {
                "account_id": "account_id",
                "trade_id": "trade_id",
                "confirmation_token": "confirmation_token",
            },
            "reuse_source_idempotency_key": True,
            "readback_action_key": _HEAD,
        },
    ),
    _action(
        key=_CONFIRM,
        label="确认费用更正入账",
        endpoint=(
            "/api/simulated-trading/accounts/<int:account_id>/trades/"
            "<int:trade_id>/fee-corrections/confirm/"
        ),
        method="POST",
        intent="confirm_owner_simulated_fee_correction",
        description="提交原预览对应的确认。仅在二次确认后入账；结果不确定时查询原请求。",
        sequence=819,
        fields=[
            _account_field(hidden=True),
            _trade_field(hidden=True),
            _hidden_body_field("confirmation_token"),
        ],
        risk="write",
        effect="update",
        confirmation_required=True,
    ),
    _action(
        key=_HEAD,
        label="核对费用更正结果",
        endpoint=(
            "/api/simulated-trading/accounts/<int:account_id>/trades/"
            "<int:trade_id>/fee-corrections/head/"
        ),
        method="GET",
        intent="read_owned_simulated_fee_correction_result",
        description="按原请求核对费用更正结果；没有回执时仍属于待核对状态。",
        sequence=820,
        fields=[_account_field(hidden=True), _trade_field(hidden=True)],
    ),
)


__all__: tuple[str, ...] = ("RUNTIME_FEE_CORRECTION_ACTIONS",)
