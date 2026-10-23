"""T3A account documentation-view and notification task contracts."""

import json
from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.account.application import tasks
from apps.account.application.documentation_use_cases import (
    DocumentationDTO,
    DocumentationImportResult,
    DocumentationStats,
)
from apps.account.interface import documentation_views


def _doc() -> DocumentationDTO:
    now = datetime.now(UTC)
    return DocumentationDTO(
        id=1,
        title="Guide",
        slug="guide",
        category="user_guide",
        category_display="User Guide",
        content="line1\nline2",
        summary="summary",
        order=1,
        is_published=True,
        created_at=now,
        updated_at=now,
    )


class _DocumentationService:
    def __init__(self) -> None:
        self.docs = [_doc()]
        self.saved: list[tuple[object, int | None]] = []

    def list_admin_docs(self, **_filters: str) -> list[DocumentationDTO]:
        return self.docs

    def get_stats(self) -> DocumentationStats:
        return DocumentationStats(total=1, published=1, draft=0, by_category={})

    def get_category_choices(self) -> list[tuple[str, str]]:
        return [("user_guide", "User Guide")]

    def get_doc(self, _doc_id: int) -> DocumentationDTO:
        return self.docs[0]

    def save_doc(self, data: object, doc_id: int | None = None) -> DocumentationDTO:
        self.saved.append((data, doc_id))
        return self.docs[0]

    def delete_doc(self, _doc_id: int) -> str:
        return "Guide"

    def list_all_docs(self) -> list[DocumentationDTO]:
        return self.docs

    def import_json_text(self, _text: str) -> DocumentationImportResult:
        return DocumentationImportResult(created=2, updated=1)

    def import_csv_text(self, _text: str) -> DocumentationImportResult:
        return DocumentationImportResult(created=1, updated=2)


def _request(
    *,
    method: str = "GET",
    get: dict[str, object] | None = None,
    post: dict[str, object] | None = None,
    files: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        method=method,
        GET=get or {},
        POST=post or {},
        FILES=files or {},
    )


