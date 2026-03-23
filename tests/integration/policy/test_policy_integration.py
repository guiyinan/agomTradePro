"""
Integration Tests for Policy Application

测试政策跟踪功能的应用层集成。
"""

from datetime import date, timedelta

import pytest
from django.test import TestCase

from apps.policy.application.use_cases import (
    CreatePolicyEventInput,
    CreatePolicyEventUseCase,
    DeletePolicyEventUseCase,
    GetPolicyHistoryUseCase,
    GetPolicyStatusUseCase,
    UpdatePolicyEventUseCase,
)
from apps.policy.domain.entities import PolicyEvent, PolicyLevel
from apps.policy.infrastructure.models import PolicyAuditQueue, PolicyLog
from apps.policy.infrastructure.repositories import DjangoPolicyRepository
from shared.infrastructure.alert_service import AlertLevel, ConsoleAlertChannel


@pytest.fixture(autouse=True)
def clean_policy_tables():
    """
    保证集成测试不受环境初始数据影响。

    说明：
    - 当前工程某些环境会存在预置 PolicyLog 数据；
    - 这些用例断言基于“空表起步”，因此每个用例前做清理。
    """
    PolicyAuditQueue._default_manager.all().delete()
    PolicyLog._default_manager.all().delete()
    yield


@pytest.mark.django_db
class TestPolicyRepository:
    """测试政策仓储"""

    def test_save_and_retrieve_event(self):
        """测试保存和获取事件"""
        repo = DjangoPolicyRepository()

        event = PolicyEvent(
            event_date=date.today(),
            level=PolicyLevel.P2,
            title="测试政策",
            description="这是一个测试政策事件",
            evidence_url="https://example.com/test"
        )

        # 保存
        saved = repo.save_event(event)
        assert saved.event_date == event.event_date
        assert saved.level == event.level

        # 获取
        retrieved = repo.get_event_by_date(event.event_date)
        assert retrieved is not None
        assert retrieved.title == "测试政策"

    def test_update_existing_event(self):
        """测试更新已有事件"""
        repo = DjangoPolicyRepository()

        event_date = date.today()
        event1 = PolicyEvent(
            event_date=event_date,
            level=PolicyLevel.P1,
            title="原标题",
            description="原描述",
            evidence_url="https://example.com/1"
        )

        repo.save_event(event1)

        # 更新
        event2 = PolicyEvent(
            event_date=event_date,
            level=PolicyLevel.P2,
            title="原标题",
            description="新描述",
            evidence_url="https://example.com/1"
        )

        saved = repo.save_event(event2)

        # 验证更新成功
        assert saved.title == "原标题"
        assert saved.level == PolicyLevel.P2
        assert saved.description == "新描述"

        # 验证数据库中只有一条记录
        count = repo.get_event_count()
        assert count == 1

    def test_same_day_distinct_events_should_not_merge(self):
        """测试同一天不同事件不应被覆盖"""
        repo = DjangoPolicyRepository()
        event_date = date.today()

        repo.save_event(PolicyEvent(
            event_date=event_date,
            level=PolicyLevel.P1,
            title="事件A",
            description="描述A",
            evidence_url="https://example.com/a"
        ))
        repo.save_event(PolicyEvent(
            event_date=event_date,
            level=PolicyLevel.P2,
            title="事件B",
            description="描述B",
            evidence_url="https://example.com/b"
        ))

        assert repo.get_event_count() == 2

    def test_get_events_in_range(self):
        """测试获取日期范围内的事件"""
        repo = DjangoPolicyRepository()

        today = date.today()
        yesterday = today - timedelta(days=1)
        two_days_ago = today - timedelta(days=2)

        # 创建三个事件
        for i, event_date in enumerate([two_days_ago, yesterday, today]):
            event = PolicyEvent(
                event_date=event_date,
                level=PolicyLevel.P1,
                title=f"事件 {i}",
                description=f"描述 {i}",
                evidence_url=f"https://example.com/{i}"
            )
            repo.save_event(event)

        # 获取范围
        events = repo.get_events_in_range(yesterday, today)

        assert len(events) == 2
        assert events[0].event_date == yesterday
        assert events[1].event_date == today

    def test_get_events_by_level(self):
        """测试按档位获取事件"""
        repo = DjangoPolicyRepository()

        today = date.today()
        yesterday = today - timedelta(days=1)

        # 创建不同档位的事件（使用不同日期避免合并）
        events = [
            (yesterday, PolicyLevel.P0),
            (yesterday, PolicyLevel.P1),
            (today, PolicyLevel.P2),
            (yesterday, PolicyLevel.P2),
        ]
        for event_date, level in events:
            event = PolicyEvent(
                event_date=event_date,
                level=level,
                title=f"{level.value} 事件",
                description="测试描述内容",
                evidence_url="https://example.com"
            )
            repo.save_event(event)

        # 获取 P2 事件
        p2_events = repo.get_events_by_level(PolicyLevel.P2)
        assert len(p2_events) == 2

    def test_get_current_policy_level(self):
        """测试获取当前档位"""
        repo = DjangoPolicyRepository()

        # 无事件时，默认 P0
        current = repo.get_current_policy_level()
        assert current == PolicyLevel.P0

        # 添加事件（需要 gate_effective=True 才能影响档位计算）
        event = PolicyEvent(
            event_date=date.today(),
            level=PolicyLevel.P2,
            title="测试",
            description="这是档位测试的详细描述，至少二十个字符",
            evidence_url="https://example.com"
        )
        repo.save_event(event, gate_effective=True)

        current = repo.get_current_policy_level()
        assert current == PolicyLevel.P2

    def test_is_intervention_active(self):
        """测试干预状态判断"""
        repo = DjangoPolicyRepository()

        assert not repo.is_intervention_active()

        repo.save_event(PolicyEvent(
            event_date=date.today(),
            level=PolicyLevel.P2,
            title="测试",
            description="这是干预档位的详细描述，至少二十个字符",
            evidence_url="https://example.com"
        ), gate_effective=True)

        assert repo.is_intervention_active()

    def test_is_crisis_mode(self):
        """测试危机模式判断"""
        repo = DjangoPolicyRepository()

        assert not repo.is_crisis_mode()

        repo.save_event(PolicyEvent(
            event_date=date.today(),
            level=PolicyLevel.P3,
            title="危机",
            description="这是危机模式的详细描述，至少二十个字符",
            evidence_url="https://example.com"
        ), gate_effective=True)

        assert repo.is_crisis_mode()

    def test_delete_event(self):
        """测试删除事件"""
        repo = DjangoPolicyRepository()

        event_date = date.today()
        repo.save_event(PolicyEvent(
            event_date=event_date,
            level=PolicyLevel.P1,
            title="测试",
            description="测试",
            evidence_url="https://example.com"
        ))

        assert repo.get_event_by_date(event_date) is not None

        # 删除
        success = repo.delete_event(event_date)
        assert success

        assert repo.get_event_by_date(event_date) is None

    def test_get_policy_level_stats(self):
        """测试档位统计"""
        repo = DjangoPolicyRepository()

        today = date.today()
        yesterday = today - timedelta(days=1)
        two_days_ago = today - timedelta(days=2)
        three_days_ago = today - timedelta(days=3)
        four_days_ago = today - timedelta(days=4)

        # 创建不同档位的事件（使用不同日期避免合并）
        levels_and_dates = [
            (PolicyLevel.P0, two_days_ago),
            (PolicyLevel.P1, three_days_ago),
            (PolicyLevel.P2, yesterday),
            (PolicyLevel.P2, today),
            (PolicyLevel.P2, four_days_ago),
        ]
        for level, event_date in levels_and_dates:
            repo.save_event(PolicyEvent(
                event_date=event_date,
                level=level,
                title=f"{level.value}",
                description="测试描述内容",
                evidence_url="https://example.com"
            ))

        stats = repo.get_policy_level_stats()

        assert stats['total'] == 5
        assert stats['by_level']['P2']['count'] == 3
        assert stats['by_level']['P0']['count'] == 1


