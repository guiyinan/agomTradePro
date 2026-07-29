"""Collection-oriented result models for the TUI workbench."""

from __future__ import annotations

import re
from math import ceil, isfinite
from typing import TYPE_CHECKING, Any

from apps.terminal.application.tui_workbench_constants import (
    ROW_IDENTIFIER_FIELDS,
)


class TuiWorkbenchCollectionResultMixin:
    """Build chart, datagrid, and operator-facing collection results."""

    if TYPE_CHECKING:

        def _view_model_path(self, *args: Any, **kwargs: Any) -> str: ...

        def _value_at_path(self, *args: Any, **kwargs: Any) -> Any: ...

        def _find_list_value(self, *args: Any, **kwargs: Any) -> list[Any] | None: ...

        def _view_model_columns(self, *args: Any, **kwargs: Any) -> list[dict[str, str]]: ...

        def _action_title(self, *args: Any, **kwargs: Any) -> str: ...

        def _status_label(self, *args: Any, **kwargs: Any) -> str: ...

        def _display_value(self, *args: Any, **kwargs: Any) -> str: ...

        def _message_list_text(self, *args: Any, **kwargs: Any) -> str: ...

        def _message_model(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...

        def _columns_for_rows(self, *args: Any, **kwargs: Any) -> list[dict[str, str]]: ...

        def _asset_name_map_for_rows(self, *args: Any, **kwargs: Any) -> dict[str, str]: ...

        def _int_from_path(self, *args: Any, **kwargs: Any) -> int: ...

        def _int_from_params(self, *args: Any, **kwargs: Any) -> int: ...

        def _empty_datagrid_message(self, *args: Any, **kwargs: Any) -> str: ...

        def _empty_datagrid_guidance(self, *args: Any, **kwargs: Any) -> list[str]: ...

        def _empty_next_steps(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]: ...

        def _display_row_value(self, *args: Any, **kwargs: Any) -> Any: ...

    def _chart_model(
        self,
        action: dict[str, Any],
        payload: Any,
        status_code: int,
    ) -> dict[str, Any]:
        """Project tabular API rows into the portable chart result contract."""

        rows: list[Any] = []
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows_path = self._view_model_path(action, "rows_path")
            explicit_rows = self._value_at_path(payload, rows_path) if rows_path else None
            discovered_rows = (
                explicit_rows if isinstance(explicit_rows, list) else self._find_list_value(payload)
            )
            rows = discovered_rows or []

        mapping_rows = [row for row in rows if isinstance(row, dict)]
        columns = self._view_model_columns(action)
        title = self._action_title(action)
        chart_type = self._view_model_path(action, "chart_type") or "line"
        if len(columns) < 2:
            return {
                "kind": "chart",
                "chart_type": chart_type,
                "title": title,
                "status": self._status_label(status_code),
                "x_axis_label": columns[0]["label"] if columns else "",
                "series": [],
                "point_count": 0,
                "source_row_count": len(mapping_rows),
                "sampled": False,
                "empty_message": f"暂无{title}数据。",
            }

        x_column, *series_columns = columns
        ordered_rows = self._ordered_chart_rows(mapping_rows, x_column["key"])
        sampled_rows = self._sample_chart_rows(ordered_rows)
        series: list[dict[str, Any]] = []
        point_count = 0
        for column in series_columns:
            points: list[dict[str, str | float]] = []
            for row in sampled_rows:
                value = self._chart_number(row.get(column["key"]))
                if value is None:
                    continue
                label = self._display_value(row.get(x_column["key"]))
                points.append({"label": label, "value": value})
            point_count += len(points)
            series.append(
                {
                    "key": column["key"],
                    "label": column["label"],
                    "points": points,
                }
            )

        return {
            "kind": "chart",
            "chart_type": chart_type,
            "title": title,
            "status": self._status_label(status_code),
            "x_axis_label": x_column["label"],
            "series": series,
            "point_count": point_count,
            "source_row_count": len(ordered_rows),
            "sampled": len(sampled_rows) < len(ordered_rows),
            "empty_message": f"暂无{title}数据。",
        }

    def _table_chart_model(
        self,
        action: dict[str, Any],
        payload: Any,
        status_code: int,
    ) -> dict[str, Any]:
        """Project one payload into the portable chart-plus-table result shape."""

        source_model = dict(action.get("view_model") or {})
        table_action = dict(action)
        table_action["view_model"] = {
            "kind": "datagrid",
            "rows_path": source_model.get("table_rows_path", ""),
            "columns": list(source_model.get("table_columns") or []),
        }
        chart_action = dict(action)
        chart_action["view_model"] = {
            "kind": "chart",
            "chart_type": source_model.get("chart_type", "line"),
            "rows_path": source_model.get("chart_rows_path", ""),
            "columns": list(source_model.get("chart_columns") or []),
        }
        table_rows: list[Any] = []
        if isinstance(payload, list):
            table_rows = payload
        elif isinstance(payload, dict):
            resolved = self._value_at_path(
                payload,
                str(source_model.get("table_rows_path") or ""),
            )
            if isinstance(resolved, list):
                table_rows = resolved
        return {
            "kind": "table_chart",
            "title": self._action_title(action),
            "status": self._status_label(status_code),
            "chart": self._chart_model(chart_action, payload, status_code),
            "table": self._datagrid_model(
                table_action,
                table_rows,
                status_code,
                envelope=payload if isinstance(payload, dict) else None,
            ),
        }

    def _ordered_chart_rows(
        self,
        rows: list[dict[str, Any]],
        x_key: str,
    ) -> list[dict[str, Any]]:
        """Order ISO date/time axes oldest-first while preserving categorical order."""

        labels = [str(row.get(x_key) or "").strip() for row in rows]
        if labels and all(re.match(r"^\d{4}-\d{2}-\d{2}(?:T.*)?$", label) for label in labels):
            return sorted(rows, key=lambda row: str(row.get(x_key) or ""))
        return rows

    def _sample_chart_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        maximum: int = 240,
    ) -> list[dict[str, Any]]:
        """Bound SVG payloads while preserving the first and last observations."""

        if len(rows) <= maximum:
            return rows
        last_index = len(rows) - 1
        indexes = {round(index * last_index / (maximum - 1)) for index in range(maximum)}
        return [rows[index] for index in sorted(indexes)]

    def _chart_number(self, value: Any) -> float | None:
        """Return a finite numeric chart value without treating booleans as numbers."""

        if value is None or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if isfinite(number) else None

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
        scalar_rows = sum(1 for row in sample if not isinstance(row, dict | list))
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
        columns = self._view_model_columns(action) or self._columns_for_rows(normalized_rows)
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
            if normalized_key in payload or isinstance(value, dict | list):
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
        if raw_value in (None, "") or isinstance(raw_value, dict | list):
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


__all__ = ["TuiWorkbenchCollectionResultMixin"]