def test_documentation_manage_edit_delete_and_markdown_views(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _DocumentationService()
    rendered: list[tuple[str, dict[str, Any]]] = []
    redirects: list[str] = []
    notices: list[tuple[str, str]] = []
    monkeypatch.setattr(documentation_views, "_service", lambda: service)
    monkeypatch.setattr(
        documentation_views,
        "render",
        lambda _request, template, context: rendered.append((template, context)) or context,
    )
    monkeypatch.setattr(
        documentation_views,
        "redirect",
        lambda target: redirects.append(target) or target,
    )
    monkeypatch.setattr(
        documentation_views.messages,
        "error",
        lambda _request, message: notices.append(("error", message)),
    )
    monkeypatch.setattr(
        documentation_views.messages,
        "success",
        lambda _request, message: notices.append(("success", message)),
    )

    manage = documentation_views.docs_manage.__wrapped__(
        _request(get={"category": "api", "status": "draft", "q": "guide", "page": "1"})
    )
    invalid = documentation_views.doc_edit.__wrapped__(
        _request(method="POST", post={"title": "", "slug": "", "content": ""})
    )
    created = documentation_views.doc_edit.__wrapped__(
        _request(
            method="POST",
            post={
                "title": "Guide",
                "slug": "guide",
                "content": "body",
                "order": "2",
                "is_published": "on",
            },
        )
    )
    deleted = documentation_views.doc_delete.__wrapped__(
        _request(method="POST"),
        doc_id=1,
    )
    markdown = documentation_views.doc_export_markdown.__wrapped__(_request(), doc_id=1)

    assert manage["page_obj"].paginator.count == 1
    assert invalid["doc"] is None
    assert created == "/admin/docs/manage/"
    assert deleted == "/admin/docs/manage/"
    assert ("error", "标题、Slug 和内容不能为空") in notices
    assert any(level == "success" for level, _message in notices)
    assert markdown["Content-Type"].startswith("text/markdown")
    assert b"# Guide" in markdown.content


def test_documentation_export_json_and_csv_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _DocumentationService()
    monkeypatch.setattr(documentation_views, "_service", lambda: service)

    json_response = documentation_views.doc_export_all.__wrapped__(_request(get={"format": "json"}))
    csv_response = documentation_views.doc_export_all.__wrapped__(_request(get={"format": "csv"}))

    assert json_response["Content-Type"].startswith("application/json")
    assert '"slug": "guide"' in json_response.content.decode()
    assert csv_response["Content-Type"].startswith("text/csv")
    assert "Guide" in csv_response.content.decode("utf-8-sig")
    assert "line1\\nline2" in csv_response.content.decode("utf-8-sig")


@pytest.mark.parametrize(
    ("import_format", "expected"),
    [("json", {"created": 2, "updated": 1}), ("csv", {"created": 1, "updated": 2})],
)
def test_documentation_import_success_by_format(
    monkeypatch: pytest.MonkeyPatch,
    import_format: str,
    expected: dict[str, int],
) -> None:
    service = _DocumentationService()
    monkeypatch.setattr(documentation_views, "_service", lambda: service)
    monkeypatch.setattr(documentation_views.transaction, "atomic", nullcontext)
    monkeypatch.setattr(documentation_views.messages, "success", lambda *_args: None)
    wrapped = documentation_views.doc_import.__wrapped__.__wrapped__
    response = wrapped(
        _request(
            method="POST",
            post={"format": import_format},
            files={"file": SimpleUploadedFile("docs.json", b"[]")},
        )
    )

    assert response.status_code == 200
    assert json.loads(response.content)["data"] == expected


def test_documentation_import_rejects_missing_unknown_and_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _DocumentationService()
    monkeypatch.setattr(documentation_views, "_service", lambda: service)
    monkeypatch.setattr(documentation_views.transaction, "atomic", nullcontext)
    wrapped = documentation_views.doc_import.__wrapped__.__wrapped__

    missing = wrapped(_request(method="POST"))
    unknown = wrapped(
        _request(
            method="POST",
            post={"format": "xml"},
            files={"file": SimpleUploadedFile("docs.xml", b"<doc />")},
        )
    )
    monkeypatch.setattr(
        service,
        "import_json_text",
        lambda _text: (_ for _ in ()).throw(ValueError("bad json")),
    )
    broken = wrapped(
        _request(
            method="POST",
            post={"format": "json"},
            files={"file": SimpleUploadedFile("docs.json", b"bad")},
        )
    )

    assert missing.status_code == 400
    assert unknown.status_code == 400
    assert broken.status_code == 400
    assert json.loads(broken.content)["error"] == "导入文件格式或内容无效"


def _analysis() -> SimpleNamespace:
    return SimpleNamespace(
        current_volatility_30d=0.3,
        current_volatility_60d=0.25,
        current_volatility_90d=0.2,
        target_volatility=0.15,
        adjustment_result=SimpleNamespace(
            volatility_ratio=2.0,
            reduction_reason="risk limit",
        ),
    )


def test_backup_email_task_handles_not_due_and_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        is_backup_due=lambda: False,
        backup_interval_days=7,
        backup_link_ttl_days=2,
        backup_password_hint="hint",
        backup_mail_from_email="from@example.test",
        backup_email="owner@example.test",
        backup_last_sent_at=None,
        save=lambda **_kwargs: None,
    )
    monkeypatch.setattr(tasks.system_settings_repo, "get_settings", lambda: config)
    skipped = tasks.send_database_backup_email_task.run()
    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "not_due"
    assert skipped["outcome"] == "noop"

    config.is_backup_due = lambda: True
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(tasks, "generate_download_token", lambda _config: "token")
    monkeypatch.setattr(
        tasks,
        "build_backup_download_url",
        lambda _token: "https://example.test/backup",
    )
    monkeypatch.setattr(
        tasks,
        "describe_backup_package",
        lambda: {"extension": ".zip", "format": "encrypted"},
    )
    monkeypatch.setattr(tasks, "get_backup_email_connection", lambda _config: object())
    monkeypatch.setattr(
        tasks,
        "EmailMessage",
        lambda **kwargs: SimpleNamespace(send=lambda **_send_kwargs: sent.append(kwargs)),
    )

    result = tasks.send_database_backup_email_task.run()

    assert result["status"] == "sent"
    assert result["email"] == "owner@example.test"
    assert result["outcome"] == "success"
    assert "https://example.test/backup" in sent[0]["body"]
    assert config.backup_last_sent_at is not None


