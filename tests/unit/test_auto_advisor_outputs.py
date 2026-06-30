from datetime import date

import pytest

from apps.dashboard.application.auto_advisor_outputs import (
    persist_auto_advisor_weekly_report_outputs,
)
from apps.dashboard.application.query_services import (
    build_auto_advisor_notifications_payload,
    build_auto_advisor_weekly_report_history_payload,
)
from apps.dashboard.infrastructure.models import (
    AutoAdvisorNotificationModel,
    AutoAdvisorWeeklyReportModel,
)


@pytest.mark.django_db
def test_persist_auto_advisor_weekly_report_outputs_creates_report_notification_and_audit(
    django_user_model,
):
    user = django_user_model.objects.create_user(username="advisor-user")
    payload = _weekly_report_payload()

    result = persist_auto_advisor_weekly_report_outputs(
        user=user,
        report_payload=payload,
    )

    report = AutoAdvisorWeeklyReportModel._default_manager.get(id=result["report"]["id"])
    notification = AutoAdvisorNotificationModel._default_manager.get(
        id=result["notification"]["id"]
    )
    assert report.user_id == user.id
    assert report.account_id == 101
    assert report.report_date == date(2026, 6, 26)
    assert report.investment_diary["status"] == "DERIVED_FROM_ADVISOR_SHEET"
    assert report.audit_log_id
    assert notification.report_id == report.id
    assert notification.delivery_status == "delivered"
    assert result["audit"]["success"] is True

    history = build_auto_advisor_weekly_report_history_payload(user=user, account_id="101")
    notifications = build_auto_advisor_notifications_payload(user=user, account_id="101")
    assert history["count"] == 1
    assert history["reports"][0]["id"] == report.id
    assert notifications["count"] == 1
    assert notifications["notifications"][0]["id"] == notification.id


def _weekly_report_payload() -> dict:
    return {
        "status": "ok",
        "account": {
            "account_id": 101,
            "account_name": "Growth",
        },
        "week": {
            "start": "2026-06-22",
            "end": "2026-06-28",
            "as_of": "2026-06-26",
        },
        "portfolio_change": {
            "status": "HISTORICAL",
            "absolute_change": 1200,
        },
        "system_vs_actual": {
            "decision_count": 2,
        },
        "investment_diary": {
            "status": "DERIVED_FROM_ADVISOR_SHEET",
            "entries": [
                {
                    "entry_date": "2026-06-26",
                    "entry_type": "WEEKLY_REVIEW",
                }
            ],
        },
        "evidence": {
            "today_conclusion": "REVIEW",
        },
    }
