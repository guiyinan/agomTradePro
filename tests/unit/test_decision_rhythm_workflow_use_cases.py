from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

from apps.alpha_trigger.domain.entities import CandidateStatus
from apps.decision_rhythm.application.management_workflows import (
    GetTrendDataUseCase,
    ResetQuotaByAccountRequest,
    ResetQuotaByAccountUseCase,
    TrendDataRequest,
)
from apps.decision_rhythm.application.page_workflows import (
    DecisionQuotaConfigPageRequest,
    DecisionQuotaPageRequest,
    GetDecisionQuotaConfigPageUseCase,
    GetDecisionQuotaPageUseCase,
)
from apps.decision_rhythm.application.query_workflows import (
    GetCooldownRemainingHoursRequest,
    GetCooldownRemainingHoursUseCase,
    ListDecisionRequestsRequest,
    ListDecisionRequestsUseCase,
)
from apps.decision_rhythm.application.submit_workflows import (
    SubmitBatchWorkflowRequest,
    SubmitBatchWorkflowUseCase,
    SubmitDecisionWorkflowRequest,
    SubmitDecisionWorkflowUseCase,
)
from apps.decision_rhythm.application.use_cases import (
    CancelDecisionRequest,
    CancelDecisionRequestUseCase,
    PrecheckDecisionUseCase,
    PrecheckRequest,
    SubmitBatchRequestRequest,
    SubmitDecisionRequestRequest,
    UpdateQuotaConfigRequest,
    UpdateQuotaConfigUseCase,
)
from apps.decision_rhythm.domain.entities import (
    CooldownPeriod,
    DecisionPriority,
    DecisionQuota,
    DecisionRequest,
    ExecutionStatus,
    QuotaPeriod,
)


@dataclass
class FakeCandidate:
    candidate_id: str
    asset_code: str = "000001.SH"
    asset_class: str = "equity"
    status: CandidateStatus = CandidateStatus.ACTIONABLE
    is_executed: bool = False
    is_expired: bool = False


class FakeCandidateRepo:
    def __init__(self, candidate=None):
        self.candidate = candidate
        self.execution_updates: list[tuple[str, str, str]] = []
        self.status_updates: list[tuple[str, CandidateStatus]] = []

    def get_by_id(self, candidate_id: str):
        if self.candidate and self.candidate.candidate_id == candidate_id:
            return self.candidate
        return None

    def update_execution_tracking(
        self,
        candidate_id: str,
        decision_request_id: str,
        execution_status: str,
    ):
        self.execution_updates.append((candidate_id, decision_request_id, execution_status))

    def update_status(self, candidate_id: str, status: CandidateStatus):
        self.status_updates.append((candidate_id, status))


class FakeWorkflowRequestRepo:
    def __init__(
        self,
        *,
        open_by_candidate=None,
        open_by_asset=None,
    ):
        self.open_by_candidate = open_by_candidate
        self.open_by_asset = open_by_asset
        self.saved_requests = []
        self.saved_responses = []

    def get_open_by_candidate_id(self, candidate_id: str):
        if self.open_by_candidate and candidate_id:
            return self.open_by_candidate
        return None

    def get_open_by_asset_code(self, asset_code: str):
        if self.open_by_asset and asset_code:
            return self.open_by_asset
        return None

    def save_request(self, decision_request):
        self.saved_requests.append(decision_request)
        return decision_request

    def save_response(self, request_id: str, response):
        self.saved_responses.append((request_id, response))
        return response


class FakeRecommendationRepo:
    def __init__(self, active_recommendation=None):
        self.active_recommendation = active_recommendation
        self.saved_snapshots = []
        self.saved_recommendations = []
        self.append_calls: list[tuple[str, list[str]]] = []

    def get_active_by_key(self, **kwargs):
        return self.active_recommendation

    def append_source_candidate_ids(self, recommendation_id: str, candidate_ids: list[str]):
        self.append_calls.append((recommendation_id, candidate_ids))
        if self.active_recommendation:
            return self.active_recommendation
        return None

    def save_feature_snapshot(self, snapshot):
        self.saved_snapshots.append(snapshot)
        return snapshot

    def save(self, recommendation):
        self.saved_recommendations.append(recommendation)
        return recommendation


