"""Readable, credential-free projections of data-egress diagnostic JSON."""

from collections.abc import Mapping
from typing import cast


def _record(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, dict) else {}


def _text(value: object) -> str:
    return str(value) if isinstance(value, (str, int, float)) else "未提供"


def build_egress_result(
    payload: Mapping[str, object], *, title: str, status_code: int
) -> dict[str, object]:
    """Show routing and each bounded attempt without dumping arbitrary response fields."""
    diagnostic = "outcome" in payload
    outcome = _text(payload.get("outcome"))
    succeeded = 200 <= status_code < 300 and (outcome == "success" if diagnostic else True)
    status = "连接成功" if succeeded and diagnostic else "路由预览"
    if not succeeded:
        status = "已阻断" if outcome == "blocked" else "未完成"
    route = _record(payload.get("route")) if diagnostic else payload
    fields: list[dict[str, str]] = []

    def add(key: str, label: str, value: object, presentation: str = "metadata") -> None:
        fields.append(
            {"key": key, "label": label, "value": _text(value), "presentation": presentation}
        )

    add("result", "结果", status)
    if diagnostic:
        add("message", "连接说明", payload.get("message") or status)
        if payload.get("error_code"):
            add("error_code", "错误标识", payload["error_code"])
    add("rule_id", "命中规则", route.get("rule_id") or "未命中")
    strategy = _text(route.get("strategy"))
    add(
        "strategy",
        "出网策略",
        {"direct": "直连", "fixed": "固定出口", "direct_fallback": "直连失败后使用备用出口"}.get(
            strategy, "未确定"
        ),
    )
    if "egress_id" in route:
        add(
            "egress_id",
            "选定出口",
            route.get("egress_id") if route.get("egress_id") is not None else "直连",
        )
    if route.get("matched_domain"):
        add("matched_domain", "匹配域名", route["matched_domain"])
    reasons = {
        "no_matching_rule": "未命中已启用规则，使用默认直连路径",
        "matched_rule": "已按优先级匹配规则",
        "endpoint_test": "仅测试指定出口",
        "blocked": "当前请求被阻断",
    }
    reason = _text(route.get("reason"))
    if reason in reasons:
        add("route_reason", "选择依据", reasons[reason])
    attempts = payload.get("attempts")
    lines: list[str] = []
    if isinstance(attempts, list):
        for index, raw in enumerate(attempts, start=1):
            attempt = _record(raw)
            exit_id = attempt.get("egress_id")
            exit_label = "直连" if exit_id is None else "出口 " + _text(exit_id)
            result = {"success": "成功", "failed": "失败", "blocked": "阻断"}.get(
                _text(attempt.get("outcome")), "未完成"
            )
            line = f"第 {index} 次：{exit_label} · {result}"
            if attempt.get("latency_ms") is not None:
                line += " · " + _text(attempt["latency_ms"]) + " ms"
            for key in ("message", "error_code", "observed_ip"):
                if attempt.get(key):
                    line += " · " + _text(attempt[key])
            lines.append(line)
    if diagnostic:
        add(
            "attempts",
            "连接尝试",
            "\n".join(lines) or "尚未发起连接，请检查匹配规则和出口配置。",
            "multiline",
        )
        add("checked_at", "检查时间", payload.get("checked_at"))
    return {
        "kind": "detail",
        "title": title,
        "status": status,
        "fields": fields,
        "business_summary": status,
        "blocking_reason": (
            ""
            if succeeded
            else _text(payload.get("message") or "请检查规则、出口和目标地址后重试。")
        ),
        "next_steps": ["预览不代表网络连通；请测试指定出口。"] if not diagnostic else [],
    }


def build_egress_saved_result(
    payload: Mapping[str, object], *, title: str, status_code: int
) -> dict[str, object]:
    """Present saved configuration with explicit state and reviewed field labels."""
    saved = 200 <= status_code < 300 and "id" in payload
    labels = {
        "id": "记录编号",
        "enabled": "启用状态",
        "name": "出口名称",
        "provider_id": "数据源编号",
        "dataset_key": "数据集",
        "region": "出口区域",
        "deployment_region": "执行节点区域",
        "domain_pattern": "目标域名",
        "strategy_label": "出网策略",
        "fixed_egress_id": "固定或备用出口编号",
        "priority": "优先级",
        "protocol": "连接方式",
        "host": "代理主机",
        "port": "代理端口",
        "concurrency_limit": "最大并发请求数",
        "username_configured": "已保存代理账号",
        "password_configured": "已保存代理密码",
    }
    fields: list[dict[str, str]] = []
    for key, label in labels.items():
        if key not in payload:
            continue
        value = payload[key]
        rendered = ("是" if value else "否") if isinstance(value, bool) else _text(value)
        fields.append({"key": key, "label": label, "value": rendered, "presentation": "metadata"})
    status = "已保存" if saved else "未保存"
    return {
        "kind": "detail",
        "title": title,
        "status": status,
        "fields": fields,
        "business_summary": status,
        "blocking_reason": "" if saved else _text(payload.get("message") or "请检查配置后重试。"),
        "next_steps": [],
    }
