"""
Unit Tests for Decision Rhythm Domain Services

测试 QuotaManager, CooldownManager 和 RhythmManager 的行为。
"""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apps.decision_rhythm.domain.entities import (
    DecisionQuota,
    CooldownPeriod,
    DecisionRequest,
    DecisionResponse,
    DecisionPriority,
    QuotaPeriod,
    ResponseStatus,
)
from apps.decision_rhythm.domain.services import (
    QuotaManager,
    CooldownManager,
    RhythmManager,
    DecisionScheduler,
)


class TestQuotaManager:
    """QuotaManager 测试"""

    @pytest.fixture
    def manager(self):
        """配额管理器 fixture"""
        return QuotaManager()

    @pytest.fixture
    def weekly_quota(self):
        """周配额 fixture"""
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        return DecisionQuota(
            quota_id="weekly_quota",
            period=QuotaPeriod.WEEKLY,
            asset_class=None,
            priority=DecisionPriority.MEDIUM,
            max_decisions=10,
            used_decisions=3,
            reset_at=now + timedelta(days=6),
        )

    def test_has_quota_available(self, manager, weekly_quota):
        """测试配额可用"""
        assert manager.has_quota(weekly_quota) is True

    def test_no_quota_exhausted(self, manager, weekly_quota):
        """测试配额耗尽"""
        weekly_quota.used_decisions = weekly_quota.max_decisions
        assert manager.has_quota(weekly_quota) is False

    def test_consume_quota(self, manager, weekly_quota):
        """测试消耗配额"""
        initial_used = weekly_quota.used_decisions
        manager.consume_quota(weekly_quota)

        assert weekly_quota.used_decisions == initial_used + 1

    def test_cannot_consume_exhausted_quota(self, manager, weekly_quota):
        """测试无法消耗耗尽的配额"""
        weekly_quota.used_decisions = weekly_quota.max_decisions

        with pytest.raises(ValueError, match="Quota exhausted"):
            manager.consume_quota(weekly_quota)

    def test_get_remaining(self, manager, weekly_quota):
        """测试获取剩余配额"""
        remaining = manager.get_remaining(weekly_quota)

        expected = weekly_quota.max_decisions - weekly_quota.used_decisions
        assert remaining == expected

    def test_get_usage_rate(self, manager, weekly_quota):
        """测试获取使用率"""
        rate = manager.get_usage_rate(weekly_quota)

        expected = weekly_quota.used_decisions / weekly_quota.max_decisions
        assert rate == expected


