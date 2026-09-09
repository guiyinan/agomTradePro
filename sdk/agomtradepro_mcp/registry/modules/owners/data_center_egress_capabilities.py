"""Native governed capabilities for regional data-center egress configuration."""

from __future__ import annotations

from typing import Any

from agomtradepro_mcp.registry.manifest import CapabilityManifest


def _text(max_length: int, *, blank: bool = False) -> dict[str, Any]:
    return {"type": "string", "minLength": 0 if blank else 1, "maxLength": max_length}


POSITIVE_ID: dict[str, Any] = {"type": "integer", "minimum": 1}
ENDPOINT_FIELDS: dict[str, Any] = {
    "name": _text(120),
    "region": _text(40),
    "protocol": {"type": "string", "enum": ["http", "https"]},
    "host": _text(255),
    "port": {"type": "integer", "minimum": 1, "maximum": 65535},
    "enabled": {"type": "boolean", "description": "首次登记默认停用。"},
    "concurrency_limit": {"type": "integer", "minimum": 1, "maximum": 512},
    "credential_username": {
        **_text(4096, blank=True),
        "writeOnly": True,
        "description": "代理账号；省略或留空保留现值。预览和审计脱敏。",
    },
    "credential_password": {
        **_text(4096, blank=True),
        "writeOnly": True,
        "description": "代理密码；省略或留空保留现值。预览和审计脱敏。",
    },
    "clear_credentials": {"type": "boolean", "description": "显式清除代理认证。"},
}
RULE_FIELDS: dict[str, Any] = {
    "provider_id": POSITIVE_ID,
    "dataset_key": _text(120),
    "domain_pattern": _text(253),
    "deployment_region": _text(40),
    "strategy": {"type": "string", "enum": ["direct", "fixed", "direct_fallback"]},
    "fixed_egress_id": {"type": ["integer", "null"], "minimum": 1},
    "priority": {"type": "integer", "minimum": 1, "maximum": 1000000},
    "enabled": {"type": "boolean", "description": "首次登记默认停用。"},
}
CONTEXT_FIELDS: dict[str, Any] = {
    "provider_id": POSITIVE_ID,
    "dataset_key": {**_text(120), "description": "具体数据集，例如 equity.price.bar。"},
    "url": {
        **_text(2048),
        "format": "uri",
        "description": "具体 HTTP(S) 目标地址，不得包含账号、密码或片段。",
    },
    "deployment_region": {**_text(40), "description": "实际执行节点区域，不能使用通配符。"},
}


def _manifest(
    key: str,
    title: str,
    summary: str,
    fields: dict[str, Any],
    required: tuple[str, ...] = (),
    *,
    write: bool = False,
) -> CapabilityManifest:
    properties = dict(fields)
    if write:
        properties["idempotency_key"] = _text(200)
    return CapabilityManifest(
        capability_key=key,
        title=title,
        summary=summary,
        description=(
            summary + " 管理员专用；出口对应可访问的 HTTP(S) 代理，FRP 进程由部署配置管理。"
            "创建默认停用。停用固定出口前应先停用规则。诊断成功与否以 result.outcome 为准。"
            "写入和联网测试需先预览，再通过 agom_confirmation_resume 确认；"
            "确认和幂等记录只在当前 MCP 进程内有效。"
        ),
        owner_app="data_center",
        risk_level="high" if write else "low",
        executor_kind="internal_handler",
        executor_ref=key.replace(".", "_"),
        tags=("data_center", "egress", "frp", "frpc", "configuration", "出口", "转发"),
        input_schema={
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        requires_confirmation=write,
        confirmation_preview_arguments={"preview_only": True} if write else {},
        confirmation_commit_arguments={"preview_only": False} if write else {},
        idempotency="required" if write else "none",
        required_roles=("staff",),
        audit_tags=("data_center:egress", "mcp:native", "mcp:write" if write else "mcp:read"),
    )


MANIFESTS = [
    _manifest(
        "data_center.read.egress_endpoints", "数据出口清单", "查看已登记出口与凭据配置状态。", {}
    ),
    _manifest(
        "data_center.read.egress_endpoint",
        "数据出口详情",
        "查看指定出口。",
        {"endpoint_id": POSITIVE_ID},
        ("endpoint_id",),
    ),
    _manifest(
        "data_center.create.egress_endpoint",
        "登记数据出口",
        "预览并登记数据代理出口。",
        ENDPOINT_FIELDS,
        ("name", "region", "protocol", "host", "port"),
        write=True,
    ),
    _manifest(
        "data_center.update.egress_endpoint",
        "修改或启停数据出口",
        "只修改明确传入的字段；False 表示停用。",
        {"endpoint_id": POSITIVE_ID, **ENDPOINT_FIELDS},
        ("endpoint_id",),
        write=True,
    ),
    _manifest(
        "data_center.run.egress_endpoint_test",
        "测试指定出口",
        "确认后对指定出口联网测试；目标需符合已登记规则，停用规则也可作为测试许可。",
        {"endpoint_id": POSITIVE_ID, **CONTEXT_FIELDS},
        ("endpoint_id", *CONTEXT_FIELDS),
        write=True,
    ),
    _manifest(
        "data_center.read.egress_rules",
        "数据出网规则清单",
        "查看数据源、域名、数据集和区域的路由规则。",
        {},
    ),
    _manifest(
        "data_center.read.egress_rule",
        "数据出网规则详情",
        "查看指定规则。",
        {"rule_id": POSITIVE_ID},
        ("rule_id",),
    ),
    _manifest(
        "data_center.create.egress_rule",
        "登记数据出网规则",
        "预览并登记直连、固定出口或直连失败后备用出口规则。",
        RULE_FIELDS,
        (
            "provider_id",
            "dataset_key",
            "domain_pattern",
            "deployment_region",
            "strategy",
            "priority",
        ),
        write=True,
    ),
    _manifest(
        "data_center.update.egress_rule",
        "修改或启停数据出网规则",
        "只修改明确传入的字段；null 清除出口绑定。",
        {"rule_id": POSITIVE_ID, **RULE_FIELDS},
        ("rule_id",),
        write=True,
    ),
    _manifest(
        "data_center.read.egress_route_preview",
        "预览数据出网路径",
        "按具体请求查看命中规则；不进行联网测试。",
        CONTEXT_FIELDS,
        tuple(CONTEXT_FIELDS),
    ),
    _manifest(
        "data_center.run.egress_diagnostics",
        "诊断数据出网连接",
        "预览路由后确认联网诊断，返回各次请求尝试和阻断原因。",
        CONTEXT_FIELDS,
        tuple(CONTEXT_FIELDS),
        write=True,
    ),
]

EGRESS_MANIFESTS_BY_REF = {manifest.executor_ref: manifest for manifest in MANIFESTS}
