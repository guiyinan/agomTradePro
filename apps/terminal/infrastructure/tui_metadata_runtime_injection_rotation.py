"""Runtime TUI metadata for rotation workbenches."""

from __future__ import annotations

from typing import Any

_SCREEN = "macro-regime.strategy"
_MODULE = "daily-decisions"
_SOURCE = "approved:runtime-rotation"


def _field(
    key: str,
    label: str,
    *,
    binding: str = "body",
    input_type: str = "text",
    value_type: str = "string",
    required: bool = False,
    default: str | bool | None = None,
) -> dict[str, Any]:
    """Build one rotation action field."""

    result: dict[str, Any] = {
        "key": key,
        "label": label,
        "binding": binding,
        "input_type": input_type,
        "value_type": value_type,
        "required": required,
    }
    if default is not None:
        result["default"] = default
    return result


def _asset_fields(*, create: bool) -> list[dict[str, Any]]:
    fields = [
        _field("name", "资产名称", required=create),
        _field("category", "资产类别", required=create),
        _field("description", "说明", input_type="textarea"),
        _field("underlying_index", "跟踪指数"),
        _field("currency", "币种"),
        _field("is_active", "启用", input_type="checkbox", value_type="boolean", default=True),
    ]
    if create:
        fields.insert(0, _field("code", "资产代码", required=True))
    return fields


def _action(
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
    *,
    admin: bool = False,
    effect: str | None = None,
) -> dict[str, Any]:
    """Build one action in the rotation asset task group."""

    result: dict[str, Any] = {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "intent": intent,
        "risk": "admin" if admin else "read",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": view_type,
        "description": description,
        "source": _SOURCE,
        "task_group": "04 轮动资产池",
        "sequence": sequence,
        "task_tier": "support",
        "fields": fields,
        "view_model": view_model,
    }
    if admin:
        result["audience"] = "admin"
    if effect is not None:
        result["effect"] = effect
        result["confirmation_required"] = True
    return result


_CODE_PATH = _field("code", "资产代码", binding="path", required=True)
_GRID_MODEL: dict[str, Any] = {
    "kind": "datagrid",
    "rows_path": "results",
    "columns": [
        {"key": "code", "label": "代码"},
        {"key": "name", "label": "名称"},
        {"key": "category", "label": "类别"},
        {"key": "underlying_index", "label": "跟踪指数"},
        {"key": "currency", "label": "币种"},
        {"key": "is_active", "label": "启用"},
        {"key": "updated_at", "label": "更新时间"},
    ],
}

RUNTIME_ROTATION_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        "rotation.asset-list",
        "查看轮动资产池",
        "/api/rotation/assets/",
        "GET",
        "list_rotation_assets",
        "datagrid",
        "筛选、搜索并导出当前轮动资产池。",
        400,
        [
            _field("category", "资产类别", binding="query"),
            _field(
                "is_active",
                "启用状态",
                binding="query",
                input_type="checkbox",
                value_type="boolean",
            ),
            _field("search", "搜索", binding="query"),
            _field("ordering", "排序字段", binding="query"),
        ],
        _GRID_MODEL,
    ),
    _action(
        "rotation.asset-detail",
        "查看轮动资产详情",
        "/api/rotation/assets/<code>/",
        "GET",
        "read_rotation_asset",
        "detail",
        "查看轮动资产的完整目录信息。",
        410,
        [_CODE_PATH],
        {"kind": "detail", "title_path": "name", "status_path": "is_active"},
    ),
    _action(
        "rotation.asset-create",
        "添加轮动资产",
        "/api/rotation/assets/",
        "POST",
        "create_rotation_asset",
        "detail",
        "向全局轮动资产目录添加资产。",
        420,
        _asset_fields(create=True),
        {"kind": "detail", "title_path": "name", "status_path": "is_active"},
        admin=True,
        effect="create",
    ),
    _action(
        "rotation.asset-update",
        "更新轮动资产",
        "/api/rotation/assets/<code>/",
        "PATCH",
        "update_rotation_asset",
        "detail",
        "更新一个轮动资产的目录属性。",
        430,
        [_CODE_PATH, *_asset_fields(create=False)],
        {"kind": "detail", "title_path": "name", "status_path": "is_active"},
        admin=True,
        effect="update",
    ),
    _action(
        "rotation.asset-delete",
        "停用或删除轮动资产",
        "/api/rotation/assets/<code>/",
        "DELETE",
        "delete_rotation_asset",
        "detail",
        "默认软停用资产；显式 hard=true 时物理删除。",
        440,
        [
            _CODE_PATH,
            _field(
                "hard",
                "物理删除",
                binding="query",
                input_type="checkbox",
                value_type="boolean",
                default=False,
            ),
        ],
        {"kind": "detail", "title_path": "code", "status_path": "status"},
        admin=True,
        effect="delete",
    ),
    _action(
        "rotation.asset-import-preview",
        "预览默认资产导入",
        "/api/rotation/assets/import-defaults-preview/",
        "GET",
        "preview_rotation_default_assets",
        "detail",
        "在写入前查看默认资产的新增、恢复和更新差异。",
        450,
        [],
        {"kind": "detail"},
        admin=True,
    ),
    _action(
        "rotation.asset-import",
        "导入默认轮动资产",
        "/api/rotation/assets/import-defaults/",
        "POST",
        "import_rotation_default_assets",
        "detail",
        "新增、恢复或更新默认轮动资产目录。",
        460,
        [],
        {"kind": "detail"},
        admin=True,
        effect="create",
    ),
    _action(
        "rotation.asset-prices",
        "查看轮动资产行情",
        "/api/rotation/assets/with_prices/",
        "GET",
        "read_rotation_assets_with_prices",
        "datagrid",
        "查看轮动资产的最新价格与动量信息。",
        470,
        [],
        {"kind": "datagrid"},
    ),
)


