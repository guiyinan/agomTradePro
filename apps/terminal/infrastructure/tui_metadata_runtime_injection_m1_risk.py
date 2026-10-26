"""Owner-scoped M1 risk publication actions for the account-inspection task."""

from __future__ import annotations

from typing import Any

_ACCOUNT_INSPECTION_SCREEN = "task.account-inspection"
_ACCOUNT_INSPECTION_SOURCE = "approved:runtime-m1-account-inspection-preview"

_APPLICABILITY_OPTIONS = [
    {"value": "", "label": "请选择状态"},
    {"value": "applicable", "label": "适用：填写具体限额"},
    {"value": "not_applicable", "label": "不适用：需要说明原因"},
    {"value": "unknown", "label": "未知：当前将阻止买入"},
]


def _owner_account_field() -> dict[str, Any]:
    """Use the existing authenticated owner-account option decorator."""

    return {
        "key": "account_id",
        "label": "选择本人账户",
        "binding": "path",
        "input_type": "select",
        "value_type": "integer",
        "required": True,
        "default": "",
        "options": [{"value": "", "label": "请选择本人账户"}],
        "presentation_semantic": "primary_selector",
    }


def _condition_fields(dimension: str, label: str) -> list[dict[str, Any]]:
    """Describe one flat condition with visible applicability and percentage fields."""

    return [
        {
            "key": f"{dimension}_applicability",
            "label": f"{label}适用状态",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": True,
            "options": [dict(option) for option in _APPLICABILITY_OPTIONS],
        },
        {
            "key": f"{dimension}_limit_pct",
            "label": f"{label}限额（%）",
            "binding": "body",
            "input_type": "text",
            "value_type": "decimal",
            "required": False,
            "min": 0,
            "max": 100,
            "unit": "%",
            "placeholder": "适用时填写0到100之间的百分数，例如20.5；其他状态留空",
        },
        {
            "key": f"{dimension}_not_applicable_reason",
            "label": f"{label}不适用原因",
            "binding": "body",
            "input_type": "textarea",
            "value_type": "string",
            "required": False,
            "placeholder": "仅选择“不适用”时填写；系统会校验原因",
        },
    ]


RUNTIME_M1_RISK_POLICY_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "account-inspection.m1-risk-policy.publish",
        "label": "发布账户风险约束",
        "endpoint": "/api/account/accounts/<int:account_id>/m1-risk-policy-revisions/",
        "method": "POST",
        "intent": "publish_owner_m1_account_risk_revision",
        "risk": "write",
        "audience": "authenticated",
        "effect": "create",
        "confirmation_required": True,
        "audit_required": True,
        "session_auth_required": True,
        "screen_key": _ACCOUNT_INSPECTION_SCREEN,
        "module_key": "daily-decisions",
        "view_type": "detail",
        "description": (
            "为所选本人账户发布风险约束。提交时会绑定当前可核验的策略和仓位规则；"
            "账户或策略规则变化后，需要重新发布。"
        ),
        "source": _ACCOUNT_INSPECTION_SOURCE,
        "task_group": "04 风险约束",
        "sequence": 56,
        "task_tier": "support",
        "submit_label": "确认发布风险约束",
        "raw_debug": False,
        "fields": [
            _owner_account_field(),
            {
                "key": "effective_from",
                "label": "生效时间（需包含时区）",
                "binding": "body",
                "input_type": "text",
                "value_type": "datetime",
                "required": True,
                "placeholder": "例如 2027-02-01T09:00:00+08:00；须晚于当前时间",
            },
            {
                "key": "effective_until",
                "label": "失效时间（需包含时区）",
                "binding": "body",
                "input_type": "text",
                "value_type": "datetime",
                "required": True,
                "placeholder": "例如 2027-03-01T09:00:00+08:00；须晚于生效时间",
            },
            {
                "key": "reason",
                "label": "发布原因",
                "binding": "body",
                "input_type": "textarea",
                "value_type": "string",
                "required": True,
                "placeholder": "说明本次风险约束的依据",
            },
            *_condition_fields("max_single_position", "单个标的"),
            *_condition_fields("max_total_position", "账户总持仓"),
            *_condition_fields("max_stop_loss", "止损"),
        ],
        "view_model": {"kind": "detail"},
    },
    {
        "key": "account-inspection.m1-risk-policy.revoke",
        "label": "撤销账户风险约束",
        "endpoint": (
            "/api/account/accounts/<int:account_id>/m1-risk-policy-revisions/"
            "<uuid:risk_policy_version>/revoke/"
        ),
        "method": "POST",
        "intent": "revoke_owner_m1_account_risk_revision",
        "risk": "write",
        "audience": "authenticated",
        "effect": "update",
        "confirmation_required": True,
        "audit_required": True,
        "session_auth_required": True,
        "screen_key": _ACCOUNT_INSPECTION_SCREEN,
        "module_key": "daily-decisions",
        "view_type": "detail",
        "description": (
            "撤销本人账户的一条指定风险约束版本。请从发布回执复制完整版本编号并填写撤销原因。"
        ),
        "source": _ACCOUNT_INSPECTION_SOURCE,
        "task_group": "04 风险约束",
        "sequence": 57,
        "task_tier": "support",
        "submit_label": "确认撤销风险约束",
        "raw_debug": False,
        "fields": [
            _owner_account_field(),
            {
                "key": "risk_policy_version",
                "label": "风险版本编号",
                "binding": "path",
                "input_type": "text",
                "value_type": "string",
                "required": True,
                "placeholder": "粘贴发布回执中的完整版本编号",
            },
            {
                "key": "reason",
                "label": "撤销原因",
                "binding": "body",
                "input_type": "textarea",
                "value_type": "string",
                "required": True,
                "placeholder": "说明撤销这条风险约束的原因",
            },
        ],
        "view_model": {"kind": "detail"},
    },
)


__all__: tuple[str, ...] = ("RUNTIME_M1_RISK_POLICY_ACTIONS",)
