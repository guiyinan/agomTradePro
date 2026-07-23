"""Alpha interface serializer contract tests."""

from apps.alpha.domain.entities import AlphaResult
from apps.alpha.interface.serializers import (
    AlphaResultSerializer,
    UploadScoreItemSerializer,
)


def test_alpha_result_create_maps_public_stocks_to_domain_scores() -> None:
    """Build the domain entity with its real ``scores`` constructor field."""

    serializer = AlphaResultSerializer(
        data={
            "success": True,
            "source": "qlib",
            "timestamp": "2026-07-23T09:30:00+08:00",
            "status": "available",
            "stocks": [
                {
                    "code": "600519.SH",
                    "score": 0.9,
                    "rank": 1,
                    "factors": {"momentum": 0.8},
                    "source": "qlib",
                    "confidence": 0.95,
                }
            ],
        }
    )

    assert serializer.is_valid(), serializer.errors
    result = serializer.save()

    assert isinstance(result, AlphaResult)
    assert result.scores[0].code == "600519.SH"
    assert result.source == "qlib"


def test_upload_score_source_field_keeps_public_default() -> None:
    """Preserve the API source field without replacing DRF field state."""

    serializer = UploadScoreItemSerializer(data={"code": "600519.sh", "score": 0.9, "rank": 1})

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["code"] == "600519.SH"
    assert serializer.validated_data["source"] == "local_qlib"
