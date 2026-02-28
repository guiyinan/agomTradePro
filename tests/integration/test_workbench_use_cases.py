"""
Integration tests for Policy Workbench use cases.

Tests the interaction between use cases, repositories, and models.
"""

import pytest
from datetime import date, datetime, timezone, timedelta
from django.contrib.auth.models import User

from apps.policy.domain.entities import PolicyLevel, EventType, GateLevel
from apps.policy.infrastructure.models import (
    PolicyLog,
    PolicyIngestionConfig,
    SentimentGateConfig,
    GateActionAuditLog,
)
from apps.policy.infrastructure.repositories import (
    DjangoPolicyRepository,
    WorkbenchRepository,
)
from apps.policy.application.use_cases import (
    GetWorkbenchSummaryUseCase,
    GetWorkbenchItemsUseCase,
    ApproveEventUseCase,
    RejectEventUseCase,
    RollbackEventUseCase,
    WorkbenchSummaryInput,
    WorkbenchItemsInput,
    ApproveEventInput,
    RejectEventInput,
    RollbackEventInput,
)


@pytest.fixture
def test_user(db):
    """Create a test user."""
    user = User.objects.create_user(username='testuser', password='testpass')
    return user


@pytest.fixture
def policy_repo():
    """Create a policy repository."""
    return DjangoPolicyRepository()


@pytest.fixture
def workbench_repo():
    """Create a workbench repository."""
    return WorkbenchRepository()


@pytest.fixture
def ingestion_config(db):
    """Create ingestion config."""
    config, _ = PolicyIngestionConfig.objects.get_or_create(
        singleton_id=1,
        defaults={
            'auto_approve_enabled': True,
            'auto_approve_threshold': 0.85,
            'p23_sla_hours': 2,
            'normal_sla_hours': 24,
        }
    )
    return config


@pytest.fixture
def gate_config(db):
    """Create sentiment gate config."""
    config, _ = SentimentGateConfig.objects.get_or_create(
        asset_class='all',
        defaults={
            'heat_l1_threshold': 30.0,
            'heat_l2_threshold': 60.0,
            'heat_l3_threshold': 85.0,
            'sentiment_l1_threshold': -0.3,
            'sentiment_l2_threshold': -0.6,
            'sentiment_l3_threshold': -0.8,
            'max_position_cap_l2': 0.7,
            'max_position_cap_l3': 0.3,
            'enabled': True,
        }
    )
    return config


@pytest.mark.django_db
class TestGetCurrentPolicyLevel:
    """Tests for get_current_policy_level repository method."""

    def test_only_effective_events_count(self, policy_repo, test_user):
        """Only effective policy events should affect policy level."""
        # Create an effective P2 event
        PolicyLog.objects.create(
            event_date=date.today() - timedelta(days=1),
            level='P2',
            title='Effective P2 Event',
            description='This event is effective',
            evidence_url='https://example.com/1',
            event_type='policy',
            gate_effective=True,
            effective_at=datetime.now(timezone.utc),
            effective_by=test_user,
        )

        # Create a non-effective P3 event (should be ignored)
        PolicyLog.objects.create(
            event_date=date.today(),
            level='P3',
            title='Non-effective P3 Event',
            description='This event is not effective',
            evidence_url='https://example.com/2',
            event_type='policy',
            gate_effective=False,
        )

        level = policy_repo.get_current_policy_level()
        assert level == PolicyLevel.P2

    def test_hotspot_events_affect_policy_level(self, policy_repo, test_user):
        """Hotspot/sentiment events SHOULD affect P0-P3 (new behavior)."""
        # Create an effective hotspot event
        PolicyLog.objects.create(
            event_date=date.today(),
            level='P3',  # Even with P3 level
            title='Hotspot Event',
            description='This is a hotspot event',
            evidence_url='https://example.com/hotspot',
            event_type='hotspot',
            gate_effective=True,
            effective_at=datetime.now(timezone.utc),
            effective_by=test_user,
            heat_score=90.0,
            sentiment_score=-0.8,
            gate_level='L3',
        )

        level = policy_repo.get_current_policy_level()
        # Should be P3 because ALL effective events now affect policy level
        assert level == PolicyLevel.P3

    def test_no_events_returns_p0(self, policy_repo):
        """When no events exist, return P0."""
        level = policy_repo.get_current_policy_level()
        assert level == PolicyLevel.P0

    def test_effective_events_ordered_by_date(self, policy_repo, test_user):
        """Effective events should be ordered by date DESC."""
        # Create older effective P1 event
        PolicyLog.objects.create(
            event_date=date.today() - timedelta(days=3),
            level='P1',
            title='Older P1 Event',
            description='This is older',
            evidence_url='https://example.com/old',
            event_type='policy',
            gate_effective=True,
            effective_at=datetime.now(timezone.utc) - timedelta(days=2),
            effective_by=test_user,
        )

        # Create newer effective P2 event
        PolicyLog.objects.create(
            event_date=date.today() - timedelta(days=1),
            level='P2',
            title='Newer P2 Event',
            description='This is newer',
            evidence_url='https://example.com/new',
            event_type='policy',
            gate_effective=True,
            effective_at=datetime.now(timezone.utc),
            effective_by=test_user,
        )

        level = policy_repo.get_current_policy_level()
        assert level == PolicyLevel.P2  # Newer event


