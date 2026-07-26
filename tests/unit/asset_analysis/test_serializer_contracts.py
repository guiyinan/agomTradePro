"""Asset-analysis serializer contract regressions."""

import pytest
from rest_framework.exceptions import ValidationError

from apps.asset_analysis.interface.serializers import (
    ScreenRequestSerializer,
    ScreenResponseSerializer,
)


def _weights() -> dict[str, float]:
    return {
        "regime": 0.4,
        "policy": 0.25,
        "sentiment": 0.2,
        "signal": 0.15,
    }


def test_screen_request_accepts_validated_context_overrides() -> None:
    serializer = ScreenRequestSerializer(
        data={
            "asset_type": "fund",
            "weights": _weights(),
            "regime": "Overheat",
            "policy_level": "P2",
            "sentiment_index": -1.5,
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["sentiment_index"] == -1.5


@pytest.mark.parametrize(
    "payload",
    [
        {"active_signals": []},
        {"owner_id": 1},
        {"weights": {"regime": 1.0}},
        {"weights": {**_weights(), "unknown": 0.0}},
        {"weights": {**_weights(), "regime": True}},
        {"weights": {**_weights(), "regime": float("nan")}},
        {"weights": {**_weights(), "regime": float("inf")}},
        {"sentiment_index": float("nan")},
        {"sentiment_index": True},
    ],
)
def test_screen_request_rejects_untrusted_or_nonfinite_inputs(
    payload: dict[str, object],
) -> None:
    serializer = ScreenRequestSerializer(data={"asset_type": "fund", **payload})

    assert not serializer.is_valid()


def test_screen_response_preserves_nested_score_contract() -> None:
    payload = {
        "success": True,
        "timestamp": "2026-07-27T01:00:00+08:00",
        "context": {
            "regime": "Recovery",
            "policy_level": "P1",
            "sentiment_index": 0.2,
        },
        "weights": _weights(),
        "assets": [
            {
                "asset_code": "110011",
                "asset_name": "示例基金",
                "asset_type": "fund",
                "style": "growth",
                "size": None,
                "sector": None,
                "scores": {
                    "regime": 80.0,
                    "policy": 70.0,
                    "sentiment": 60.0,
                    "signal": 50.0,
                    "custom": {"quality": 75.0},
                    "total": 68.5,
                },
                "rank": 1,
                "allocation": "10%",
                "risk_level": "中",
            }
        ],
        "message": None,
    }

    serialized = ScreenResponseSerializer(payload).data

    assert serialized["assets"][0]["scores"]["total"] == 68.5
    assert serialized["assets"][0]["scores"]["custom"] == {"quality": 75.0}


def test_screen_response_rejects_nonfinite_score() -> None:
    payload = {
        "success": True,
        "timestamp": "2026-07-27T01:00:00+08:00",
        "context": {},
        "weights": _weights(),
        "assets": [
            {
                "asset_code": "110011",
                "asset_name": "示例基金",
                "asset_type": "fund",
                "scores": {
                    "regime": float("nan"),
                    "policy": 70.0,
                    "sentiment": 60.0,
                    "signal": 50.0,
                    "custom": {},
                    "total": 68.5,
                },
                "rank": 1,
                "allocation": "10%",
                "risk_level": "中",
            }
        ],
        "message": None,
    }

    with pytest.raises(ValidationError, match="finite number"):
        _ = ScreenResponseSerializer(payload).data
