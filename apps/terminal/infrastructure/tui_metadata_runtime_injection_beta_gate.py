"""Runtime TUI metadata for Beta Gate configuration and testing."""

from __future__ import annotations

from typing import Any

_SCREEN = "macro-regime.strategy"
_MODULE = "daily-decisions"
_SOURCE = "approved:runtime-beta-gate"


def _field(
    key: str,
    label: str,
    *,
    input_type: str = "text",
    binding: str = "body",
    value_type: str = "string",
    required: bool = False,
    default: str | bool | None = None,
    options: list[str] | None = None,
) -> dict[str, Any]:
    """Build one typed runtime field without duplicating metadata boilerplate."""

    field: dict[str, Any] = {
        "key": key,
        "label": label,
        "input_type": input_type,
        "required": required,
        "binding": binding,
        "value_type": value_type,
    }
    if default is not None:
        field["default"] = default
    if options is not None:
        field["options"] = options
    return field


def _action(
    *,
    key: str,
    label: str,
    endpoint: str,
    method: str,
    intent: str,
    view_type: str,
    description: str,
    sequence: int,
    fields: list[dict[str, Any]],
    view_model: dict[str, Any],
    risk: str = "read",
    effect: str | None = None,
    admin: bool = False,
) -> dict[str, Any]:
    """Build one Beta Gate action with a consistent task location."""

    action: dict[str, Any] = {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "intent": intent,
        "risk": "admin" if admin else risk,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": view_type,
        "description": description,
        "source": _SOURCE,
        "task_group": "03 Beta Gate 配置",
        "sequence": sequence,
        "task_tier": "support",
        "fields": fields,
        "view_model": view_model,
    }
    if effect is not None:
        action["effect"] = effect
        action["confirmation_required"] = True
    if admin:
        action["audience"] = "admin"
    return action


_CONFIG_ID = _field("pk", "配置 ID", binding="path", required=True)
_RISK_PROFILES = ["conservative", "balanced", "aggressive"]