def _config_fields(*, include_id: bool, create: bool) -> list[dict[str, Any]]:
    """Return the complete persisted rotation-config form contract."""

    fields = [
        _field("name", "配置名称", required=create),
        _field("description", "说明", input_type="textarea"),
        {
            **_field(
                "strategy_type",
                "策略类型",
                input_type="select",
                required=create,
                default="momentum" if create else None,
            ),
            "options": [
                "regime_based",
                "momentum",
                "risk_parity",
                "mean_reversion",
                "custom",
            ],
        },
        _field("asset_universe", "资产池（JSON 数组）", input_type="textarea", value_type="list"),
        _field("params", "策略参数（JSON）", input_type="textarea", value_type="object"),
        _field("rebalance_frequency", "调仓频率", default="monthly" if create else None),
        _field("min_weight", "最小权重", input_type="number", value_type="float"),
        _field("max_weight", "最大权重", input_type="number", value_type="float"),
        _field("max_turnover", "最大换手率", input_type="number", value_type="float"),
        _field("lookback_period", "回溯周期", input_type="number", value_type="integer"),
        _field(
            "regime_allocations",
            "象限配置（JSON）",
            input_type="textarea",
            value_type="object",
        ),
        _field(
            "momentum_periods",
            "动量周期（JSON 数组）",
            input_type="textarea",
            value_type="list",
        ),
        _field("top_n", "选资产数量", input_type="number", value_type="integer"),
        _field(
            "is_active",
            "启用",
            input_type="checkbox",
            value_type="boolean",
            default=True if create else None,
        ),
    ]
    if include_id:
        fields.insert(0, _field("pk", "配置 ID", binding="path", required=True))
    return fields


def _config_action(
    key: str,
    label: str,
    endpoint: str,
    method: str,
    sequence: int,
    fields: list[dict[str, Any]],
    *,
    view_type: str = "detail",
    admin: bool = False,
    effect: str | None = None,
) -> dict[str, Any]:
    """Build one global rotation configuration action."""

    return _action(
        key,
        label,
        endpoint,
        method,
        key.replace("-", "_").replace(".", "_"),
        view_type,
        f"{label}。",
        sequence,
        fields,
        (
            {
                "kind": "datagrid",
                "rows_path": "results",
                "columns": [
                    {"key": "id", "label": "ID"},
                    {"key": "name", "label": "名称"},
                    {"key": "strategy_type", "label": "策略"},
                    {"key": "rebalance_frequency", "label": "调仓频率"},
                    {"key": "top_n", "label": "资产数"},
                    {"key": "is_active", "label": "启用"},
                    {"key": "updated_at", "label": "更新时间"},
                ],
            }
            if view_type == "datagrid"
            else {"kind": "detail", "title_path": "name", "status_path": "is_active"}
        ),
        admin=admin,
        effect=effect,
    ) | {"task_group": "05 轮动策略配置"}


