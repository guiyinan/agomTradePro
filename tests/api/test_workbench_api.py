"""
API Contract Tests for Policy Workbench.

Tests the API endpoints for correct response structure and status codes.
"""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APIClient

from apps.policy.infrastructure.models import (
    PolicyIngestionConfig,
    PolicyLog,
    RSSFetchLog,
    RSSSourceConfigModel,
    SentimentGateConfig,
)


@pytest.fixture
def api_client():
    """Create an API client."""
    return APIClient()


@pytest.fixture
def authenticated_client(api_client, db):
    """Create an authenticated API client."""
    user = User.objects.create_user(username='testuser', password='testpass')
    api_client.force_authenticate(user=user)
    return api_client, user


@pytest.fixture
def ingestion_config(db):
    """Create ingestion config."""
    config, _ = PolicyIngestionConfig.objects.get_or_create(
        singleton_id=1,
        defaults={
            'auto_approve_enabled': True,
            'auto_approve_threshold': 0.85,
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
            'enabled': True,
        }
    )
    return config


@pytest.mark.django_db
class TestWorkbenchSummaryAPI:
    """Tests for /api/policy/workbench/summary/ endpoint."""

    def test_summary_requires_authentication(self, api_client):
        """Unauthenticated request should return 403 (DRF uses 403 for IsAuthenticated)."""
        response = api_client.get('/api/policy/workbench/summary/')
        # DRF returns 403 Forbidden for IsAuthenticated when not logged in
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    def test_summary_returns_correct_structure(self, authenticated_client, ingestion_config, gate_config):
        """Summary should return correct data structure."""
        client, user = authenticated_client

        response = client.get('/api/policy/workbench/summary/')

        assert response.status_code == status.HTTP_200_OK
        data = response.data

        # Check required fields
        assert 'policy_level' in data
        assert 'global_heat_score' in data
        assert 'global_sentiment_score' in data
        assert 'global_gate_level' in data
        assert 'pending_review_count' in data
        assert 'sla_exceeded_count' in data
        assert 'effective_today_count' in data

    def test_summary_returns_correct_policy_level(self, authenticated_client, ingestion_config, gate_config):
        """Summary should return correct policy level from effective events."""
        client, user = authenticated_client

        # Create an effective policy event
        PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Test Policy Event',
            description='Test description',
            evidence_url='https://example.com/test',
            event_type='policy',
            gate_effective=True,
            effective_at=datetime.now(UTC),
            effective_by=user,
        )

        response = client.get('/api/policy/workbench/summary/')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['policy_level'] == 'P2'


@pytest.mark.django_db
class TestWorkbenchItemsAPI:
    """Tests for /api/policy/workbench/items/ endpoint."""

    def test_items_requires_authentication(self, api_client):
        """Unauthenticated request should return 401 or 403."""
        response = api_client.get('/api/policy/workbench/items/')
        # DRF can return 403 Forbidden instead of 401 Unauthorized
        # depending on authentication configuration
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    def test_items_returns_correct_structure(self, authenticated_client):
        """Items should return correct data structure."""
        client, user = authenticated_client

        response = client.get('/api/policy/workbench/items/')

        assert response.status_code == status.HTTP_200_OK
        data = response.data

        assert 'success' in data
        assert 'items' in data
        assert 'total' in data
        assert isinstance(data['items'], list)

    def test_items_filter_by_event_type(self, authenticated_client):
        """Should filter items by event_type."""
        client, user = authenticated_client

        # Create policy event
        PolicyLog.objects.create(
            event_date=date.today(),
            level='P1',
            title='Policy Event',
            description='Test',
            evidence_url='https://example.com/policy',
            event_type='policy',
        )

        # Create hotspot event
        PolicyLog.objects.create(
            event_date=date.today(),
            level='P1',
            title='Hotspot Event',
            description='Test',
            evidence_url='https://example.com/hotspot',
            event_type='hotspot',
            heat_score=70.0,
        )

        response = client.get('/api/policy/workbench/items/?event_type=hotspot')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['total'] == 1
        assert response.data['items'][0]['event_type'] == 'hotspot'

    def test_items_filter_by_level(self, authenticated_client):
        """Should filter items by level."""
        client, user = authenticated_client

        PolicyLog.objects.create(
            event_date=date.today(),
            level='P1',
            title='P1 Event',
            description='Test',
            evidence_url='https://example.com/p1',
            event_type='policy',
        )

        PolicyLog.objects.create(
            event_date=date.today(),
            level='P3',
            title='P3 Event',
            description='Test',
            evidence_url='https://example.com/p3',
            event_type='policy',
        )

        response = client.get('/api/policy/workbench/items/?level=P3')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['total'] == 1
        assert response.data['items'][0]['level'] == 'P3'

    def test_items_pagination(self, authenticated_client):
        """Should support pagination."""
        client, user = authenticated_client

        # Create multiple events
        for i in range(10):
            PolicyLog.objects.create(
                event_date=date.today(),
                level='P1',
                title=f'Event {i}',
                description='Test',
                evidence_url=f'https://example.com/{i}',
                event_type='policy',
            )

        response = client.get('/api/policy/workbench/items/?limit=5&offset=0')

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['items']) == 5
        assert response.data['total'] == 10