class FakeSingleSubmitUseCase:
    def __init__(self, submit_response):
        self.submit_response = submit_response
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return self.submit_response


class FakeBatchSubmitUseCase:
    def __init__(self, submit_response):
        self.submit_response = submit_response
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return self.submit_response


class FakeCooldownRepo:
    def __init__(self, cooldowns=None, remaining_hours: float = 0.0):
        self.cooldowns = cooldowns or []
        self.remaining_hours = remaining_hours
        self.last_get_recent_asset = None

    def get_active_cooldown(self, asset_code: str):
        for cooldown in self.cooldowns:
            if cooldown.asset_code == asset_code:
                return cooldown
        return None

    def get_all_active(self):
        return self.cooldowns

    def get_remaining_hours(self, asset_code: str, direction=None):
        self.last_get_recent_asset = (asset_code, direction)
        return self.remaining_hours


class FakeQuotaRepo:
    def __init__(self, quota=None):
        self.quota = quota
        self.saved_quota = None
        self.reset_calls: list[tuple[QuotaPeriod, str]] = []
        self.reset_returns: dict[tuple[QuotaPeriod, str], bool] = {}

    def get_quota(self, period: QuotaPeriod, account_id: str = "default"):
        if (
            self.quota
            and self.quota.period == period
            and (self.quota.account_id or "default") == account_id
        ):
            return self.quota
        return None

    def save(self, quota: DecisionQuota):
        self.saved_quota = quota
        self.quota = quota
        return quota

    def get_all_quotas(
        self,
        period: QuotaPeriod | None = None,
        account_id: str | None = None,
    ):
        if self.quota is None:
            return []
        if period is not None and self.quota.period != period:
            return []
        if account_id is not None and (self.quota.account_id or "default") != account_id:
            return []
        return [self.quota]

    def reset_quota(self, period: QuotaPeriod, account_id: str = "default"):
        self.reset_calls.append((period, account_id))
        return self.reset_returns.get((period, account_id), True)


class FakeRequestRepo:
    def __init__(self, decision_request=None, recent_requests=None, statistics=None):
        self.decision_request = decision_request
        self.recent_requests = recent_requests or []
        self.statistics = statistics or {}
        self.status_updates: list[tuple[str, ExecutionStatus]] = []
        self.get_recent_calls: list[tuple[int, str | None]] = []

    def get_by_id(self, request_id: str):
        if self.decision_request and self.decision_request.request_id == request_id:
            return self.decision_request
        return None

    def get_recent(self, days: int = 30, asset_code: str | None = None):
        self.get_recent_calls.append((days, asset_code))
        return self.recent_requests

    def get_statistics(self, days: int = 30):
        return {"days": days, **self.statistics}

    def update_execution_status(self, request_id: str, execution_status, **kwargs):
        self.status_updates.append((request_id, execution_status))
        return True


class FakeAccountRepo:
    def __init__(self, accounts=None):
        self.accounts = accounts or []

    def get_by_user(self, user_id: int):
        return self.accounts


class FakeAssetNameResolver:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}
        self.calls: list[list[str]] = []

    def __call__(self, codes: list[str]):
        self.calls.append(codes)
        return self.mapping


def test_precheck_use_case_requires_actionable_candidate():
    candidate_repo = FakeCandidateRepo(
        FakeCandidate(candidate_id="cand-1", status=CandidateStatus.WATCH)
    )
    quota_repo = FakeQuotaRepo(
        DecisionQuota(
            period=QuotaPeriod.WEEKLY,
            max_decisions=5,
            max_execution_count=3,
        )
    )
    use_case = PrecheckDecisionUseCase(
        candidate_repo=candidate_repo,
        quota_repo=quota_repo,
        cooldown_repo=FakeCooldownRepo(),
    )

    response = use_case.execute(PrecheckRequest(candidate_id="cand-1"))

    assert response.success is True
    assert response.result is not None
    assert response.result.candidate_valid is False
    assert any("ACTIONABLE" in error for error in response.result.errors)