RUNTIME_ROTATION_CONFIG_ACTIONS: tuple[dict[str, Any], ...] = (
    _config_action(
        "rotation.config-list",
        "查看轮动策略配置",
        "/api/rotation/configs/",
        "GET",
        500,
        [
            _field("is_active", "启用状态", binding="query"),
            _field("strategy_type", "策略类型", binding="query"),
            _field("rebalance_frequency", "调仓频率", binding="query"),
            _field("search", "搜索", binding="query"),
        ],
        view_type="datagrid",
    ),
    _config_action(
        "rotation.config-detail",
        "查看轮动配置详情",
        "/api/rotation/configs/<pk>/",
        "GET",
        510,
        [_field("pk", "配置 ID", binding="path", required=True)],
    ),
    _config_action(
        "rotation.config-create",
        "创建轮动策略配置",
        "/api/rotation/configs/",
        "POST",
        520,
        _config_fields(include_id=False, create=True),
        admin=True,
        effect="create",
    ),
    _config_action(
        "rotation.config-update",
        "更新轮动策略配置",
        "/api/rotation/configs/<pk>/",
        "PATCH",
        530,
        _config_fields(include_id=True, create=False),
        admin=True,
        effect="update",
    ),
    _config_action(
        "rotation.config-delete",
        "删除轮动策略配置",
        "/api/rotation/configs/<pk>/",
        "DELETE",
        540,
        [_field("pk", "配置 ID", binding="path", required=True)],
        admin=True,
        effect="delete",
    ),
    *[
        _config_action(
            f"rotation.config-{operation}",
            label,
            f"/api/rotation/configs/<pk>/{operation}/",
            "POST",
            sequence,
            [_field("pk", "配置 ID", binding="path", required=True)],
            admin=True,
            effect=effect,
        )
        for operation, label, sequence, effect in (
            ("activate", "启用轮动策略配置", 550, "toggle"),
            ("deactivate", "停用轮动策略配置", 560, "toggle"),
            ("generate_signal", "按配置生成轮动信号", 570, "execute"),
        )
    ],
)


def _scoped_action(
    key: str,
    label: str,
    endpoint: str,
    method: str,
    sequence: int,
    fields: list[dict[str, Any]],
    view_model: dict[str, Any],
    *,
    group: str,
    effect: str | None = None,
) -> dict[str, Any]:
    """Build an authenticated user-scoped rotation action."""

    action = _action(
        key,
        label,
        endpoint,
        method,
        key.replace("-", "_").replace(".", "_"),
        str(view_model["kind"]),
        f"{label}。",
        sequence,
        fields,
        view_model,
        effect=effect,
    ) | {"task_group": group}
    action["audience"] = "authenticated"
    if effect is not None:
        action["risk"] = "write"
    return action


_ACCOUNT_CONFIG_FIELDS = [
    _field("account", "账户 ID", input_type="number", value_type="integer", required=True),
    _field("base_config", "基础配置 ID", input_type="number", value_type="integer"),
    {
        **_field("risk_tolerance", "风险偏好", input_type="select", default="moderate"),
        "options": ["conservative", "moderate", "aggressive"],
    },
    _field(
        "regime_allocations",
        "象限配置（JSON）",
        input_type="textarea",
        value_type="object",
        required=True,
    ),
    _field(
        "is_enabled",
        "启用轮动",
        input_type="checkbox",
        value_type="boolean",
        default=True,
    ),
]

