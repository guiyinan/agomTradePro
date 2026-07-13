"""Governed API views for Alpha score-cache uploads."""

from typing import Any

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.alpha.application.interface_services import (
    preview_alpha_score_upload,
    upload_alpha_scores,
)

from .serializers import UploadScoresSerializer


def _validated_upload(request: Request) -> dict[str, Any]:
    serializer = UploadScoresSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


def _write_user(request: Request, scope: str):
    if scope == "system":
        if not request.user.is_staff:
            raise PermissionDenied("只有管理员可以上传系统级评分（scope=system）")
        return None
    return request.user


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def preview_score_upload(request: Request) -> Response:
    """Preview the exact Alpha score-cache upsert without writing it."""

    data = _validated_upload(request)
    scope = data.get("scope", "user")
    preview = preview_alpha_score_upload(
        write_user=_write_user(request, scope),
        universe_id=data["universe_id"],
        asof_date=data["asof_date"],
        intended_trade_date=data["intended_trade_date"],
        model_id=data["model_id"],
        model_artifact_hash=data["model_artifact_hash"],
        scores=data["scores"],
    )
    return Response({"success": True, "preview": preview})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def upload_scores(request: Request) -> Response:
    """Create or replace one exact Alpha score-cache target."""

    data = _validated_upload(request)
    scope = data.get("scope", "user")
    cache_obj, created = upload_alpha_scores(
        write_user=_write_user(request, scope),
        universe_id=data["universe_id"],
        asof_date=data["asof_date"],
        intended_trade_date=data["intended_trade_date"],
        model_id=data["model_id"],
        model_artifact_hash=data["model_artifact_hash"],
        scores=data["scores"],
    )
    return Response(
        {
            "success": True,
            "count": len(data["scores"]),
            "scope": scope,
            "id": cache_obj.pk,
            "created": created,
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )
