"""Personal QMT pairing and staff market-source approval tasks."""

from typing import Any


def _field(key: str, label: str, *, binding: str = "body", numeric: bool = False) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "binding": binding,
        "required": True,
        "input_type": "number" if numeric else "text",
        "value_type": ("integer" if key == "provider_id" else "decimal") if numeric else "string",
    }


def _action(
    key: str,
    label: str,
    fields: list[dict[str, Any]],
    *,
    control: bool = False,
    admin: bool = False,
    read: bool = False,
) -> dict[str, Any]:
    return {
        "key": f"qmt-bridge.{key}",
        "label": label,
        "endpoint": "/api/data-center/qmt-bridge/bindings/" + ("{binding_id}/" if control else ""),
        "method": "GET" if read else "POST",
        "intent": f"qmt_bridge_{key}",
        "risk": "read" if read else "write",
        "effect": "read" if read else "update",
        "confirmation_required": not read,
        "audit_required": not read,
        "screen_key": "broker-execution.qmt-setup" if admin else "account.self-service",
        "module_key": "system-governance" if admin else "personal-settings",
        "audience": "admin" if admin else "authenticated",
        "view_type": "datagrid" if read else "detail",
        "fields": fields,
        "description": "绑定本人的 Windows QMT 到当前服务器；行情与交易分别授权。",
        "source": "approved:runtime-qmt-bridge",
        "task_group": "05 QMT 整体桥",
        "task_tier": "support" if read else "operation",
        "sequence": 510,
        "view_model": (
            {
                "kind": "datagrid",
                "rows_path": "data",
                "columns": [
                    {"key": "agent_id", "label": "本地桥"},
                    {"key": "binding_id", "label": "绑定编号"},
                    {"key": "paired", "label": "已配对"},
                    {"key": "enabled", "label": "采集已启用"},
                    {"key": "observed_at", "label": "观测时间"},
                    {"key": "freshness", "label": "行情时效"},
                ],
            }
            if read
            else {
                "kind": "detail",
                "field_presentations": {
                    "pairing_code": "secret",
                    "server_url": "copyable",
                    "binding_id": "copyable",
                    "agent_id": "copyable",
                    "pair_command": "multiline",
                },
            }
        ),
        "result_semantics": ["primary_list"] if read else ["copyable_secret", "primary_status"],
    }


def _control(key: str, label: str) -> dict[str, Any]:
    action = _action(key, label, [_field("binding_id", "绑定编号", binding="path")], control=True)
    action["fields"].append(
        {
            "key": "action",
            "label": "操作",
            "binding": "body",
            "input_type": "text",
            "value_type": "string",
            "default": key,
            "required": True,
        }
    )
    return action


RUNTIME_QMT_BRIDGE_ACTIONS: tuple[dict[str, Any], ...] = (
    _action("list", "我的 QMT 桥", [], read=True),
    _action(
        "create",
        "绑定我的 QMT 桥",
        [_field("agent_id", "本地桥名称"), _field("assets", "采集标的（用逗号分隔代码）")],
    ),
    *(
        _control(key, label)
        for key, label in (
            ("pause", "暂停行情采集"),
            ("resume", "恢复行情采集"),
            ("repair", "重新配对本地桥"),
            ("revoke", "撤销本地桥绑定"),
        )
    ),
    _action(
        "approve",
        "批准 QMT 行情接入",
        [
            _field("binding_id", "绑定编号", binding="path"),
            {
                "key": "action",
                "label": "操作",
                "binding": "body",
                "input_type": "text",
                "value_type": "string",
                "default": "approve",
                "required": True,
            },
            _field("provider_id", "QMT 数据源编号", numeric=True),
            _field("quote_multiplier", "快照成交量转股数倍率", numeric=True),
            _field("bar_multiplier", "日线成交量转股数倍率", numeric=True),
        ],
        control=True,
        admin=True,
    ),
)