@pytest.mark.django_db
class TestCreatePolicyEventUseCase:
    """测试创建政策事件用例"""

    def test_create_valid_event(self):
        """测试创建有效事件"""
        repo = DjangoPolicyRepository()
        alert_channel = ConsoleAlertChannel()

        use_case = CreatePolicyEventUseCase(
            event_store=repo,
            alert_service=alert_channel
        )

        input_data = CreatePolicyEventInput(
            event_date=date.today(),
            level=PolicyLevel.P2,
            title="央行降准",
            description="中国人民银行决定下调存款准备金率 0.5 个百分点",
            evidence_url="https://example.com/news/1"
        )

        output = use_case.execute(input_data)

        assert output.success
        assert output.event is not None
        assert output.event.title == "央行降准"

    def test_create_invalid_event(self):
        """测试创建无效事件"""
        repo = DjangoPolicyRepository()

        use_case = CreatePolicyEventUseCase(event_store=repo)

        input_data = CreatePolicyEventInput(
            event_date=date.today(),
            level=PolicyLevel.P2,
            title="",  # 空标题
            description="描述",
            evidence_url="https://example.com"
        )

        output = use_case.execute(input_data)

        assert not output.success
        assert len(output.errors) > 0


@pytest.mark.django_db
class TestGetPolicyStatusUseCase:
    """测试获取政策状态用例"""

    def test_get_status_without_events(self):
        """测试无事件时的状态"""
        repo = DjangoPolicyRepository()
        use_case = GetPolicyStatusUseCase(event_store=repo)

        status = use_case.execute()

        assert status.current_level == PolicyLevel.P0
        assert not status.is_intervention_active
        assert not status.is_crisis_mode

    def test_get_status_with_p2_event(self):
        """测试 P2 事件的状态"""
        repo = DjangoPolicyRepository()

        repo.save_event(PolicyEvent(
            event_date=date.today(),
            level=PolicyLevel.P2,
            title="干预政策",
            description="测试",
            evidence_url="https://example.com"
        ), gate_effective=True)

        use_case = GetPolicyStatusUseCase(event_store=repo)
        status = use_case.execute()

        assert status.current_level == PolicyLevel.P2
        assert status.is_intervention_active
        assert not status.is_crisis_mode
        assert status.response_config.cash_adjustment == 20.0