def test_cancel_decision_request_use_case_updates_request_and_candidate_tracking():
    request_repo = FakeRequestRepo(
        SimpleNamespace(
            request_id="req-1",
            execution_status=ExecutionStatus.PENDING,
            candidate_id="cand-1",
        )
    )
    candidate_repo = FakeCandidateRepo(FakeCandidate(candidate_id="cand-1"))
    use_case = CancelDecisionRequestUseCase(
        request_repo=request_repo,
        candidate_repo=candidate_repo,
    )

    response = use_case.execute(CancelDecisionRequest(request_id="req-1", reason="manual cancel"))

    assert response.success is True
    assert response.status == ExecutionStatus.CANCELLED.value
    assert request_repo.status_updates == [("req-1", ExecutionStatus.CANCELLED)]
    assert candidate_repo.execution_updates == [
        ("cand-1", "req-1", ExecutionStatus.CANCELLED.value)
    ]


def test_update_quota_config_use_case_preserves_existing_usage():
    existing = DecisionQuota(
        period=QuotaPeriod.WEEKLY,
        max_decisions=5,
        max_execution_count=2,
        used_decisions=3,
        used_executions=1,
        quota_id="quota_existing",
        account_id="acct-1",
    )
    quota_repo = FakeQuotaRepo(existing)
    use_case = UpdateQuotaConfigUseCase(quota_repo)

    response = use_case.execute(
        UpdateQuotaConfigRequest(
            account_id="acct-1",
            period=QuotaPeriod.WEEKLY,
            max_decisions=10,
            max_executions=4,
        )
    )

    assert response.success is True
    assert response.created is False
    assert response.quota is not None
    assert response.quota.used_decisions == 3
    assert response.quota.used_executions == 1
    assert response.quota.max_decisions == 10
    assert response.quota.max_execution_count == 4


def test_submit_decision_workflow_use_case_reuses_open_candidate_request():
    existing_request = SimpleNamespace(request_id="req-existing", candidate_id="cand-1")
    request_repo = FakeWorkflowRequestRepo(open_by_candidate=existing_request)
    workflow = SubmitDecisionWorkflowUseCase(
        submit_use_case=FakeSingleSubmitUseCase(submit_response=None),
        request_repo=request_repo,
        recommendation_repo=FakeRecommendationRepo(),
        candidate_repo=FakeCandidateRepo(),
    )

    response = workflow.execute(
        SubmitDecisionWorkflowRequest(
            submit_request=SubmitDecisionRequestRequest(
                asset_code="000001.SH",
                asset_class="equity",
                direction="BUY",
                priority=DecisionPriority.HIGH,
                candidate_id="cand-1",
            ),
            account_id="acct-1",
        )
    )

    assert response.success is True
    assert response.deduplicated is True
    assert response.decision_request is existing_request
    assert request_repo.saved_requests == []
    assert request_repo.saved_responses == []


def test_submit_decision_workflow_use_case_persists_recommendation_and_compacts_candidate():
    decision_request = SimpleNamespace(
        request_id="req-1",
        candidate_id="cand-1",
        asset_code="000001.SH",
    )
    decision_response = SimpleNamespace(
        request_id="req-1",
        approved=True,
    )
    submit_use_case = FakeSingleSubmitUseCase(
        SimpleNamespace(
            success=True,
            decision_request=decision_request,
            response=decision_response,
        )
    )
    request_repo = FakeWorkflowRequestRepo()
    recommendation_repo = FakeRecommendationRepo()
    candidate_repo = FakeCandidateRepo(FakeCandidate(candidate_id="cand-1"))
    workflow = SubmitDecisionWorkflowUseCase(
        submit_use_case=submit_use_case,
        request_repo=request_repo,
        recommendation_repo=recommendation_repo,
        candidate_repo=candidate_repo,
    )

    response = workflow.execute(
        SubmitDecisionWorkflowRequest(
            submit_request=SubmitDecisionRequestRequest(
                asset_code="000001.SH",
                asset_class="equity",
                direction="BUY",
                priority=DecisionPriority.HIGH,
                candidate_id="cand-1",
                reason="alpha",
                expected_confidence=0.7,
                quantity=100,
                notional=5000,
            ),
            account_id="acct-1",
        )
    )

    assert response.success is True
    assert response.recommendation_id is not None
    assert submit_use_case.requests and submit_use_case.requests[0].candidate_id == "cand-1"
    assert request_repo.saved_requests == [decision_request]
    assert request_repo.saved_responses == [("req-1", decision_response)]
    assert len(recommendation_repo.saved_snapshots) == 1
    assert len(recommendation_repo.saved_recommendations) == 1
    assert candidate_repo.status_updates == [("cand-1", CandidateStatus.CANDIDATE)]
    assert candidate_repo.execution_updates == [("cand-1", "req-1", "PENDING")]


def test_submit_batch_workflow_use_case_persists_each_request_and_response():
    decision_request_1 = SimpleNamespace(request_id="req-1")
    decision_request_2 = SimpleNamespace(request_id="req-2")
    decision_response_1 = SimpleNamespace(request_id="req-1")
    decision_response_2 = SimpleNamespace(request_id="req-2")
    submit_use_case = FakeBatchSubmitUseCase(
        SimpleNamespace(
            success=True,
            decision_requests=[decision_request_1, decision_request_2],
            responses=[decision_response_1, decision_response_2],
            summary={"approved": 2},
            error=None,
        )
    )
    request_repo = FakeWorkflowRequestRepo()
    workflow = SubmitBatchWorkflowUseCase(
        submit_use_case=submit_use_case,
        request_repo=request_repo,
    )

    response = workflow.execute(
        SubmitBatchWorkflowRequest(
            batch_request=SubmitBatchRequestRequest(
                requests=[
                    SubmitDecisionRequestRequest(
                        asset_code="000001.SH",
                        asset_class="equity",
                        direction="BUY",
                        priority=DecisionPriority.HIGH,
                    ),
                    SubmitDecisionRequestRequest(
                        asset_code="000002.SH",
                        asset_class="equity",
                        direction="SELL",
                        priority=DecisionPriority.MEDIUM,
                    ),
                ],
                quota_period=QuotaPeriod.WEEKLY,
            )
        )
    )

    assert response.success is True
    assert response.decision_requests == [decision_request_1, decision_request_2]
    assert response.summary == {"approved": 2}
    assert request_repo.saved_requests == [decision_request_1, decision_request_2]
    assert request_repo.saved_responses == [
        ("req-1", decision_response_1),
        ("req-2", decision_response_2),
    ]


def test_reset_quota_by_account_use_case_resets_all_periods_for_account():
    quota_repo = FakeQuotaRepo()
    use_case = ResetQuotaByAccountUseCase(quota_repo)

    response = use_case.execute(ResetQuotaByAccountRequest(account_id="acct-1"))

    assert response.success is True
    assert response.message == "配额已重置 (account=acct-1)"
    assert response.reset_periods == [period.value for period in QuotaPeriod]
    assert quota_repo.reset_calls == [
        (QuotaPeriod.DAILY, "acct-1"),
        (QuotaPeriod.WEEKLY, "acct-1"),
        (QuotaPeriod.MONTHLY, "acct-1"),
    ]


def test_get_trend_data_use_case_uses_daily_quota_from_repository():
    quota_repo = FakeQuotaRepo(
        DecisionQuota(
            period=QuotaPeriod.DAILY,
            max_decisions=12,
            max_execution_count=6,
            account_id="acct-1",
        )
    )
    use_case = GetTrendDataUseCase(quota_repo)

    response = use_case.execute(TrendDataRequest(days=7, account_id="acct-1"))

    assert response.success is True
    assert response.data is not None
    assert response.data["period_days"] == 7
    assert response.data["daily_quota_limit"] == 12
    assert len(response.data["daily_decisions"]) == 7
    assert len(response.data["daily_executions"]) == 7