RUNTIME_BETA_GATE_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        key="beta-gate.config-list",
        label="查看 Beta Gate 配置",
        endpoint="/api/beta-gate/configs/",
        method="GET",
        intent="list_beta_gate_configs",
        view_type="datagrid",
        description="查看当前或全部 Beta Gate 配置版本。",
        sequence=300,
        fields=[
            _field(
                "active_only",
                "仅看激活配置",
                input_type="select",
                binding="query",
                value_type="boolean",
                default="true",
                options=["true", "false"],
            )
        ],
        view_model={
            "kind": "datagrid",
            "rows_path": "results",
            "columns": [
                {"key": "config_id", "label": "配置 ID"},
                {"key": "risk_profile", "label": "风险画像"},
                {"key": "version", "label": "版本"},
                {"key": "is_active", "label": "激活"},
                {"key": "is_expired", "label": "过期"},
                {"key": "effective_date", "label": "生效日期"},
                {"key": "expires_at", "label": "过期日期"},
            ],
        },
    ),
    _action(
        key="beta-gate.config-detail",
        label="查看 Beta Gate 配置详情",
        endpoint="/api/beta-gate/configs/<pk>/",
        method="GET",
        intent="read_beta_gate_config",
        view_type="detail",
        description="查看一个 Beta Gate 配置的完整约束。",
        sequence=310,
        fields=[_CONFIG_ID],
        view_model={
            "kind": "detail",
            "title_path": "result.config_id",
            "status_path": "success",
        },
    ),
    _action(
        key="beta-gate.config-create",
        label="创建 Beta Gate 配置",
        endpoint="/api/beta-gate/configs/",
        method="POST",
        intent="create_beta_gate_config",
        view_type="detail",
        description="创建一个不可变的 Beta Gate 配置版本。",
        sequence=320,
        admin=True,
        effect="create",
        fields=[
            _field("config_id", "配置 ID（可选）"),
            _field(
                "risk_profile",
                "风险画像",
                input_type="select",
                required=True,
                default="balanced",
                options=_RISK_PROFILES,
            ),
            _field(
                "allowed_regimes",
                "允许的宏观象限（JSON 数组）",
                input_type="textarea",
                value_type="list",
            ),
            _field(
                "min_confidence",
                "最低置信度",
                input_type="number",
                value_type="float",
                default="0.3",
            ),
            _field(
                "max_policy_level",
                "最高政策档位",
                input_type="number",
                value_type="integer",
                default="2",
            ),
            _field(
                "veto_on_p3",
                "P3 一票否决",
                input_type="checkbox",
                value_type="boolean",
                default=True,
            ),
            _field(
                "max_total_position",
                "总仓位上限（%）",
                input_type="number",
                value_type="float",
                default="95",
            ),
            _field(
                "max_single_position",
                "单仓上限（%）",
                input_type="number",
                value_type="float",
                default="20",
            ),
        ],
        view_model={
            "kind": "detail",
            "title_path": "result.config_id",
            "status_path": "success",
        },
    ),
    _action(
        key="beta-gate.config-update",
        label="创建替代配置版本",
        endpoint="/api/beta-gate/configs/<pk>/",
        method="PATCH",
        intent="replace_beta_gate_config",
        view_type="detail",
        description="以不可变替换语义更新一个 Beta Gate 配置。",
        sequence=330,
        admin=True,
        effect="update",
        fields=[
            _CONFIG_ID,
            _field(
                "risk_profile",
                "风险画像",
                input_type="select",
                options=["", *_RISK_PROFILES],
            ),
            *[
                _field(key, label, input_type="textarea", value_type="object")
                for key, label in (
                    ("regime_constraints", "宏观象限约束（JSON）"),
                    ("policy_constraints", "Policy 约束（JSON）"),
                    ("portfolio_constraints", "组合约束（JSON）"),
                )
            ],
        ],
        view_model={
            "kind": "detail",
            "title_path": "result.config_id",
            "status_path": "success",
        },
    ),
    _action(
        key="beta-gate.config-delete",
        label="停用 Beta Gate 配置",
        endpoint="/api/beta-gate/configs/<pk>/",
        method="DELETE",
        intent="deactivate_beta_gate_config",
        view_type="detail",
        description="软停用一个配置并保留审计历史。",
        sequence=340,
        admin=True,
        effect="delete",
        fields=[_CONFIG_ID],
        view_model={"kind": "detail"},
    ),
    _action(
        key="beta-gate.test-assets",
        label="测试资产是否通过 Beta Gate",
        endpoint="/api/beta-gate/test/",
        method="POST",
        intent="evaluate_beta_gate_assets",
        view_type="datagrid",
        description="使用指定市场上下文做无持久化的批量闸门评估。",
        sequence=350,
        risk="write",
        effect="execute",
        fields=[
            _field(
                "asset_codes",
                "资产代码（JSON 数组）",
                input_type="textarea",
                value_type="list",
                required=True,
            ),
            _field("asset_class", "资产类别", required=True),
            _field(
                "current_regime",
                "当前宏观象限",
                input_type="select",
                required=True,
                options=["Recovery", "Overheat", "Deflation", "Stagflation"],
            ),
            _field(
                "regime_confidence",
                "宏观象限置信度",
                input_type="number",
                value_type="float",
                required=True,
            ),
            _field(
                "policy_level",
                "政策档位",
                input_type="number",
                value_type="integer",
                required=True,
            ),
            _field(
                "risk_profile",
                "风险画像",
                input_type="select",
                default="balanced",
                options=_RISK_PROFILES,
            ),
        ],
        view_model={"kind": "datagrid", "rows_path": "results"},
    ),
    _action(
        key="beta-gate.version-compare",
        label="对比 Beta Gate 版本",
        endpoint="/api/beta-gate/version/compare/",
        method="GET",
        intent="compare_beta_gate_versions",
        view_type="detail",
        description="列出近期版本，或对比两个指定配置版本。",
        sequence=360,
        fields=[
            _field("version1", "版本一 ID", binding="query"),
            _field("version2", "版本二 ID", binding="query"),
        ],
        view_model={"kind": "detail", "status_path": "success"},
    ),
    _action(
        key="beta-gate.rollback",
        label="回滚到指定 Beta Gate 配置",
        endpoint="/api/beta-gate/config/rollback/<config_id>/",
        method="POST",
        intent="rollback_beta_gate_config",
        view_type="detail",
        description="把指定历史配置重新激活为当前配置。",
        sequence=370,
        admin=True,
        effect="update",
        fields=[_field("config_id", "配置 ID", binding="path", required=True)],
        view_model={
            "kind": "detail",
            "title_path": "message",
            "status_path": "success",
        },
    ),
)
