"""
Unit tests for decision_rhythm domain entities/services.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from apps.decision_rhythm.domain.entities import (
    CooldownPeriod,
    DecisionPriority,
    DecisionQuota,
    DecisionRequest,
    DecisionResponse,
    DecisionStatus,
    QuotaPeriod,
)
from apps.decision_rhythm.domain.services import (
    CooldownManager,
    DecisionScheduler,
    QuotaManager,
    RhythmManager,
)


def _mk_request(priority: DecisionPriority = DecisionPriority.MEDIUM) -> DecisionRequest:
    return DecisionRequest(
        request_id="req_001",
        asset_code="000001.SH",
        asset_class="a_share_financial",
        direction="BUY",
        priority=priority,
        reason="test",
        created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
    )


class TestQuotaManager:
    def test_check_quota_available(self):
        manager = QuotaManager()
        request = _mk_request(DecisionPriority.MEDIUM)
        result = manager.check_quota(request, QuotaPeriod.WEEKLY)
        assert result.passed is True

    def test_check_quota_exhausted(self):
        manager = QuotaManager()
        quota = manager.quotas[QuotaPeriod.WEEKLY]
        manager.quotas[QuotaPeriod.WEEKLY] = DecisionQuota(
            period=quota.period,
            max_decisions=quota.max_decisions,
            max_execution_count=quota.max_execution_count,
            used_decisions=quota.max_decisions,
            used_executions=quota.used_executions,
            period_start=quota.period_start,
            period_end=quota.period_end,
            quota_id=quota.quota_id,
            created_at=quota.created_at,
            updated_at=quota.updated_at,
            is_active=quota.is_active,
        )
        request = _mk_request(DecisionPriority.MEDIUM)
        result = manager.check_quota(request, QuotaPeriod.WEEKLY)
        assert result.passed is False

    def test_consume_quota(self):
        manager = QuotaManager()
        request = _mk_request(DecisionPriority.MEDIUM)
        before = manager.quotas[QuotaPeriod.WEEKLY]
        after = manager.consume_quota(request, QuotaPeriod.WEEKLY)
        assert after.used_decisions == before.used_decisions + 1
        assert manager.quotas[QuotaPeriod.WEEKLY].used_decisions == before.used_decisions + 1

    def test_critical_request_bypasses_exhausted_quota(self) -> None:
        manager = QuotaManager()
        quota = manager.quotas[QuotaPeriod.WEEKLY]
        manager.quotas[QuotaPeriod.WEEKLY] = DecisionQuota(
            **{
                **quota.__dict__,
                "used_decisions": quota.max_decisions,
                "used_executions": quota.max_execution_count,
            }
        )

        result = manager.check_quota(
            _mk_request(DecisionPriority.CRITICAL),
            QuotaPeriod.WEEKLY,
        )

        assert result.passed is True
        assert result.available_at is None

    def test_execution_quota_blocks_non_info_request(self) -> None:
        manager = QuotaManager()
        quota = manager.quotas[QuotaPeriod.WEEKLY]
        manager.quotas[QuotaPeriod.WEEKLY] = DecisionQuota(
            **{
                **quota.__dict__,
                "used_executions": quota.max_execution_count,
            }
        )

        result = manager.check_quota(
            _mk_request(DecisionPriority.HIGH),
            QuotaPeriod.WEEKLY,
        )

        assert result.passed is False
        assert "执行配额" in result.reason

    def test_info_consumption_only_uses_decision_quota(self) -> None:
        manager = QuotaManager()
        before = manager.quotas[QuotaPeriod.DAILY]

        after = manager.consume_quota(
            _mk_request(DecisionPriority.INFO),
            QuotaPeriod.DAILY,
        )

        assert after.used_decisions == before.used_decisions + 1
        assert after.used_executions == before.used_executions

    def test_reset_and_status_helpers_publish_all_periods(self) -> None:
        manager = QuotaManager()
        manager.consume_quota(_mk_request(), QuotaPeriod.DAILY)

        manager.reset_all_quotas()
        statuses = manager.get_all_quota_statuses()

        assert statuses.keys() == {"daily", "weekly", "monthly"}
        assert statuses["daily"]["used_decisions"] == 0


class TestCooldownManager:
    def test_check_cooldown_blocked(self):
        manager = CooldownManager()
        req = _mk_request(DecisionPriority.MEDIUM)
        manager.cooldowns[req.asset_code] = CooldownPeriod(
            asset_code=req.asset_code,
            last_decision_at=datetime.now(UTC) - timedelta(hours=1),
            min_decision_interval_hours=24,
        )
        result = manager.check_cooldown(req)
        assert result.passed is False
        assert result.wait_hours > 0

    def test_check_cooldown_passed(self):
        manager = CooldownManager()
        req = _mk_request(DecisionPriority.MEDIUM)
        manager.cooldowns[req.asset_code] = CooldownPeriod(
            asset_code=req.asset_code,
            last_decision_at=datetime.now(UTC) - timedelta(hours=30),
            min_decision_interval_hours=24,
        )
        result = manager.check_cooldown(req)
        assert result.passed is True

    def test_execution_cooldown_and_critical_bypass(self) -> None:
        manager = CooldownManager()
        req = _mk_request(DecisionPriority.HIGH)
        manager.cooldowns[req.asset_code] = CooldownPeriod(
            asset_code=req.asset_code,
            last_execution_at=datetime.now(UTC) - timedelta(hours=1),
            min_execution_interval_hours=24,
        )

        blocked = manager.check_cooldown(req, check_execution=True)
        bypassed = manager.check_cooldown(
            _mk_request(DecisionPriority.CRITICAL),
            check_execution=True,
        )

        assert blocked.passed is False
        assert blocked.ready_at is not None
        assert bypassed.passed is True

    def test_update_and_clear_cooldown_state(self) -> None:
        manager = CooldownManager()

        decision = manager.update_decision_time("000001.SH")
        execution = manager.update_execution_time("000001.SH")
        assert decision.last_decision_at is not None
        assert execution.last_execution_at is not None

        manager.clear_cooldown("000001.SH")
        assert manager.cooldowns == {}
        manager.update_decision_time("000002.SH")
        manager.clear_all_cooldowns()
        assert manager.cooldowns == {}


class TestDecisionScheduler:
    def test_get_next_by_priority(self):
        scheduler = DecisionScheduler()
        low = _mk_request(DecisionPriority.LOW)
        high = _mk_request(DecisionPriority.HIGH)
        critical = _mk_request(DecisionPriority.CRITICAL)
        low = DecisionRequest(**{**low.__dict__, "request_id": "low"})
        high = DecisionRequest(**{**high.__dict__, "request_id": "high"})
        critical = DecisionRequest(**{**critical.__dict__, "request_id": "critical"})
        scheduler.add_request(low)
        scheduler.add_request(high)
        scheduler.add_request(critical)
        nxt = scheduler.get_next()
        assert nxt is not None
        assert nxt.request_id == "critical"

    def test_queue_limit_remove_and_summary(self) -> None:
        scheduler = DecisionScheduler(max_queue_size=1)
        request = _mk_request(DecisionPriority.LOW)

        assert scheduler.get_next() is None
        assert scheduler.add_request(request) is True
        assert scheduler.add_request(_mk_request(DecisionPriority.HIGH)) is False
        assert scheduler.get_queue_summary() == {
            "size": 1,
            "by_priority": {"low": 1},
        }
        assert scheduler.remove_request("missing") is False
        assert scheduler.remove_request(request.request_id) is True
        assert scheduler.get_queue_summary() == {"size": 0, "by_priority": {}}


class TestRhythmManager:
    def test_submit_request_returns_response(self):
        manager = RhythmManager()
        req = _mk_request(DecisionPriority.HIGH)
        resp = manager.submit_request(req, quota_period=QuotaPeriod.WEEKLY)
        assert isinstance(resp, DecisionResponse)

    def test_submit_request_reports_cooldown_rejection(self) -> None:
        manager = RhythmManager()
        request = _mk_request(DecisionPriority.HIGH)
        manager.cooldown_manager.cooldowns[request.asset_code] = CooldownPeriod(
            asset_code=request.asset_code,
            last_decision_at=datetime.now(UTC),
            min_decision_interval_hours=24,
        )

        response = manager.submit_request(request)

        assert response.approved is False
        assert response.approval_reason == "冷却期内"
        assert response.wait_until is not None

    def test_submit_batch_orders_by_priority_and_summary_is_serializable(self) -> None:
        manager = RhythmManager()
        low = DecisionRequest(**{**_mk_request(DecisionPriority.LOW).__dict__, "request_id": "low"})
        critical = DecisionRequest(
            **{
                **_mk_request(DecisionPriority.CRITICAL).__dict__,
                "request_id": "critical",
            }
        )

        responses = manager.submit_batch([low, critical])
        summary = manager.get_summary()

        assert [response.request_id for response in responses] == ["critical", "low"]
        assert summary["cooldown_count"] == 1
        assert set(summary) == {"quota_statuses", "cooldown_count", "config"}


class TestEntitiesAndEnums:
    def test_request_creation(self):
        req = DecisionRequest(
            request_id="r1",
            asset_code="000001.SH",
            asset_class="a_share_financial",
            direction="BUY",
            priority=DecisionPriority.HIGH,
            reason="alpha",
            trigger_id="t1",
            expected_confidence=0.75,
            quantity=1000,
            notional=15000.0,
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
            status=DecisionStatus.PENDING,
        )
        assert req.request_id == "r1"
        assert req.priority == DecisionPriority.HIGH
        assert req.status == DecisionStatus.PENDING

    def test_response_flags(self):
        approved = DecisionResponse(
            request_id="r1",
            approved=True,
            approval_reason="ok",
            rejection_reason=None,
        )
        rejected = DecisionResponse(
            request_id="r2",
            approved=False,
            approval_reason="",
            rejection_reason="quota exhausted",
        )
        assert approved.approved is True
        assert rejected.approved is False

    def test_period_values(self):
        assert QuotaPeriod.DAILY.value == "daily"
        assert QuotaPeriod.WEEKLY.value == "weekly"
        assert QuotaPeriod.MONTHLY.value == "monthly"

    def test_priority_ordering(self):
        priorities = [
            DecisionPriority.LOW,
            DecisionPriority.MEDIUM,
            DecisionPriority.HIGH,
            DecisionPriority.CRITICAL,
        ]
        assert priorities.index(DecisionPriority.CRITICAL) > priorities.index(DecisionPriority.HIGH)
        assert priorities.index(DecisionPriority.HIGH) > priorities.index(DecisionPriority.MEDIUM)
