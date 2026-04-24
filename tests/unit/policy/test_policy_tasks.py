from apps.policy.application.tasks import (
    auto_assign_pending_audits,
    cleanup_old_policy_logs,
    generate_daily_policy_summary,
    monitor_sla_exceeded_task,
)


class _FakePolicyRepository:
    def __init__(self):
        self.deleted_before = None

    def delete_events_before(self, cutoff_date):
        self.deleted_before = cutoff_date
        return 7


class _FakeWorkbenchRepository:
    def __init__(self):
        self.assigned = []

    def list_unassigned_audit_queue_ids(self):
        return [101, 102, 103]

    def list_staff_auditor_ids(self):
        return [11, 12]

    def get_pending_assignment_counts(self, auditor_ids):
        return {11: 1, 12: 0}

    def assign_audit_queue_item(self, *, queue_id, auditor_id, assigned_at):
        self.assigned.append((queue_id, auditor_id))
        return True

    def delete_reviewed_queue_before(self, cutoff_datetime):
        return 4

    def get_daily_policy_summary(self, target_date):
        return {
            "date": target_date.isoformat(),
            "total_new": 5,
            "by_level": {"P1 - 预警": 2},
            "by_category": {"宏观政策": 3},
            "by_audit_status": {"待审核": 1},
            "pending_review": 1,
            "ai_classified": 2,
        }

    def get_ingestion_config(self):
        class _Config:
            p23_sla_hours = 2
            normal_sla_hours = 24

        return _Config()

    def get_sla_exceeded_breakdown(self, *, p23_sla_hours, normal_sla_hours):
        return {
            "p23_exceeded": 2,
            "normal_exceeded": 1,
            "total_exceeded": 3,
        }


class _FakeNotificationService:
    def __init__(self):
        self.sla_alerts = []

    def send_sla_alert(self, p23_count, normal_count):
        self.sla_alerts.append((p23_count, normal_count))


def test_cleanup_old_policy_logs_uses_policy_repository(monkeypatch):
    fake_repo = _FakePolicyRepository()
    monkeypatch.setattr(
        "apps.policy.application.tasks.get_current_policy_repository",
        lambda: fake_repo,
    )

    result = cleanup_old_policy_logs.run(days_to_keep=30)

    assert result["status"] == "success"
    assert result["deleted_count"] == 7
    assert fake_repo.deleted_before is not None


def test_auto_assign_pending_audits_uses_workbench_repository(monkeypatch):
    fake_repo = _FakeWorkbenchRepository()
    monkeypatch.setattr(
        "apps.policy.application.tasks.get_workbench_repository",
        lambda: fake_repo,
    )

    result = auto_assign_pending_audits.run(max_per_user=2)

    assert result == {
        "assigned": 3,
        "remaining": 0,
        "auditors": 2,
    }
    assert fake_repo.assigned == [(101, 11), (102, 12), (103, 12)]


def test_generate_daily_policy_summary_uses_workbench_repository(monkeypatch):
    fake_repo = _FakeWorkbenchRepository()
    monkeypatch.setattr(
        "apps.policy.application.tasks.get_workbench_repository",
        lambda: fake_repo,
    )

    result = generate_daily_policy_summary.run()

    assert result["total_new"] == 5
    assert result["pending_review"] == 1


def test_monitor_sla_exceeded_task_uses_workbench_repository(monkeypatch):
    fake_repo = _FakeWorkbenchRepository()
    fake_notification_service = _FakeNotificationService()
    monkeypatch.setattr(
        "apps.policy.application.tasks.get_workbench_repository",
        lambda: fake_repo,
    )
    monkeypatch.setattr(
        "apps.policy.application.tasks._get_notification_service",
        lambda: fake_notification_service,
    )

    result = monitor_sla_exceeded_task.run()

    assert result == {
        "status": "success",
        "p23_exceeded": 2,
        "normal_exceeded": 1,
        "total_exceeded": 3,
    }
    assert fake_notification_service.sla_alerts == [(2, 1)]
