"""Generate candidate TUI operation metadata from compile-time evidence."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _humanize(value: str) -> str:
    return re.sub(r"[_\-.]+", " ", value).strip().title()


def _operator_label(value: str) -> str:
    label = _humanize(value)
    label = re.sub(r"^(Get|List|Read|Fetch)\s+", "", label, flags=re.IGNORECASE).strip()
    return label or "System Tool"


FIELD_LABELS = {
    "account_id": "账户 ID",
    "asset_class": "资产类别",
    "asset_code": "资产代码",
    "code": "代码",
    "config_id": "配置 ID",
    "factor_id": "因子 ID",
    "event_id": "事件 ID",
    "event_date": "事件日期",
    "from_code": "源币种",
    "fund_code": "基金代码",
    "id": "ID",
    "indicator_code": "指标代码",
    "log_id": "日志 ID",
    "pk": "记录 ID",
    "plan_id": "计划 ID",
    "portfolio_id": "组合 ID",
    "report_id": "报告 ID",
    "request_id": "请求 ID",
    "short_code": "分享码",
    "signal_id": "信号 ID",
    "snapshot_id": "快照 ID",
    "strategy_id": "策略 ID",
    "summary_id": "汇总 ID",
    "symbol": "代码",
    "task_id": "任务 ID",
    "to_code": "目标币种",
    "universe": "标的池",
    "validation_id": "验证 ID",
}


LABEL_REPLACEMENTS = (
    ("Decision Rhythm", "决策节奏"),
    ("Decision", "决策"),
    ("Workspace", "工作台"),
    ("Cooldowns", "冷却期"),
    ("Requests", "请求"),
    ("Request", "请求"),
    ("Account", "账户"),
    ("Accounts", "账户"),
    ("Portfolio", "组合"),
    ("Portfolios", "组合"),
    ("Positions", "持仓"),
    ("Position", "持仓"),
    ("Trades", "交易"),
    ("Transactions", "交易流水"),
    ("Capital Flows", "资金流水"),
    ("Assets", "资产"),
    ("Asset", "资产"),
    ("Observer Grants", "观察授权"),
    ("Trading Cost Configs", "交易成本配置"),
    ("Categories", "分类"),
    ("Currencies", "币种"),
    ("Exchange Rates", "汇率"),
    ("Latest", "最新"),
    ("Allocation", "配置"),
    ("Performance Report", "绩效报告"),
    ("Performance", "绩效"),
    ("Valuation Snapshot", "估值快照"),
    ("Valuation Timeline", "估值时间线"),
    ("Benchmarks", "基准"),
    ("Equity Curve", "净值曲线"),
    ("Inspections", "检查记录"),
    ("Simulated Trading", "模拟交易"),
    ("Strategy", "策略"),
    ("Strategies", "策略"),
    ("Position Rules", "仓位规则"),
    ("Rules", "规则"),
    ("Execution Logs", "执行日志"),
    ("Script Config", "脚本配置"),
    ("AI Config", "AI 配置"),
    ("Rotation", "轮动"),
    ("Hedge", "对冲"),
    ("Alerts", "预警"),
    ("Factor", "因子"),
    ("Alpha", "Alpha"),
    ("Signal", "信号"),
    ("Signals", "信号"),
    ("Fund", "基金"),
    ("Sector", "板块"),
    ("Sentiment", "情绪"),
    ("Data Center", "数据中心"),
    ("Market Thermometer", "市场温度"),
    ("Prompt", "Prompt"),
    ("Templates", "模板"),
    ("Chains", "链路"),
    ("Logs", "日志"),
    ("Provider", "Provider"),
    ("Providers", "Provider"),
    ("Health", "健康"),
    ("Status", "状态"),
    ("Summary", "概览"),
    ("Metrics", "指标"),
    ("By Class", "按类别"),
    ("By Asset", "按资产"),
    ("From Code", "源币种"),
    ("To Code", "目标币种"),
    ("Asset Code", "资产代码"),
    ("Account Id", "账户 ID"),
    ("Portfolio Id", "组合 ID"),
    ("Snapshot Id", "快照 ID"),
    ("Pk", "记录"),
)


ROUTE_SEGMENT_LABELS = {
    "account": "账户",
    "accounts": "账户",
    "actions": "动作",
    "ai": "AI",
    "ai-capability": "AI 能力",
    "ai_config": "AI 配置",
    "allocation": "配置",
    "alpha": "Alpha",
    "asset": "资产",
    "asset-analysis": "资产分析",
    "asset-classes": "资产类别",
    "assets": "资产",
    "audit": "审计",
    "attribution-chart-data": "归因图表数据",
    "backtest": "回测",
    "backtests": "回测",
    "benchmarks": "基准",
    "beta-gate": "Beta Gate",
    "by-asset": "按资产",
    "by-account": "按账户",
    "by-class": "按类别",
    "capital-flows": "资金流水",
    "categories": "分类",
    "chains": "链路",
    "children": "子项",
    "commands": "指令",
    "config": "配置",
    "configs": "配置",
    "cooldowns": "冷却期",
    "correlations": "相关性",
    "currencies": "币种",
    "data-center": "数据中心",
    "decision": "决策",
    "decision-rhythm": "决策节奏",
    "equity": "股票",
    "equity-curve": "净值曲线",
    "events": "事件",
    "event": "事件",
    "exchange-rates": "汇率",
    "execution-logs": "执行日志",
    "execution_logs": "执行日志",
    "factor": "因子",
    "factors": "因子",
    "filter": "筛选",
    "fund": "基金",
    "health": "健康",
    "hedge": "对冲",
    "holding": "持仓",
    "info": "信息",
    "inspections": "检查记录",
    "indicator-performance": "指标表现",
    "indicator-performance-data": "指标表现数据",
    "latest": "最新",
    "logs": "日志",
    "market-thermometer": "市场温度",
    "metrics": "指标",
    "nav": "净值",
    "news": "新闻",
    "observer-grants": "观察授权",
    "operation-logs": "操作日志",
    "pairs": "组合",
    "performance": "绩效",
    "performance-report": "绩效报告",
    "policy": "政策",
    "plans": "计划",
    "portfolios": "组合",
    "position-rule": "仓位规则",
    "position_rule": "仓位规则",
    "position-rules": "仓位规则",
    "positions": "持仓",
    "public": "公开分享",
    "access": "访问记录",
    "prompt": "Prompt",
    "providers": "Provider",
    "requests": "请求",
    "rotation": "轮动",
    "rules": "规则",
    "sector": "板块",
    "sentiment": "情绪",
    "signals": "信号",
    "simulated-trading": "模拟交易",
    "share": "分享",
    "snapshot": "快照",
    "snapshots": "快照",
    "statistics": "统计",
    "strategy": "策略",
    "strategies": "策略",
    "style": "风格",
    "system": "系统",
    "status": "状态",
    "script_config": "脚本配置",
    "threshold-validation-data": "阈值验证数据",
    "templates": "模板",
    "terminal": "终端",
    "trades": "交易",
    "trading-cost-configs": "交易成本配置",
    "transactions": "交易流水",
    "valuation": "估值",
    "valuation-snapshot": "估值快照",
    "valuation-timeline": "估值时间线",
    "workspace": "工作台",
    "workbench": "工作台",
    "items": "事项",
}


def _localized_label(value: str) -> str:
    label = _operator_label(value)
    label = re.sub(r"\b(?:Int|Str|Slug|Uuid):", "", label)
    label = re.sub(r"\b(?:Int|Str|Slug|Uuid)\b", "", label)
    label = re.sub(r"\bDrf Format Suffix:?\s*Format\b", "", label, flags=re.IGNORECASE)
    for old, new in LABEL_REPLACEMENTS:
        label = re.sub(rf"\b{re.escape(old)}\b", new, label)
    label = re.sub(r"\s+", " ", label).strip(" -:/")
    return label or "条件查询"


def _parameterized_label(record: dict[str, Any], endpoint: str) -> str:
    segments = [
        segment
        for segment in endpoint.strip("/").split("/")
        if segment and segment != "api" and not _has_unresolved_path_parameter(segment)
    ]
    labels = [ROUTE_SEGMENT_LABELS.get(segment, _humanize(segment)) for segment in segments]
    compact: list[str] = []
    for label in labels:
        if compact and compact[-1] == label:
            continue
        compact.append(label)
    if not compact:
        return _localized_label(str(record.get("name") or endpoint))
    if endpoint.rstrip("/").split("/")[-1].startswith("<") and compact[-1] not in {"详情", "最新"}:
        compact.append("详情")
    return " / ".join(compact)


def _action_key(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", ".", value).strip(".").lower()


def _has_unresolved_path_parameter(endpoint: str) -> bool:
    return bool(re.search(r"(<[^>]+>|\{[^}]+\}|:[a-zA-Z_][a-zA-Z0-9_]*)", endpoint))


def _is_write_like_candidate(record: dict[str, Any]) -> bool:
    text = f"{record.get('endpoint', '')} {record.get('key', '')} {record.get('name', '')}".lower()
    write_terms = {
        "approve",
        "bind",
        "cancel",
        "clear",
        "clear-cache",
        "close",
        "deactivate",
        "delete",
        "disable",
        "enable",
        "evaluate",
        "execute",
        "export",
        "fetch",
        "generate",
        "import",
        "invalidate",
        "rebuild",
        "refresh",
        "reject",
        "repair",
        "rerun",
        "resolve",
        "revoke",
        "run",
        "sync",
        "test-script",
        "train",
        "trigger",
        "unbind",
        "update",
    }
    if "apply-template" in text or "check_effectiveness" in text:
        return True
    return any(term in text for term in write_terms)


def _is_direct_safe_read_candidate(record: dict[str, Any]) -> bool:
    endpoint = str(record.get("endpoint", "")).lower()
    if not _is_safe_api(record):
        return False
    if _has_unresolved_path_parameter(endpoint):
        return False
    if endpoint in {"/api/", "/api"}:
        return False
    blocked_segments = {
        "debug",
        "docs",
        "openapi",
        "redoc",
        "schema",
        "swagger",
        "tui",
    }
    segments = [segment for segment in endpoint.strip("/").split("/") if segment]
    if any(segment in blocked_segments for segment in segments):
        return False
    return not _is_write_like_candidate(record)


AUTO_LIBRARY_SCREENS = {
    "workflow": {
        "key": "api-library.workflow",
        "label": "决策与工作流工具",
        "summary": "已发布的决策上下文、仪表盘和日常工作流工具。",
    },
    "macro": {
        "key": "api-library.macro",
        "label": "环境与策略工具",
        "summary": "已发布的宏观环境、策略、节奏和市场状态工具。",
    },
    "research": {
        "key": "api-library.research",
        "label": "研究与信号工具",
        "summary": "已发布的研究、因子、信号、回测和标的分析工具。",
    },
    "account": {
        "key": "api-library.account",
        "label": "账户与组合工具",
        "summary": "已发布的账户、组合、资产和模拟交易工具。",
    },
    "execution": {
        "key": "api-library.execution",
        "label": "执行与复盘工具",
        "summary": "已发布的执行、审计、任务和风控检查工具。",
    },
    "system": {
        "key": "api-library.system",
        "label": "系统与 AI 工具",
        "summary": "已发布的系统健康、AI 能力、终端和数据中心工具。",
    },
    "parameterized": {
        "key": "api-library.parameterized",
        "label": "带条件查询",
        "summary": "需要输入对象编号、代码或主键后才能执行的详情工具。",
    },
}


def _screen_bucket(record: dict[str, Any]) -> str:
    category = str(record.get("category") or "").lower()
    if category in {"decision", "dashboard", "policy"}:
        return "workflow"
    if category in {
        "regime",
        "pulse",
        "rotation",
        "strategy",
        "hedge",
        "decision-rhythm",
        "beta-gate",
    }:
        return "macro"
    if category in {
        "alpha",
        "alpha-triggers",
        "asset-analysis",
        "backtest",
        "equity",
        "factor",
        "filter",
        "fund",
        "sector",
        "sentiment",
        "signal",
    }:
        return "research"
    if category in {"account", "portfolio", "simulated-trading"}:
        return "account"
    if category in {"audit", "events", "realtime", "share", "task-monitor"}:
        return "execution"
    return "system"


def _ensure_auto_library_screens(payload: dict[str, Any]) -> None:
    screens = payload.setdefault("screens", [])
    existing_screen_keys = {screen.get("key") for screen in screens if isinstance(screen, dict)}
    for spec in AUTO_LIBRARY_SCREENS.values():
        if spec["key"] in existing_screen_keys:
            continue
        screens.append(
            {
                "key": spec["key"],
                "label": spec["label"],
                "module_key": "api-library",
                "group": "system",
                "summary": spec["summary"],
                "view_type": "datagrid",
                "status": "online",
            }
        )
        existing_screen_keys.add(spec["key"])


def _is_safe_api(record: dict[str, Any]) -> bool:
    endpoint = str(record.get("endpoint", "")).lower()
    if str(record.get("method", "")).upper() != "GET":
        return False
    if record.get("requires_confirmation"):
        return False
    if str(record.get("visibility", "")).lower() == "admin" or "/admin/" in endpoint:
        return False
    if str(record.get("risk_level", "")).lower() in {"critical", "high"}:
        return False
    if "unsafe" in str(record.get("route_group", "")).lower():
        return False
    if endpoint.startswith("/api/schema") or endpoint.startswith("/api/docs"):
        return False
    return endpoint.startswith("/api/")


def _path_parameters(endpoint: str) -> list[dict[str, str]]:
    params: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(
        r"<(?:(?P<converter>[a-zA-Z_][a-zA-Z0-9_]*):)?(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>", endpoint
    ):
        name = match.group("name")
        if name not in seen:
            params.append({"name": name, "converter": match.group("converter") or "str"})
            seen.add(name)
    for match in re.finditer(r"\{(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\}", endpoint):
        name = match.group("name")
        if name not in seen:
            params.append({"name": name, "converter": "str"})
            seen.add(name)
    for match in re.finditer(r"/:(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)", endpoint):
        name = match.group("name")
        if name not in seen:
            params.append({"name": name, "converter": "str"})
            seen.add(name)
    return params


def _is_parameterized_safe_read_candidate(record: dict[str, Any]) -> bool:
    endpoint = str(record.get("endpoint", "")).lower()
    if not _is_safe_api(record):
        return False
    if not _has_unresolved_path_parameter(endpoint):
        return False
    params = _path_parameters(endpoint)
    if not params:
        return False
    if any(
        param.get("converter") == "drf_format_suffix" or param["name"] == "format"
        for param in params
    ):
        return False
    blocked_segments = {
        "debug",
        "docs",
        "openapi",
        "redoc",
        "schema",
        "swagger",
        "tui",
    }
    segments = [segment for segment in endpoint.strip("/").split("/") if segment]
    if any(segment in blocked_segments for segment in segments):
        return False
    if any(segment in {"activate", "calculate", "close", "evaluate"} for segment in segments):
        return False
    return not _is_write_like_candidate(record)


def _limit_items(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return items
    return items[:limit]


def collect_api_capability_records() -> list[dict[str, Any]]:
    """Return normalized API capability records from compile-time catalog evidence."""

    from apps.ai_capability.infrastructure.collectors.api_collector import ApiCapabilityCollector

    records: list[dict[str, Any]] = []
    for capability in ApiCapabilityCollector().collect():
        target = dict(capability.execution_target or {})
        endpoint = str(target.get("path") or "").strip()
        method = str(target.get("method") or "").upper()
        if not endpoint or not method:
            continue
        endpoint = "/" + endpoint.lstrip("/")
        records.append(
            {
                "key": capability.capability_key,
                "name": capability.name,
                "summary": capability.summary,
                "category": capability.category,
                "method": method,
                "endpoint": endpoint,
                "route_group": getattr(capability.route_group, "value", str(capability.route_group)),
                "risk_level": getattr(capability.risk_level, "value", str(capability.risk_level)),
                "visibility": getattr(capability.visibility, "value", str(capability.visibility)),
                "requires_confirmation": capability.requires_confirmation,
                "input_schema": dict(capability.input_schema or {}),
                "auto_collected": capability.auto_collected,
            }
        )
    return records


def collect_api_evidence(limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records = collect_api_capability_records()
    safe = [record for record in records if _is_safe_api(record)]
    evidence = [
        {
            "key": record["key"],
            "name": record.get("name", ""),
            "method": record["method"],
            "endpoint": record["endpoint"],
            "category": record.get("category", ""),
            "risk_level": record.get("risk_level", ""),
            "visibility": record.get("visibility", ""),
        }
        for record in _limit_items(safe, limit)
    ]
    return safe, evidence


def collect_sdk_evidence(root: Path, limit: int = 0) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    module_dir = root / "sdk" / "agomtradepro" / "modules"
    for path in sorted(module_dir.glob("*.py")):
        if path.name.startswith("__") or path.name == "base.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            doc = ast.get_docstring(node) or ""
            evidence.append(
                {
                    "module": path.stem,
                    "method": node.name,
                    "args": [arg.arg for arg in node.args.args if arg.arg != "self"],
                    "summary": doc.strip().splitlines()[0] if doc.strip() else "",
                    "source": str(path.relative_to(root)).replace("\\", "/"),
                }
            )
            if limit > 0 and len(evidence) >= limit:
                return evidence
    return evidence


def collect_mcp_evidence(root: Path, limit: int = 0) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    tools_dir = root / "sdk" / "agomtradepro_mcp" / "tools"
    for path in sorted(tools_dir.glob("*_tools.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.FunctionDef)
                or node.name.startswith("register_")
                or node.name.startswith("_")
            ):
                continue
            doc = ast.get_docstring(node) or ""
            evidence.append(
                {
                    "tool": node.name,
                    "args": [arg.arg for arg in node.args.args],
                    "summary": doc.strip().splitlines()[0] if doc.strip() else "",
                    "source": str(path.relative_to(root)).replace("\\", "/"),
                }
            )
            if limit > 0 and len(evidence) >= limit:
                return evidence
    return evidence


def collect_template_evidence(root: Path, limit: int = 0) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    candidates = list((root / "core" / "templates").rglob("*.html"))
    candidates += list((root / "apps").glob("*/templates/**/*.html"))
    for path in sorted(candidates):
        rel = str(path.relative_to(root)).replace("\\", "/")
        text = path.read_text(encoding="utf-8", errors="replace")
        features = {
            "status_cards": len(
                re.findall(r"(overview-card|summary-card|metric-card|pulse-card)", text)
            ),
            "tabs": len(re.findall(r"(tab-btn|data-tab=|nav-tabs)", text)),
            "filters": len(re.findall(r"(filter-|filters|type=\"date\"|<select)", text)),
            "tables": len(re.findall(r"<table|tbody|DataTable", text, flags=re.IGNORECASE)),
            "modals": len(re.findall(r"(modal|dialog)", text, flags=re.IGNORECASE)),
            "batch_actions": len(
                re.findall(r"(batch|select-all|selected-count)", text, flags=re.IGNORECASE)
            ),
            "pagination": len(
                re.findall(r"(pagination|page-|paginator)", text, flags=re.IGNORECASE)
            ),
            "onclick_actions": sorted(set(re.findall(r"onclick=\"([a-zA-Z0-9_]+)\(", text)))[:16],
        }
        if any(value for key, value in features.items() if key != "onclick_actions"):
            evidence.append({"template": rel, "features": features})
        if limit > 0 and len(evidence) >= limit:
            return evidence
    return evidence


def add_safe_api_actions(
    payload: dict[str, Any], safe_records: list[dict[str, Any]], limit: int
) -> int:
    if limit <= 0:
        return 0
    _ensure_auto_library_screens(payload)
    existing_keys = {action["key"] for action in payload["actions"]}
    existing_endpoints = {action["endpoint"] for action in payload["actions"]}
    added = 0
    for record in safe_records:
        if added >= limit:
            break
        if not _is_direct_safe_read_candidate(record):
            continue
        endpoint = record["endpoint"]
        if endpoint in existing_endpoints:
            continue
        screen_key = AUTO_LIBRARY_SCREENS[_screen_bucket(record)]["key"]
        label = _operator_label(str(record.get("name") or endpoint))
        key = "auto." + _action_key(str(record["key"]))
        if key in existing_keys:
            continue
        payload["actions"].append(
            {
                "key": key,
                "label": label,
                "method": "GET",
                "endpoint": endpoint,
                "intent": "auto_safe_read_candidate",
                "screen_key": screen_key,
                "module_key": "api-library",
                "view_type": "auto",
                "risk": "read",
                "fields": [],
                "description": str(record.get("summary") or f"只读查看：{label}。"),
                "source": "api-collector:candidate",
                "raw_debug": True,
            }
        )
        existing_keys.add(key)
        existing_endpoints.add(endpoint)
        added += 1
    return added


def _field_for_path_parameter(param: dict[str, str]) -> dict[str, Any]:
    name = param["name"]
    converter = param.get("converter") or "str"
    input_type = (
        "number"
        if converter in {"int", "slugint"} or name.endswith("_id") or name == "pk"
        else "text"
    )
    label = FIELD_LABELS.get(name, _humanize(name))
    return {
        "key": name,
        "label": label,
        "input_type": input_type,
        "required": True,
        "default": "",
        "placeholder": f"输入{label}",
        "binding": "path",
    }


def remove_generated_parameterized_actions(payload: dict[str, Any]) -> int:
    actions = list(payload.get("actions") or [])
    kept = [
        action
        for action in actions
        if str(action.get("source")) != "api-collector:parameterized-candidate"
    ]
    payload["actions"] = kept
    return len(actions) - len(kept)


def add_parameterized_safe_api_actions(
    payload: dict[str, Any],
    safe_records: list[dict[str, Any]],
    limit: int,
) -> int:
    if limit <= 0:
        return 0
    _ensure_auto_library_screens(payload)
    remove_generated_parameterized_actions(payload)
    existing_keys = {action["key"] for action in payload["actions"]}
    existing_endpoints = {action["endpoint"] for action in payload["actions"]}
    added = 0
    for record in safe_records:
        if added >= limit:
            break
        if not _is_parameterized_safe_read_candidate(record):
            continue
        endpoint = record["endpoint"]
        if endpoint in existing_endpoints:
            continue
        key = "param." + _action_key(str(record["key"]))
        if key in existing_keys:
            continue
        params = _path_parameters(endpoint)
        if not params:
            continue
        label = _parameterized_label(record, endpoint)
        payload["actions"].append(
            {
                "key": key,
                "label": label,
                "method": "GET",
                "endpoint": endpoint,
                "intent": "parameterized_safe_read",
                "screen_key": AUTO_LIBRARY_SCREENS["parameterized"]["key"],
                "module_key": "api-library",
                "view_type": "auto",
                "risk": "read",
                "fields": [_field_for_path_parameter(param) for param in params],
                "description": f"输入必要条件后只读查看：{label}。",
                "source": "api-collector:parameterized-candidate",
                "raw_debug": True,
                "task_group": "需要输入",
                "sequence": 800,
            }
        )
        existing_keys.add(key)
        existing_endpoints.add(endpoint)
        added += 1
    return added


def build_coverage_summary(
    *,
    safe_records: list[dict[str, Any]],
    added_actions: int,
    added_parameterized_actions: int = 0,
    payload: dict[str, Any],
) -> dict[str, Any]:
    direct_candidates = [
        record for record in safe_records if _is_direct_safe_read_candidate(record)
    ]
    parameterized_candidates = [
        record for record in safe_records if _is_parameterized_safe_read_candidate(record)
    ]
    parameterized_candidate_endpoints = {
        str(record.get("endpoint", "")) for record in parameterized_candidates
    }
    covered_parameterized_actions = {
        str(action.get("endpoint", ""))
        for action in payload.get("actions", [])
        if str(action.get("endpoint", "")) in parameterized_candidate_endpoints
        and action.get("fields")
        and str(action.get("risk", "read")) == "read"
    }
    covered_parameterized_count = max(
        added_parameterized_actions,
        len(covered_parameterized_actions),
    )
    deferred_path_params = [
        record
        for record in safe_records
        if _has_unresolved_path_parameter(str(record.get("endpoint", "")))
    ]
    deferred_write_like = [
        record
        for record in safe_records
        if not _has_unresolved_path_parameter(str(record.get("endpoint", "")))
        and _is_write_like_candidate(record)
    ]
    deferred_internal = [
        record
        for record in safe_records
        if str(record.get("endpoint", "")).lower() in {"/api/", "/api"}
        or any(
            segment in {"debug", "docs", "openapi", "redoc", "schema", "swagger", "tui"}
            for segment in str(record.get("endpoint", "")).lower().strip("/").split("/")
        )
    ]
    return {
        "safe_read_evidence": len(safe_records),
        "direct_safe_read_candidates": len(direct_candidates),
        "parameterized_safe_read_candidates": len(parameterized_candidates),
        "added_safe_api_actions": added_actions,
        "added_parameterized_api_actions": covered_parameterized_count,
        "published_actions": len(payload.get("actions", [])),
        "deferred": {
            "path_parameters": max(0, len(deferred_path_params) - covered_parameterized_count),
            "write_like_or_heavy": len(deferred_write_like),
            "internal_debug_or_docs": len(deferred_internal),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate candidate TUI operation metadata.")
    parser.add_argument(
        "--baseline",
        default="config/tui/published/tui_operation_graph.published.json",
        help="Reviewed baseline JSON to copy and enrich",
    )
    parser.add_argument(
        "--output",
        default="config/tui/generated/tui_operation_graph.generated.json",
        help="Candidate JSON output path",
    )
    parser.add_argument(
        "--evidence-output",
        default="config/tui/generated/tui_operation_evidence.generated.json",
        help="Separate compile-time evidence output path",
    )
    parser.add_argument(
        "--inline-evidence",
        action="store_true",
        help="Keep source_evidence inside the generated graph for one-off debugging",
    )
    parser.add_argument(
        "--api-evidence-limit", type=int, default=0, help="0 means collect all safe API evidence"
    )
    parser.add_argument(
        "--sdk-evidence-limit", type=int, default=0, help="0 means collect all SDK method evidence"
    )
    parser.add_argument(
        "--mcp-evidence-limit", type=int, default=0, help="0 means collect all MCP tool evidence"
    )
    parser.add_argument(
        "--template-evidence-limit",
        type=int,
        default=0,
        help="0 means collect all classic template evidence",
    )
    parser.add_argument("--include-safe-api-actions", type=int, default=0)
    parser.add_argument("--include-parameterized-api-actions", type=int, default=0)
    parser.add_argument(
        "--publish-ready",
        action="store_true",
        help="Write a reviewed-runtime shaped payload without raw source evidence arrays",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and print summary without writing output"
    )
    args = parser.parse_args()

    root = _repo_root()
    sys.path.insert(0, str(root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development_sqlite")

    import django

    django.setup()

    from apps.terminal.application.tui_metadata import (
        compact_tui_metadata_payload,
        validate_tui_metadata,
    )

    baseline = (root / args.baseline).resolve()
    output = (root / args.output).resolve()
    evidence_output = (root / args.evidence_output).resolve()
    payload = json.loads(baseline.read_text(encoding="utf-8"))

    safe_records, api_evidence = collect_api_evidence(args.api_evidence_limit)
    added_actions = add_safe_api_actions(payload, safe_records, args.include_safe_api_actions)
    added_parameterized_actions = add_parameterized_safe_api_actions(
        payload,
        safe_records,
        args.include_parameterized_api_actions,
    )
    sdk_evidence = collect_sdk_evidence(root, args.sdk_evidence_limit)
    mcp_evidence = collect_mcp_evidence(root, args.mcp_evidence_limit)
    template_evidence = collect_template_evidence(root, args.template_evidence_limit)
    evidence_counts = {
        "api_safe_read": len(api_evidence),
        "sdk_methods": len(sdk_evidence),
        "mcp_tools": len(mcp_evidence),
        "classic_templates": len(template_evidence),
    }
    payload["status"] = "published" if args.publish_ready else "generated"
    payload["coverage_summary"] = build_coverage_summary(
        safe_records=safe_records,
        added_actions=added_actions,
        added_parameterized_actions=added_parameterized_actions,
        payload=payload,
    )
    source_evidence = {
        "api_safe_read": api_evidence,
        "sdk_methods": sdk_evidence,
        "mcp_tools": mcp_evidence,
        "classic_templates": template_evidence,
    }
    if args.publish_ready:
        payload.pop("source_evidence", None)
        payload.pop("source_evidence_ref", None)
        payload.pop("source_evidence_counts", None)
        payload.pop("generation_note", None)
        payload["publication_note"] = (
            "Publish-ready TUI metadata generated from reviewed baseline plus direct safe-read tool candidates."
        )
    else:
        if args.inline_evidence:
            payload["source_evidence"] = source_evidence
            payload.pop("source_evidence_ref", None)
        else:
            payload.pop("source_evidence", None)
            payload["source_evidence_ref"] = str(evidence_output.relative_to(root).as_posix())
        payload["source_evidence_counts"] = evidence_counts
        payload["generation_note"] = (
            "Candidate metadata generated at compile time. Review graph and separate evidence before publishing."
        )
    validated = validate_tui_metadata(payload)
    summary = {
        "ok": True,
        "baseline": str(baseline),
        "output": str(output),
        "dry_run": args.dry_run,
        "publish_ready": args.publish_ready,
        "groups": len(validated["groups"]),
        "modules": len(validated["modules"]),
        "screens": len(validated["screens"]),
        "actions": len(validated["actions"]),
        "added_safe_api_actions": added_actions,
        "added_parameterized_api_actions": added_parameterized_actions,
        "coverage_summary": payload["coverage_summary"],
        "source_evidence": evidence_counts,
    }
    if not args.dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)
        output_payload = compact_tui_metadata_payload(validated)
        output.write_text(
            json.dumps(output_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if not args.publish_ready and not args.inline_evidence:
            evidence_output.parent.mkdir(parents=True, exist_ok=True)
            evidence_output.write_text(
                json.dumps(
                    {
                        "version": validated["version"],
                        "registry_key": validated.get("registry_key", "default"),
                        "source_evidence_counts": evidence_counts,
                        "source_evidence": source_evidence,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
