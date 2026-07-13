"""Focused SDK contracts for governed Sector reads."""

from unittest.mock import patch

import pytest

from agomtradepro import AgomTradeProClient


def test_get_rotation_ranking_uses_canonical_persisted_read_endpoint():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")

    with patch.object(
        client,
        "get",
        return_value={
            "success": True,
            "regime": "Recovery",
            "top_sectors": [{"sector_code": "801010"}],
            "data_source": "persisted",
        },
    ) as mock_get:
        result = client.sector.get_rotation_ranking(
            regime="Recovery",
            lookback_days=30,
            level="SW2",
            top_n=12,
        )

    assert result["top_sectors"][0]["sector_code"] == "801010"
    mock_get.assert_called_once_with(
        "/api/sector/rotation/",
        params={
            "regime": "Recovery",
            "lookback_days": 30,
            "level": "SW2",
            "top_n": 12,
        },
    )


def test_list_sectors_uses_rotation_ranking_without_regime_side_call():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")

    with patch.object(
        client.sector,
        "get_rotation_ranking",
        return_value={"top_sectors": [{"sector_code": "801010"}]},
    ) as ranking:
        result = client.sector.list_sectors(
            limit=7,
            regime=None,
            lookback_days=20,
            level="SW1",
        )

    assert result == [{"sector_code": "801010"}]
    ranking.assert_called_once_with(
        regime=None,
        lookback_days=20,
        level="SW1",
        top_n=7,
    )


@pytest.mark.parametrize(
    "arguments",
    (
        {"lookback_days": 4},
        {"lookback_days": 121},
        {"level": "GICS"},
        {"top_n": 0},
        {"top_n": 51},
    ),
)
def test_get_rotation_ranking_rejects_invalid_arguments(arguments):
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")

    with pytest.raises(ValueError):
        client.sector.get_rotation_ranking(**arguments)
