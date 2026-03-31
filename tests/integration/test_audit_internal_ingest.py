"""
Integration tests for internal operation log ingest API.
"""

import hashlib
import hmac
import json
import time

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.audit.infrastructure.models import OperationLogModel


def _sign(secret_key: str, timestamp: str, payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    sign_content = f"{timestamp}:{body}"
    return hmac.new(
        secret_key.encode("utf-8"),
        sign_content.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@pytest.mark.django_db
class TestAuditInternalIngest:
    @pytest.fixture(autouse=True)
    def _override_cache_and_throttle(self, settings):
        settings.CACHES = {
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "audit-ingest-tests",
            }
        }
        settings.REST_FRAMEWORK = {
            **getattr(settings, "REST_FRAMEWORK", {}),
            "DEFAULT_THROTTLE_CLASSES": [],
            "DEFAULT_THROTTLE_RATES": {},
        }

    def test_ingest_with_valid_signature_creates_log(self):
        client = APIClient()
        payload = {
            "request_id": "req-internal-001",
            "source": "MCP",
            "operation_type": "MCP_CALL",
            "module": "signal",
            "action": "CREATE",
            "mcp_tool_name": "create_signal",
            "request_params": {"password": "secret", "asset_code": "000001.SH"},
            "response_status": 200,
        }
        ts = str(int(time.time()))
        secret = "test-audit-secret"
        signature = _sign(secret, ts, payload)

        with override_settings(AUDIT_INTERNAL_SECRET_KEY=secret, DEBUG=False):
            response = client.post(
                "/api/audit/internal/operation-logs/",
                data=payload,
                format="json",
                HTTP_X_AUDIT_TIMESTAMP=ts,
                HTTP_X_AUDIT_SIGNATURE=signature,
            )

        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["log_id"]

        log = OperationLogModel._default_manager.get(id=data["log_id"])
        assert log.request_id == "req-internal-001"
        assert log.mcp_tool_name == "create_signal"
        assert log.request_params["password"] == "***"

    def test_ingest_with_invalid_signature_rejected(self):
        client = APIClient()
        payload = {
            "request_id": "req-internal-002",
            "source": "MCP",
            "operation_type": "MCP_CALL",
            "module": "signal",
            "action": "READ",
        }
        ts = str(int(time.time()))

        with override_settings(AUDIT_INTERNAL_SECRET_KEY="right-secret", DEBUG=False):
            response = client.post(
                "/api/audit/internal/operation-logs/",
                data=payload,
                format="json",
                HTTP_X_AUDIT_TIMESTAMP=ts,
                HTTP_X_AUDIT_SIGNATURE="wrong-signature",
            )

        assert response.status_code == 403
        assert OperationLogModel._default_manager.filter(request_id="req-internal-002").count() == 0
