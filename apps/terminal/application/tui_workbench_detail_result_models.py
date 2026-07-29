"""Detail-oriented result models for the TUI workbench."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from apps.terminal.application.tui_workbench_constants import (
    ASSET_CODE_FIELDS,
    ASSET_CODE_PATTERN,
    ASSET_NAME_FIELDS,
    EMBEDDED_VALUE_LABELS,
    ESCAPED_HTML_TAG_PATTERN,
    FIELD_VALUE_LABELS,
    HTML_TAG_PATTERN,
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


class TuiWorkbenchDetailResultMixin:
    """Build messages, detail fields, endpoints, and display values."""

    if TYPE_CHECKING:

        def _looks_like_password_challenge(self, *args: Any, **kwargs: Any) -> bool: ...

        def _humanize(self, *args: Any, **kwargs: Any) -> str: ...

        def _action_title(self, *args: Any, **kwargs: Any) -> str: ...

        def _status_label(self, *args: Any, **kwargs: Any) -> str: ...

        def _operator_text(self, *args: Any, **kwargs: Any) -> str: ...

        def _resolve_asset_names(self, *args: Any, **kwargs: Any) -> dict[str, str]: ...

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
        if any(isinstance(row, dict | list | tuple | set) for row in rows):
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
            if not isinstance(value, dict | list)
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
        scalar_count = sum(1 for _, value in business_items if not isinstance(value, dict | list))
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
        if value is None or isinstance(value, bool | dict | list):
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
                if key not in keys and not isinstance(value, dict | list):
                    keys.append(key)
        if not keys and rows:
            keys = [key for key in rows[0].keys() if not str(key).startswith("__")][:6]
        return [{"key": key, "label": self._humanize(key)} for key in keys[:8]]

    def _view_model_columns(self, action: dict[str, Any]) -> list[dict[str, str]]:
        """Return explicitly published datagrid columns in their user-facing order."""

        view_model = action.get("view_model") or {}
        if not isinstance(view_model, dict):
            return []
        columns = view_model.get("columns")
        if not isinstance(columns, list):
            return []
        return [
            {"key": str(column["key"]), "label": str(column["label"])}
            for column in columns
            if isinstance(column, dict) and column.get("key") and column.get("label")
        ][:8]

    def _display_value(self, value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, bool):
            return "是" if value else "否"
        if isinstance(value, dict | list):
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


__all__ = ["TuiWorkbenchDetailResultMixin"]