@pytest.mark.django_db
class TestGetWorkbenchSummaryUseCase:
    """Tests for GetWorkbenchSummaryUseCase."""

    def test_summary_returns_policy_level(self, test_user, ingestion_config, gate_config):
        """Summary should return correct policy level."""
        # Create an effective policy event
        PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Test Policy Event',
            description='Test description',
            evidence_url='https://example.com/test',
            event_type='policy',
            gate_effective=True,
            effective_at=datetime.now(timezone.utc),
            effective_by=test_user,
        )

        use_case = GetWorkbenchSummaryUseCase()
        output = use_case.execute(WorkbenchSummaryInput())

        assert output.success is True
        assert output.summary.policy_level == PolicyLevel.P2

    def test_summary_counts_pending_review(self, ingestion_config, gate_config):
        """Summary should count pending review events."""
        # Create pending review events
        for i in range(3):
            PolicyLog.objects.create(
                event_date=date.today(),
                level='P1',
                title=f'Pending Event {i}',
                description='Test description',
                evidence_url=f'https://example.com/pending/{i}',
                event_type='policy',
                audit_status='pending_review',
            )

        use_case = GetWorkbenchSummaryUseCase()
        output = use_case.execute(WorkbenchSummaryInput())

        assert output.success is True
        assert output.summary.pending_review_count == 3


@pytest.mark.django_db
class TestGetWorkbenchItemsUseCase:
    """Tests for GetWorkbenchItemsUseCase."""

    def test_pending_tab_returns_pending_events(self):
        """Pending tab should return only pending review events."""
        # Create pending event
        PolicyLog.objects.create(
            event_date=date.today(),
            level='P1',
            title='Pending Event',
            description='Test description',
            evidence_url='https://example.com/pending',
            event_type='policy',
            audit_status='pending_review',
        )

        # Create effective event
        PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Effective Event',
            description='Test description',
            evidence_url='https://example.com/effective',
            event_type='policy',
            gate_effective=True,
            audit_status='manual_approved',
        )

        use_case = GetWorkbenchItemsUseCase()
        output = use_case.execute(WorkbenchItemsInput(tab='pending'))

        assert output.success is True
        assert output.total == 1
        assert output.items[0]['title'] == 'Pending Event'

    def test_effective_tab_returns_effective_events(self):
        """Effective tab should return only effective events."""
        # Create pending event
        PolicyLog.objects.create(
            event_date=date.today(),
            level='P1',
            title='Pending Event',
            description='Test description',
            evidence_url='https://example.com/pending',
            event_type='policy',
            audit_status='pending_review',
        )

        # Create effective event
        PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Effective Event',
            description='Test description',
            evidence_url='https://example.com/effective',
            event_type='policy',
            gate_effective=True,
        )

        use_case = GetWorkbenchItemsUseCase()
        output = use_case.execute(WorkbenchItemsInput(tab='effective'))

        assert output.success is True
        assert output.total == 1
        assert output.items[0]['title'] == 'Effective Event'

    def test_filter_by_event_type(self):
        """Should filter by event type."""
        # Create policy event
        PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Policy Event',
            description='Test description',
            evidence_url='https://example.com/policy',
            event_type='policy',
        )

        # Create hotspot event
        PolicyLog.objects.create(
            event_date=date.today(),
            level='P1',
            title='Hotspot Event',
            description='Test description',
            evidence_url='https://example.com/hotspot',
            event_type='hotspot',
            heat_score=70.0,
        )

        use_case = GetWorkbenchItemsUseCase()
        output = use_case.execute(WorkbenchItemsInput(tab='all', event_type='hotspot'))

        assert output.success is True
        assert output.total == 1
        assert output.items[0]['event_type'] == 'hotspot'


