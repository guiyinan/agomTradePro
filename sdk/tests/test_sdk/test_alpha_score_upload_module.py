from unittest.mock import patch

from agomtradepro import AgomTradeProClient


def test_preview_score_upload_uses_canonical_preview_endpoint():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    scores = [{"code": "000001.SZ", "score": 0.9, "rank": 1}]
    with patch.object(client, "_request", return_value={"success": True}) as request:
        result = client.alpha.preview_score_upload(
            scores=scores,
            universe_id="csi300",
            asof_date="2026-07-11",
            intended_trade_date="2026-07-12",
            model_id="model-1",
            model_artifact_hash="hash-1",
            scope="system",
        )

    assert result == {"success": True}
    request.assert_called_once_with(
        "POST",
        "/api/alpha/scores/upload/preview/",
        data=None,
        json={
            "universe_id": "csi300",
            "asof_date": "2026-07-11",
            "intended_trade_date": "2026-07-12",
            "model_id": "model-1",
            "model_artifact_hash": "hash-1",
            "scope": "system",
            "scores": scores,
        },
    )
