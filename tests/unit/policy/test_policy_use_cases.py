from types import SimpleNamespace

from apps.policy.application.use_cases import (
    AutoAssignAuditsUseCase,
    GetAuditQueueUseCase,
    GetWorkbenchItemsUseCase,
    GetWorkbenchSummaryUseCase,
    ReviewPolicyItemInput,
    ReviewPolicyItemUseCase,
    WorkbenchItemsInput,
    WorkbenchSummaryInput,
)
from apps.policy.domain.entities import AuditStatus, PolicyLevel


class _FakePolicyRepository:
    def get_current_policy_level(self):
        return PolicyLevel.P2


class _FakeWorkbenchRepository:
    def __init__(self):
        self.review_calls = []
        self.assign_calls = []

    def list_audit_queue_items(self, *, assigned_user_id, status, priority, limit):
        return [
            {
                "id": 11,
                "title": "Queued Policy",
                "priority": "urgent",
                "created_at": "2026-04-22T10:00:00+00:00",
            }
        ]

    def review_policy_item(
        self,
        *,
        policy_log_id,
        approved,
        reviewer_id,
        notes="",
        modifications=None,
    ):
        self.review_calls.append(
            {
                "policy_log_id": policy_log_id,
                "approved": approved,
                "reviewer_id": reviewer_id,
                "notes": notes,
                "modifications": modifications,
            }
        )
        if policy_log_id == 404:
            return None
        return {
            "id": policy_log_id,
            "audit_status": "manual_approved" if approved else "rejected",
        }

    def list_unassigned_audit_queue_ids(self):
        return [101, 102, 103]

    def list_staff_auditor_ids(self):
        return [21, 22]

    def get_pending_assignment_counts(self, auditor_ids):
        return {21: 1, 22: 0}

    def assign_audit_queue_item(self, *, queue_id, auditor_id, assigned_at):
        self.assign_calls.append((queue_id, auditor_id))
        return True

    def get_latest_effective_policy_title(self):
        return "Latest Policy"

    def get_global_heat_sentiment(self):
        return 71.5, -0.25

    def get_gate_config(self, asset_class):
        return SimpleNamespace(
            heat_l1_threshold=30.0,
            heat_l2_threshold=60.0,
            heat_l3_threshold=85.0,
            sentiment_l1_threshold=-0.3,
            sentiment_l2_threshold=-0.6,
            sentiment_l3_threshold=-0.8,
            max_position_cap_l2=0.7,
            max_position_cap_l3=0.3,
        )

    def get_ingestion_config(self):
        return SimpleNamespace(p23_sla_hours=2, normal_sla_hours=24)

    def get_pending_review_count(self):
        return 5

    def get_sla_exceeded_count(self, *, p23_sla_hours, normal_sla_hours):
        return 2

    def get_effective_today_count(self):
        return 3

    def get_last_fetch_at(self):
        return "2026-04-22T08:30:00+00:00"

    def list_workbench_items(self, **kwargs):
        return {
            "total": 1,
            "items": [
                {
                    "id": 88,
                    "title": "Workbench Item",
                    "event_type": kwargs["event_type"],
                    "audit_status": "pending_review",
                }
            ],
        }


def test_get_audit_queue_use_case_reads_from_workbench_repository():
    use_case = GetAuditQueueUseCase(
        policy_repository=_FakePolicyRepository(),
        workbench_repo=_FakeWorkbenchRepository(),
    )

    reviewer = SimpleNamespace(id=7)
    items = use_case.execute(user=reviewer, priority="urgent", limit=10)

    assert len(items) == 1
    assert items[0]["title"] == "Queued Policy"


def test_review_policy_item_use_case_uses_workbench_repository():
    workbench_repo = _FakeWorkbenchRepository()
    use_case = ReviewPolicyItemUseCase(
        policy_repository=_FakePolicyRepository(),
        workbench_repo=workbench_repo,
    )

    reviewer = SimpleNamespace(id=9, username="reviewer")
    output = use_case.execute(
        ReviewPolicyItemInput(
            policy_log_id=12,
            approved=True,
            reviewer=reviewer,
            notes="looks good",
            modifications={"summary": "updated"},
        )
    )

    assert output.success is True
    assert output.audit_status == AuditStatus.MANUAL_APPROVED
    assert workbench_repo.review_calls == [
        {
            "policy_log_id": 12,
            "approved": True,
            "reviewer_id": 9,
            "notes": "looks good",
            "modifications": {"summary": "updated"},
        }
    ]


def test_auto_assign_audits_use_case_uses_repository_round_robin():
    workbench_repo = _FakeWorkbenchRepository()
    use_case = AutoAssignAuditsUseCase(workbench_repo=workbench_repo)

    result = use_case.execute(max_per_user=2)

    assert result == {
        "assigned": 3,
        "remaining": 0,
        "auditors": 2,
    }
    assert workbench_repo.assign_calls == [(101, 21), (102, 22), (103, 22)]


def test_get_workbench_summary_use_case_uses_repository_snapshots():
    use_case = GetWorkbenchSummaryUseCase(
        workbench_repo=_FakeWorkbenchRepository(),
        policy_repo=_FakePolicyRepository(),
    )

    output = use_case.execute(WorkbenchSummaryInput())

    assert output.success is True
    assert output.summary.policy_level == PolicyLevel.P2
    assert output.summary.policy_level_event == "Latest Policy"
    assert output.summary.pending_review_count == 5


def test_get_workbench_items_use_case_uses_repository_results():
    use_case = GetWorkbenchItemsUseCase(workbench_repo=_FakeWorkbenchRepository())

    output = use_case.execute(WorkbenchItemsInput(tab="all", event_type="policy"))

    assert output.success is True
    assert output.total == 1
    assert output.items == [
        {
            "id": 88,
            "title": "Workbench Item",
            "event_type": "policy",
            "audit_status": "pending_review",
        }
    ]
