from unittest.mock import call, patch

from agomtradepro import AgomTradeProClient


def test_audit_attribution_preview_and_commit_use_canonical_endpoints() -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")
    payload = {"backtest_id": 7}

    with patch.object(
        client,
        "post",
        side_effect=[{"success": True, "preview": {}}, {"id": 42}],
    ) as mocked:
        preview = client.audit.preview_report_generation(payload)
        result = client.audit.generate_report(payload)

    assert preview["success"] is True
    assert result["id"] == 42
    assert mocked.call_args_list == [
        call("/api/audit/reports/generate/preview/", data=None, json=payload),
        call("/api/audit/reports/generate/", data=None, json=payload),
    ]
