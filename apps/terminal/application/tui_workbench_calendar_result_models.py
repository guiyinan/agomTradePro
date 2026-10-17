"""Pure presentation helpers for reference-calendar workbench results."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

_CALENDAR_FRESHNESS_KEYS = frozenset(
    {"source_observed_at", "source_available_at", "source_time_status"}
)
_CALENDAR_PREVIEW_RESULT_KEYS = frozenset(
    {
        "publication_status",
        "must_not_execute",
        "must_not_use_for_decision",
        "blocked_reason",
        "freshness",
        "reliability",
        "exchange",
        "coverage_start",
        "coverage_end",
        "first_seen_at",
        "source_published_at",
        "previewed_at",
        "response_expires_at",
        "message",
    }
)
_CALENDAR_COMMIT_RESULT_KEYS = frozenset(
    {
        "publication_status",
        "must_not_execute",
        "must_not_use_for_decision",
        "blocked_reason",
        "freshness",
        "reliability",
        "exchange",
        "coverage_start",
        "coverage_end",
        "transition_label",
        "published_at",
        "first_seen_at",
        "source_published_at",
        "response_expires_at",
        "checked_at",
        "message",
    }
)
_CALENDAR_COMMIT_TRANSITIONS = frozenset(
    {"日历已首次发布", "日历版本已更新", "当前日历版本已再次确认"}
)


class TuiWorkbenchCalendarResultMixin:
    """Project reference-calendar owner results into safe TUI models."""

    if TYPE_CHECKING:

        def _message_model(
            self, action: dict[str, Any], message: str, status_code: int
        ) -> dict[str, Any]: ...
        def _datagrid_model(
            self,
            action: dict[str, Any],
            rows: list[Any],
            status_code: int,
            envelope: dict[str, Any] | None = None,
            request_params: dict[str, Any] | None = None,
        ) -> dict[str, Any]: ...

    def _calendar_scope_result_model(
        self,
        action: dict[str, Any],
        payload: Any,
        status_code: int,
    ) -> dict[str, Any]:
        """Show only the calendar configuration message and its configured TTL."""

        if not 200 <= status_code < 300:
            return self._calendar_message_model(
                action, "日历配置状态读取失败，请检查管理员配置后重试。", status_code, "读取失败"
            )
        if type(payload) is not dict:
            return self._calendar_message_model(
                action, "日历配置状态无法安全显示，请重新读取。", status_code, "状态待确认"
            )
        if payload.get("metadata_status") == "blocked" and payload.get("metadata") is None:
            return self._calendar_message_model(
                action,
                "未能确定唯一可用的日历配置，请管理员检查配置后重试。",
                status_code,
                "配置不可用",
            )
        metadata = payload.get("metadata")
        if payload.get("metadata_status") != "metadata_selected" or type(metadata) is not dict:
            return self._calendar_message_model(
                action, "日历配置状态无法安全显示，请重新读取。", status_code, "状态待确认"
            )
        response_age = metadata.get("calendar_response_max_age_seconds")
        if type(response_age) is not int or response_age <= 0:
            return self._calendar_message_model(
                action, "日历配置状态无法安全显示，请重新读取。", status_code, "状态待确认"
            )
        message = (
            f"日历配置元数据已读取；来源响应最大有效期为 {response_age} 秒。"
            "凭据、数据源运行状态和当前发布状态尚未检查。"
        )
        return self._calendar_message_model(action, message, status_code, "已读取配置元数据")

    def _calendar_preview_result_model(
        self,
        action: dict[str, Any],
        payload: Any,
        status_code: int,
        request_params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Show a validated preview receipt in the visible primary result area."""

        if not 200 <= status_code < 300:
            return self._calendar_message_model(
                action,
                "日历预览未能完成，请检查状态后重新准备。",
                status_code,
                "预览未完成",
            )
        if type(payload) is not dict or not self._calendar_receipt_base_is_displayable(
            payload,
            allowed_keys=_CALENDAR_PREVIEW_RESULT_KEYS,
            publication_status="preview",
            reliability="unpublished_publication_preview",
        ):
            return self._calendar_message_model(
                action,
                "预览结果无法安全确认，请重新读取配置并准备预览。",
                status_code,
                "状态待确认",
            )

        exchange = payload["exchange"]
        start = self._calendar_date(payload["coverage_start"])
        end = self._calendar_date(payload["coverage_end"])
        first_seen = self._calendar_utc_timestamp(payload["first_seen_at"])
        previewed_at = self._calendar_utc_timestamp(payload["previewed_at"])
        expiry = self._calendar_utc_timestamp(payload["response_expires_at"])
        if (
            start is None
            or end is None
            or first_seen is None
            or previewed_at is None
            or expiry is None
            or not self._calendar_result_matches_request(
                payload,
                request_params,
                exchange=exchange,
                start=start,
                end=end,
            )
        ):
            return self._calendar_message_model(
                action,
                "预览结果无法安全确认，请重新读取配置并准备预览。",
                status_code,
                "状态待确认",
            )

        source_time = self._calendar_source_time_text(payload["source_published_at"])
        message = (
            f"日历预览已准备，尚未发布。交易所 {exchange}；覆盖日期 {start.isoformat()} 至 "
            f"{end.isoformat()}。来源响应完成时间（本地首次记录）{first_seen}；"
            f"预览时间 {previewed_at}；来源响应有效期至 {expiry}。{source_time}"
            "上游观测时间未知；仅供参考，不可用于交易或投资决策。请在有效期内明确确认。"
        )
        return self._calendar_message_model(action, message, status_code, "预览已准备")

    def _calendar_commit_result_model(
        self,
        action: dict[str, Any],
        payload: Any,
        status_code: int,
    ) -> dict[str, Any]:
        """Show a bounded publication receipt while hiding all server identities."""

        if not 200 <= status_code < 300:
            return self._calendar_message_model(
                action,
                "发布结果无法确认，请重新读取当前日历后再决定是否重试。",
                status_code,
                "发布结果待确认",
            )
        if type(payload) is not dict or not self._calendar_receipt_base_is_displayable(
            payload,
            allowed_keys=_CALENDAR_COMMIT_RESULT_KEYS,
            publication_status="published",
            reliability="audited_calendar_reference",
        ):
            return self._calendar_message_model(
                action,
                "发布回执无法安全确认，请重新读取当前日历。",
                status_code,
                "状态待确认",
            )

        transition = payload["transition_label"]
        start = self._calendar_date(payload["coverage_start"])
        end = self._calendar_date(payload["coverage_end"])
        first_seen = self._calendar_utc_timestamp(payload["first_seen_at"])
        published_at = self._calendar_utc_timestamp(payload["published_at"])
        checked_at = self._calendar_utc_timestamp(payload["checked_at"])
        expiry = self._calendar_utc_timestamp(payload["response_expires_at"])
        if (
            type(transition) is not str
            or transition not in _CALENDAR_COMMIT_TRANSITIONS
            or start is None
            or end is None
            or first_seen is None
            or published_at is None
            or checked_at is None
            or expiry is None
        ):
            return self._calendar_message_model(
                action,
                "发布回执无法安全确认，请重新读取当前日历。",
                status_code,
                "状态待确认",
            )

        source_time = self._calendar_source_time_text(payload["source_published_at"])
        message = (
            f"{transition}。交易所 {payload['exchange']}；覆盖日期 {start.isoformat()} 至 "
            f"{end.isoformat()}。来源响应完成时间（本地首次记录）{first_seen}；"
            f"发布确认时间 {published_at}；来源响应有效期至 {expiry}。{source_time}"
            f"上游观测时间未知；{transition}后的日历仅供参考，不可用于交易或投资决策。"
        )
        return self._calendar_message_model(action, message, status_code, transition)

    def _calendar_receipt_base_is_displayable(
        self,
        payload: dict[str, Any],
        *,
        allowed_keys: frozenset[str],
        publication_status: str,
        reliability: str,
    ) -> bool:
        """Require the exact owner receipt shape and its reference-only boundary."""

        freshness = payload.get("freshness")
        source_published_at = payload.get("source_published_at")
        start = self._calendar_date(payload.get("coverage_start"))
        end = self._calendar_date(payload.get("coverage_end"))
        return bool(
            set(payload) == allowed_keys
            and type(freshness) is dict
            and set(freshness) == _CALENDAR_FRESHNESS_KEYS
            and payload.get("publication_status") == publication_status
            and payload.get("must_not_execute") is True
            and payload.get("must_not_use_for_decision") is True
            and payload.get("blocked_reason") == "exchange_calendar_reference_only"
            and payload.get("reliability") == reliability
            and freshness.get("source_observed_at") is None
            and freshness.get("source_available_at") is None
            and freshness.get("source_time_status") == "not_provided"
            and type(payload.get("exchange")) is str
            and bool(payload["exchange"])
            and payload["exchange"].strip() == payload["exchange"]
            and start is not None
            and end is not None
            and start <= end
            and (source_published_at is None or self._calendar_utc_timestamp(source_published_at))
            and type(payload.get("message")) is str
            and bool(payload["message"].strip())
        )

    def _calendar_result_matches_request(
        self,
        payload: dict[str, Any],
        request_params: dict[str, Any] | None,
        *,
        exchange: str,
        start: date,
        end: date,
    ) -> bool:
        """Bind the returned preview to the exact exchange and dates requested."""

        if type(request_params) is not dict:
            return False
        request_start = self._calendar_date(request_params.get("coverage_start"))
        request_end = self._calendar_date(request_params.get("coverage_end"))
        return bool(
            request_params.get("exchange") == exchange
            and request_start == start
            and request_end == end
            and payload.get("coverage_start") == request_params.get("coverage_start")
            and payload.get("coverage_end") == request_params.get("coverage_end")
        )

    def _calendar_source_time_text(self, source_published_at: Any) -> str:
        """Describe an optional upstream publication time without inventing one."""

        if source_published_at is None:
            return "上游发布时间未知；"
        timestamp = self._calendar_utc_timestamp(source_published_at)
        return f"上游发布时间 {timestamp}；" if timestamp is not None else ""

    def _calendar_current_result_model(
        self,
        action: dict[str, Any],
        payload: Any,
        status_code: int,
        request_params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Render a current reference calendar or a bounded non-success message."""

        if not 200 <= status_code < 300:
            return self._calendar_message_model(
                action,
                "当前参考日历读取失败，请检查交易所标识或配置后重试。",
                status_code,
                "读取失败",
            )
        if type(payload) is not dict:
            return self._calendar_message_model(
                action, "当前日历结果无法确认，请重新读取。", status_code, "状态待确认"
            )
        current_status = payload.get("current_status")
        if current_status == "blocked" and payload.get("configuration_status") == "blocked":
            return self._calendar_message_model(
                action, "当前日历配置不可用，读取已阻断；请管理员检查配置。", status_code, "已阻断"
            )
        if (
            current_status == "not_found"
            and payload.get("configuration_status") == "metadata_selected"
        ):
            return self._calendar_message_model(
                action, "当前配置下没有已发布的参考日历。", status_code, "无当前版本"
            )
        if (
            current_status != "published"
            or payload.get("configuration_status") != "metadata_selected"
        ):
            return self._calendar_message_model(
                action, "当前日历结果无法确认，请重新读取。", status_code, "状态待确认"
            )
        current = payload.get("current")
        if type(current) is not dict or not self._calendar_current_is_displayable(current):
            return self._calendar_message_model(
                action, "当前日历结果无法确认，请重新读取。", status_code, "状态待确认"
            )
        if not isinstance(request_params, dict) or current.get("exchange") != request_params.get(
            "exchange"
        ):
            return self._calendar_message_model(
                action, "当前日历结果无法确认，请重新读取。", status_code, "状态待确认"
            )
        rows = self._calendar_display_rows(current)
        if rows is None:
            return self._calendar_message_model(
                action, "当前日历结果无法确认，请重新读取。", status_code, "状态待确认"
            )
        grid = self._datagrid_model(action, rows, status_code)
        grid["status"] = "仅供参考"
        grid["business_summary"] = (
            f"{current['exchange']} 参考日历（{current['coverage_start']} 至 "
            f"{current['coverage_end']}）；来源响应完成时间 {current['first_seen_at']} "
            "（本地首次记录，非上游观测时间）；上游观测时间未知；"
            f"来源响应有效期至 {current['response_expires_at']}。"
            "仅供参考，不可用于交易或投资决策。"
        )
        grid["blocking_reason"] = ""
        return grid

    def _calendar_current_is_displayable(self, current: dict[str, Any]) -> bool:
        """Require the published reference-only state and its original UTC window."""

        freshness = current.get("freshness")
        if type(freshness) is not dict:
            return False
        if not (
            current.get("publication_status") == "published"
            and current.get("must_not_execute") is True
            and current.get("must_not_use_for_decision") is True
            and current.get("reliability") == "audited_calendar_reference"
            and freshness.get("source_observed_at") is None
            and freshness.get("source_available_at") is None
            and freshness.get("source_time_status") == "not_provided"
        ):
            return False
        exchange = current.get("exchange")
        start = self._calendar_date(current.get("coverage_start"))
        end = self._calendar_date(current.get("coverage_end"))
        first_seen = self._calendar_utc_timestamp(current.get("first_seen_at"))
        expiry = self._calendar_utc_timestamp(current.get("response_expires_at"))
        return bool(
            type(exchange) is str
            and exchange
            and start is not None
            and end is not None
            and first_seen is not None
            and expiry is not None
        )

    def _calendar_display_rows(self, current: dict[str, Any]) -> list[dict[str, str]] | None:
        """Project the owner's typed calendar facts into three user-facing columns."""

        days = current.get("calendar_days")
        if type(days) is not list or not days:
            return None
        exchange = current.get("exchange")
        rows: list[dict[str, str]] = []
        for day in days:
            if type(day) is not dict or day.get("exchange") != exchange:
                return None
            calendar_date = self._calendar_date(day.get("calendar_date"))
            previous_open = day.get("previous_open_date")
            if (
                calendar_date is None
                or type(day.get("is_open")) is not bool
                or (previous_open is not None and self._calendar_date(previous_open) is None)
            ):
                return None
            rows.append(
                {
                    "calendar_date": calendar_date.isoformat(),
                    "calendar_state": "开市" if day["is_open"] else "休市",
                    "previous_open_date": previous_open or "未提供",
                }
            )
        return rows

    @staticmethod
    def _calendar_date(value: Any) -> date | None:
        """Parse only canonical ISO dates at this presentation boundary."""

        if type(value) is not str:
            return None
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.isoformat() == value else None

    @staticmethod
    def _calendar_utc_timestamp(value: Any) -> str | None:
        """Preserve a nonempty UTC timestamp without inventing source timing."""

        if type(value) is not str or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return value if parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0) else None

    def _calendar_message_model(
        self,
        action: dict[str, Any],
        message: str,
        status_code: int,
        status_label: str,
    ) -> dict[str, Any]:
        """Return a safe message with no raw owner metadata."""

        model = self._message_model(action, message, status_code)
        model["status"] = status_label
        model["business_summary"] = message
        model["blocking_reason"] = message if status_code >= 400 else ""
        return model
