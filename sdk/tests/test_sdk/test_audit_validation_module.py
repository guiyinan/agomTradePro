from unittest.mock import call, patch

from agomtradepro import AgomTradeProClient


def test_audit_validation_preview_and_commit_use_canonical_endpoints() -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")
    payload = {"start_date": "2025-01-01", "end_date": "2025-12-31"}

    with patch.object(
        client,
        "post",
        side_effect=[{"success": True, "preview": {}}, {"success": True}],
    ) as mocked:
        preview = client.audit.preview_validation(payload)
        result = client.audit.run_validation(payload)

    assert preview["success"] is True
    assert result["success"] is True
    assert mocked.call_args_list == [
        call("/api/audit/run-validation/preview/", data=None, json=payload),
        call("/api/audit/run-validation/", data=None, json=payload),
    ]