RUNTIME_ROTATION_SIGNAL_ACCOUNT_ACTIONS: tuple[dict[str, Any], ...] = (
    _scoped_action(
        "rotation.signal-list",
        "查看轮动信号",
        "/api/rotation/signals/",
        "GET",
        600,
        [
            _field("config", "配置 ID", binding="query"),
            _field("signal_date", "信号日期", binding="query", input_type="date", value_type="date"),
            _field("current_regime", "当前象限", binding="query"),
            _field("action_required", "建议操作", binding="query"),
        ],
        {
            "kind": "datagrid",
            "rows_path": "results",
            "columns": [
                {"key": "id", "label": "ID"},
                {"key": "config_name", "label": "配置"},
                {"key": "signal_date", "label": "日期"},
                {"key": "current_regime", "label": "象限"},
                {"key": "action_required", "label": "建议"},
                {"key": "data_quality", "label": "数据质量"},
                {"key": "is_stale", "label": "过期"},
                {"key": "actionable", "label": "可执行"},
            ],
        },
        group="06 轮动信号",
    ),
    _scoped_action(
        "rotation.signal-latest",
        "查看各配置最新轮动信号",
        "/api/rotation/signals/latest/",
        "GET",
        610,
        [],
        {"kind": "datagrid"},
        group="06 轮动信号",
    ),
    _scoped_action(
        "rotation.signal-detail",
        "查看轮动信号详情",
        "/api/rotation/signals/<pk>/",
        "GET",
        620,
        [_field("pk", "信号 ID", binding="path", required=True)],
        {"kind": "detail", "title_path": "config_name", "status_path": "actionable"},
        group="06 轮动信号",
    ),
    _scoped_action(
        "rotation.account-config-list",
        "查看我的账户轮动配置",
        "/api/rotation/account-configs/",
        "GET",
        700,
        [],
        {
            "kind": "datagrid",
            "rows_path": "results",
            "columns": [
                {"key": "id", "label": "ID"},
                {"key": "account", "label": "账户 ID"},
                {"key": "account_name", "label": "账户"},
                {"key": "risk_tolerance", "label": "风险偏好"},
                {"key": "base_config_name", "label": "基础配置"},
                {"key": "is_enabled", "label": "启用"},
                {"key": "updated_at", "label": "更新时间"},
            ],
        },
        group="07 账户轮动配置",
    ),
    _scoped_action(
        "rotation.account-config-detail",
        "查看账户轮动配置详情",
        "/api/rotation/account-configs/<pk>/",
        "GET",
        710,
        [_field("pk", "配置 ID", binding="path", required=True)],
        {"kind": "detail", "title_path": "account_name", "status_path": "is_enabled"},
        group="07 账户轮动配置",
    ),
    _scoped_action(
        "rotation.account-config-by-account",
        "按账户查看轮动配置",
        "/api/rotation/account-configs/by-account/<account_id>/",
        "GET",
        720,
        [_field("account_id", "账户 ID", binding="path", required=True)],
        {"kind": "detail", "title_path": "account_name", "status_path": "is_enabled"},
        group="07 账户轮动配置",
    ),
    _scoped_action(
        "rotation.account-config-create",
        "创建账户轮动配置",
        "/api/rotation/account-configs/",
        "POST",
        730,
        _ACCOUNT_CONFIG_FIELDS,
        {"kind": "detail", "title_path": "account_name", "status_path": "is_enabled"},
        group="07 账户轮动配置",
        effect="create",
    ),
    _scoped_action(
        "rotation.account-config-update",
        "更新账户轮动配置",
        "/api/rotation/account-configs/<pk>/",
        "PATCH",
        740,
        [
            _field("pk", "配置 ID", binding="path", required=True),
            *[{**field, "required": False} for field in _ACCOUNT_CONFIG_FIELDS],
        ],
        {"kind": "detail", "title_path": "account_name", "status_path": "is_enabled"},
        group="07 账户轮动配置",
        effect="update",
    ),
    _scoped_action(
        "rotation.account-config-delete",
        "删除账户轮动配置",
        "/api/rotation/account-configs/<pk>/",
        "DELETE",
        750,
        [_field("pk", "配置 ID", binding="path", required=True)],
        {"kind": "detail"},
        group="07 账户轮动配置",
        effect="delete",
    ),
    _scoped_action(
        "rotation.account-config-apply-template",
        "应用账户轮动模板",
        "/api/rotation/account-configs/<pk>/apply-template/",
        "POST",
        760,
        [
            _field("pk", "配置 ID", binding="path", required=True),
            _field("template_key", "模板 Key", required=True),
        ],
        {"kind": "detail", "title_path": "account_name", "status_path": "is_enabled"},
        group="07 账户轮动配置",
        effect="update",
    ),
    _scoped_action(
        "rotation.template-list",
        "查看轮动预设模板",
        "/api/rotation/templates/",
        "GET",
        770,
        [],
        {"kind": "datagrid", "rows_path": "results"},
        group="07 账户轮动配置",
    ),
)