@pytest.mark.django_db
class TestApproveEventAPI:
    """Tests for /api/policy/workbench/items/{id}/approve/ endpoint."""

    def test_approve_requires_authentication(self, api_client):
        """Unauthenticated request should return 401 or 403."""
        response = api_client.post('/api/policy/workbench/items/1/approve/')
        # DRF can return 403 Forbidden instead of 401 Unauthorized
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    def test_approve_nonexistent_event(self, authenticated_client):
        """Approve nonexistent event should return error."""
        client, user = authenticated_client

        response = client.post('/api/policy/workbench/items/99999/approve/', {})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['success'] is False

    def test_approve_success(self, authenticated_client):
        """Successful approve should return event_id."""
        client, user = authenticated_client

        event = PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Test Event',
            description='Test',
            evidence_url='https://example.com/test',
            event_type='policy',
            audit_status='pending_review',
        )

        response = client.post(f'/api/policy/workbench/items/{event.id}/approve/', {
            'reason': 'Test approval'
        })

        assert response.status_code == status.HTTP_200_OK
        assert response.data['success'] is True
        assert response.data['event_id'] == event.id


@pytest.mark.django_db
class TestRejectEventAPI:
    """Tests for /api/policy/workbench/items/{id}/reject/ endpoint."""

    def test_reject_requires_reason(self, authenticated_client):
        """Reject without reason should return error."""
        client, user = authenticated_client

        event = PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Test Event',
            description='Test',
            evidence_url='https://example.com/test',
            event_type='policy',
            audit_status='pending_review',
        )

        response = client.post(f'/api/policy/workbench/items/{event.id}/reject/', {
            'reason': ''
        })

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['success'] is False

    def test_reject_success(self, authenticated_client):
        """Successful reject should return event_id."""
        client, user = authenticated_client

        event = PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Test Event',
            description='Test',
            evidence_url='https://example.com/test',
            event_type='policy',
            audit_status='pending_review',
        )

        response = client.post(f'/api/policy/workbench/items/{event.id}/reject/', {
            'reason': 'Test rejection reason'
        })

        assert response.status_code == status.HTTP_200_OK
        assert response.data['success'] is True


@pytest.mark.django_db
class TestRollbackEventAPI:
    """Tests for /api/policy/workbench/items/{id}/rollback/ endpoint."""

    def test_rollback_requires_reason(self, authenticated_client):
        """Rollback without reason should return error."""
        client, user = authenticated_client

        event = PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Test Event',
            description='Test',
            evidence_url='https://example.com/test',
            event_type='policy',
            gate_effective=True,
        )

        response = client.post(f'/api/policy/workbench/items/{event.id}/rollback/', {
            'reason': ''
        })

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['success'] is False

    def test_rollback_success(self, authenticated_client):
        """Successful rollback should return event_id."""
        client, user = authenticated_client

        event = PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Test Event',
            description='Test',
            evidence_url='https://example.com/test',
            event_type='policy',
            gate_effective=True,
            effective_at=datetime.now(UTC),
            effective_by=user,
        )

        response = client.post(f'/api/policy/workbench/items/{event.id}/rollback/', {
            'reason': 'Test rollback reason'
        })

        assert response.status_code == status.HTTP_200_OK
        assert response.data['success'] is True

        # Verify gate_effective is now False
        event.refresh_from_db()
        assert event.gate_effective is False


@pytest.mark.django_db
class TestSentimentGateStateAPI:
    """Tests for /api/policy/sentiment-gate/state/ endpoint."""

    def test_gate_state_requires_authentication(self, api_client):
        """Unauthenticated request should return 401 or 403."""
        response = api_client.get('/api/policy/sentiment-gate/state/')
        # DRF can return 403 Forbidden instead of 401 Unauthorized
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    def test_gate_state_returns_correct_structure(self, authenticated_client, gate_config):
        """Gate state should return correct data structure."""
        client, user = authenticated_client

        response = client.get('/api/policy/sentiment-gate/state/')

        assert response.status_code == status.HTTP_200_OK
        data = response.data

        assert 'success' in data
        assert 'asset_class' in data
        assert 'gate_level' in data
        assert 'heat_score' in data
        assert 'sentiment_score' in data
        assert 'max_position_cap' in data
        assert 'thresholds' in data


