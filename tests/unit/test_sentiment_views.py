"""
Unit tests for Sentiment Interface Views.

Tests for API and page views in the sentiment module.
"""

import uuid
from datetime import date, datetime
from unittest.mock import MagicMock, Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.sentiment.interface.views import (
    SentimentAnalyzePageView,
    SentimentAnalyzeView,
    SentimentBatchAnalyzeView,
    SentimentCacheClearView,
    SentimentDashboardView,
    SentimentHealthView,
    SentimentIndexRangeView,
    SentimentIndexRecentView,
    SentimentIndexView,
)


def _make_test_user():
    User = get_user_model()
    return User.objects.create_user(
        username=f"testuser_{uuid.uuid4().hex[:8]}",
        password='testpass'
    )


class TestSentimentAnalyzeView(TestCase):
    """Tests for SentimentAnalyzeView API"""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = SentimentAnalyzeView.as_view()
        self.user = _make_test_user()

    @patch('apps.sentiment.interface.views.analyze_sentiment_text')
    def test_analyze_text_success(self, mock_analyze_text):
        """Test successful text analysis"""
        mock_analyze_text.return_value = {
            'text': '测试文本',
            'sentiment_score': 1.5,
            'category': 'POSITIVE',
        }

        # Create request
        request = self.factory.post(
            '/sentiment/api/analyze/',
            {'text': '测试文本'},
            content_type='application/json'
        )
        force_authenticate(request, user=self.user)

        # Get response
        response = self.view(request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['sentiment_score'] == 1.5
        assert response.data['category'] == 'POSITIVE'

    def test_analyze_text_missing_text_field(self):
        """Test request with missing text field"""
        request = self.factory.post(
            '/sentiment/api/analyze/',
            {},
            content_type='application/json'
        )
        force_authenticate(request, user=self.user)
        response = self.view(request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_analyze_text_with_cache_hit(self):
        """Test analysis returns cached result when available"""
        with patch(
            'apps.sentiment.interface.views.analyze_sentiment_text',
            return_value={
                'text': '测试文本',
                'sentiment_score': 1.0,
                'category': 'POSITIVE',
            },
        ):
            request = self.factory.post(
                '/sentiment/api/analyze/',
                {'text': '测试文本', 'use_cache': True},
                content_type='application/json'
            )
            force_authenticate(request, user=self.user)
            response = self.view(request)
            assert response.status_code == status.HTTP_200_OK
            assert response.data['sentiment_score'] == 1.0


class TestSentimentBatchAnalyzeView(TestCase):
    """Tests for SentimentBatchAnalyzeView API"""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = SentimentBatchAnalyzeView.as_view()
        self.user = _make_test_user()

    @patch('apps.sentiment.interface.views.analyze_sentiment_batch')
    def test_batch_analyze_success(self, mock_analyze_batch):
        """Test successful batch analysis"""
        mock_analyze_batch.return_value = {
            'results': [
                {'text': '文本1', 'sentiment_score': 1.0, 'category': 'POSITIVE'},
                {'text': '文本2', 'sentiment_score': -0.5, 'category': 'NEGATIVE'},
            ],
            'total': 2,
        }

        request = self.factory.post(
            '/sentiment/api/batch-analyze/',
            {'texts': ['文本1', '文本2']},
            content_type='application/json'
        )
        force_authenticate(request, user=self.user)
        response = self.view(request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['total'] == 2
        assert len(response.data['results']) == 2

    def test_batch_analyze_missing_texts_field(self):
        """Test batch analyze with missing texts field"""
        request = self.factory.post(
            '/sentiment/api/batch-analyze/',
            {},
            content_type='application/json'
        )
        force_authenticate(request, user=self.user)
        response = self.view(request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestSentimentIndexView(TestCase):
    """Tests for SentimentIndexView API"""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = SentimentIndexView.as_view()
        self.user = _make_test_user()

    @patch('apps.sentiment.interface.views.get_sentiment_index_payload')
    def test_get_latest_index(self, mock_get_index):
        """Test getting latest sentiment index"""
        mock_get_index.return_value = {'date': '2024-01-01', 'composite_index': 0.5}

        request = self.factory.get('/sentiment/api/index/')
        force_authenticate(request, user=self.user)
        response = self.view(request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['date'] == '2024-01-01'

    @patch('apps.sentiment.interface.views.get_sentiment_index_payload')
    def test_get_index_by_date(self, mock_get_index):
        """Test getting sentiment index by specific date"""
        mock_get_index.return_value = {'date': '2024-01-15', 'composite_index': 0.3}

        request = self.factory.get('/sentiment/api/index/?date=2024-01-15')
        force_authenticate(request, user=self.user)
        response = self.view(request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['date'] == '2024-01-15'

    @patch('apps.sentiment.interface.views.get_sentiment_index_payload')
    def test_get_index_not_found(self, mock_get_index):
        """Test getting index when not found"""
        mock_get_index.return_value = None

        request = self.factory.get('/sentiment/api/index/')
        force_authenticate(request, user=self.user)
        response = self.view(request)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_index_invalid_date_format(self):
        """Test getting index with invalid date format"""
        request = self.factory.get('/sentiment/api/index/?date=invalid')
        force_authenticate(request, user=self.user)
        response = self.view(request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestSentimentIndexRangeView(TestCase):
    """Tests for SentimentIndexRangeView API"""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = SentimentIndexRangeView.as_view()
        self.user = _make_test_user()

    @patch('apps.sentiment.interface.views.get_sentiment_index_range_payload')
    def test_get_index_range(self, mock_get_range):
        """Test getting index range"""
        mock_get_range.return_value = {
            'indices': [
                {'date': '2024-01-01', 'composite_index': 0.1},
                {'date': '2024-01-02', 'composite_index': 0.2},
                {'date': '2024-01-03', 'composite_index': 0.3},
            ],
            'total': 3,
        }

        request = self.factory.get(
            '/sentiment/api/index/range/?start_date=2024-01-01&end_date=2024-01-03'
        )
        force_authenticate(request, user=self.user)
        response = self.view(request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['total'] == 3

    def test_get_index_range_missing_params(self):
        """Test getting range with missing parameters"""
        request = self.factory.get('/sentiment/api/index/range/?start_date=2024-01-01')
        force_authenticate(request, user=self.user)
        response = self.view(request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestSentimentIndexRecentView(TestCase):
    """Tests for SentimentIndexRecentView API"""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = SentimentIndexRecentView.as_view()
        self.user = _make_test_user()

    @patch('apps.sentiment.interface.views.get_recent_sentiment_indices_payload')
    def test_get_recent_indices_default_days(self, mock_get_recent):
        """Test getting recent indices with default days (30)"""
        mock_get_recent.return_value = {'indices': [], 'total': 0}

        request = self.factory.get('/sentiment/api/index/recent/')
        force_authenticate(request, user=self.user)
        response = self.view(request)

        assert response.status_code == status.HTTP_200_OK
        mock_get_recent.assert_called_once_with(days=30)

    @patch('apps.sentiment.interface.views.get_recent_sentiment_indices_payload')
    def test_get_recent_indices_custom_days(self, mock_get_recent):
        """Test getting recent indices with custom days"""
        mock_get_recent.return_value = {'indices': [], 'total': 0}

        request = self.factory.get('/sentiment/api/index/recent/?days=7')
        force_authenticate(request, user=self.user)
        response = self.view(request)

        assert response.status_code == status.HTTP_200_OK
        mock_get_recent.assert_called_once_with(days=7)

    @patch('apps.sentiment.interface.views.get_recent_sentiment_indices_payload')
    def test_get_recent_indices_clamps_days(self, mock_get_recent):
        """Test that days parameter is clamped to valid range"""
        mock_get_recent.return_value = {'indices': [], 'total': 0}

        # Test exceeding maximum
        request = self.factory.get('/sentiment/api/index/recent/?days=400')
        force_authenticate(request, user=self.user)
        response = self.view(request)
        assert response.status_code == status.HTTP_200_OK
        mock_get_recent.assert_called_once_with(days=30)

        # Test below minimum
        request2 = self.factory.get('/sentiment/api/index/recent/?days=0')
        force_authenticate(request2, user=self.user)
        response2 = self.view(request2)
        assert response2.status_code == status.HTTP_200_OK


class TestSentimentHealthView(TestCase):
    """Tests for SentimentHealthView API"""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = SentimentHealthView.as_view()
        self.user = _make_test_user()

    @patch('apps.sentiment.interface.views.get_sentiment_health_payload')
    def test_health_check_healthy(self, mock_health_payload):
        """Test health check when AI provider is available"""
        mock_health_payload.return_value = {
            'status': 'healthy',
            'ai_provider_available': True,
            'cache_count': 100,
            'latest_index_date': '2024-01-01',
        }

        request = self.factory.get('/sentiment/api/health/')
        force_authenticate(request, user=self.user)
        response = self.view(request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == 'healthy'
        assert response.data['ai_provider_available'] is True

    @patch('apps.sentiment.interface.views.get_sentiment_health_payload')
    def test_health_check_degraded(self, mock_health_payload):
        """Test health check when no AI provider available"""
        mock_health_payload.return_value = {
            'status': 'degraded',
            'ai_provider_available': False,
            'cache_count': 0,
            'latest_index_date': None,
        }

        request = self.factory.get('/sentiment/api/health/')
        force_authenticate(request, user=self.user)
        response = self.view(request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == 'degraded'
        assert response.data['ai_provider_available'] is False


class TestSentimentCacheClearView(TestCase):
    """Tests for SentimentCacheClearView API"""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = SentimentCacheClearView.as_view()
        self.user = _make_test_user()

    @patch('apps.sentiment.interface.views.clear_sentiment_cache_payload')
    def test_clear_cache(self, mock_clear_cache):
        """Test clearing cache"""
        mock_clear_cache.return_value = {
            'success': True,
            'message': '已清除 42 条缓存记录',
        }

        request = self.factory.post('/sentiment/api/cache/clear/')
        force_authenticate(request, user=self.user)
        response = self.view(request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['success'] is True
        assert '42' in response.data['message']


class TestSentimentDashboardView(TestCase):
    """Tests for SentimentDashboardView page"""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = _make_test_user()

    @patch('apps.sentiment.interface.views.get_sentiment_dashboard_context')
    def test_dashboard_authenticated(self, mock_dashboard_context):
        """Test dashboard page for authenticated user"""
        mock_dashboard_context.return_value = {
            'latest_index': {'date': '2024-01-01', 'composite_index': 0.5},
            'recent_indices': [{'date': '2024-01-01', 'composite_index': 0.5}],
            'ai_available': True,
        }

        view = SentimentDashboardView.as_view()
        request = self.factory.get('/sentiment/dashboard/')
        request.user = self.user

        response = view(request)

        assert response.status_code == 200
        assert 'latest_index' in response.context_data

    def test_dashboard_requires_login(self):
        """Test dashboard requires authentication"""
        view = SentimentDashboardView.as_view()
        request = self.factory.get('/sentiment/dashboard/')
        request.user = Mock(is_authenticated=False)

        response = view(request)
        assert response.status_code == 302  # Redirect to login


class TestSentimentAnalyzePageView(TestCase):
    """Tests for SentimentAnalyzePageView page"""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = _make_test_user()

    @patch('apps.sentiment.interface.views.get_sentiment_analyze_page_context')
    def test_analyze_page_authenticated(self, mock_page_context):
        """Test analyze page for authenticated user"""
        mock_page_context.return_value = {'ai_available': True}

        view = SentimentAnalyzePageView.as_view()
        request = self.factory.get('/sentiment/analyze/')
        request.user = self.user

        response = view(request)

        assert response.status_code == 200
        assert response.context_data['ai_available'] is True

    def test_analyze_page_handles_exception(self):
        """Test analyze page handles exceptions gracefully"""
        with patch('apps.sentiment.interface.views.get_sentiment_analyze_page_context') as mock_page_context:
            mock_page_context.side_effect = Exception("Test error")

            view = SentimentAnalyzePageView.as_view()
            request = self.factory.get('/sentiment/analyze/')
            request.user = self.user

            response = view(request)
            assert response.status_code == 200
            assert response.context_data['ai_available'] is False


class TestSentimentTemplateRendering(TestCase):
    """Tests for sentiment template rendering - catches NoReverseMatch errors"""

    def test_analyze_template_renders_without_url_error(self):
        """
        Regression test: Template must use valid URL names.

        Previously failed with NoReverseMatch when template used
        'sentiment:api_analyze' but route was renamed to 'analyze'.
        """
        from django.template.loader import render_to_string

        # This should not raise NoReverseMatch
        try:
            render_to_string('sentiment/analyze.html', {
                'ai_available': True,
                'ai_providers': [],
            })
        except Exception as e:
            if 'NoReverseMatch' in str(type(e).__name__):
                pytest.fail(f"Template uses invalid URL name: {e}")
            raise
