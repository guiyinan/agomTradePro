"""Service-level projections for the exchange-calendar TUI workbench."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.infrastructure import tui_metadata_repository
from apps.terminal.infrastructure.tui_metadata_repository import (
    PublishedTuiMetadataRepository,
)

ROOT = Path(__file__).resolve().parents[3]
PUBLISHED_PATH = ROOT / "config" / "tui" / "published" / "tui_operation_graph.published.json"
SCOPE_ACTION = "data-center.calendar-workbench-scope"
CURRENT_ACTION = "data-center.calendar-workbench-current"
PREPARE_ACTION = "data-center.calendar-workbench-prepare"
CONFIRM_ACTION = "data-center.calendar-workbench-confirm"


class _StaticMetadataRepository:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def load_published(self, registry_key: str = "default") -> dict[str, Any]:
        del registry_key
        return self.payload


class _Executor:
    def __init__(
        self,
        payload: dict[str, Any],
        status_code: int = 200,
        continuation: dict[str, Any] | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.continuation = continuation
        self.calls: list[dict[str, Any]] = []

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        response_payload = {
            "outcome": "success",
            "success": True,
            "data": self.payload,
        }
        if self.continuation is not None:
            response_payload["continuation"] = self.continuation
        return {
            "status_code": self.status_code,
            "payload": response_payload,
        }


def _service(
    payload: dict[str, Any],
    monkeypatch: Any,
    status_code: int = 200,
    *,
    continuation: dict[str, Any] | None = None,
) -> tuple[TuiWorkbenchService, _Executor]:
    """Build the real workbench service with normalized published runtime metadata."""

    raw = json.loads(PUBLISHED_PATH.read_text(encoding="utf-8"))
    repository = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)
    monkeypatch.setattr(
        tui_metadata_repository,
        "RUNTIME_METADATA_INJECTIONS",
        copy.deepcopy(tui_metadata_repository.RUNTIME_METADATA_INJECTIONS),
    )
    metadata = repository.validate_and_normalize_runtime_payload(raw)
    executor = _Executor(payload, status_code, continuation)
    service = TuiWorkbenchService(
        metadata_repository=_StaticMetadataRepository(metadata),
        action_executor=executor,
    )
    return service, executor


def _admin() -> SimpleNamespace:
    return SimpleNamespace(
        pk=71,
        is_authenticated=True,
        is_staff=True,
        is_superuser=True,
        role="admin",
    )


def _preview_payload() -> dict[str, Any]:
    """Mirror the exact safe data object returned by the Calendar API presenter."""

    return {
        "publication_status": "preview",
        "must_not_execute": True,
        "must_not_use_for_decision": True,
        "blocked_reason": "exchange_calendar_reference_only",
        "freshness": {
            "source_observed_at": None,
            "source_available_at": None,
            "source_time_status": "not_provided",
        },
        "reliability": "unpublished_publication_preview",
        "exchange": "SSE",
        "coverage_start": "2026-10-15",
        "coverage_end": "2026-10-16",
        "first_seen_at": "2026-10-17T02:00:00Z",
        "source_published_at": None,
        "previewed_at": "2026-10-17T02:01:00Z",
        "response_expires_at": "2026-10-18T02:00:00Z",
        "message": "预览已准备，请在有效期内确认；该日历仅供参考，不可用于交易或投资决策。",
    }


def _published_payload() -> dict[str, Any]:
    """Mirror the exact safe commit object returned by the Calendar API presenter."""

    return {
        "publication_status": "published",
        "must_not_execute": True,
        "must_not_use_for_decision": True,
        "blocked_reason": "exchange_calendar_reference_only",
        "freshness": {
            "source_observed_at": None,
            "source_available_at": None,
            "source_time_status": "not_provided",
        },
        "reliability": "audited_calendar_reference",
        "exchange": "SSE",
        "coverage_start": "2026-10-15",
        "coverage_end": "2026-10-16",
        "transition_label": "日历已首次发布",
        "published_at": "2026-10-17T02:02:00Z",
        "first_seen_at": "2026-10-17T02:00:00Z",
        "source_published_at": None,
        "response_expires_at": "2026-10-18T02:00:00Z",
        "checked_at": "2026-10-17T02:02:01Z",
        "message": "日历发布已完成，但当前数据仍仅供参考，不可用于交易或投资决策。",
    }


def test_scope_service_projection_exposes_only_safe_message_and_configured_ttl(
    monkeypatch: Any,
) -> None:
    payload = {
        "metadata_status": "metadata_selected",
        "blocked_reason": None,
        "secret_runtime_status": "not_checked",
        "current_pointer_status": "not_scoped",
        "known_at": "2026-10-17T02:00:00Z",
        "metadata": {
            "dataset_key": "internal.dataset.calendar",
            "contract_version": "calendar-v1",
            "schema_version": "schema-private",
            "calendar_response_max_age_seconds": 86400,
            "policy_identity": "private-policy-hash",
            "policy_version": 17,
            "member_codec_version": "calendar-v1",
            "provider_id": "private-provider-id",
            "provider": "tushare",
            "capability": "trade_cal",
            "validator_key": "private-validator",
        },
        "message": "日历捕获配置已读取；凭据、数据源运行状态和当前发布状态尚未检查。",
    }
    service, executor = _service(payload, monkeypatch)

    result = service.run_action(action_key=SCOPE_ACTION, params={}, user=_admin())
    view_model = result["view_model"]

    assert len(executor.calls) == 1
    assert view_model["kind"] == "message"
    assert "86400 秒" in view_model["message"]
    assert all(
        item in view_model["message"]
        for item in ("凭据", "数据源运行状态", "当前发布状态", "尚未检查")
    )
    visible = repr(view_model)
    for private_value in (
        "internal.dataset.calendar",
        "schema-private",
        "private-policy-hash",
        "private-provider-id",
        "private-validator",
        "tushare",
        "trade_cal",
    ):
        assert private_value not in visible


def test_prepare_service_projection_surfaces_exact_safe_preview_receipt(
    monkeypatch: Any,
) -> None:
    service, executor = _service(
        _preview_payload(),
        monkeypatch,
        status_code=201,
        continuation={
            "action_key": CONFIRM_ACTION,
            "input": {"confirmation_token": "encrypted:v1:fixture-token"},
            "expires_at": "2999-10-18T02:00:00Z",
        },
    )

    result = service.run_action(
        action_key=PREPARE_ACTION,
        params={
            "exchange": "SSE",
            "coverage_start": "2026-10-15",
            "coverage_end": "2026-10-16",
        },
        user=_admin(),
        confirmed=True,
    )
    view_model = result["view_model"]

    assert len(executor.calls) == 1
    assert view_model["kind"] == "message"
    assert view_model["status"] == "预览已准备"
    message = view_model["message"]
    for expected in (
        "SSE",
        "2026-10-15",
        "2026-10-16",
        "2026-10-17T02:00:00Z",
        "2026-10-18T02:00:00Z",
        "上游观测时间未知",
        "仅供参考",
        "不可用于交易或投资决策",
    ):
        assert expected in message
    assert "previewed_at" not in repr(view_model)
    assert "confirmation_token" not in repr(view_model)
    assert "fixture-token" not in repr(result["debug"])
    assert "exchange_calendar_reference_only" not in repr(view_model)


def test_confirm_service_projection_surfaces_exact_safe_publication_receipt(
    monkeypatch: Any,
) -> None:
    service, executor = _service(_published_payload(), monkeypatch, status_code=201)

    result = service.run_action(
        action_key=CONFIRM_ACTION,
        params={"confirmation_token": "encrypted:v1:must-not-display"},
        user=_admin(),
        confirmed=True,
    )
    view_model = result["view_model"]

    assert len(executor.calls) == 1
    assert view_model["kind"] == "message"
    assert view_model["status"] == "日历已首次发布"
    message = view_model["message"]
    for expected in (
        "SSE",
        "2026-10-15",
        "2026-10-16",
        "2026-10-17T02:00:00Z",
        "2026-10-18T02:00:00Z",
        "2026-10-17T02:02:00Z",
        "上游观测时间未知",
        "仅供参考",
        "不可用于交易或投资决策",
    ):
        assert expected in message
    visible = repr(view_model)
    for private_value in (
        "encrypted:v1:must-not-display",
        "confirmation_token",
        "exchange_calendar_reference_only",
        "audited_calendar_reference",
        "content_hash",
        "activation_id",
    ):
        assert private_value not in visible


def test_prepare_projection_preserves_zero_and_fractional_timestamp_text(
    monkeypatch: Any,
) -> None:
    payload = _preview_payload() | {
        "first_seen_at": "2026-10-17T02:00:00Z",
        "previewed_at": "2026-10-17T02:00:00.100000Z",
        "response_expires_at": "2026-10-18T02:00:00Z",
    }
    service, _ = _service(
        payload,
        monkeypatch,
        status_code=201,
        continuation={
            "action_key": CONFIRM_ACTION,
            "input": {"confirmation_token": "encrypted:v1:fixture-token"},
            "expires_at": "2999-10-18T02:00:00Z",
        },
    )

    result = service.run_action(
        action_key=PREPARE_ACTION,
        params={
            "exchange": "SSE",
            "coverage_start": "2026-10-15",
            "coverage_end": "2026-10-16",
        },
        user=_admin(),
        confirmed=True,
    )

    view_model = result["view_model"]
    assert view_model["status"] == "预览已准备"
    assert all(
        value in view_model["message"]
        for value in (
            "2026-10-17T02:00:00Z",
            "2026-10-17T02:00:00.100000Z",
            "2026-10-18T02:00:00Z",
        )
    )


def test_commit_projection_preserves_zero_and_fractional_timestamp_text(
    monkeypatch: Any,
) -> None:
    payload = _published_payload() | {
        "first_seen_at": "2026-10-17T02:00:00Z",
        "published_at": "2026-10-17T02:00:00.100000Z",
        "checked_at": "2026-10-17T02:00:00.200000Z",
        "response_expires_at": "2026-10-18T02:00:00Z",
    }
    service, _ = _service(payload, monkeypatch, status_code=201)

    result = service.run_action(
        action_key=CONFIRM_ACTION,
        params={"confirmation_token": "encrypted:v1:must-not-display"},
        user=_admin(),
        confirmed=True,
    )

    view_model = result["view_model"]
    assert view_model["status"] == "日历已首次发布"
    assert all(
        value in view_model["message"]
        for value in (
            "2026-10-17T02:00:00Z",
            "2026-10-17T02:00:00.100000Z",
            "2026-10-18T02:00:00Z",
        )
    )


def test_malformed_or_unknown_calendar_mutation_result_fails_closed(
    monkeypatch: Any,
) -> None:
    cases = (
        (PREPARE_ACTION, _preview_payload() | {"preview_hash": "private-hash"}, 201),
        (
            CONFIRM_ACTION,
            _published_payload() | {"activation_id": "private-activation"},
            201,
        ),
        (
            CONFIRM_ACTION,
            _published_payload() | {"transition_label": ["日历已首次发布"]},
            201,
        ),
        (
            CONFIRM_ACTION,
            _published_payload() | {"transition_label": {"label": "日历已首次发布"}},
            201,
        ),
        (
            PREPARE_ACTION,
            _preview_payload() | {"coverage_start": "not-a-date"},
            201,
        ),
        (CONFIRM_ACTION, {"error": "private owner error", "code": "PRIVATE_CODE"}, 409),
    )
    for action_key, payload, status_code in cases:
        continuation = (
            {
                "action_key": CONFIRM_ACTION,
                "input": {"confirmation_token": "encrypted:v1:fixture-token"},
                "expires_at": "2999-10-18T02:00:00Z",
            }
            if action_key == PREPARE_ACTION and status_code < 400
            else None
        )
        service, _ = _service(
            payload,
            monkeypatch,
            status_code=status_code,
            continuation=continuation,
        )
        params = (
            {
                "exchange": "SSE",
                "coverage_start": "2026-10-15",
                "coverage_end": "2026-10-16",
            }
            if action_key == PREPARE_ACTION
            else {"confirmation_token": "encrypted:v1:must-not-display"}
        )

        result = service.run_action(
            action_key=action_key,
            params=params,
            user=_admin(),
            confirmed=True,
        )

        view_model = result["view_model"]
        assert view_model["kind"] == "message"
        expected_status = "发布结果待确认" if status_code >= 400 else "状态待确认"
        assert view_model["status"] == expected_status
        visible = repr(view_model)
        for private_value in (
            "private-hash",
            "private-activation",
            "private owner error",
            "PRIVATE_CODE",
            "encrypted:v1:must-not-display",
            "exchange_calendar_reference_only",
        ):
            assert private_value not in visible


def test_current_service_projection_shows_dates_and_reference_time_limits(monkeypatch: Any) -> None:
    payload = {
        "configuration_status": "metadata_selected",
        "current_status": "published",
        "blocked_reason": None,
        "current": {
            "publication_status": "published",
            "must_not_execute": True,
            "must_not_use_for_decision": True,
            "blocked_reason": "exchange_calendar_reference_only",
            "freshness": {
                "source_observed_at": None,
                "source_available_at": None,
                "source_time_status": "not_provided",
            },
            "reliability": "audited_calendar_reference",
            "exchange": "SSE",
            "coverage_start": "2026-10-17",
            "coverage_end": "2026-10-18",
            "as_of": "2026-10-17T02:00:00Z",
            "first_seen_at": "2026-10-16T23:59:00Z",
            "source_published_at": "2026-10-16T23:55:00Z",
            "response_expires_at": "2026-10-17T23:59:00Z",
            "calendar_days": [
                {
                    "exchange": "SSE",
                    "calendar_date": "2026-10-17",
                    "is_open": True,
                    "previous_open_date": "2026-10-16",
                },
                {
                    "exchange": "SSE",
                    "calendar_date": "2026-10-18",
                    "is_open": False,
                    "previous_open_date": "2026-10-16",
                },
            ],
        },
        "message": "当前发布日历仅供参考，不可用于交易或投资决策。",
    }
    service, executor = _service(payload, monkeypatch)

    result = service.run_action(
        action_key=CURRENT_ACTION,
        params={"exchange": "SSE"},
        user=_admin(),
    )
    view_model = result["view_model"]

    assert len(executor.calls) == 1
    assert view_model["kind"] == "datagrid"
    assert [column["label"] for column in view_model["columns"]] == [
        "日期",
        "状态",
        "前一开市日",
    ]
    assert [row["calendar_state"] for row in view_model["rows"]] == ["开市", "休市"]
    assert view_model["rows"][0]["previous_open_date"] == "2026-10-16"
    assert view_model["rows"][1]["previous_open_date"] == "2026-10-16"
    assert [row["calendar_date"] for row in view_model["rows"]] == [
        "2026-10-17",
        "2026-10-18",
    ]
    summary = view_model["business_summary"]
    assert "2026-10-16T23:59:00Z" in summary
    assert "2026-10-17T23:59:00Z" in summary
    assert "上游观测时间未知" in summary
    assert "仅供参考" in summary and "不可用于交易或投资决策" in summary
    visible = repr(view_model)
    for private_value in (
        "exchange_calendar_reference_only",
        "audited_calendar_reference",
        "source_observed_at",
        "source_available_at",
        "must_not_execute",
        "must_not_use_for_decision",
    ):
        assert private_value not in visible


def test_current_blocked_not_found_and_error_results_never_claim_a_calendar(
    monkeypatch: Any,
) -> None:
    cases = (
        (
            {
                "configuration_status": "blocked",
                "current_status": "blocked",
                "blocked_reason": "private-error-code",
                "current": None,
                "message": "private provider data",
            },
            200,
            "已阻断",
            "读取已阻断",
        ),
        (
            {
                "configuration_status": "metadata_selected",
                "current_status": "not_found",
                "blocked_reason": "private-error-code",
                "current": None,
                "message": "private provider data",
            },
            200,
            "无当前版本",
            "没有已发布的参考日历",
        ),
        (
            {"detail": "private provider data", "blocked_reason": "private-error-code"},
            503,
            "读取失败",
            "读取失败",
        ),
    )
    for payload, status_code, expected_status, expected_text in cases:
        service, _ = _service(payload, monkeypatch, status_code)
        result = service.run_action(
            action_key=CURRENT_ACTION,
            params={"exchange": "SSE"},
            user=_admin(),
        )
        model = result["view_model"]
        assert model["kind"] == "message"
        assert model["status"] == expected_status
        assert expected_text in model["message"]
        assert "private-error-code" not in repr(model)
        assert "private provider data" not in repr(model)
        if status_code == 503:
            assert result["outcome"] == "failed"


def test_incomplete_published_payload_fails_closed_without_technical_metadata(
    monkeypatch: Any,
) -> None:
    service, _ = _service(
        {
            "configuration_status": "metadata_selected",
            "current_status": "published",
            "current": {
                "publication_status": "published",
                "must_not_execute": False,
                "must_not_use_for_decision": True,
                "blocked_reason": "private-error-code",
            },
        },
        monkeypatch,
    )

    result = service.run_action(
        action_key=CURRENT_ACTION,
        params={"exchange": "SSE"},
        user=_admin(),
    )

    assert result["view_model"]["kind"] == "message"
    assert result["view_model"]["status"] == "状态待确认"
    assert "无法确认" in result["view_model"]["message"]
    assert "private-error-code" not in repr(result["view_model"])
