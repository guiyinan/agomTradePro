from unittest.mock import Mock
from uuid import UUID

from agomtradepro_mcp.audit import AuditContext, AuditLogger, use_audit_sink


def test_default_backend_url_follows_remote_api_base(monkeypatch) -> None:
    monkeypatch.delenv("AGOMTRADEPRO_AUDIT_URL", raising=False)
    monkeypatch.setenv("AGOMTRADEPRO_BASE_URL", "https://demo.example.com/")

    logger = AuditLogger(secret_key="k")

    assert logger.backend_url == "https://demo.example.com/api/audit/internal/operation-logs/"


def test_send_audit_log_forwards_user_access_token(monkeypatch) -> None:
    monkeypatch.setenv("AGOMTRADEPRO_API_TOKEN", "user-access-token")
    logger = AuditLogger(
        backend_url="https://demo.example.com/api/audit/internal/operation-logs/",
        secret_key="",
    )

    class FakeResponse:
        status_code = 201
        text = '{"success": true, "log_id": "log-1"}'

        @staticmethod
        def json() -> dict[str, object]:
            return {"success": True, "log_id": "log-1"}

    fake_requests = Mock()
    fake_requests.post.return_value = FakeResponse()
    monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)

    assert logger._send_audit_log({"request_id": "r-token"}) == "log-1"
    headers = fake_requests.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Token user-access-token"
    assert fake_requests.post.call_args.kwargs["timeout"] == 5.0
    UUID(fake_requests.post.call_args.kwargs["json"]["delivery_id"])


def test_scoped_audit_sink_bypasses_backend_http(monkeypatch) -> None:
    """Embedded MCP hosts may persist audit events without self-HTTP."""

    audit = AuditLogger()
    sink = Mock(return_value="local-log-id")
    request = Mock()
    monkeypatch.setattr("requests.post", request)

    with use_audit_sink(sink):
        log_id = audit._send_audit_log({"request_id": "req-local"})

    assert log_id == "local-log-id"
    sink.assert_called_once_with({"request_id": "req-local"})
    request.assert_not_called()


def test_mask_sensitive_params_recursive() -> None:
    params = {
        "password": "secret",
        "nested": [{"token": "abc"}, {"value": 1}],
        "normal": "ok",
    }
    masked = AuditLogger._mask_sensitive_params(params)
    assert masked["password"] == "***"
    assert masked["nested"][0]["token"] == "***"
    assert masked["nested"][1]["value"] == 1
    assert masked["normal"] == "ok"


def test_compute_signature_stable() -> None:
    logger = AuditLogger(secret_key="k")
    payload = {"b": 1, "a": 2}
    signature = logger._compute_signature("123", payload)
    # Expected from HMAC-SHA256(timestamp + sorted JSON body)
    assert signature
    assert len(signature) == 64


def test_send_audit_log_handles_application_failure(monkeypatch) -> None:
    logger = AuditLogger(secret_key="k")

    class FakeResponse:
        status_code = 201

        @staticmethod
        def json():
            return {"success": False, "error": "db error"}

        text = '{"success": false}'

    fake_requests = Mock()
    fake_requests.post.return_value = FakeResponse()
    monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)

    log_id = logger._send_audit_log({"request_id": "r-1"})
    # status 201 but business failed => should not be treated as success
    assert log_id is None


def test_log_mcp_call_non_blocking_on_network_error(monkeypatch) -> None:
    import requests

    logger = AuditLogger(secret_key="k")
    ctx = AuditContext.create(request_id="req-1", username="u")
    monkeypatch.setenv("AGOMTRADEPRO_AUDIT_MAX_ATTEMPTS", "1")

    monkeypatch.setattr(
        requests,
        "post",
        Mock(side_effect=requests.RequestException("network down")),
    )

    result = logger.log_mcp_call(
        tool_name="create_signal",
        params={"asset_code": "000001.SH"},
        result={"ok": True},
        error=None,
        context=ctx,
    )
    assert result is None


def test_send_audit_log_retries_with_same_delivery_id(monkeypatch) -> None:
    """A timed-out write can be retried without creating a second audit event."""

    import requests

    logger = AuditLogger(secret_key="k")
    monkeypatch.setenv("AGOMTRADEPRO_AUDIT_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("AGOMTRADEPRO_AUDIT_RETRY_BACKOFF_SECONDS", "0")

    class FakeResponse:
        status_code = 201
        text = '{"success": true, "log_id": "log-retried"}'

        @staticmethod
        def json() -> dict[str, object]:
            return {"success": True, "log_id": "log-retried"}

    post = Mock(side_effect=[requests.ReadTimeout("first attempt"), FakeResponse()])
    monkeypatch.setattr(requests, "post", post)

    assert logger._send_audit_log({"request_id": "req-retry"}) == "log-retried"
    assert post.call_count == 2
    first_payload = post.call_args_list[0].kwargs["json"]
    second_payload = post.call_args_list[1].kwargs["json"]
    assert first_payload["delivery_id"] == second_payload["delivery_id"]
    UUID(first_payload["delivery_id"])


def test_log_mcp_call_includes_response_payload_and_traceback(monkeypatch) -> None:
    logger = AuditLogger(secret_key="k")
    ctx = AuditContext.create(request_id="req-2", username="u")
    captured = {}

    def fake_send(data):
        captured.update(data)
        return "log-1"

    monkeypatch.setattr(logger, "_send_audit_log", fake_send)

    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        result = logger.log_mcp_call(
            tool_name="create_signal",
            params={"asset_code": "000001.SH"},
            result={"token": "secret", "ok": True},
            error=exc,
            context=ctx,
        )

    assert result == "log-1"
    assert captured["response_payload"]["token"] == "***"
    assert captured["response_payload"]["ok"] is True
    assert '"token": "***"' in captured["response_text"]
    assert "RuntimeError: boom" in captured["exception_traceback"]


def test_log_governed_capability_event_includes_lifecycle_metadata(monkeypatch) -> None:
    logger = AuditLogger(secret_key="k")
    ctx = AuditContext.create(request_id="req-3", username="u", mcp_role="investment_manager")
    captured = {}

    def fake_send(data):
        captured.update(data)
        return "log-2"

    monkeypatch.setattr(logger, "_send_audit_log", fake_send)

    result = logger.log_governed_capability_event(
        tool_name="agom_capability_call",
        capability_key="account.import.positions",
        params={
            "portfolio_id": 1,
            "positions": [{"asset_code": "510300.SH", "token": "secret"}],
        },
        result={"ok": False, "status": "confirmation_required"},
        error=None,
        context=ctx,
        owner_app="account",
        risk_level="medium",
        event_type="preview_staged",
        confirmation_status="pending",
        idempotency_key="idem-1",
        request_arguments={"portfolio_id": 1},
        affected_objects={"portfolio_id": 1, "position_count": 1},
    )

    assert result == "log-2"
    assert captured["module"] == "account"
    assert captured["action"] == "UPDATE"
    assert captured["mcp_tool_name"] == "agom_capability_call"
    assert captured["resource_type"] == "mcp_capability"
    assert captured["resource_id"] == "account.import.positions"
    assert captured["request_path"] == "/mcp/capabilities/account.import.positions"
    assert captured["request_params"]["event_type"] == "preview_staged"
    assert captured["request_params"]["confirmation_status"] == "pending"
    assert captured["request_params"]["idempotency_key"] == "idem-1"
    assert captured["request_params"]["arguments"]["positions"][0]["token"] == "***"
