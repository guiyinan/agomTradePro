"""
E2E-style checks for "my operation logs" flow (Django client based).
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.audit.infrastructure.models import OperationLogModel


def _response_text(response) -> str:
    return response.content.decode("utf-8")


def _assert_my_logs_page_contract(response) -> str:
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")

    content = _response_text(response)
    for fragment in (
        "我的操作记录",
        "查看您的 MCP/SDK 操作历史",
        "筛选条件",
        "操作记录",
        "查询",
        "重置",
        'id="filter-form"',
        'id="start-date"',
        'id="end-date"',
        'id="logs-table"',
        'id="total-badge"',
        'id="detail-modal"',
        "操作详情",
    ):
        assert fragment in content
    return content


@pytest.mark.django_db
class TestMyOperationLogs:
    @pytest.fixture(autouse=True)
    def _override_cache_and_throttle(self, settings):
        settings.CACHES = {
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "my-logs-e2e",
            }
        }
        settings.REST_FRAMEWORK = {
            **getattr(settings, "REST_FRAMEWORK", {}),
            "DEFAULT_THROTTLE_CLASSES": [],
            "DEFAULT_THROTTLE_RATES": {},
        }

    def test_user_can_open_my_logs_page(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            username=f"user_{uuid.uuid4().hex[:8]}",
            password="test-pass-123",
        )

        client = Client()
        client.force_login(user)
        response = client.get("/audit/my-logs/")

        _assert_my_logs_page_contract(response)

    def test_user_only_sees_own_logs_via_api(self):
        user_model = get_user_model()
        user_a = user_model.objects.create_user(
            username=f"usera_{uuid.uuid4().hex[:8]}",
            password="test-pass-123",
        )
        user_b = user_model.objects.create_user(
            username=f"userb_{uuid.uuid4().hex[:8]}",
            password="test-pass-123",
        )

        OperationLogModel._default_manager.create(
            request_id="req-a",
            user_id=user_a.id,
            username=user_a.username,
            source="MCP",
            operation_type="MCP_CALL",
            module="signal",
            action="READ",
            mcp_tool_name="get_signals",
            request_params={},
            response_status=200,
        )
        OperationLogModel._default_manager.create(
            request_id="req-b",
            user_id=user_b.id,
            username=user_b.username,
            source="MCP",
            operation_type="MCP_CALL",
            module="signal",
            action="READ",
            mcp_tool_name="get_signals",
            request_params={},
            response_status=200,
        )

        client = Client()
        client.force_login(user_a)
        response = client.get("/api/audit/operation-logs/?user_id=999999")

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["logs"]
        for row in payload["logs"]:
            assert row["user_id"] == user_a.id
