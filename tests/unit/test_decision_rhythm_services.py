"""
Unit tests for decision_rhythm domain entities/services.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.decision_rhythm.domain.entities import (
    CooldownPeriod,
    DecisionPriority,
    DecisionRequest,
    DecisionResponse,
    DecisionStatus,
    DecisionQuota,
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


class TestCooldownManager:
    def test_check_cooldown_blocked(self):
        manager = CooldownManager()
        req = _mk_request(DecisionPriority.MEDIUM)
        manager.cooldowns[req.asset_code] = CooldownPeriod(
            asset_code=req.asset_code,
            last_decision_at=datetime.now() - timedelta(hours=1),
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
            last_decision_at=datetime.now() - timedelta(hours=30),
            min_decision_interval_hours=24,
        )
        result = manager.check_cooldown(req)
        assert result.passed is True


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


class TestRhythmManager:
    def test_submit_request_returns_response(self):
        manager = RhythmManager()
        req = _mk_request(DecisionPriority.HIGH)
        resp = manager.submit_request(req, quota_period=QuotaPeriod.WEEKLY)
        assert isinstance(resp, DecisionResponse)


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
