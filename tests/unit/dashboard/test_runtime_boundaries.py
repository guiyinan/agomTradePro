"""Security and dynamic-type checks for Dashboard runtime boundaries."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from rest_framework.test import APIRequestFactory, force_authenticate

from apps.dashboard.application import tasks
from apps.dashboard.interface import workflow_views
from apps.dashboard.templatetags.dashboard_tags import get_attr


def test_weekly_task_redacts_report_generation_failure(monkeypatch, caplog) -> None:
    """Celery result and logs do not retain provider/database exception text."""

    monkeypatch.setattr(
        tasks,
        "list_active_account_targets",
        lambda: [{"account_id": 101, "user_id": 7}],
    )
    monkeypatch.setattr(
        tasks,
        "get_application_user_by_id",
        lambda _: SimpleNamespace(id=7),
    )

    def _fail(**_: object) -> dict[str, object]:
        raise RuntimeError("postgresql://user:secret@internal/report")

    monkeypatch.setattr(tasks, "build_auto_advisor_weekly_report_payload", _fail)

    with caplog.at_level(logging.ERROR, logger="apps.dashboard.application.tasks"):
        payload = tasks.generate_auto_advisor_weekly_reports_task.run(as_of="2026-07-25")

    assert payload["errors"][0]["error"] == "auto_advisor_weekly_report_failed"
    assert "secret" not in str(payload)
    assert "secret" not in caplog.text


def test_workflow_view_redacts_candidate_failure(monkeypatch, caplog) -> None:
    """Authenticated workflow errors remain stable and credential-free."""

    monkeypatch.setattr(
        workflow_views,
        "get_dashboard_detail_query",
        lambda: SimpleNamespace(
            generate_alpha_candidates=lambda: (_ for _ in ()).throw(
                RuntimeError("redis://user:secret@internal/0")
            )
        ),
    )
    request = APIRequestFactory().post("/api/dashboard/workflow/refresh-candidates/", {})
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True, pk=7))

    with caplog.at_level(logging.ERROR, logger="apps.dashboard.interface.workflow_views"):
        response = workflow_views.workflow_refresh_candidates(request)

    assert response.status_code == 500
    assert json.loads(response.content)["error"] == "workflow_candidate_refresh_failed"
    assert "secret" not in caplog.text


def test_dashboard_get_attr_rejects_dunder_access() -> None:
    """Template callers cannot traverse Python internals through a dynamic attribute."""

    assert get_attr(SimpleNamespace(name="safe"), "name") == "safe"
    assert get_attr(SimpleNamespace(name="safe"), "__class__") is None