@pytest.mark.django_db
class TestUpdateAndDeleteUseCases:
    """测试更新和删除用例"""

    def test_update_event(self):
        """测试更新事件"""
        repo = DjangoPolicyRepository()

        event_date = date.today()
        repo.save_event(PolicyEvent(
            event_date=event_date,
            level=PolicyLevel.P1,
            title="原标题",
            description="原描述",
            evidence_url="https://example.com/1"
        ))

        use_case = UpdatePolicyEventUseCase(event_store=repo)
        output = use_case.execute(
            event_date=event_date,
            level=PolicyLevel.P2,
            title="新标题",
            description="这是一个新的描述内容，长度超过二十个字符以通过验证",
            evidence_url="https://example.com/2"
        )

        assert output.success
        assert output.event.title == "新标题"

    def test_delete_event(self):
        """测试删除事件"""
        repo = DjangoPolicyRepository()

        event_date = date.today()
        repo.save_event(PolicyEvent(
            event_date=event_date,
            level=PolicyLevel.P1,
            title="测试",
            description="测试",
            evidence_url="https://example.com"
        ))

        use_case = DeletePolicyEventUseCase(event_store=repo)
        success, message = use_case.execute(event_date)

        assert success
        assert "已删除" in message
        assert repo.get_event_by_date(event_date) is None
