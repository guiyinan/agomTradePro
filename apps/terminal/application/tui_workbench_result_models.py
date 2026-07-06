"""Result view-model helpers for TUI workbench."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from math import ceil
from typing import Any
from urllib.parse import urlparse

from apps.terminal.application.tui_workbench_constants import (
    ASSET_CODE_FIELDS,
    ASSET_CODE_PATTERN,
    ASSET_NAME_FIELDS,
    EMBEDDED_VALUE_LABELS,
    ESCAPED_HTML_TAG_PATTERN,
    FIELD_VALUE_LABELS,
    HTML_TAG_PATTERN,
    ROW_IDENTIFIER_FIELDS,
    STATUS_LABELS,
    VALUE_LABELS,
)


class _PlainTextHTMLParser(HTMLParser):
    """Extract readable text from legacy HTML/HTMX fragments."""

    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
    _SKIP_TAGS = {"script", "style", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag.lower() in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag.lower() in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data:
            self._parts.append(data)

    def text(self) -> str:
        lines = []
        for line in "".join(self._parts).splitlines():
            collapsed = re.sub(r"\s+", " ", line).strip()
            if collapsed:
                lines.append(collapsed)
        return "\n".join(lines)


class TuiWorkbenchResultModelMixin:
    """View-model rendering helpers shared by the TUI workbench service."""

    def _resolve_asset_names(self, codes: list[str]) -> dict[str, str]:
        raise NotImplementedError

    def _to_view_model(
        self,
        *,
        action: dict[str, Any],
        payload: Any,
        status_code: int,
        request_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = self._unwrap_payload(payload)
        custom_model = self._custom_view_model(
            action,
            data,
            status_code,
            request_params=request_params,
        )
        if custom_model is not None:
            return self._finalize_view_model(
                action,
                custom_model,
                payload=data,
                status_code=status_code,
            )
        forced_kind = self._view_model_path(action, "kind")
        if isinstance(data, dict) and self._is_endpoint_directory(data):
            return self._finalize_view_model(
                action,
                self._endpoint_directory_model(action, data, status_code),
                payload=data,
                status_code=status_code,
            )
        if forced_kind == "detail" and isinstance(data, dict):
            return self._finalize_view_model(
                action,
                self._detail_model(action, data, status_code),
                payload=data,
                status_code=status_code,
            )
        if forced_kind == "message":
            return self._finalize_view_model(
                action,
                {
                    "kind": "message",
                    "title": self._action_title(action),
                    "status": self._status_label(status_code),
                    "message": self._display_value(data),
                    "raw_hint": "原始响应只在调试抽屉中查看。",
                },
                payload=data,
                status_code=status_code,
            )
        if forced_kind == "datagrid":
            if isinstance(data, list):
                return self._finalize_view_model(
                    action,
                    self._datagrid_model(action, data, status_code, request_params=request_params),
                    payload=data,
                    status_code=status_code,
                )
            if isinstance(data, dict):
                rows_path = self._view_model_path(action, "rows_path")
                if not rows_path and self._looks_like_detail_payload(data):
                    return self._finalize_view_model(
                        action,
                        self._detail_model(action, data, status_code),
                        payload=data,
                        status_code=status_code,
                    )
                explicit_value = self._value_at_path(data, rows_path) if rows_path else None
                list_value = (
                    explicit_value
                    if isinstance(explicit_value, list)
                    else self._find_list_value(data)
                )
                if list_value is not None:
                    return self._finalize_view_model(
                        action,
                        self._datagrid_model(
                            action,
                            list_value,
                            status_code,
                            envelope=data,
                            request_params=request_params,
                        ),
                        payload=data,
                        status_code=status_code,
                    )
        if isinstance(data, list):
            return self._finalize_view_model(
                action,
                self._datagrid_model(action, data, status_code, request_params=request_params),
                payload=data,
                status_code=status_code,
            )
        if isinstance(data, dict):
            html_text = self._dominant_html_text(data)
            if html_text:
                return self._finalize_view_model(
                    action,
                    self._message_model(action, html_text, status_code),
                    payload=data,
                    status_code=status_code,
                )
            if str(action.get("view_type")) in {"status", "detail", "queue_workbench"}:
                return self._finalize_view_model(
                    action,
                    self._detail_model(action, data, status_code),
                    payload=data,
                    status_code=status_code,
                )
            if str(action.get("view_type")) == "datagrid" and self._looks_like_detail_payload(data):
                return self._finalize_view_model(
                    action,
                    self._detail_model(action, data, status_code),
                    payload=data,
                    status_code=status_code,
                )
            rows_path = self._view_model_path(action, "rows_path")
            explicit_value = self._value_at_path(data, rows_path) if rows_path else None
            list_value = (
                explicit_value if isinstance(explicit_value, list) else self._find_list_value(data)
            )
            if list_value is not None:
                return self._finalize_view_model(
                    action,
                    self._datagrid_model(
                        action,
                        list_value,
                        status_code,
                        envelope=data,
                        request_params=request_params,
                    ),
                    payload=data,
                    status_code=status_code,
                )
            return self._finalize_view_model(
                action,
                self._detail_model(action, data, status_code),
                payload=data,
                status_code=status_code,
            )
        if self._looks_like_html(data):
            return self._finalize_view_model(
                action,
                self._message_model(action, self._html_to_text(str(data)), status_code),
                payload=data,
                status_code=status_code,
            )
        return self._finalize_view_model(
            action,
            {
                "kind": "message",
                "title": self._action_title(action),
                "status": self._status_label(status_code),
                "message": self._display_value(data),
                "raw_hint": "原始响应只在调试抽屉中查看。",
            },
            payload=data,
            status_code=status_code,
        )

    def _custom_view_model(
        self,
        action: dict[str, Any],
        payload: Any,
        status_code: int,
        *,
        request_params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        action_key = str(action.get("key") or "")
        if action_key == "advisor.today_sheet" and isinstance(payload, dict):
            return self._advisor_today_sheet_model(action, payload)
        if action_key in {
            "terminal.chat_router",
            "cli.chat_router",
            "capability-router.route-message",
        } and isinstance(payload, dict):
            return self._ai_router_result_model(action, payload, status_code)
        return None

    def _finalize_view_model(
        self,
        action: dict[str, Any],
        view_model: dict[str, Any],
        *,
        payload: Any,
        status_code: int,
    ) -> dict[str, Any]:
        model = dict(view_model)
        model.setdefault(
            "business_summary",
            self._default_business_summary(action, model, payload, status_code),
        )
        model.setdefault("blocking_reason", self._default_blocking_reason(payload, status_code))
        next_steps = model.get("next_steps")
        model["next_steps"] = list(next_steps) if isinstance(next_steps, list) else []
        debug_hidden_fields = model.get("debug_hidden_fields")
        model["debug_hidden_fields"] = (
            list(debug_hidden_fields) if isinstance(debug_hidden_fields, list) else []
        )
        return model

    def _action_title(self, action: dict[str, Any]) -> str:
        return self._operator_text(action.get("label") or "")

    def _unwrap_payload(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            if "data" in payload and len(payload) <= 4:
                return payload.get("data")
        return payload

    def _view_model_path(self, action: dict[str, Any], key: str) -> str:
        view_model = action.get("view_model") or {}
        if not isinstance(view_model, dict):
            return ""
        return str(view_model.get(key) or "").strip()

    def _value_at_path(self, payload: Any, path: str) -> Any:
        if not path:
            return None
        current = payload
        for part in path.split("."):
            if not part:
                return None
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                index = int(part)
                current = current[index] if 0 <= index < len(current) else None
            else:
                return None
        return current

    def _find_list_value(self, payload: dict[str, Any]) -> list[Any] | None:
        candidates = self._list_candidates(payload)
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]

    def _list_candidates(self, value: Any, *, depth: int = 0) -> list[tuple[int, list[Any]]]:
        if depth > 3:
            return []
        if isinstance(value, list):
            return [(self._list_score(value, depth), value)]
        if not isinstance(value, dict):
            return []
        candidates: list[tuple[int, list[Any]]] = []
        for child in value.values():
            candidates.extend(self._list_candidates(child, depth=depth + 1))
        return candidates

    def _list_score(self, rows: list[Any], depth: int) -> int:
        if not rows:
            return 0
        sample = rows[:5]
        dict_rows = sum(1 for row in sample if isinstance(row, dict))
        scalar_rows = sum(1 for row in sample if not isinstance(row, (dict, list)))
        nested_penalty = depth * 4
        return dict_rows * 10 + scalar_rows * 4 + min(len(rows), 20) - nested_penalty

    def _datagrid_model(
        self,
        action: dict[str, Any],
        rows: list[Any],
        status_code: int,
        envelope: dict[str, Any] | None = None,
        request_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_list = self._message_list_text(rows)
        if message_list:
            return self._message_model(action, message_list, status_code)
        normalized_rows = [row if isinstance(row, dict) else {"value": row} for row in rows]
        normalized_rows = self._filter_rows_for_action(action, normalized_rows)
        columns = self._columns_for_rows(normalized_rows)
        asset_name_map = self._asset_name_map_for_rows(normalized_rows)
        explicit_page_size = self._int_from_path(action, envelope, "page_size_path", default=0)
        request_limit = self._int_from_params(request_params, "limit", default=0)
        page_size = explicit_page_size or request_limit
        if str(action.get("intent")) == "list_ai_capabilities":
            total = len(normalized_rows)
        else:
            total = int(
                self._int_from_path(action, envelope, "total_path", default=0)
                or len(normalized_rows)
            )
        if page_size <= 0:
            page_size = len(normalized_rows) if self._view_model_path(action, "total_path") else 20
        page_size = max(1, page_size)
        explicit_page = self._int_from_path(action, envelope, "page_path", default=0)
        request_offset = self._int_from_params(request_params, "offset", default=0)
        page = explicit_page or max(1, (request_offset // page_size) + 1)
        pagination_mode = (
            "page"
            if explicit_page or self._view_model_path(action, "page_path")
            else "limit_offset" if self._view_model_path(action, "total_path") else "page"
        )
        return {
            "kind": "datagrid",
            "title": self._action_title(action),
            "status": self._status_label(status_code),
            "columns": columns,
            "rows": [
                self._datagrid_row_payload(row, columns, asset_name_map)
                for row in normalized_rows[:page_size]
            ],
            "empty_message": self._empty_datagrid_message(action, total),
            "empty_guidance": self._empty_datagrid_guidance(action, total),
            "pager": {
                "page": page,
                "page_size": page_size,
                "offset": request_offset,
                "pagination_mode": pagination_mode,
                "total_rows": total,
                "total_pages": max(1, ceil(total / page_size)),
                "has_next": page * page_size < total,
                "has_previous": page > 1,
            },
            "next_steps": self._empty_next_steps(action, total),
        }

    def _datagrid_row_payload(
        self,
        row: dict[str, Any],
        columns: list[dict[str, str]],
        asset_name_map: dict[str, str],
    ) -> dict[str, str]:
        payload: dict[str, Any] = {}
        for column in columns:
            key = column["key"]
            display_value = self._display_row_value(row, key, asset_name_map)
            payload[key] = display_value
            raw_value = row.get(key)
            if self._should_preserve_raw_row_value(key, raw_value, display_value):
                payload[f"__raw_{key}"] = raw_value
        for key, value in row.items():
            normalized_key = str(key)
            if normalized_key.startswith("__"):
                normalized_key = normalized_key[2:]
            if normalized_key in payload or isinstance(value, (dict, list)):
                continue
            if not self._should_preserve_row_identifier(normalized_key):
                continue
            payload[normalized_key] = self._display_row_value(row, key, asset_name_map)
        return payload

    def _should_preserve_row_identifier(self, key: str) -> bool:
        normalized = str(key or "").strip().lower().replace("-", "_")
        return normalized in ROW_IDENTIFIER_FIELDS or normalized.endswith("_id")

    def _should_preserve_raw_row_value(
        self,
        key: str,
        raw_value: Any,
        display_value: str,
    ) -> bool:
        if raw_value in (None, "") or isinstance(raw_value, (dict, list)):
            return False
        normalized = str(key or "").strip().lower().replace("-", "_")
        if not (
            self._should_preserve_row_identifier(normalized)
            or normalized == "code"
            or normalized.endswith("_code")
        ):
            return False
        return str(raw_value) != str(display_value)

    def _filter_rows_for_action(
        self, action: dict[str, Any], rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if str(action.get("intent")) != "list_ai_capabilities":
            return rows
        safe_values = {"safe", "read", "low", "readonly", "无风险", "安全"}
        filtered: list[dict[str, Any]] = []
        for row in rows:
            capability_key = str(row.get("capability_key") or row.get("key") or "")
            if capability_key.startswith("api."):
                continue
            risk = str(row.get("risk_level") or row.get("risk") or "").strip().lower()
            confirmation = row.get("requires_confirmation")
            if isinstance(confirmation, str):
                needs_confirmation = confirmation.strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "y",
                    "是",
                }
            else:
                needs_confirmation = bool(confirmation)
            if risk in safe_values and not needs_confirmation:
                filtered.append(self._operator_ai_capability_row(row))
        return filtered

    def _operator_ai_capability_row(self, row: dict[str, Any]) -> dict[str, Any]:
        capability_key = str(row.get("capability_key") or row.get("key") or "")
        curated = {
            "builtin.market_regime": {
                "name": "市场环境判断",
                "summary": "查看当前市场环境、政策档位和基础行动边界。",
            },
            "builtin.system_status": {
                "name": "系统状态",
                "summary": "检查系统健康、就绪状态和基础运行情况。",
            },
            "terminal_command.market_temperature": {
                "name": "市场温度",
                "summary": "查看市场温度、风险区间和过热提示。",
            },
        }.get(capability_key, {})
        return {
            "__capability_key": capability_key,
            "name": curated.get("name") or self._clean_operator_text(row.get("name")),
            "summary": curated.get("summary") or self._clean_operator_text(row.get("summary")),
            "category": self._display_value(row.get("category")),
            "risk_level": self._display_value(row.get("risk_level")),
            "requires_confirmation": self._display_value(row.get("requires_confirmation")),
        }

    def _clean_operator_text(self, value: Any) -> str:
        text = self._display_value(value)
        text = re.sub(r"\b(GET|POST|PUT|PATCH|DELETE)\s+/api/[^\s，。；;]*", "内部接口", text)
        text = re.sub(r"\bAPI endpoint:\s*", "能力入口：", text, flags=re.IGNORECASE)
        text = text.replace("_", " ")
        return text.strip()

    def _operator_text(self, value: Any) -> str:
        """Remove security/compiler jargon from operator-facing labels."""

        text = self._clean_operator_text(value)
        replacements = {
            "自动批准的只读": "已发布的",
            "只读详情工具": "详情工具",
            "只读决策上下文": "决策上下文",
            "只读宏观环境": "宏观环境",
            "只读研究": "研究",
            "只读账户": "账户",
            "只读执行": "执行",
            "只读系统健康": "系统健康",
            "只读": "可查看",
            "直接读取": "直接打开",
            "读取业务视图": "打开业务视图",
            "Beta Gate": "Beta 闸门",
            "Regime": "宏观象限",
            "AI Provider": "AI 服务商",
            "Provider": "服务商",
            "Prompt": "提示词",
            "Chat": "对话",
            "Templates": "模板",
            "Template": "模板",
            "Chains": "链路",
            "Chain": "链路",
            "Logs": "日志",
            "Log": "日志",
            "Assignments": "绑定",
            "Assignment": "绑定",
            "Execution": "执行",
            "Strategy": "策略",
            "Runtime": "运行时",
            "Workflow": "流程",
            "funnel": "漏斗",
            "Conflict": "冲突",
            "Context": "上下文",
            "Params": "参数",
            "Reasoning": "原因说明",
            "Freshness": "时效",
            "Benchmark": "基准",
            "Excess": "超额",
            "Accuracy": "准确率",
            "Records": "记录",
            "Composite": "综合",
            "Liquidity": "流动性",
            "Actionable": "可操作",
            "Aggregated": "汇总",
            "TopStocks": "前列股票",
            "IcTrends": "IC趋势",
            "Top10": "前10",
            "TopRanked": "前列排名",
            "RequestedTrade": "请求交易",
            "PendingRequests": "待处理请求",
            "LessonLearned": "复盘经验",
            "SelectionEffect": "选股效应",
            "RecommendedSectors": "推荐板块",
            "BenefitingStyles": "受益风格",
            "TransitionTarget": "切换目标",
            "TransitionProbability": "切换概率",
            "RiskBudget": "风险预算",
            "PerTrade": "单笔交易",
            "Source": "来源",
            "Keyword": "关键词",
            "Config": "配置",
            "Model": "模型",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = re.sub(r"\bTop-down\b", "自上而下", text, flags=re.IGNORECASE)
        text = re.sub(r"\bBottom-up\b", "自下而上", text, flags=re.IGNORECASE)
        text = re.sub(r"\bBUY\b", "买入", text)
        text = re.sub(r"\bSELL\b", "卖出", text)
        text = re.sub(r"\bmoderate\b", "中等", text, flags=re.IGNORECASE)
        text = re.sub(r"\bhigh\b", "高", text, flags=re.IGNORECASE)
        text = re.sub(r"\bmedium\b", "中", text, flags=re.IGNORECASE)
        text = re.sub(r"\blow\b", "低", text, flags=re.IGNORECASE)
        text = re.sub(r"\bdelta\b", "调仓差额", text, flags=re.IGNORECASE)
        text = text.replace("绑定s", "绑定")
        text = re.sub(r"\bBy\b", "按", text)
        text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
        return text.strip()

    def _detail_model(
        self, action: dict[str, Any], payload: dict[str, Any], status_code: int
    ) -> dict[str, Any]:
        fields = self._detail_fields(payload)
        if self._looks_like_password_challenge(status_code, payload):
            fields.append(
                {
                    "key": "operator_hint",
                    "label": "操作提示",
                    "value": "请在当前屏使用“公开分享 / 验证访问”动作输入密码后重试。",
                }
            )
        nested = [
            {"key": key, "label": self._humanize(key), "count": len(value)}
            for key, value in payload.items()
            if isinstance(value, list) and not self._is_technical_detail_field(str(key), value)
        ]
        return {
            "kind": "detail",
            "title": self._action_title(action),
            "status": self._status_label(status_code, payload),
            "fields": fields,
            "nested": nested,
        }

    def _message_model(
        self, action: dict[str, Any], message: str, status_code: int
    ) -> dict[str, Any]:
        normalized_message = self._operator_text(message)
        return {
            "kind": "message",
            "title": self._action_title(action),
            "status": self._status_label(status_code, {"detail": normalized_message}),
            "message": normalized_message,
            "sections": self._message_sections(normalized_message),
            "raw_hint": "原始响应只在调试抽屉中查看。",
        }

    def _message_list_text(self, rows: list[Any]) -> str:
        if not rows or len(rows) > 12:
            return ""
        if any(isinstance(row, (dict, list, tuple, set)) for row in rows):
            return ""
        messages = [str(row).strip() for row in rows if str(row).strip()]
        if len(messages) != len(rows):
            return ""
        if not any(self._looks_like_message_line(message) for message in messages):
            return ""
        return "\n".join(messages)

    def _looks_like_message_line(self, value: str) -> bool:
        text = str(value or "").strip()
        if len(text) >= 12:
            return True
        return any(marker in text for marker in ("，", "。", "：", ":", "；", " ", "无法", "跳过"))

    def _message_sections(self, message: str) -> list[dict[str, Any]]:
        lines = [line.strip() for line in str(message or "").splitlines() if line.strip()]
        sections: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for line in lines:
            inline_heading = self._split_inline_heading(line)
            if inline_heading is not None:
                heading, remainder = inline_heading
                current = {"title": heading, "rows": [], "body": []}
                sections.append(current)
                if remainder:
                    label, value = self._split_message_row(remainder)
                    if label:
                        current["rows"].append({"label": label, "value": value})
                    else:
                        current["body"].append(remainder)
                continue
            if self._is_section_heading(line):
                current = {"title": line, "rows": [], "body": []}
                sections.append(current)
                continue
            if current is None:
                current = {"title": "摘要", "rows": [], "body": []}
                sections.append(current)
            label, value = self._split_message_row(line)
            if label:
                current["rows"].append({"label": label, "value": value})
            else:
                current["body"].append(line)
        return sections[:12]

    def _split_inline_heading(self, line: str) -> tuple[str, str] | None:
        text = line.strip()
        prefix_match = re.match(r"^(阶段\s*\d+\s*[：:])", text)
        if not prefix_match:
            return None
        remainder_text = text[prefix_match.end() :]
        split_match = re.search(
            r"(当前|本阶段|只回答|系统级|若要|工作台|统一|该列表|计划|当前账户|配置建议|轮动信号|推荐偏好)",
            remainder_text,
        )
        if not split_match:
            return None
        heading = f"{prefix_match.group(1)}{remainder_text[: split_match.start()]}".strip()
        remainder = remainder_text[split_match.start() :].strip()
        if not remainder:
            return None
        return heading, remainder

    def _is_section_heading(self, line: str) -> bool:
        stripped = line.strip()
        if len(stripped) > 36:
            return False
        if stripped.startswith(("阶段", "第")) and ("：" in stripped or ":" in stripped):
            return True
        if stripped.startswith(("📉", "💓", "🏛", "⚠", "✅", "📌")):
            return True
        return bool(re.match(r"^[一二三四五六七八九十]+、", stripped))

    def _split_message_row(self, line: str) -> tuple[str, str]:
        for separator in ("：", ":"):
            if separator in line:
                label, value = line.split(separator, 1)
                if 1 <= len(label.strip()) <= 18 and value.strip():
                    return label.strip(), self._display_value(value.strip())
        return "", ""

    def _is_endpoint_directory(self, payload: dict[str, Any]) -> bool:
        endpoints = payload.get("endpoints")
        if isinstance(endpoints, dict):
            values = [value for value in endpoints.values() if isinstance(value, str)]
            return bool(values) and all(self._is_internal_api_path(value) for value in values)
        if not isinstance(endpoints, list) or not endpoints:
            return self._looks_like_internal_path_directory(payload)
        values = [value for value in endpoints if isinstance(value, str)]
        return bool(values) and all(self._is_internal_api_path(value) for value in values)

    def _endpoint_directory_model(
        self, action: dict[str, Any], payload: dict[str, Any], status_code: int
    ) -> dict[str, Any]:
        raw_endpoints = payload.get("endpoints")
        if isinstance(raw_endpoints, dict):
            endpoint_count = len(raw_endpoints)
        elif isinstance(raw_endpoints, list):
            endpoint_count = len([value for value in raw_endpoints if isinstance(value, str)])
        else:
            endpoint_count = len(self._internal_path_directory_values(payload))
        message = str(payload.get("message") or action["label"]).strip()
        return {
            "kind": "detail",
            "title": self._action_title(action),
            "status": self._status_label(status_code),
            "fields": [
                {
                    "key": "service",
                    "label": "服务",
                    "value": self._display_value(message),
                },
                {
                    "key": "capability_count",
                    "label": "已登记能力",
                    "value": f"{endpoint_count} 项",
                },
                {
                    "key": "operator_hint",
                    "label": "操作提示",
                    "value": "请从左侧业务任务进入具体操作；内部接口路径只在调试抽屉中查看。",
                },
            ],
            "nested": [],
        }

    def _looks_like_internal_path_directory(self, payload: dict[str, Any]) -> bool:
        values = self._internal_path_directory_values(payload)
        return bool(values) and all(self._is_internal_api_path(value) for value in values)

    def _internal_path_directory_values(self, payload: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for key, value in payload.items():
            if key == "message":
                continue
            if isinstance(value, str):
                values.append(value)
                continue
            if value in (None, ""):
                continue
            return []
        return values

    def _dominant_html_text(self, payload: dict[str, Any]) -> str:
        html_keys = {
            "body",
            "content",
            "html",
            "markup",
            "partial",
            "rendered",
            "template",
        }
        scalar_values = [
            (str(key), value)
            for key, value in payload.items()
            if not isinstance(value, (dict, list))
        ]
        html_values = [
            self._html_to_text(str(value))
            for key, value in scalar_values
            if key.lower() in html_keys and self._looks_like_html(value)
        ]
        if len(scalar_values) == 1 and not html_values:
            only_value = scalar_values[0][1]
            if self._looks_like_html(only_value):
                html_values.append(self._html_to_text(str(only_value)))
        return "\n".join(value for value in html_values if value).strip()

    def _detail_fields(
        self,
        payload: dict[str, Any],
        *,
        prefix: str = "",
        depth: int = 0,
        limit: int = 24,
    ) -> list[dict[str, str]]:
        fields: list[dict[str, str]] = []
        for key, value in payload.items():
            if len(fields) >= limit:
                break
            field_key = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, list):
                continue
            if self._is_technical_detail_field(field_key, value):
                continue
            if isinstance(value, dict):
                if depth < 1:
                    fields.extend(
                        self._detail_fields(
                            value,
                            prefix=field_key,
                            depth=depth + 1,
                            limit=limit - len(fields),
                        )
                    )
                else:
                    fields.append(
                        {
                            "key": field_key,
                            "label": self._humanize(field_key),
                            "value": f"{len(value)} 个字段",
                        }
                    )
                continue
            fields.append(
                {
                    "key": field_key,
                    "label": self._humanize(field_key),
                    "value": self._display_value_for_key(field_key, value, payload),
                }
            )
        return fields[:limit]

    def _is_technical_detail_field(self, key: str, value: Any) -> bool:
        normalized = str(key or "").strip().lower()
        if normalized == "endpoints" or normalized.startswith("endpoints."):
            return True
        if normalized in {"success", "ok"} and isinstance(value, bool):
            return True
        if isinstance(value, str) and self._is_internal_api_path(value):
            return True
        return False

    def _looks_like_detail_payload(self, payload: dict[str, Any]) -> bool:
        business_items = [
            (str(key or "").strip().lower(), value)
            for key, value in payload.items()
            if str(key or "").strip().lower() not in {"success", "ok", "status", "message"}
        ]
        if not business_items:
            return False
        if len(business_items) == 1 and isinstance(business_items[0][1], dict):
            return True
        list_keys = [key for key, value in business_items if isinstance(value, list)]
        scalar_count = sum(1 for _, value in business_items if not isinstance(value, (dict, list)))
        nested_dict_count = sum(1 for _, value in business_items if isinstance(value, dict))
        has_identifier = any(
            key in {"id", "pk", "name", "title", "code"} for key, _ in business_items
        )
        collection_list_keys = {"results", "items", "data", "records"}
        if len(list_keys) > 1:
            if (
                has_identifier
                and scalar_count >= 3
                and not any(key in collection_list_keys for key in list_keys)
            ):
                return True
            return False
        if len(list_keys) == 1:
            list_key = list_keys[0]
            if list_key in collection_list_keys:
                return False
            if scalar_count >= 1 and any(
                key in {"status", "service", "module"} for key, _ in business_items
            ):
                return True
            return has_identifier and scalar_count >= 2
        if scalar_count >= 3:
            return True
        if nested_dict_count >= 2:
            return True
        return has_identifier and (scalar_count + nested_dict_count) >= 2

    def _asset_name_map_for_rows(self, rows: list[dict[str, Any]]) -> dict[str, str]:
        codes: set[str] = set()
        for row in rows[:200]:
            if self._asset_name_from_row(row):
                continue
            for key, value in row.items():
                if self._is_asset_code_field(key) and self._looks_like_asset_code(value):
                    codes.update(self._asset_lookup_keys(value))
        return self._resolve_asset_names(sorted(codes)) if codes else {}

    def _display_row_value(
        self,
        row: dict[str, Any],
        key: str,
        asset_name_map: dict[str, str],
    ) -> str:
        value = row.get(key)
        if self._is_asset_code_field(key) and self._looks_like_asset_code(value):
            name = self._asset_name_from_row(row) or self._resolved_asset_name(
                value, asset_name_map
            )
            return self._display_asset_code(value, name)
        contextual = self._field_value_label(key, value)
        if contextual is not None:
            return contextual
        return self._display_value(value)

    def _display_value_for_key(
        self, key: str, value: Any, payload: dict[str, Any] | None = None
    ) -> str:
        if self._is_asset_code_field(key) and self._looks_like_asset_code(value):
            name = self._asset_name_from_row(payload or {})
            if not name:
                lookup_keys = self._asset_lookup_keys(value)
                name = self._resolved_asset_name(
                    value,
                    self._resolve_asset_names(lookup_keys) if lookup_keys else {},
                )
            return self._display_asset_code(value, name)
        contextual = self._field_value_label(key, value)
        if contextual is not None:
            return contextual
        return self._display_value(value)

    def _field_value_label(self, key: str, value: Any) -> str | None:
        if value is None or isinstance(value, (bool, dict, list)):
            return None
        normalized_key = str(key or "").strip().lower().replace("-", "_").split(".")[-1]
        value_labels = FIELD_VALUE_LABELS.get(normalized_key)
        if not value_labels:
            return None
        normalized_value = str(value).strip().lower()
        if not normalized_value:
            return None
        return value_labels.get(normalized_value)

    def _is_asset_code_field(self, key: str) -> bool:
        last_part = str(key or "").strip().lower().replace("-", "_").split(".")[-1]
        return last_part in ASSET_CODE_FIELDS

    def _looks_like_asset_code(self, value: Any) -> bool:
        if value is None or isinstance(value, bool):
            return False
        text = str(value).strip().upper()
        return bool(ASSET_CODE_PATTERN.match(text))

    def _asset_lookup_keys(self, value: Any) -> list[str]:
        text = str(value or "").strip().upper()
        if not text or not self._looks_like_asset_code(text):
            return []
        keys = [text]
        prefixed = re.match(r"^(SH|SZ|BJ)(\d{6})$", text)
        if prefixed:
            keys.append(f"{prefixed.group(2)}.{prefixed.group(1)}")
            keys.append(prefixed.group(2))
        elif "." in text:
            keys.append(text.split(".", 1)[0])
        return list(dict.fromkeys(keys))

    def _asset_name_from_row(self, row: dict[str, Any]) -> str:
        for key in ASSET_NAME_FIELDS:
            value = str(row.get(key) or "").strip()
            if value:
                return value
        return ""

    def _resolved_asset_name(self, value: Any, asset_name_map: dict[str, str]) -> str:
        for key in self._asset_lookup_keys(value):
            name = str(asset_name_map.get(key) or "").strip()
            if name:
                return name
        return ""

    def _display_asset_code(self, value: Any, name: str) -> str:
        code = self._display_value(value)
        clean_name = str(name or "").strip()
        if not clean_name or clean_name.upper() == str(value or "").strip().upper():
            return code
        if clean_name in code:
            return code
        return f"{code} {clean_name}"

    def _columns_for_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, str]]:
        keys: list[str] = []
        for row in rows[:12]:
            for key, value in row.items():
                if str(key).startswith("__"):
                    continue
                if key not in keys and not isinstance(value, (dict, list)):
                    keys.append(key)
        if not keys and rows:
            keys = [key for key in rows[0].keys() if not str(key).startswith("__")][:6]
        return [{"key": key, "label": self._humanize(key)} for key in keys[:8]]

    def _display_value(self, value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, bool):
            return "是" if value else "否"
        if isinstance(value, (dict, list)):
            return f"{len(value)} 项" if isinstance(value, list) else f"{len(value)} 个字段"
        text = str(value)
        if self._looks_like_html(text):
            return self._html_to_text(text)
        if self._is_internal_api_path(text):
            return "内部接口路径（调试抽屉查看）"
        return VALUE_LABELS.get(text.strip().lower(), text)

    def _is_internal_api_path(self, value: str) -> bool:
        text = str(value or "").strip()
        if text.startswith("/api/") or text.startswith("api/"):
            return True
        parsed = urlparse(text)
        return parsed.path.startswith("/api/")

    def _looks_like_html(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        text = value.strip()
        if not text:
            return False
        return bool(HTML_TAG_PATTERN.search(text) or ESCAPED_HTML_TAG_PATTERN.search(text))

    def _html_to_text(self, value: str) -> str:
        parser = _PlainTextHTMLParser()
        parser.feed(unescape(value))
        parser.close()
        text = parser.text()
        if not text:
            text = HTML_TAG_PATTERN.sub(" ", unescape(value))
            text = re.sub(r"\s+", " ", text).strip()
        text = self._translate_embedded_value_labels(text)
        return text[:4000]

    def _translate_embedded_value_labels(self, text: str) -> str:
        result = text
        for source, target in EMBEDDED_VALUE_LABELS.items():
            result = re.sub(rf"\b{re.escape(source)}\b", target, result, flags=re.IGNORECASE)
        return result

    def _advisor_today_sheet_model(
        self, action: dict[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
        order_summary = (
            payload.get("order_summary") if isinstance(payload.get("order_summary"), dict) else {}
        )
        execution_plan = (
            payload.get("execution_plan")
            if isinstance(payload.get("execution_plan"), dict)
            else {}
        )
        blockers = list(payload.get("blockers") or [])
        warnings = list(payload.get("warnings") or [])
        next_actions = list(payload.get("next_actions") or [])
        conclusion = self._advisor_verdict_label(payload.get("today_conclusion"))
        holdings_text = (
            f"{account.get('holding_count', 0)} 个持仓 / 现金 {self._display_value(account.get('available_cash'))} "
            f"/ 总资产 {self._display_value(account.get('total_asset'))}"
        )
        blocker_text = "无明确阻断项"
        if blockers:
            blocker_text = "；".join(
                self._operator_text(item.get("message") or "") for item in blockers[:2] if item
            ) or f"{len(blockers)} 项阻断"
        action_text = (
            f"共 {order_summary.get('total', 0)} 单 / 可执行 {order_summary.get('actionable', 0)} 单 "
            f"/ 阻断 {order_summary.get('blocked', 0)} 单"
        )
        risk_text = "；".join(
            filter(
                None,
                [
                    self._advisor_data_health_message(payload.get("data_health")),
                    f"执行模式 {self._display_value(execution_plan.get('execution_mode'))}",
                    f"确认 {self._display_value(execution_plan.get('confirmation_status'))}",
                ],
            )
        )
        return {
            "kind": "detail",
            "title": self._display_value(account.get("account_name") or action.get("label")),
            "status": conclusion,
            "fields": [
                {"key": "today_conclusion", "label": "账户结论", "value": conclusion},
                {"key": "holding_summary", "label": "持仓摘要", "value": holdings_text},
                {"key": "blockers", "label": "阻断项", "value": blocker_text},
                {"key": "orders", "label": "建议动作/建议订单", "value": action_text},
                {
                    "key": "risk_hints",
                    "label": "风险提示",
                    "value": risk_text or "当前未返回额外风险提示",
                },
            ],
            "nested": [
                {"key": "holdings", "label": "当前持仓", "count": len(payload.get("holdings") or [])},
                {"key": "order_intents", "label": "建议订单", "count": len(payload.get("order_intents") or [])},
                {"key": "blockers", "label": "阻断清单", "count": len(blockers)},
            ],
            "business_summary": f"{conclusion}；{action_text}",
            "blocking_reason": self._advisor_blocking_reason(payload),
            "next_steps": [
                *[
                    {
                        "label": self._operator_text(item.get("label") or "下一步"),
                        "hint": self._operator_text(item.get("hint") or ""),
                    }
                    for item in next_actions[:3]
                    if isinstance(item, dict)
                ],
                {
                    "label": "建议单因子明细",
                    "action_key": "advisor.factor_breakdown",
                    "params": {"account_id": account.get("account_id")},
                    "hint": "查看市场温度与组件明细。",
                },
            ],
            "debug_hidden_fields": [
                "holdings",
                "decision_cards",
                "data_health.market_thermometer.components",
                "execution_plan.orders",
            ],
        }

    def _ai_router_result_model(
        self, action: dict[str, Any], payload: dict[str, Any], status_code: int
    ) -> dict[str, Any]:
        reply = self._operator_text(
            payload.get("reply") or payload.get("message") or payload.get("error") or ""
        )
        error_code, mapped_reply = self._map_user_facing_ai_error(payload, reply)
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        selected_capability = self._display_value(
            payload.get("selected_capability_key")
            or metadata.get("selected_capability_key")
            or metadata.get("capability_name")
        )
        route_decision = self._display_value(
            metadata.get("decision") or payload.get("decision") or metadata.get("route")
        )
        requires_confirmation = self._display_value(
            payload.get("route_confirmation_required")
            or payload.get("requires_confirmation")
            or metadata.get("requires_confirmation")
        )
        next_step = self._ai_router_next_step(payload, error_code=error_code)
        status = self._status_label(status_code, payload)
        if error_code:
            status = "需配置"
        elif 400 <= int(status_code) < 500:
            status = "错误"
        return {
            "kind": "detail",
            "title": self._action_title(action),
            "status": status,
            "fields": [
                {"key": "reply", "label": "回复", "value": mapped_reply or reply or "-"},
                {
                    "key": "route",
                    "label": "已选能力/路由结论",
                    "value": f"{selected_capability} / {route_decision}",
                },
                {"key": "confirmation", "label": "是否需确认", "value": requires_confirmation},
                {"key": "next_step", "label": "建议下一步", "value": next_step},
            ],
            "nested": [],
            "business_summary": mapped_reply or reply or route_decision,
            "blocking_reason": mapped_reply if error_code else self._default_blocking_reason(payload, status_code),
            "next_steps": self._ai_router_next_steps(action, error_code=error_code),
            "debug_hidden_fields": [
                "session_id",
                "metadata.provider",
                "metadata.model",
                "metadata.answer_chain",
                "missing_params",
                "suggested_command",
                "suggested_intent",
            ],
            "user_error_code": error_code,
        }

    def _default_business_summary(
        self,
        action: dict[str, Any],
        view_model: dict[str, Any],
        payload: Any,
        status_code: int,
    ) -> str:
        if view_model.get("kind") == "datagrid":
            total = int(((view_model.get("pager") or {}).get("total_rows") or 0))
            return f"{self._action_title(action)}：{total} 行。"
        if view_model.get("kind") == "detail":
            fields = list(view_model.get("fields") or [])
            if fields:
                return "；".join(
                    f"{self._operator_text(item.get('label') or '')} {self._display_value(item.get('value'))}"
                    for item in fields[:2]
                )
        if view_model.get("kind") == "message":
            return self._operator_text(view_model.get("message") or "")
        return self._status_label(status_code, payload)

    def _default_blocking_reason(self, payload: Any, status_code: int) -> str:
        if 200 <= int(status_code) < 300:
            return ""
        if isinstance(payload, dict):
            for key in ("detail", "error", "message"):
                text = self._operator_text(payload.get(key) or "")
                if text:
                    return text
        return ""

    def _empty_next_steps(self, action: dict[str, Any], total: int) -> list[dict[str, Any]]:
        if total > 0:
            return []
        if str(action.get("screen_key") or "") != "macro-regime.strategy":
            return []
        return [
            {
                "label": "仓位规则",
                "action_key": "auto.api.get.api.strategy.position-rules",
                "hint": "先确认当前仓位规则是否已配置。",
            },
            {
                "label": "策略绑定",
                "action_key": "auto.api.get.api.strategy.assignments",
                "hint": "核对策略是否已绑定到账户或组合。",
            },
            {
                "label": "相关配置/同步任务",
                "action_key": "auto.api.get.api.strategy.script-configs",
                "hint": "打开策略配置，继续补齐同步或脚本配置。",
            },
        ]

    def _advisor_verdict_label(self, verdict: Any) -> str:
        mapping = {
            "ACT": "可以行动",
            "REVIEW": "需要复核",
            "WAIT": "继续等待",
            "BLOCKED": "已阻断",
        }
        normalized = str(verdict or "").strip().upper()
        return mapping.get(normalized, self._display_value(verdict))

    def _advisor_data_health_message(self, data_health: Any) -> str:
        if not isinstance(data_health, dict):
            return ""
        blocked_reasons = list(data_health.get("blocked_reasons") or [])
        if blocked_reasons:
            return self._operator_text(blocked_reasons[0])
        return f"数据状态 {self._display_value(data_health.get('status'))}"

    def _advisor_blocking_reason(self, payload: dict[str, Any]) -> str:
        blockers = list(payload.get("blockers") or [])
        if blockers:
            return "；".join(
                self._operator_text(item.get("message") or "") for item in blockers[:2] if item
            )
        warnings = list(payload.get("warnings") or [])
        if warnings:
            return self._operator_text(str(warnings[0]))
        data_health = payload.get("data_health")
        if isinstance(data_health, dict) and str(data_health.get("status") or "").strip().lower() not in {
            "",
            "ok",
            "normal",
        }:
            return self._advisor_data_health_message(data_health)
        return ""

    def _map_user_facing_ai_error(
        self, payload: dict[str, Any], reply: str
    ) -> tuple[str, str]:
        code = str(payload.get("code") or "").strip().upper()
        text = reply or ""
        if "System fallback quota is not configured for this user." in text:
            return (
                "AI_PROVIDER_NOT_CONFIGURED",
                "当前账号未配置默认 AI 服务，请先到 AI 服务商与用量 / 提示词与模型配置 完成配置。",
            )
        if "System fallback quota exhausted for today." in text:
            return (
                "AI_FALLBACK_QUOTA_DAILY_EXHAUSTED",
                "当前账号的默认 AI 当日额度已用完，请稍后重试或切换到个人 AI 服务商。",
            )
        if "System fallback quota exhausted for this month." in text:
            return (
                "AI_FALLBACK_QUOTA_MONTHLY_EXHAUSTED",
                "当前账号的默认 AI 当月额度已用完，请切换到个人 AI 服务商或联系管理员调整额度。",
            )
        if code == "VALIDATION_ERROR":
            return ("VALIDATION_ERROR", self._operator_text(payload.get("error") or "请求参数验证失败"))
        return "", ""

    def _ai_router_next_step(self, payload: dict[str, Any], *, error_code: str) -> str:
        if error_code == "AI_PROVIDER_NOT_CONFIGURED":
            return "先完成默认 AI 服务配置，再回到当前页面重试。"
        missing_params = list(payload.get("missing_params") or [])
        if missing_params:
            return "先补全缺失参数，再重新发起请求。"
        suggestion_prompt = self._operator_text(payload.get("suggestion_prompt") or "")
        if suggestion_prompt:
            return suggestion_prompt
        return "继续等待结果，或切换到更明确的能力/配置页面。"

    def _ai_router_next_steps(
        self, action: dict[str, Any], *, error_code: str
    ) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = [{"label": "重试", "action_key": str(action.get("key") or "")}]
        if error_code:
            steps.extend(
                [
                    {"label": "AI 服务商与用量", "screen_key": "ai-ops.providers"},
                    {"label": "提示词与模型配置", "screen_key": "ai-ops.prompts"},
                ]
            )
        elif str(action.get("key") or "") == "cli.chat_router":
            steps.extend(
                [
                    {"label": "打开 AI 交互终端", "screen_key": "ai-ops.terminal"},
                    {"label": "打开能力路由接入", "screen_key": "capability-router.gateway"},
                ]
            )
        return steps

    def _status_label(self, status_code: int, payload: Any | None = None) -> str:
        if 200 <= int(status_code) < 300:
            return STATUS_LABELS["OK"]
        if 300 <= int(status_code) < 400:
            return STATUS_LABELS["REDIRECT"]
        if self._looks_like_password_challenge(status_code, payload):
            return "需要密码"
        if self._looks_like_empty_state(status_code, payload):
            return STATUS_LABELS["EMPTY"]
        return STATUS_LABELS["ERROR"]

    def _looks_like_password_challenge(self, status_code: int, payload: Any | None) -> bool:
        if int(status_code) != 401 or not isinstance(payload, dict):
            return False
        if bool(payload.get("requires_password")):
            return True
        for key in ("detail", "error", "message"):
            value = payload.get(key)
            if isinstance(value, str) and "密码" in value:
                return True
        return False

    def _looks_like_empty_state(self, status_code: int, payload: Any | None) -> bool:
        if int(status_code) != 404 or not isinstance(payload, dict):
            return False
        detail = payload.get("detail")
        if not isinstance(detail, str):
            return False
        normalized = detail.strip().lower()
        if not normalized:
            return False
        empty_markers = (
            "没有",
            "暂无",
            "not found",
            "does not have",
            "missing",
            "不存在",
            "未配置",
        )
        return any(marker in normalized for marker in empty_markers)
