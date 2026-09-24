from dataclasses import replace
from datetime import UTC, datetime

import pytest

from apps.dashboard.application.alpha_refresh_notice import build_refresh_notice
from apps.task_monitor.domain.entities import TaskExecutionRecord, TaskPriority, TaskStatus


def record(result, **kwargs):
    return TaskExecutionRecord(
        task_id="private-id",
        task_name="apps.alpha.application.tasks.qlib_predict_scores",
        status=TaskStatus.SUCCESS,
        args=("csi300", "2026-09-18"),
        kwargs=kwargs,
        started_at=datetime(2026, 9, 19, tzinfo=UTC),
        finished_at=datetime(2026, 9, 19, tzinfo=UTC),
        result=result,
        exception=None,
        traceback=None,
        runtime_seconds=1,
        retries=0,
        priority=TaskPriority.NORMAL,
        queue=None,
        worker=None,
    )


@pytest.mark.parametrize("encoding", [repr, __import__("json").dumps])
def test_business_block_even_with_celery_success_and_no_secret_leak(encoding):
    notice = build_refresh_notice(
        [
            record(
                encoding(
                    {
                        "outcome": "blocked",
                        "reason": "model_market_source_conflict",
                        "error": "token=supersecret",
                        "stored": 0,
                    }
                )
            )
        ],
        portfolio_id=None,
        universe_id="csi300",
    )
    assert notice["code"] == "model_market_source_conflict"
    assert "口径" in notice["message"]
    assert "supersecret" not in str(notice)
    assert "private-id" not in str(notice)


def test_scope_isolation_and_latest_success_clears_old_failure():
    failure = record("{'outcome': 'failed'}", scope_payload={"portfolio_id": 8})
    assert build_refresh_notice([failure], portfolio_id=9, universe_id="portfolio-9") == {}
    success = record("{'outcome': 'success', 'stored': 20}", scope_payload={"portfolio_id": 8})
    assert build_refresh_notice([success, failure], portfolio_id=8, universe_id="portfolio-8") == {}


def test_queued_parent_does_not_hide_last_failure():
    failure = replace(record(None), status=TaskStatus.TIMEOUT, exception="password=secret")
    queued = replace(
        record("{'outcome': 'success', 'stored': 0, 'task_id': 'new'}"),
        task_name="alpha.qlib_daily_inference",
    )
    notice = build_refresh_notice([queued, failure], portfolio_id=None, universe_id="csi300")
    assert notice["code"] == "inference_timeout"
    assert "secret" not in str(notice)


def test_running_attempt_is_visible_alongside_last_completed_failure():
    failed = replace(
        record(
            "{'outcome': 'partial', 'phase': 'publication', 'requested': 57, 'succeeded': 56, 'stored': 11114, 'count_unit': 'sync_operation', 'error_code': 'PUBLICATION_FAILED'}"
        ),
        status=TaskStatus.FAILURE,
        finished_at=datetime(2026, 9, 24, 9, 48, tzinfo=UTC),
    )
    running = replace(
        record(
            "{'outcome': 'partial', 'phase': 'publication', 'count_unit': 'sync_operation', "
            "'requested': 57, 'succeeded': 56, 'phase_results': "
            "[{'phase': 'publication', 'requested': 1, 'succeeded': 0, 'failed': 1}]}"
        ),
        task_id="current-task",
        status=TaskStatus.STARTED,
        started_at=datetime(2026, 9, 24, 10, 0, tzinfo=UTC),
        finished_at=None,
    )

    notice = build_refresh_notice(
        [running, failed],
        portfolio_id=None,
        universe_id="csi300",
    )

    assert notice["code"] == "inference_in_progress"
    assert notice["current_attempt"]["phase"] == "publication"
    assert notice["current_attempt"]["requested"] == 57
    assert notice["current_attempt"]["stored"] is None
    assert notice["last_completed"]["error_code"] == "PUBLICATION_FAILED"
    assert notice["current_attempt"]["phase_results"][0]["failed"] == 1
    assert "current-task" not in str(notice)
    assert __import__("json").dumps(notice)


def test_malformed_failure_is_visible_without_raw_error():
    failure = replace(record("not JSON token=secret"), status=TaskStatus.FAILURE)
    notice = build_refresh_notice([failure], portfolio_id=None, universe_id="csi300")
    assert notice["code"] == "inference_failed"
    assert "secret" not in str(notice)


@pytest.mark.parametrize(
    "code, message",
    [
        ("model_market_local_feature_invalid", "特征文件异常"),
        ("model_market_scope_incomplete", "完整组合股票池"),
    ],
)
def test_model_data_repair_errors_are_visible(code, message):
    notice = build_refresh_notice(
        [record(repr({"outcome": "blocked", "reason": code}))],
        portfolio_id=None,
        universe_id="csi300",
    )
    assert notice["code"] == code
    assert message in notice["message"]