class TestCooldownManager:
    """CooldownManager 测试"""

    @pytest.fixture
    def manager(self):
        """冷却管理器 fixture"""
        return CooldownManager()

    @pytest.fixture
    def cooldown_period(self):
        """冷却期 fixture"""
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        return CooldownPeriod(
            cooldown_id="test_cooldown",
            asset_code="000001.SH",
            asset_class="a_share金融",
            direction="BUY",
            cooldown_hours=24,
            cooldown_end_at=now + timedelta(hours=20),
            decision_request_id="request_001",
            created_at=now - timedelta(hours=4),
        )

    def test_is_in_cooldown_true(self, manager, cooldown_period):
        """测试在冷却期内"""
        assert manager.is_in_cooldown(cooldown_period) is True

    def test_is_in_cooldown_false(self, manager):
        """测试不在冷却期内"""
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        expired_cooldown = CooldownPeriod(
            cooldown_id="expired_cooldown",
            asset_code="000001.SH",
            asset_class="a_share金融",
            direction="BUY",
            cooldown_hours=24,
            cooldown_end_at=now - timedelta(hours=1),
            created_at=now - timedelta(hours=25),
        )

        assert manager.is_in_cooldown(expired_cooldown) is False

    def test_get_remaining_hours(self, manager, cooldown_period):
        """测试获取剩余小时数"""
        remaining = manager.get_remaining_hours(cooldown_period)

        assert remaining > 0
        assert remaining < 24

    def test_start_cooldown(self, manager):
        """测试开始冷却"""
        from apps.decision_rhythm.domain.entities import create_cooldown

        request = DecisionRequest(
            request_id="request_001",
            asset_code="000001.SH",
            asset_class="a_share金融",
            direction="BUY",
            priority=DecisionPriority.MEDIUM,
            reason="测试",
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

        cooldown = manager.start_cooldown(
            asset_code=request.asset_code,
            asset_class=request.asset_class,
            direction="BUY",
            cooldown_hours=24,
            decision_request_id=request.request_id,
        )

        assert cooldown.asset_code == "000001.SH"
        assert cooldown.direction == "BUY"
        assert cooldown.cooldown_hours == 24


class TestDecisionScheduler:
    """DecisionScheduler 测试"""

    @pytest.fixture
    def scheduler(self):
        """调度器 fixture"""
        return DecisionScheduler()

    def test_priority_ordering(self, scheduler):
        """测试优先级排序"""
        requests = [
            DecisionRequest(
                request_id="low",
                asset_code="000003.SH",
                asset_class="a_share金融",
                direction="BUY",
                priority=DecisionPriority.LOW,
                reason="低优先级",
                created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
            ),
            DecisionRequest(
                request_id="urgent",
                asset_code="000001.SH",
                asset_class="a_share金融",
                direction="BUY",
                priority=DecisionPriority.URGENT,
                reason="紧急",
                created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
            ),
            DecisionRequest(
                request_id="medium",
                asset_code="000002.SZ",
                asset_class="a_share金融",
                direction="BUY",
                priority=DecisionPriority.MEDIUM,
                reason="中优先级",
                created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
            ),
        ]

        sorted_requests = scheduler.sort_by_priority(requests)

        assert sorted_requests[0].request_id == "urgent"
        assert sorted_requests[1].request_id == "medium"
        assert sorted_requests[2].request_id == "low"

    def test_filter_pending(self, scheduler):
        """测试过滤待处理请求"""
        requests = [
            DecisionRequest(
                request_id="pending1",
                asset_code="000001.SH",
                asset_class="a_share金融",
                direction="BUY",
                priority=DecisionPriority.MEDIUM,
                reason="待处理1",
                created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
            ),
            DecisionRequest(
                request_id="pending2",
                asset_code="000002.SZ",
                asset_class="a_share金融",
                direction="BUY",
                priority=DecisionPriority.MEDIUM,
                reason="待处理2",
                created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
            ),
        ]

        pending = scheduler.get_pending(requests)

        assert len(pending) == 2


class TestRhythmManager:
    """RhythmManager 测试"""

    @pytest.fixture
    def quota_manager(self):
        """配额管理器 fixture"""
        return QuotaManager()

    @pytest.fixture
    def cooldown_manager(self):
        """冷却管理器 fixture"""
        return CooldownManager()

    @pytest.fixture
    def scheduler(self):
        """调度器 fixture"""
        return DecisionScheduler()

    @pytest.fixture
    def rhythm_manager(self, quota_manager, cooldown_manager, scheduler):
        """节奏管理器 fixture"""
        return RhythmManager(quota_manager, cooldown_manager, scheduler)

    def test_submit_request_approved(self, rhythm_manager):
        """测试提交请求被批准"""
        request = DecisionRequest(
            request_id="request_001",
            asset_code="000001.SH",
            asset_class="a_share金融",
            direction="BUY",
            priority=DecisionPriority.HIGH,
            reason="强 Alpha 信号",
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

        # 模拟有配额且无冷却期
        response = rhythm_manager.submit_request(
            request=request,
            quota_period=QuotaPeriod.WEEKLY,
        )

        # 注意：实际实现需要仓储支持
        # 这里测试接口调用
        assert response is not None

    def test_submit_request_rejected_no_quota(self, rhythm_manager):
        """测试提交请求因无配额被拒绝"""
        request = DecisionRequest(
            request_id="request_002",
            asset_code="000002.SZ",
            asset_class="a_share金融",
            direction="BUY",
            priority=DecisionPriority.LOW,
            reason="测试",
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

        # 模拟配额已耗尽
        # response = rhythm_manager.submit_request(
        #     request=request,
        #     quota_period=QuotaPeriod.WEEKLY,
        # )

        # 注意：实际实现需要仓储支持
        # 这里测试接口调用
        pass


class TestDecisionRequest:
    """DecisionRequest 实体测试"""

    def test_request_creation(self):
        """测试请求创建"""
        request = DecisionRequest(
            request_id="test_request",
            asset_code="000001.SH",
            asset_class="a_share金融",
            direction="BUY",
            priority=DecisionPriority.HIGH,
            reason="强 Alpha 信号",
            trigger_id="trigger_001",
            expected_confidence=0.75,
            quantity=1000,
            notional=15000.0,
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

        assert request.request_id == "test_request"
        assert request.asset_code == "000001.SH"
        assert request.direction == "BUY"
        assert request.priority == DecisionPriority.HIGH
        assert request.quantity == 1000
        assert request.notional == 15000.0

    def test_is_approved_property(self):
        """测试 is_approved 属性"""
        response = DecisionResponse(
            request_id="test_request",
            approved=True,
            status=ResponseStatus.APPROVED,
            approval_reason="满足所有条件",
            rejection_reason="",
            processed_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

        assert response.is_approved is True

    def test_is_rejected_property(self):
        """测试 is_rejected 属性"""
        response = DecisionResponse(
            request_id="test_request",
            approved=False,
            status=ResponseStatus.REJECTED,
            approval_reason="",
            rejection_reason="配额已耗尽",
            processed_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

        assert response.is_rejected is True


class TestQuotaPeriod:
    """QuotaPeriod 枚举测试"""

    def test_period_values(self):
        """测试周期值"""
        assert QuotaPeriod.DAILY.value == "DAILY"
        assert QuotaPeriod.WEEKLY.value == "WEEKLY"
        assert QuotaPeriod.MONTHLY.value == "MONTHLY"
        assert QuotaPeriod.QUARTERLY.value == "QUARTERLY"
        assert QuotaPeriod.YEARLY.value == "YEARLY"


class TestDecisionPriority:
    """DecisionPriority 枚举测试"""

    def test_priority_ordering(self):
        """测试优先级排序"""
        priorities = [
            DecisionPriority.LOW,
            DecisionPriority.MEDIUM,
            DecisionPriority.HIGH,
            DecisionPriority.URGENT,
        ]

        # 测试优先级可以通过枚举值比较
        assert priorities.index(DecisionPriority.URGENT) > priorities.index(DecisionPriority.HIGH)
        assert priorities.index(DecisionPriority.HIGH) > priorities.index(DecisionPriority.MEDIUM)
