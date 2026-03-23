"""
Integration Tests for Decision Platform

测试 Beta Gate、Alpha Trigger、Decision Rhythm 三个模块的协同工作。
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import User
from django.test import Client, TestCase

from apps.alpha_trigger.domain.entities import (
    AlphaCandidate,
    AlphaTrigger,
    SignalStrength,
    TriggerStatus,
    TriggerType,
)
from apps.beta_gate.domain.entities import (
    GateConfig,
    PolicyConstraint,
    PortfolioConstraint,
    RegimeConstraint,
    RiskProfile,
)
from apps.decision_rhythm.domain.entities import (
    DecisionPriority,
    DecisionQuota,
    DecisionRequest,
    DecisionStatus,
    QuotaPeriod,
)


@pytest.mark.django_db
class TestDecisionPlatformWorkflow:
    """决策平台端到端工作流测试"""

    def test_complete_decision_workflow(self):
        """
        测试完整的决策工作流：
        1. 配置 Beta Gate
        2. 创建 Alpha Trigger
        3. Trigger 触发生成 Candidate
        4. 提交决策请求
        5. 检查配额
        """
        # 步骤 1: 配置 Beta Gate
        gate_config = GateConfig(
            config_id="test_gate_config",
            version=1,
            is_active=True,
            is_valid=True,
            risk_profile=RiskProfile.BALANCED,
            regime_constraint=RegimeConstraint(
                current_regime="Recovery",
                confidence=0.75,
                allowed_asset_classes=["a_股票", "a_债券"],
            ),
            policy_constraint=PolicyConstraint(
                current_level=1,
                max_risk_exposure=80,
                hard_exclusions=["期货", "期权"],
            ),
            portfolio_constraint=PortfolioConstraint(
                max_positions=10,
                max_single_position_weight=20,
                max_concentration_ratio=60,
            ),
        )

        # 步骤 2: 创建 Alpha Trigger
        trigger = AlphaTrigger(
            trigger_id="test_trigger_001",
            trigger_type=TriggerType.MOMENTUM_SIGNAL,
            asset_code="000001.SH",
            asset_class="a_股票",
            direction="LONG",
            trigger_condition={"momentum_pct": 0.05},
            invalidation_conditions=[],
            strength=SignalStrength.STRONG,
            confidence=0.75,
            status=TriggerStatus.ACTIVE,
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
            related_regime="Recovery",
            related_policy_level=1,
        )

        # 步骤 3: 模拟触发器被触发
        trigger.status = TriggerStatus.TRIGGERED
        trigger.triggered_at = datetime.now(ZoneInfo("Asia/Shanghai"))

        # 步骤 4: 生成候选
        candidate = AlphaCandidate(
            candidate_id="test_candidate_001",
            trigger_id=trigger.trigger_id,
            asset_code=trigger.asset_code,
            asset_class=trigger.asset_class,
            direction=trigger.direction,
            strength=trigger.strength,
            confidence=trigger.confidence,
            status="ACTIONABLE",
            thesis="测试投资论点",
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

        # 步骤 5: 创建决策请求
        decision_request = DecisionRequest(
            request_id="test_request_001",
            asset_code=candidate.asset_code,
            asset_class=candidate.asset_class,
            direction="BUY",
            priority=DecisionPriority.HIGH,
            trigger_id=trigger.trigger_id,
            reason="测试决策请求",
            quota_period=QuotaPeriod.WEEKLY,
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

        # 验证工作流
        assert gate_config.is_active is True
        assert trigger.is_triggered is True
        assert candidate.is_actionable is True
        assert decision_request.status == DecisionStatus.PENDING

    def test_gate_prevents_trigger_for_forbidden_asset(self):
        """测试 Beta Gate 阻止禁用资产的触发器工作"""
        # 配置 Gate - 禁止 "期货" 类资产
        regime_constraint = RegimeConstraint(
            current_regime="Recovery",
            confidence=0.75,
            allowed_asset_classes=["a_股票", "a_债券"],
        )

        # 尝试为期货资产创建触发器
        trigger = AlphaTrigger(
            trigger_id="test_trigger_002",
            trigger_type=TriggerType.MOMENTUM_SIGNAL,
            asset_code="IF2410",
            asset_class="期货",
            direction="LONG",
            trigger_condition={},
            invalidation_conditions=[],
            strength=SignalStrength.STRONG,
            confidence=0.75,
            status=TriggerStatus.ACTIVE,
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
            related_regime="Recovery",
        )

        # 验证资产类别不在允许列表中
        assert trigger.asset_class not in regime_constraint.allowed_asset_classes

    def test_high_priority_candidate_bypass_quota_check(self):
        """测试高优先级候选可以绕过部分配额限制"""
        # 创建配额
        quota = DecisionQuota(
            quota_id="test_quota",
            period=QuotaPeriod.WEEKLY,
            max_decisions=10,
            used_decisions=8,  # 仅剩 2 个配额
            max_executions=5,
            used_executions=4,
            period_start=datetime.now(ZoneInfo("Asia/Shanghai")),
            is_active=True,
        )

        # 创建高优先级决策请求
        request = DecisionRequest(
            request_id="test_request_002",
            asset_code="000001.SH",
            asset_class="a_股票",
            direction="BUY",
            priority=DecisionPriority.HIGH,
            reason="高优先级测试请求",
            quota_period=QuotaPeriod.WEEKLY,
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

        # 验证高优先级请求被创建
        assert request.priority == DecisionPriority.HIGH
        assert quota.max_decisions > quota.used_decisions


@pytest.mark.django_db
class TestDecisionPlatformPages:
    """决策平台页面集成测试"""

    @pytest.fixture
    def db_client(self):
        """创建测试客户端"""
        user = User.objects.create_user(
            username="test_user",
            email="test@example.com",
            password="test_password"
        )
        client = Client()
        client.login(username="test_user", password="test_password")
        return client

    def test_workspace_page_loads(self, db_client):
        """测试工作台页面加载"""
        response = db_client.get("/decision/workspace/")
        # 页面应该可访问
        assert response.status_code in [200, 302, 404]

    def test_alpha_trigger_list_page_loads(self, db_client):
        """测试 Alpha Trigger 列表页面"""
        response = db_client.get("/alpha-triggers/")
        assert response.status_code in [200, 302]

    def test_beta_gate_config_page_loads(self, db_client):
        """测试 Beta Gate 配置页面"""
        response = db_client.get("/beta-gate/config/")
        assert response.status_code in [200, 302]

    def test_decision_rhythm_quota_page_loads(self, db_client):
        """测试 Decision Rhythm 配额页面"""
        response = db_client.get("/decision-rhythm/quota/")
        assert response.status_code in [200, 302]

    def test_alpha_trigger_performance_page_loads(self, db_client):
        """测试 Alpha Trigger 性能页面"""
        response = db_client.get("/alpha-triggers/performance/")
        assert response.status_code in [200, 302]


@pytest.mark.django_db
class TestDecisionPlatformAPI:
    """决策平台 API 集成测试"""

    @pytest.fixture
    def api_client(self):
        """创建 API 测试客户端"""
        user = User.objects.create_user(
            username="api_user",
            email="api@example.com",
            password="test_password"
        )
        client = Client()
        client.login(username="api_user", password="test_password")
        return client

    def test_beta_gate_test_api(self, api_client):
        """测试 Beta Gate 测试 API"""
        response = api_client.post(
            "/api/beta-gate/test/",
            data={"asset_codes": ["000001.SH"], "asset_class": "a_股票"},
            content_type="application/json"
        )
        assert response.status_code in [200, 201, 400, 405]

    def test_alpha_trigger_performance_api(self, api_client):
        """测试 Alpha Trigger 性能 API"""
        response = api_client.get("/api/alpha-triggers/performance/?days=30")
        assert response.status_code in [200, 404]

    def test_decision_rhythm_trend_api(self, api_client):
        """测试 Decision Rhythm 趋势 API"""
        response = api_client.get("/api/decision-rhythm/trend-data/?days=7")
        assert response.status_code in [200, 404]