def test_queue_failure_visible_without_a_persisted_task(monkeypatch):
    from apps.dashboard.application import alpha_refresh_notice

    monkeypatch.setattr(
        alpha_refresh_notice,
        "list_task_executions",
        lambda *args, **kwargs: pytest.fail("queue failure must not need a task record"),
    )
    notice = alpha_refresh_notice.get_refresh_notice(
        portfolio_id=None, universe_id="csi300", request_failed=True
    )
    assert notice["code"] == "inference_queue_failed"
    assert "后台" in notice["message"]


@pytest.mark.parametrize("items", [[], [{"code": "000001.SZ", "alpha_score": 1}]])
def test_tui_notice_survives_empty_and_cached_results(items):
    from apps.terminal.application.tui_workbench import TuiWorkbenchService
    from apps.terminal.infrastructure.tui_metadata_runtime_injection_dashboard_alpha import (
        RUNTIME_DASHBOARD_ALPHA_ACTIONS,
    )

    service = TuiWorkbenchService.__new__(TuiWorkbenchService)
    service._resolve_asset_names = lambda codes: {}
    action = next(
        item for item in RUNTIME_DASHBOARD_ALPHA_ACTIONS if item["key"] == "dashboard.alpha-ranking"
    )
    result = service._to_view_model(
        action=action,
        status_code=200,
        payload={
            "items": items,
            "count": len(items),
            "meta": {
                "effective_asof_date": "2026-09-04",
                "requested_trade_date": "2026-09-18",
                "refresh_notice": {
                    "message": "行情口径不一致",
                    "attempted_at": "2026-09-19T01:00:00Z",
                },
            },
        },
    )
    assert "2026-09-04" in result["business_summary"]
    assert result["blocking_reason"] == "行情口径不一致"
    assert len(result["rows"]) == len(items)


def test_classic_notice_renders_even_without_candidates():
    from django.template.loader import render_to_string

    html = render_to_string(
        "dashboard/partials/alpha_stocks_table.html",
        {
            "alpha_scope": "general",
            "alpha_meta": {
                "effective_asof_date": "2026-09-04",
                "requested_trade_date": "2026-09-18",
                "refresh_notice": {"title": "Alpha 自动更新异常", "message": "行情口径不一致"},
            },
        },
    )
    assert 'role="alert"' in html
    assert "行情口径不一致" in html
    assert "2026-09-04" in html


@pytest.mark.parametrize("portfolio_id", [None, 8])
def test_prediction_success_does_not_hide_independent_market_block(portfolio_id):
    success = record(
        "{'outcome': 'success', 'stored': 30}",
        **({"scope_payload": {"portfolio_id": portfolio_id}} if portfolio_id else {}),
    )
    blocked = replace(
        record("{'outcome': 'blocked', 'blocked_reason': 'system_audit_runtime_disabled'}"),
        task_name="data_center.refresh_full_market_publications",
    )
    notice = build_refresh_notice(
        [success, blocked], portfolio_id=portfolio_id, universe_id="csi300"
    )
    assert notice["code"] == "system_audit_unavailable"
    assert "服务身份" in notice["message"]
    repaired = replace(blocked, result="{'outcome': 'success', 'published_members': 16695}")
    assert (
        build_refresh_notice(
            [success, repaired, blocked], portfolio_id=portfolio_id, universe_id="csi300"
        )
        == {}
    )


def test_market_publication_validation_failure_has_specific_safe_message() -> None:
    failed = replace(
        record(
            "{'outcome': 'partial', "
            "'blocked_reason': 'MARKET_PUBLICATION_VALIDATION_FAILED', "
            "'error': 'token=secret'}"
        ),
        task_name="data_center.refresh_full_market_publications",
    )

    notice = build_refresh_notice([failed], portfolio_id=None, universe_id="csi300")

    assert notice["code"] == "market_publication_validation_failed"
    assert "发布证据未通过校验" in notice["message"]
    assert "secret" not in str(notice)


def test_verified_publications_newer_than_failed_task_clear_notice() -> None:
    failed = replace(
        record("{'outcome': 'failed'}"),
        task_name="data_center.refresh_full_market_publications",
        finished_at=datetime(2026, 9, 24, 9, tzinfo=UTC),
    )

    notice = build_refresh_notice(
        [failed],
        portfolio_id=None,
        universe_id="csi300",
        market_recovered_at=datetime(2026, 9, 24, 10, tzinfo=UTC),
    )

    assert notice == {}
