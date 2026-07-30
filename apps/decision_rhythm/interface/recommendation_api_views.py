"""Recommendation Api Views"""

import logging
from enum import Enum
from typing import Any, TypeVar

from django.conf import settings
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from shared.request_payload import request_data_mapping

from ..application.dtos import (
    ConflictsListDTO,
    RecommendationsListDTO,
    RefreshRecommendationsRequestDTO,
)
from ..application.user_action_labels import build_user_action_label
from ..application.workspace_services import (
    get_model_params_payload,
    list_workspace_conflicts,
    list_workspace_recommendations,
    refresh_workspace_recommendations,
    update_model_param_payload,
    update_workspace_recommendation_action,
)
from ..domain.recommendation_entities import (
    RecommendationStatus,
    UserDecisionAction,
)

logger = logging.getLogger(__name__)
EnumValue = TypeVar("EnumValue", bound=Enum)


def _normalize_enum_filter(
    raw_value: str | None,
    enum_cls: type[EnumValue],
    field_name: str,
) -> str | None:
    if raw_value in (None, ""):
        return None

    candidate = str(raw_value).strip().upper()
    try:
        return str(enum_cls(candidate).value)
    except ValueError:
        allowed = ", ".join(item.value for item in enum_cls)
        raise ValueError(f"{field_name} must be one of: {allowed}") from None


def _validate_security_codes_payload(raw_value: Any) -> list[str] | None:
    if raw_value in (None, ""):
        return None
    if not isinstance(raw_value, list):
        raise ValueError("security_codes must be a list of strings")

    normalized: list[str] = []
    for item in raw_value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("security_codes must be a list of non-empty strings")
        normalized.append(item.strip())
    return normalized


def _optional_text(value: Any) -> str | None:
    """Normalize an optional request value to stripped text."""

    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _request_username(request: Request) -> str:
    """Return the authenticated audit username or the API fallback actor."""

    if not request.user.is_authenticated:
        return "api"
    username = getattr(request.user, "username", "")
    return str(username or "api")