@pytest.mark.django_db
class TestIngestionConfigAPI:
    """Tests for /api/policy/ingestion-config/ endpoint."""

    def test_get_ingestion_config(self, authenticated_client, ingestion_config):
        """GET should return current config."""
        client, user = authenticated_client

        response = client.get('/api/policy/ingestion-config/')

        assert response.status_code == status.HTTP_200_OK
        assert 'auto_approve_enabled' in response.data
        assert 'auto_approve_threshold' in response.data
        assert 'p23_sla_hours' in response.data

    def test_put_ingestion_config(self, authenticated_client, ingestion_config):
        """PUT should update config."""
        client, user = authenticated_client

        response = client.put('/api/policy/ingestion-config/', {
            'auto_approve_enabled': True,
            'auto_approve_min_level': 'P2',
            'auto_approve_threshold': 0.90,
            'p23_sla_hours': 3,
            'normal_sla_hours': 24,
            'version': 1,
        }, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['success'] is True


@pytest.mark.django_db
class TestSentimentGateConfigAPI:
    """Tests for /api/policy/sentiment-gate-config/ endpoint."""

    def test_put_gate_config_updates_existing_config(self, authenticated_client, gate_config):
        """PUT should update an existing gate config through the interface service."""
        client, user = authenticated_client

        response = client.put('/api/policy/sentiment-gate-config/', {
            'asset_class': 'all',
            'heat_l1_threshold': 35.0,
            'heat_l2_threshold': 65.0,
            'heat_l3_threshold': 90.0,
            'sentiment_l1_threshold': -0.25,
            'sentiment_l2_threshold': -0.55,
            'sentiment_l3_threshold': -0.75,
            'max_position_cap_l2': 0.6,
            'max_position_cap_l3': 0.3,
            'enabled': True,
        }, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['success'] is True
        assert response.data['asset_class'] == 'all'
        assert response.data['created'] is False

        gate_config.refresh_from_db()
        assert gate_config.heat_l1_threshold == 35.0
        assert gate_config.version == response.data['version']
        assert gate_config.updated_by == user


@pytest.mark.django_db
class TestWorkbenchBootstrapAPI:
    """Tests for /api/policy/workbench/bootstrap/ endpoint."""

    def test_bootstrap_returns_sources_and_fetch_status(
        self,
        authenticated_client,
        ingestion_config,
        gate_config,
    ):
        """Bootstrap should include active sources and recent fetch errors."""
        client, user = authenticated_client
        source = RSSSourceConfigModel.objects.create(
            name='Policy Feed',
            url='https://example.com/rss',
            category='other',
            is_active=True,
        )
        RSSFetchLog.objects.create(
            source=source,
            status='error',
            items_count=10,
            new_items_count=0,
            error_message='upstream timeout',
        )

        response = client.get('/api/policy/workbench/bootstrap/')

        assert response.status_code == status.HTTP_200_OK
        payload = response.data
        assert payload['success'] is True
        assert payload['filter_options']['sources'][0]['name'] == 'Policy Feed'
        assert payload['fetch_status']['last_fetch_status'] == 'error'
        assert payload['fetch_status']['recent_fetch_errors'][0]['source__name'] == 'Policy Feed'


@pytest.mark.django_db
class TestWorkbenchItemDetailAPI:
    """Tests for /api/policy/workbench/items/{id}/ endpoint."""

    def test_item_detail_returns_related_names(self, authenticated_client):
        """Detail should resolve related RSS source and user names."""
        client, user = authenticated_client
        source = RSSSourceConfigModel.objects.create(
            name='Detail Feed',
            url='https://example.com/detail-rss',
            category='other',
            is_active=True,
        )
        event = PolicyLog.objects.create(
            event_date=date.today(),
            level='P2',
            title='Detailed Event',
            description='Detail payload',
            evidence_url='https://example.com/detail',
            event_type='policy',
            gate_effective=True,
            effective_at=datetime.now(UTC),
            effective_by=user,
            audit_status='manual_approved',
            reviewed_by=user,
            reviewed_at=datetime.now(UTC),
            rss_source=source,
            rss_item_guid='guid-123',
        )

        response = client.get(f'/api/policy/workbench/items/{event.id}/')

        assert response.status_code == status.HTTP_200_OK
        payload = response.data
        assert payload['success'] is True
        assert payload['item']['rss_source_name'] == 'Detail Feed'
        assert payload['item']['effective_by_name'] == user.username
        assert payload['item']['reviewed_by_name'] == user.username
