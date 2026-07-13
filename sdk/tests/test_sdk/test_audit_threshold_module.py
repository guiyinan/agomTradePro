from unittest.mock import call, patch

from agomtradepro import AgomTradeProClient


def test_audit_threshold_preview_and_commit_use_canonical_endpoints() -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")
    payload = {"indicator_code": "CN_PMI", "level_low": 49.0, "level_high": 51.0}

    with patch.object(
        client,
        "post",
        side_effect=[{"success": True, "preview": {}}, {"success": True}],
    ) as mocked:
        preview = client.audit.preview_threshold_update(payload)
        result = client.audit.update_threshold(payload)

    assert preview["success"] is True
    assert result["success"] is True
    assert mocked.call_args_list == [
        call("/api/audit/update-threshold/preview/", data=None, json=payload),
        call("/api/audit/update-threshold/", data=None, json=payload),
    ]