def test_backup_failure_retries_but_risk_stage_failure_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backup setup retains retries; entered automated-exit stages do not retry."""

    monkeypatch.setattr(
        tasks.system_settings_repo,
        "get_settings",
        lambda: (_ for _ in ()).throw(RuntimeError("settings unavailable")),
    )
    monkeypatch.setattr(
        tasks.send_database_backup_email_task,
        "retry",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("backup retry")),
    )
    with pytest.raises(RuntimeError, match="backup retry"):
        tasks.send_database_backup_email_task.run()

    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(
            check_and_execute_stop_loss=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("risk source unavailable")
            )
        ),
    )
    monkeypatch.setattr(tasks, "record_exception", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tasks.check_stop_loss_task,
        "retry",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("risk stage must not retry")),
    )
    result = tasks.check_stop_loss_task.run(user_id=7)
    assert result["outcome"] == "failed"
    assert result["stage_unknown_count"] == 1
    assert result["stored"] is None


def test_volatility_outer_failure_keeps_retry_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The unrelated volatility task keeps its existing retry behavior."""

    monkeypatch.setattr(
        tasks.portfolio_repo,
        "list_active_portfolios",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("portfolio unavailable")),
    )
    monkeypatch.setattr(
        tasks.check_volatility_and_adjust_task,
        "retry",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("volatility retry")),
    )
    with pytest.raises(RuntimeError, match="volatility retry"):
        tasks.check_volatility_and_adjust_task.run(user_id=7)


def test_combined_unknown_stage_stops_without_retry_and_notice_lookup_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Combined checks stop at an unknown stage and notification errors stay isolated."""

    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(
            check_and_execute_stop_loss=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("stage outcome unknown")
            )
        ),
    )
    take_case = SimpleNamespace(
        check_and_execute_take_profit=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("later stage must not run")
        )
    )
    monkeypatch.setattr(tasks, "AutoTakeProfitUseCase", lambda: take_case)
    monkeypatch.setattr(tasks, "record_exception", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tasks.check_stop_loss_and_take_profit_task,
        "retry",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("unknown stage must not retry")),
    )
    result = tasks.check_stop_loss_and_take_profit_task.run(user_id=7)
    assert result["stage_unknown_count"] == 1
    assert result["stored"] is None

    notification = SimpleNamespace(
        asset_code="000001.SZ",
        position_id=1,
        triggered=True,
        check_status="evaluated",
        execution_status="blocked",
        execution_receipt_id=None,
        current_price=8.0,
        price_source="unified_quote",
        price_observed_at=datetime(2026, 4, 1, tzinfo=UTC),
        price_freshness="realtime",
        must_not_use_for_decision=True,
        must_not_execute=True,
        unrealized_pnl_pct=-0.2,
        partial_level=None,
        check_result=SimpleNamespace(trigger_reason="threshold", stop_price=9.0),
    )
    monkeypatch.setattr(
        tasks.position_repo,
        "get_position_notification_context",
        lambda _position_id: (_ for _ in ()).throw(RuntimeError("lookup failed")),
    )
    tasks._send_stop_loss_notifications([notification])
    tasks._send_take_profit_notifications([notification])


def test_volatility_adjustment_missing_portfolio_is_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tasks.portfolio_repo,
        "get_portfolio_notification_context",
        lambda _portfolio_id: None,
    )

    tasks._send_volatility_adjustment_notification(
        portfolio_id=404,
        user_id=7,
        analysis=_analysis(),
        result={"position_multiplier": 0.5, "reduced_positions": []},
    )


def test_volatility_notifications_send_to_owner_and_isolate_missing_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict[str, object]] = []
    contexts: dict[int, dict[str, str] | None] = {
        1: {"name": "Core", "user_email": "owner@example.test"},
        2: {"name": "No Email", "user_email": ""},
        3: None,
    }
    monkeypatch.setattr(
        tasks.portfolio_repo,
        "get_portfolio_notification_context",
        lambda portfolio_id: contexts[portfolio_id],
    )
    monkeypatch.setattr(tasks, "send_mail", lambda **kwargs: sent.append(kwargs))
    analysis = _analysis()

    tasks._send_volatility_adjustment_notification(
        portfolio_id=1,
        user_id=7,
        analysis=analysis,
        result={"position_multiplier": 0.5, "reduced_positions": [1, 2]},
    )
    tasks._send_volatility_warning_notification(
        portfolio_id=1,
        user_id=7,
        analysis=analysis,
    )
    tasks._send_volatility_adjustment_notification(
        portfolio_id=2,
        user_id=7,
        analysis=analysis,
        result={"position_multiplier": 0.5, "reduced_positions": []},
    )
    tasks._send_volatility_warning_notification(
        portfolio_id=3,
        user_id=7,
        analysis=analysis,
    )

    assert len(sent) == 2
    assert sent[0]["recipient_list"] == ["owner@example.test"]
    assert "已降仓" in sent[0]["subject"]
    assert "波动率偏高" in sent[1]["subject"]
