"""Runtime consent actions for the existing simulated-account TUI screen."""

from __future__ import annotations

from typing import Any

from apps.terminal.application.tui_simulated_corporate_action_consent_result import (
    CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY,
    CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY,
    CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY,
    CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY,
)

_SCREEN = "execution.accounts"
_MODULE = "daily-decisions"
_SOURCE = "approved:runtime-simulated-corporate-action-consent"
_ENDPOINT = "/api/simulated-trading/accounts/<int:account_id>/corporate-action-consent/"


def _action(
    *,
    key: str,
    label: str,
    endpoint: str,
    intent: str,
    description: str,
    sequence: int,
    fields: list[dict[str, Any]],
    risk: str = "read",
    effect: str = "read",
    confirmation_required: bool = False,
    result_continuation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one session-bound consent task on the existing account screen."""

    action: dict[str, Any] = {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": "POST",
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
        "task_tier": "support",
        "submit_label": label,
        "fields": fields,
        "view_model": {"kind": "detail"},
    }
    if result_continuation is not None:
        action["result_continuation"] = result_continuation
        action["result_panel_key"] = "simulated-account-workspace"
    return action


def _account_selector_field() -> dict[str, Any]:
    """Show the selected account in a preview form before binding its endpoint path."""

    return {
        "key": "account_id",
        "label": "账户编号",
        "binding": "body",
        "input_type": "number",
        "value_type": "integer",
        "required": True,
        "min": 1,
    }


def _hidden_continuation_field(key: str, label: str) -> dict[str, Any]:
    """Describe a hidden value supplied only by a validated owner result."""

    return {
        "key": key,
        "label": label,
        "binding": "body",
        "input_type": "hidden",
        "value_type": "string",
        "required": True,
        "presentation_semantic": "api_token",
    }


def _capability_choice_field(key: str, label: str) -> dict[str, Any]:
    """Collect each explicit choice, including unchecked false, without requiring a tick."""
    return {
        "key": key,
        "label": label,
        "binding": "body",
        "input_type": "checkbox",
        "value_type": "boolean",
        "required": False,
        "default": False,
    }


def _explicit_confirmation_field(label: str, description: str) -> dict[str, Any]:
    """Require a separate explicit body acknowledgement without a default."""

    return {
        "key": "confirmed",
        "label": label,
        "binding": "body",
        "input_type": "select",
        "value_type": "boolean",
        "required": True,
        "options": [
            {"value": "", "label": "请选择"},
            {"value": "true", "label": "确认"},
            {"value": "false", "label": "暂不确认"},
        ],
        "placeholder": description,
    }


RUNTIME_CORPORATE_ACTION_CONSENT_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        key=CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY,
        label="读取模拟授权确认资料",
        endpoint=f"{_ENDPOINT}prepare/",
        intent="prepare_owner_simulated_corporate_action_consent",
        description=(
            "先勾选本次同意的能力，至少一项，再读取来源观测时间、有效期和完整条款。"
            "新授权将替换原授权范围；此步骤只准备资料，不保存授权，也不实际入账。"
        ),
        sequence=830,
        fields=[
            _account_selector_field(),
            _capability_choice_field("cash_dividend", "现金分红模拟权益与支付日模拟到账"),
            _capability_choice_field("tax_assessment", "股息红利税额评估与证据留存"),
            _capability_choice_field("tax_withholding", "股息红利模拟扣税与欠税记录"),
        ],
        result_continuation={
            "target_action_key": CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY,
            "field_map": {
                "account_id": "account_id",
                "consent_token": "consent_token",
            },
        },
    ),
    _action(
        key=CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY,
        label="明确同意模拟公司行为授权",
        endpoint=_ENDPOINT,
        intent="confirm_owner_simulated_corporate_action_consent",
        description=(
            "核对本人账户、所选能力、完整条款、来源观测与有限期限后，再明确确认。"
            "本操作仅保存所列授权，不会评估税额、扣税、入账或下单。"
        ),
        sequence=831,
        fields=[
            _hidden_continuation_field("account_id", "本人账户编号"),
            _hidden_continuation_field("consent_token", "本次授权确认凭证"),
            _explicit_confirmation_field(
                "确认保存模拟授权",
                "请明确选择确认；保存授权不会实际入账。",
            ),
        ],
        risk="write",
        effect="update",
        confirmation_required=True,
    ),
    _action(
        key=CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY,
        label="读取授权撤回确认资料",
        endpoint=f"{_ENDPOINT}withdraw/prepare/",
        intent="prepare_owner_simulated_corporate_action_consent_withdrawal",
        description=(
            "读取本人账户当前授权并准备单独撤回确认。此步骤只读取和准备资料，"
            "不会撤回授权或改变模拟账本。"
        ),
        sequence=832,
        fields=[_account_selector_field()],
        result_continuation={
            "target_action_key": CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY,
            "field_map": {
                "account_id": "account_id",
                "withdrawal_token": "withdrawal_token",
            },
        },
    ),
    _action(
        key=CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY,
        label="明确确认撤回模拟授权",
        endpoint=f"{_ENDPOINT}withdraw/",
        intent="withdraw_owner_simulated_corporate_action_consent",
        description=(
            "再次核对本人账户后明确确认撤回模拟公司行为授权。此操作仅撤回授权，"
            "不会调整现金、持仓或其他模拟账本，也不代表银行到账状态。"
        ),
        sequence=833,
        fields=[
            _hidden_continuation_field("account_id", "本人账户编号"),
            _hidden_continuation_field("withdrawal_token", "本次撤回确认凭证"),
            _explicit_confirmation_field(
                "确认撤回模拟授权",
                "请明确选择确认；撤回授权不会修改账本。",
            ),
        ],
        risk="write",
        effect="update",
        confirmation_required=True,
    ),
)


__all__: tuple[str, ...] = ("RUNTIME_CORPORATE_ACTION_CONSENT_ACTIONS",)
