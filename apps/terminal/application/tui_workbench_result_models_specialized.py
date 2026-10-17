"""Business-specific result-model helpers for the TUI workbench."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from apps.terminal.application.tui_dashboard_result import TuiDashboardResultMixin
from apps.terminal.application.tui_egress_result import (
    build_egress_result,
    build_egress_saved_result,
)

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


class TuiWorkbenchSpecializedResultMixin(TuiDashboardResultMixin):
    """Specialized view-model builders layered on top of the base mixin."""

    if TYPE_CHECKING:

        def _action_title(self, action: dict[str, Any]) -> str: ...

        def _default_blocking_reason(self, payload: Any, status_code: int) -> str: ...

        def _display_value(self, value: Any) -> str: ...

        def _operator_text(self, value: Any) -> str: ...

        def _status_label(self, status_code: int, payload: Any | None = None) -> str: ...

        def _detail_model(
            self, action: dict[str, Any], payload: dict[str, Any], status_code: int
        ) -> dict[str, Any]: ...

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

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        """Return a mapping payload or an empty mapping for malformed API data."""

        return value if isinstance(value, dict) else {}

    def _custom_view_model(
        self,
        action: dict[str, Any],
        payload: Any,
        status_code: int,
        *,
        request_params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        action_key = str(action.get("key") or "")
        if action_key == "data-center.calendar-workbench-scope":
            return self._calendar_scope_result_model(action, payload, status_code)
        if action_key == "data-center.calendar-workbench-current":
            return self._calendar_current_result_model(action, payload, status_code, request_params)
        if action_key == "data-center.calendar-workbench-prepare":
            return self._calendar_preview_result_model(action, payload, status_code, request_params)
        if action_key == "data-center.calendar-workbench-confirm":
            return self._calendar_commit_result_model(action, payload, status_code)
        if action_key == "dashboard.alpha-ranking" and isinstance(payload, dict):
            meta = self._mapping(payload.get("meta"))
            notice = self._mapping(meta.get("refresh_notice"))
            if notice:
                rows = payload.get("items")
                result = self._datagrid_model(
                    action,
                    rows if isinstance(rows, list) else [],
                    status_code,
                    envelope=payload,
                    request_params=request_params,
                )
                result["business_summary"] = (
                    f"Alpha 自动更新异常。当前评分日期：{meta.get('effective_asof_date') or meta.get('cache_date') or '暂无可用评分'}；"
                    f"目标日期：{meta.get('requested_trade_date') or '未知'}；"
                    f"最近尝试：{notice.get('attempted_at') or '未知'}。"
                )
                result["blocking_reason"] = str(
                    notice.get("message") or "推理更新失败，请检查任务记录。"
                )
                return result
        if action_key in {
            "data-center.egress-preview",
            "data-center.egress-endpoint-test",
            "data-center.egress-diagnostics",
        } and isinstance(payload, dict):
            return build_egress_result(
                payload, title=self._action_title(action), status_code=status_code
            )
        if action_key in {
            "data-center.egress-endpoint-create",
            "data-center.egress-endpoint-update",
            "data-center.egress-rule-create",
            "data-center.egress-rule-update",
        } and isinstance(payload, dict):
            return build_egress_saved_result(
                payload, title=self._action_title(action), status_code=status_code
            )
        if action_key == "policy.queue_summary" and isinstance(payload, dict):
            keys = (
                "pending_review_count",
                "sla_exceeded_count",
                "effective_today_count",
                "policy_level",
                "gate_level",
            )
            ordered = {key: payload[key] for key in keys if key in payload}
            ordered.update(payload)
            result = self._detail_model(action, ordered, status_code)
            if payload.get("sla_exceeded_count"):
                result["status"] = "存在超时待审事件"
            elif payload.get("pending_review_count"):
                result["status"] = "有事件待审核"
            return result
        if action_key == "sentiment.awareness-summary" and isinstance(payload, dict):
            rows = [row for row in payload.get("indices", []) if isinstance(row, dict)]
            latest = sorted(rows, key=lambda row: str(row.get("date") or ""), reverse=True)[:1]
            return self._datagrid_model(
                action, latest, status_code, {**payload, "total": len(latest)}
            )
        if action_key == "advisor.today_sheet" and isinstance(payload, dict):
            return self._advisor_today_sheet_model(action, payload)
        if action_key in {
            "terminal.chat_router",
            "terminal.agent_chat",
            "terminal.agent_stream",
            "cli.chat_router",
            "cli.agent_chat",
            "cli.agent_stream",
            "capability-router.route-message",
        } and isinstance(payload, dict):
            return self._ai_router_result_model(action, payload, status_code)
        if action_key == "cli.agent_queue" and isinstance(payload, dict):
            return self._queued_agent_result_model(action, payload, status_code)
        if action_key in {
            "capability-router.mcp-self-status",
            "capability-router.mcp-self-endpoints",
            "capability-router.mcp-self-prompt-guide",
        } and isinstance(payload, dict):
            return self._mcp_self_service_result_model(action, payload)
        if action_key == "capability-router.verify-my-mcp-access" and isinstance(payload, dict):
            return self._mcp_access_verification_result_model(payload)
        if action_key in {
            "capability-router.create-my-mcp-token",
            "capability-router.revoke-my-mcp-token",
        } and isinstance(payload, dict):
            return self._mcp_self_service_mutation_result_model(action, payload)
        if (
            action_key == "regime.current"
            and isinstance(payload, dict)
            and isinstance(payload.get("summary"), dict)
        ):
            return self._regime_current_result_model(action, payload, status_code)
        if action_key == "dashboard.overview-summary" and isinstance(payload, dict):
            return self._dashboard_overview_result_model(action, payload, status_code)
        return None

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

    def _regime_current_result_model(
        self,
        action: dict[str, Any],
        payload: dict[str, Any],
        status_code: int,
    ) -> dict[str, Any]:
        """Project the Regime overview response onto the quadrant renderer contract."""

        summary = self._mapping(payload.get("summary"))
        available = bool(payload.get("available"))
        regime = self._display_value(summary.get("quadrant") or "Unknown")
        confidence = self._display_value(summary.get("confidence_percent"))
        growth_trend = self._regime_trend_label(summary.get("growth_trend"))
        inflation_trend = self._regime_trend_label(summary.get("inflation_trend"))
        trend = f"增长{growth_trend} / 通胀{inflation_trend}"
        raw_warnings = summary.get("warnings")
        warnings = (
            [self._operator_text(item) for item in raw_warnings]
            if isinstance(raw_warnings, list)
            else []
        )
        error = self._operator_text(summary.get("error") or "")
        warning = error or (warnings[0] if warnings else "无")
        status = self._status_label(status_code, payload) if available else "数据不足"
        return {
            "kind": "detail",
            "title": self._action_title(action),
            "status": status,
            "fields": [
                {"key": "current_regime", "label": "当前判断", "value": regime},
                {"key": "confidence", "label": "置信度", "value": confidence},
                {"key": "trend", "label": "增长与通胀趋势", "value": trend},
                {"key": "warning", "label": "拐点预警", "value": warning},
                {
                    "key": "growth_level",
                    "label": "增长水平",
                    "value": self._display_value(summary.get("growth_level")),
                },
                {
                    "key": "inflation_level",
                    "label": "通胀水平",
                    "value": self._display_value(summary.get("inflation_level")),
                },
                {
                    "key": "data_source",
                    "label": "数据来源",
                    "value": self._display_value(summary.get("source")),
                },
                {
                    "key": "as_of_date",
                    "label": "分析日期",
                    "value": self._display_value(summary.get("as_of_date")),
                },
            ],
            "nested": [],
            "business_summary": f"当前判断 {regime}；置信度 {confidence}%",
            "blocking_reason": error if not available else "",
            "next_steps": [],
            "debug_hidden_fields": ["distribution", "momentum", "history"],
        }

    def _regime_trend_label(self, value: Any) -> str:
        """Translate the bounded Regime trend vocabulary for operator display."""

        normalized = str(value or "flat").strip().lower()
        return {
            "up": "上行",
            "rising": "上行",
            "improving": "改善",
            "down": "下行",
            "falling": "下行",
            "deteriorating": "走弱",
            "flat": "持平",
            "stable": "稳定",
        }.get(normalized, self._display_value(value))

    def _advisor_today_sheet_model(
        self, action: dict[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        account = self._mapping(payload.get("account"))
        order_summary = self._mapping(payload.get("order_summary"))
        execution_plan = self._mapping(payload.get("execution_plan"))
        blockers = list(payload.get("blockers") or [])
        next_actions = list(payload.get("next_actions") or [])
        conclusion = self._advisor_verdict_label(payload.get("today_conclusion"))
        holdings_text = (
            f"{account.get('holding_count', 0)} 个持仓 / 现金 {self._display_value(account.get('available_cash'))} "
            f"/ 总资产 {self._display_value(account.get('total_asset'))}"
        )
        blocker_text = "无明确阻断项"
        if blockers:
            blocker_text = (
                "；".join(
                    self._operator_text(item.get("message") or "") for item in blockers[:2] if item
                )
                or f"{len(blockers)} 项阻断"
            )
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
                {
                    "key": "holdings",
                    "label": "当前持仓",
                    "count": len(payload.get("holdings") or []),
                },
                {
                    "key": "order_intents",
                    "label": "建议订单",
                    "count": len(payload.get("order_intents") or []),
                },
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
        metadata = self._mapping(payload.get("metadata"))
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
        if error_code == "AI_AGENT_BUSY":
            status = "系统繁忙"
        elif error_code == "AI_AGENT_TIMEOUT":
            status = "执行超时"
        elif error_code:
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
            "blocking_reason": (
                mapped_reply if error_code else self._default_blocking_reason(payload, status_code)
            ),
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

    def _queued_agent_result_model(
        self,
        action: dict[str, Any],
        payload: dict[str, Any],
        status_code: int,
    ) -> dict[str, Any]:
        """Project a durable server-side run admission into a bounded TUI detail.

        The TUI receives only the public run selectors and replay URLs.  The
        prompt, provider, broker, and worker internals remain on the server;
        a malformed admission is rendered as a stable error instead of being
        treated as a successful local or inline Agent execution.
        """

        run_id = payload.get("run_id")
        task_id = payload.get("task_id")
        run_status = payload.get("status")
        urls = {key: payload.get(key) for key in ("status_url", "events_url", "cancel_url")}
        valid_run = (
            isinstance(run_id, str)
            and bool(run_id)
            and isinstance(task_id, int)
            and not isinstance(task_id, bool)
            and task_id > 0
            and isinstance(run_status, str)
            and run_status in {"accepted", "queued"}
            and all(isinstance(value, str) and value.startswith("/api/") for value in urls.values())
        )
        if int(status_code) == 202 and valid_run:
            queued_run: dict[str, Any] = {
                "run_id": run_id,
                "task_id": task_id,
                "status": run_status,
                "status_url": urls["status_url"],
                "events_url": urls["events_url"],
                "cancel_url": urls["cancel_url"],
                "event_cursor": 0,
                "events": [],
            }
            return {
                "kind": "detail",
                "title": self._action_title(action),
                "status": "已排队",
                "fields": [
                    {"key": "run_id", "label": "运行编号", "value": run_id},
                    {"key": "task_id", "label": "任务 ID", "value": str(task_id)},
                    {"key": "run_status", "label": "运行状态", "value": "已排队"},
                    {
                        "key": "event_summary",
                        "label": "服务器进度",
                        "value": "等待服务器端 Worker 接收任务",
                    },
                ],
                "nested": [],
                "queued_run": queued_run,
                "business_summary": f"任务 {run_id} 已提交到服务器端队列。",
                "blocking_reason": "",
                "next_steps": [],
                "debug_hidden_fields": [
                    "status_url",
                    "events_url",
                    "cancel_url",
                    "task_id",
                ],
            }

        reason_code = str(payload.get("reason_code") or payload.get("code") or "").strip()
        if reason_code == "queued_runtime_not_wired":
            status = "队列暂不可用"
            detail = "服务器端排队运行时尚未启用；本次请求没有创建任务，也不会改用本地 Agent。"
            next_step = "由管理员完成服务器端队列与 Worker 配置后，再回到此处重试。"
            error_code = "QUEUED_RUNTIME_NOT_WIRED"
        elif int(status_code) == 429:
            status = "队列容量已满"
            detail = "服务器端队列当前已达到容量上限，请稍后重试。"
            next_step = "等待已有服务器端任务完成，不要重复提交相同请求。"
            error_code = "QUEUED_RUNTIME_CAPACITY_REJECTED"
        else:
            status = "排队请求失败"
            detail = self._operator_text(payload.get("error") or "服务器端没有接受排队请求。")
            next_step = "检查已有任务 ID 和请求内容后重试。"
            error_code = "QUEUED_RUN_REQUEST_FAILED"
        return {
            "kind": "detail",
            "title": self._action_title(action),
            "status": status,
            "fields": [
                {"key": "run_status", "label": "运行状态", "value": status},
                {"key": "detail", "label": "说明", "value": detail},
                {"key": "next_step", "label": "建议下一步", "value": next_step},
            ],
            "nested": [],
            "business_summary": detail,
            "blocking_reason": detail,
            "next_steps": [],
            "debug_hidden_fields": ["reason_code", "code", "retryable"],
            "user_error_code": error_code,
        }

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
        if isinstance(data_health, dict) and str(
            data_health.get("status") or ""
        ).strip().lower() not in {
            "",
            "ok",
            "normal",
        }:
            return self._advisor_data_health_message(data_health)
        return ""

    def _map_user_facing_ai_error(self, payload: dict[str, Any], reply: str) -> tuple[str, str]:
        code = str(payload.get("code") or "").strip().upper()
        text = reply or ""
        raw_error = str(payload.get("error") or "").strip().lower()
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
            return (
                "VALIDATION_ERROR",
                self._operator_text(payload.get("error") or "请求参数验证失败"),
            )
        if code == "AI_PROVIDER_UNAVAILABLE":
            return (
                "AI_PROVIDER_NOT_CONFIGURED",
                "当前账号没有可用的 AI 服务，请先完成服务商配置并测试连通性。",
            )
        if code == "AI_PROVIDER_REQUEST_FAILED" or raw_error == "terminal_agent_unavailable":
            return (
                "AI_PROVIDER_REQUEST_FAILED",
                "AI 服务调用失败，请检查服务商连通性、默认模型和额度后重试。",
            )
        if code == "AI_AGENT_BUSY":
            return (
                "AI_AGENT_BUSY",
                "已有智能助手任务正在执行，请等待当前任务完成后再重试，不要连续提交。",
            )
        if code == "AI_AGENT_TIMEOUT":
            return (
                "AI_AGENT_TIMEOUT",
                "智能助手执行超过时间上限，已安全停止；请缩小问题范围后重试。",
            )
        return "", ""

    def _ai_router_next_step(self, payload: dict[str, Any], *, error_code: str) -> str:
        if error_code == "AI_PROVIDER_NOT_CONFIGURED":
            return "先完成默认 AI 服务配置，再回到当前页面重试。"
        if error_code == "AI_PROVIDER_REQUEST_FAILED":
            return "先在 AI 服务商页面测试连通性，再核对默认模型和额度。"
        if error_code == "AI_AGENT_BUSY":
            return "等待当前任务完成后再重试，不要连续点击提交。"
        if error_code == "AI_AGENT_TIMEOUT":
            return "缩小问题范围、减少一次请求中的任务数量，然后重新提交。"
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
        steps: list[dict[str, Any]] = [
            {"label": "重试", "action_key": str(action.get("key") or "")}
        ]
        if error_code in {
            "AI_PROVIDER_NOT_CONFIGURED",
            "AI_PROVIDER_REQUEST_FAILED",
        }:
            steps.extend(
                [
                    {"label": "AI 服务商与用量", "screen_key": "ai-ops.providers"},
                    {"label": "提示词与模型配置", "screen_key": "ai-ops.prompts"},
                ]
            )
        elif str(action.get("key") or "") in {
            "cli.chat_router",
            "cli.agent_chat",
            "cli.agent_stream",
        }:
            steps.extend(
                [
                    {"label": "打开 AI 交互终端", "screen_key": "ai-ops.terminal"},
                    {"label": "打开能力路由接入", "screen_key": "capability-router.gateway"},
                ]
            )
        return steps

    def _mcp_self_service_result_model(
        self,
        action: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        action_key = str(action.get("key") or "")
        username = self._display_value(payload.get("username") or action.get("label"))
        mcp_status = "已开启" if bool(payload.get("mcp_enabled")) else "已关闭"
        preferred_token = self._mapping(payload.get("preferred_token"))
        token_name = self._display_value(
            preferred_token.get("name") or payload.get("agent_bootstrap_token_name") or "未配置"
        )
        token_display = self._display_value(
            payload.get("current_token_value")
            or payload.get("current_token_display")
            or preferred_token.get("display_token")
            or preferred_token.get("plaintext")
            or preferred_token.get("preview")
            or "未生成"
        )
        token_level = self._display_value(
            preferred_token.get("access_level_label")
            or payload.get("agent_bootstrap_access_level_label")
            or "-"
        )
        default_account = self._display_value(
            payload.get("default_account_name") or payload.get("default_account_id") or "未设置"
        )
        prompt_ready = (
            "已就绪" if bool(payload.get("agent_bootstrap_token_ready")) else "待生成令牌"
        )
        operator_hint = (
            "先创建只读令牌，再把下方智能路由地址与接入提示词交给助手。"
            if bool(payload.get("mcp_enabled"))
            else "当前账号未开通 MCP/SDK 接入，请先让管理员开启权限。"
        )

        access_package = self._mapping(payload.get("access_package"))
        if action_key == "capability-router.mcp-self-status" and access_package:
            state_labels = {
                "disabled": "未开通",
                "no_token": "待创建令牌",
                "ready": "可接入",
                "unavailable": "暂不可用",
            }
            blocking_reason_labels = {
                "mcp_disabled": "系统或当前账号尚未开启 MCP。",
                "no_token": "当前账号还没有有效 MCP 令牌。",
                "routing_unavailable": "智能路由服务当前不可用。",
                "catalog_unavailable": "能力目录服务当前不可用。",
                "token_plaintext_disabled": "系统策略禁止恢复历史令牌明文。",
                "token_decryption_failed": (
                    "当前部署密钥无法解密历史令牌；请恢复与数据库匹配的加密密钥。"
                ),
                "token_plaintext_unavailable": "当前令牌明文不可恢复，请重新签发令牌。",
                "https_required": "当前发布的是远程 HTTP 地址；请改用配置了有效证书的 HTTPS 域名。",
            }
            state = str(payload.get("self_service_state") or "unavailable")
            blocking_reason_code = str(payload.get("self_service_blocking_reason") or "")
            blocking_reason = blocking_reason_labels.get(blocking_reason_code, "")
            access_package_text = "\n".join(
                [
                    "AgomTradePro MCP 接入包",
                    f"Token: {access_package.get('token') or '未生成'}",
                    f"Route Endpoint: {access_package.get('route_endpoint') or '-'}",
                    (
                        "Capability Catalog: "
                        f"{access_package.get('capability_catalog_endpoint') or '-'}"
                    ),
                    (
                        "Transport Security: "
                        f"{access_package.get('transport_security') or '-'}; "
                        "certificate verification required"
                    ),
                    "",
                    str(access_package.get("agent_prompt") or "未生成接入提示词"),
                    "",
                    str(access_package.get("environment_statement") or "-"),
                ]
            )
            return {
                "kind": "detail",
                "title": username,
                "status": state_labels.get(state, "暂不可用"),
                "fields": [
                    {
                        "key": "access_token",
                        "label": "接入令牌",
                        "value": self._display_value(access_package.get("token") or "未生成"),
                        "presentation": "secret",
                    },
                    {
                        "key": "route_endpoint",
                        "label": "智能路由地址",
                        "value": str(access_package.get("route_endpoint") or "-"),
                        "presentation": "copyable",
                    },
                    {
                        "key": "capability_catalog_endpoint",
                        "label": "能力目录地址",
                        "value": str(access_package.get("capability_catalog_endpoint") or "-"),
                        "presentation": "copyable",
                    },
                    {
                        "key": "access_package",
                        "label": "完整接入包",
                        "value": access_package_text,
                        "presentation": "secret",
                    },
                    {
                        "key": "transport_security",
                        "label": "连接安全",
                        "value": {
                            "https": "HTTPS（必须校验证书）",
                            "local_http": "本机 HTTP（仅限同机）",
                            "insecure_http": "远程 HTTP（不可接入）",
                        }.get(
                            str(access_package.get("transport_security") or ""),
                            "未确认",
                        ),
                        "presentation": "metadata",
                    },
                    {
                        "key": "environment_statement",
                        "label": "环境说明",
                        "value": self._display_value(
                            access_package.get("environment_statement") or "-"
                        ),
                        "presentation": "metadata",
                    },
                    {
                        "key": "blocking_reason",
                        "label": "当前阻断",
                        "value": self._display_value(blocking_reason or "无"),
                        "presentation": "metadata",
                    },
                ],
                "nested": [],
                "blocking_reason": blocking_reason,
                "business_summary": (
                    f"当前接入状态：{state_labels.get(state, '暂不可用')}。" f"{blocking_reason}"
                ),
            }

        if action_key == "capability-router.mcp-self-endpoints":
            return {
                "kind": "detail",
                "title": username,
                "status": mcp_status,
                "fields": [
                    {
                        "key": "base_url",
                        "label": "基础地址",
                        "value": str(payload.get("base_url") or "-"),
                    },
                    {
                        "key": "api_root_endpoint",
                        "label": "系统入口",
                        "value": str(payload.get("api_root_endpoint") or "-"),
                    },
                    {
                        "key": "route_endpoint",
                        "label": "智能路由地址",
                        "value": str(payload.get("route_endpoint") or "-"),
                    },
                    {
                        "key": "web_endpoint",
                        "label": "网页对话地址",
                        "value": str(payload.get("web_endpoint") or "-"),
                    },
                    {
                        "key": "capability_endpoint",
                        "label": "能力目录地址",
                        "value": str(payload.get("capability_endpoint") or "-"),
                    },
                    {
                        "key": "operator_hint",
                        "label": "接入顺序",
                        "value": "优先走智能路由地址；只在排障时读取能力目录或网页对话地址。",
                    },
                ],
                "nested": [],
                "business_summary": "已提供个人接入所需地址。",
            }

        if action_key == "capability-router.mcp-self-prompt-guide":
            return {
                "kind": "detail",
                "title": username,
                "status": prompt_ready,
                "fields": [
                    {"key": "prompt_ready", "label": "提示词状态", "value": prompt_ready},
                    {"key": "token_name", "label": "当前令牌", "value": token_name},
                    {"key": "token_level", "label": "令牌级别", "value": token_level},
                    {"key": "operator_hint", "label": "操作提示", "value": operator_hint},
                    {
                        "key": "agent_bootstrap_prompt",
                        "label": "接入提示词",
                        "value": self._display_value(payload.get("agent_bootstrap_prompt") or "-"),
                    },
                ],
                "nested": [],
                "business_summary": "已生成可直接交给助手的接入提示词。",
            }

        return {
            "kind": "detail",
            "title": username,
            "status": mcp_status,
            "fields": [
                {
                    "key": "rbac_role",
                    "label": "角色",
                    "value": self._display_value(payload.get("rbac_role") or "-"),
                },
                {"key": "mcp_enabled", "label": "MCP 接入", "value": mcp_status},
                {
                    "key": "active_token_count",
                    "label": "活跃令牌",
                    "value": self._display_value(payload.get("active_token_count")),
                },
                {
                    "key": "token_plaintext_allowed",
                    "label": "明文显示",
                    "value": self._display_value(payload.get("token_plaintext_allowed")),
                },
                {"key": "current_token", "label": "当前令牌", "value": token_display},
                {"key": "current_token_level", "label": "当前令牌级别", "value": token_level},
                {"key": "default_account", "label": "默认账户", "value": default_account},
                {
                    "key": "base_url",
                    "label": "基础地址",
                    "value": self._display_value(payload.get("base_url")),
                },
            ],
            "nested": [
                {
                    "key": "access_tokens",
                    "label": "令牌列表",
                    "count": len(payload.get("access_tokens") or []),
                }
            ],
            "business_summary": f"{mcp_status}；令牌 {self._display_value(payload.get('active_token_count'))} 个。",
        }

    def _mcp_access_verification_result_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Build a bounded read-only MCP access verification model."""

        checks = list(payload.get("checks") or [])
        status = "验证通过" if payload.get("state") == "ready" else "需要处理"
        return {
            "kind": "detail",
            "title": "MCP 接入验证",
            "status": status,
            "fields": [
                {
                    "key": str(item.get("key") or "check"),
                    "label": self._display_value(item.get("label") or "检查项"),
                    "value": self._display_value(item.get("detail") or "-"),
                }
                for item in checks
                if isinstance(item, dict)
            ],
            "nested": [],
            "business_summary": status,
        }

    def _mcp_self_service_mutation_result_model(
        self,
        action: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        action_key = str(action.get("key") or "")
        self_service = self._mapping(payload.get("self_service"))
        token_payload = self._mapping(payload.get("token_payload"))
        created_prompt = self._mapping(payload.get("created_agent_prompt"))
        username = self._display_value(
            self_service.get("username") or token_payload.get("username") or action.get("label")
        )
        active_token_count = self._display_value(self_service.get("active_token_count"))
        route_endpoint = str(self_service.get("route_endpoint") or "-")

        if action_key == "capability-router.create-my-mcp-token":
            token_name = self._display_value(
                token_payload.get("token_name")
                or self_service.get("agent_bootstrap_token_name")
                or "未命名令牌"
            )
            token_level = self._display_value(
                token_payload.get("access_level_label")
                or created_prompt.get("agent_bootstrap_access_level_label")
                or self_service.get("agent_bootstrap_access_level_label")
                or "-"
            )
            token_value = self._display_value(
                token_payload.get("token")
                or self_service.get("current_token_value")
                or self_service.get("current_token_display")
                or "未返回明文令牌"
            )
            prompt_value = self._display_value(
                created_prompt.get("agent_bootstrap_prompt")
                or self_service.get("agent_bootstrap_prompt")
                or "-"
            )
            return {
                "kind": "detail",
                "title": username,
                "status": "已创建",
                "fields": [
                    {
                        "key": "message",
                        "label": "处理结果",
                        "value": self._display_value(payload.get("message") or "MCP 令牌已创建"),
                    },
                    {"key": "token_name", "label": "新令牌", "value": token_name},
                    {"key": "token_level", "label": "访问级别", "value": token_level},
                    {"key": "token_value", "label": "令牌明文", "value": token_value},
                    {
                        "key": "active_token_count",
                        "label": "活跃令牌",
                        "value": active_token_count,
                    },
                    {
                        "key": "route_endpoint",
                        "label": "智能路由地址",
                        "value": route_endpoint,
                    },
                    {
                        "key": "agent_bootstrap_prompt",
                        "label": "接入提示词",
                        "value": prompt_value,
                    },
                ],
                "nested": [
                    {
                        "key": "access_tokens",
                        "label": "令牌列表",
                        "count": len(self_service.get("access_tokens") or []),
                    }
                ],
                "business_summary": self._display_value(
                    payload.get("message") or f"已创建 {token_name}"
                ),
            }

        preferred_token = self._mapping(self_service.get("preferred_token"))
        token_display = self._display_value(
            self_service.get("current_token_value")
            or self_service.get("current_token_display")
            or preferred_token.get("display_token")
            or preferred_token.get("plaintext")
            or preferred_token.get("preview")
            or "未生成"
        )
        return {
            "kind": "detail",
            "title": username,
            "status": "已撤销",
            "fields": [
                {
                    "key": "message",
                    "label": "处理结果",
                    "value": self._display_value(payload.get("message") or "MCP 令牌已撤销"),
                },
                {"key": "active_token_count", "label": "剩余活跃令牌", "value": active_token_count},
                {"key": "current_token", "label": "当前令牌", "value": token_display},
                {"key": "route_endpoint", "label": "智能路由地址", "value": route_endpoint},
            ],
            "nested": [
                {
                    "key": "access_tokens",
                    "label": "令牌列表",
                    "count": len(self_service.get("access_tokens") or []),
                }
            ],
            "business_summary": self._display_value(
                payload.get("message") or "令牌已撤销，请复制新的可用令牌。"
            ),
        }