@pytest.mark.django_db
class TestApproveEventUseCase:
    """Tests for ApproveEventUseCase."""

    def test_approve_sets_effective(self, test_user):
        """Approve should set gate_effective=True."""
        event = PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Test Event',
            description='Test description',
            evidence_url='https://example.com/test',
            event_type='policy',
            audit_status='pending_review',
        )

        use_case = ApproveEventUseCase()
        output = use_case.execute(ApproveEventInput(
            event_id=event.id,
            user_id=test_user.id,
            reason='Test approval'
        ))

        assert output.success is True

        event.refresh_from_db()
        assert event.gate_effective is True
        assert event.effective_by == test_user
        assert event.audit_status == 'manual_approved'

    def test_approve_creates_audit_log(self, test_user):
        """Approve should create an audit log."""
        event = PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Test Event',
            description='Test description',
            evidence_url='https://example.com/test',
            event_type='policy',
            audit_status='pending_review',
        )

        use_case = ApproveEventUseCase()
        use_case.execute(ApproveEventInput(
            event_id=event.id,
            user_id=test_user.id,
            reason='Test approval'
        ))

        audit_log = GateActionAuditLog.objects.filter(
            event=event,
            action='approve'
        ).first()

        assert audit_log is not None
        assert audit_log.operator == test_user


@pytest.mark.django_db
class TestRejectEventUseCase:
    """Tests for RejectEventUseCase."""

    def test_reject_requires_reason(self, test_user):
        """Reject should require a reason."""
        event = PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Test Event',
            description='Test description',
            evidence_url='https://example.com/test',
            event_type='policy',
            audit_status='pending_review',
        )

        use_case = RejectEventUseCase()
        output = use_case.execute(RejectEventInput(
            event_id=event.id,
            user_id=test_user.id,
            reason=''  # Empty reason
        ))

        assert output.success is False
        assert '不能为空' in output.error

    def test_reject_updates_status(self, test_user):
        """Reject should update audit_status."""
        event = PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Test Event',
            description='Test description',
            evidence_url='https://example.com/test',
            event_type='policy',
            audit_status='pending_review',
        )

        use_case = RejectEventUseCase()
        output = use_case.execute(RejectEventInput(
            event_id=event.id,
            user_id=test_user.id,
            reason='Test rejection reason'
        ))

        assert output.success is True

        event.refresh_from_db()
        assert event.audit_status == 'rejected'


@pytest.mark.django_db
class TestRollbackEventUseCase:
    """Tests for RollbackEventUseCase."""

    def test_rollback_sets_gate_not_effective(self, test_user):
        """Rollback should set gate_effective=False."""
        event = PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Test Event',
            description='Test description',
            evidence_url='https://example.com/test',
            event_type='policy',
            gate_effective=True,
            effective_at=datetime.now(timezone.utc),
            effective_by=test_user,
        )

        use_case = RollbackEventUseCase()
        output = use_case.execute(RollbackEventInput(
            event_id=event.id,
            user_id=test_user.id,
            reason='Test rollback reason'
        ))

        assert output.success is True

        event.refresh_from_db()
        assert event.gate_effective is False
        assert 'Test rollback reason' in event.rollback_reason

    def test_rollback_requires_reason(self, test_user):
        """Rollback should require a reason."""
        event = PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Test Event',
            description='Test description',
            evidence_url='https://example.com/test',
            event_type='policy',
            gate_effective=True,
        )

        use_case = RollbackEventUseCase()
        output = use_case.execute(RollbackEventInput(
            event_id=event.id,
            user_id=test_user.id,
            reason=''
        ))

        assert output.success is False
        assert '不能为空' in output.error