def test_list_decision_requests_use_case_passes_query_filters():
    expected_request = SimpleNamespace(request_id="req-1")
    request_repo = FakeRequestRepo(recent_requests=[expected_request])
    use_case = ListDecisionRequestsUseCase(request_repo)

    response = use_case.execute(ListDecisionRequestsRequest(days=14, asset_code="000001.SH"))

    assert response == [expected_request]
    assert request_repo.get_recent_calls == [(14, "000001.SH")]


def test_get_cooldown_remaining_hours_use_case_marks_active_state():
    cooldown_repo = FakeCooldownRepo(remaining_hours=6.5)
    use_case = GetCooldownRemainingHoursUseCase(cooldown_repo)

    response = use_case.execute(
        GetCooldownRemainingHoursRequest(
            asset_code="000001.SH",
            direction="BUY",
        )
    )

    assert response.asset_code == "000001.SH"
    assert response.remaining_hours == 6.5
    assert response.is_active is True
    assert cooldown_repo.last_get_recent_asset == ("000001.SH", "BUY")


def test_get_decision_quota_page_use_case_builds_template_compatible_context():
    quota_repo = FakeQuotaRepo(
        DecisionQuota(
            period=QuotaPeriod.WEEKLY,
            max_decisions=8,
            max_execution_count=4,
            used_decisions=3,
            used_executions=1,
            period_start=datetime(2026, 4, 1, tzinfo=UTC),
            period_end=datetime(2026, 4, 7, tzinfo=UTC),
            account_id="101",
        )
    )
    cooldown_repo = FakeCooldownRepo(
        cooldowns=[
            CooldownPeriod(
                asset_code="000001.SH",
                min_decision_interval_hours=24,
                min_execution_interval_hours=48,
                last_decision_at=datetime(2026, 4, 1, 9, 0, tzinfo=UTC),
            )
        ]
    )
    request_repo = FakeRequestRepo(
        recent_requests=[
            DecisionRequest(
                request_id="req-1",
                asset_code="000001.SH",
                asset_class="equity",
                direction="BUY",
                priority=DecisionPriority.HIGH,
                requested_at=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
            )
        ]
    )
    account_repo = FakeAccountRepo(
        accounts=[
            SimpleNamespace(
                account_id=101,
                account_name="Main",
                account_type=SimpleNamespace(value="real"),
            )
        ]
    )
    asset_name_resolver = FakeAssetNameResolver({"000001.SH": "平安银行"})
    use_case = GetDecisionQuotaPageUseCase(
        account_repo=account_repo,
        quota_repo=quota_repo,
        cooldown_repo=cooldown_repo,
        request_repo=request_repo,
        asset_name_resolver=asset_name_resolver,
    )

    context = use_case.execute(
        DecisionQuotaPageRequest(
            user_id=1,
            is_authenticated=True,
        )
    ).to_context()

    assert context["current_account_id"] == "101"
    assert context["quota_total"] == 8
    assert context["quota_used"] == 3
    assert context["quota_remaining"] == 5
    assert context["recent_requests"][0].asset_name == "平安银行"
    assert context["recent_requests"][0].get_execution_status_display() == "待执行"
    assert context["active_cooldowns"][0].asset_name == "平安银行"
    assert asset_name_resolver.calls == [["000001.SH", "000001.SH"]]


def test_get_decision_quota_config_page_use_case_uses_period_value_items():
    quota_repo = FakeQuotaRepo(
        DecisionQuota(
            period=QuotaPeriod.MONTHLY,
            max_decisions=12,
            max_execution_count=6,
            used_decisions=2,
            used_executions=1,
            account_id="acct-1",
        )
    )
    account_repo = FakeAccountRepo()
    use_case = GetDecisionQuotaConfigPageUseCase(
        account_repo=account_repo,
        quota_repo=quota_repo,
    )

    context = use_case.execute(
        DecisionQuotaConfigPageRequest(
            requested_account_id="acct-1",
            is_authenticated=False,
        )
    ).to_context()

    assert context["current_account_id"] == "acct-1"
    assert context["quotas"][0].period == "monthly"
    assert context["period_choices"] == [
        ("daily", "每日"),
        ("weekly", "每周"),
        ("monthly", "每月"),
    ]
