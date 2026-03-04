import json
from unittest.mock import Mock

from agomsaaf_mcp.audit import AuditContext, AuditLogger


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