class UnifiedRecommendationsView(APIView):
    """
    GET /api/decision/workspace/recommendations/

    返回统一聚合建议列表。
    """

    def get(self, request: Request) -> Response:
        """
        获取推荐列表

        Query params:
            account_id: 账户 ID（必填）
            status: 状态过滤（可选）
            page: 页码（默认 1）
            page_size: 每页大小（默认 20）
        """
        # 灰度开关检查
        if not getattr(settings, "DECISION_WORKSPACE_V2_ENABLED", True):
            return Response(
                {
                    "success": False,
                    "error": "Decision Workspace V2 is disabled. Use legacy /api/decision-rhythm/submit/ endpoint.",
                    "feature_flag": "DECISION_WORKSPACE_V2_ENABLED",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        account_id = request.query_params.get("account_id")
        if not account_id:
            return Response(
                {"success": False, "error": "account_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            status_filter = _normalize_enum_filter(
                request.query_params.get("status"),
                RecommendationStatus,
                "status",
            )
            user_action_filter = _normalize_enum_filter(
                request.query_params.get("user_action"),
                UserDecisionAction,
                "user_action",
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        security_code_filter = request.query_params.get("security_code")
        include_ignored = str(request.query_params.get("include_ignored", "")).lower() in {
            "1",
            "true",
            "yes",
        }
        recommendation_id = request.query_params.get("recommendation_id")
        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("page_size", 20))
        except (TypeError, ValueError):
            return Response(
                {"success": False, "error": "page and page_size must be integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if page < 1 or page_size < 1 or page_size > 200:
            return Response(
                {"success": False, "error": "page must be >=1 and page_size must be in [1, 200]"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            recommendations, total_count = list_workspace_recommendations(
                account_id=account_id,
                status=status_filter,
                user_action=user_action_filter,
                security_code=security_code_filter,
                include_ignored=include_ignored,
                recommendation_id=recommendation_id,
                page=page,
                page_size=page_size,
            )

            # 构建响应
            list_dto = RecommendationsListDTO(
                recommendations=recommendations,
                total_count=total_count,
                page=page,
                page_size=page_size,
            )

            return Response(
                {
                    "success": True,
                    "data": list_dto.to_dict(),
                }
            )

        except Exception as exc:
            logger.error("Failed to get recommendations: %s", exc, exc_info=True)
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class RecommendationUserActionView(APIView):
    """
    POST /api/decision/workspace/recommendations/action/

    为统一推荐记录用户动作状态。
    """

    ACTION_MAPPING: dict[str, UserDecisionAction] = {
        "watch": UserDecisionAction.WATCHING,
        "adopt": UserDecisionAction.ADOPTED,
        "ignore": UserDecisionAction.IGNORED,
        "pending": UserDecisionAction.PENDING,
    }

    def post(self, request: Request) -> Response:
        request_payload = request_data_mapping(request)
        recommendation_id = _optional_text(request_payload.get("recommendation_id"))
        action = str(request_payload.get("action") or "").strip().lower()
        account_id = _optional_text(request_payload.get("account_id"))
        note = str(request_payload.get("note") or "").strip()

        if not recommendation_id:
            return Response(
                {"success": False, "error": "recommendation_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if action not in self.ACTION_MAPPING:
            return Response(
                {
                    "success": False,
                    "error": "action must be one of: watch, adopt, ignore, pending",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_action = self.ACTION_MAPPING[action]
        dto = update_workspace_recommendation_action(
            recommendation_id=recommendation_id,
            action=user_action,
            note=note,
            account_id=account_id,
        )
        if dto is None:
            return Response(
                {"success": False, "error": "Recommendation not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "success": True,
                "data": {
                    "recommendation": dto.to_dict(),
                    "message": f"已更新为{build_user_action_label(dto.user_action)}",
                },
            }
        )


class RefreshRecommendationsView(APIView):
    """
    POST /api/decision/workspace/recommendations/refresh/

    手动触发推荐重算。
    """

    def post(self, request: Request) -> Response:
        """
        触发刷新

        Request body:
            account_id: 账户 ID（可选，不传则使用 default 账户口径）
            security_codes: 证券代码列表（可选）
            force: 是否强制刷新（默认 False）
            async_mode: 是否异步执行（默认 True）
        """
        payload: dict[str, Any] = {
            str(key): value for key, value in dict(request.data or {}).items()
        }
        try:
            payload["security_codes"] = _validate_security_codes_payload(
                payload.get("security_codes")
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 解析请求
        dto = RefreshRecommendationsRequestDTO.from_dict(payload)

        try:
            response_dto = refresh_workspace_recommendations(dto)

            return Response(
                {
                    "success": response_dto.status != "FAILED",
                    "data": response_dto.to_dict(),
                }
            )

        except Exception as exc:
            logger.error("Failed to refresh recommendations: %s", exc, exc_info=True)
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ConflictsView(APIView):
    """
    GET /api/decision/workspace/conflicts/

    返回冲突建议。
    """

    def get(self, request: Request) -> Response:
        """
        获取冲突列表

        Query params:
            account_id: 账户 ID（必填）
        """
        account_id = request.query_params.get("account_id")
        if not account_id:
            return Response(
                {"success": False, "error": "account_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            conflicts = list_workspace_conflicts(account_id)

            # 构建响应
            list_dto = ConflictsListDTO(
                conflicts=conflicts,
                total_count=len(conflicts),
            )

            return Response(
                {
                    "success": True,
                    "data": list_dto.to_dict(),
                }
            )

        except Exception as exc:
            logger.error("Failed to get conflicts: %s", exc, exc_info=True)
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ModelParamsView(APIView):
    """
    GET /api/decision/workspace/params/

    获取当前模型参数配置。
    """

    def get(self, request: Request) -> Response:
        """
        获取参数配置

        Query params:
            env: 环境（默认 dev）
        """
        env = str(request.query_params.get("env", "dev"))

        try:
            return Response(
                {
                    "success": True,
                    "data": get_model_params_payload(env),
                }
            )

        except Exception as exc:
            logger.error("Failed to get model params: %s", exc, exc_info=True)
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class UpdateModelParamView(APIView):
    """
    POST /api/decision/workspace/params/update/

    更新模型参数。
    """

    def post(self, request: Request) -> Response:
        """
        更新参数

        Request body:
            param_key: 参数键（必填）
            param_value: 参数值（必填）
            param_type: 参数类型（默认 float）
            env: 环境（默认 dev）
            updated_reason: 变更原因（必填）
        """
        request_payload = request_data_mapping(request)
        param_key = _optional_text(request_payload.get("param_key"))
        param_value = request_payload.get("param_value")
        param_type = str(request_payload.get("param_type", "float"))
        env = str(request_payload.get("env", "dev"))
        updated_reason = str(request_payload.get("updated_reason", ""))

        if not param_key or param_value is None:
            return Response(
                {"success": False, "error": "param_key and param_value are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = update_model_param_payload(
                param_key=param_key,
                param_value=str(param_value),
                param_type=param_type,
                env=env,
                updated_by=_request_username(request),
                updated_reason=updated_reason,
            )
            return Response(
                {
                    "success": True,
                    "data": payload,
                }
            )

        except Exception as exc:
            logger.error("Failed to update model param: %s", exc, exc_info=True)
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
