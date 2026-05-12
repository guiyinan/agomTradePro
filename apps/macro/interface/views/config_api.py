"""
Config API Views for Macro Data.

Handles data deletion and configuration operations.
"""

import json
import logging
from datetime import datetime

from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from apps.data_center.application.dtos import CreateProviderRequest, UpdateProviderRequest
from apps.data_center.application.interface_services import (
    make_manage_provider_config_use_case,
    make_run_provider_connection_test_use_case,
)
from apps.data_center.application.registry_factory import refresh_registry
from apps.macro.application.data_management import (
    DeleteDataRequest,
    DeleteDataUseCase,
)
from apps.macro.interface.serializers import DataSourceConfigSerializer

from .helpers import get_repository

logger = logging.getLogger(__name__)


@api_view(["GET", "POST"])
@permission_classes([IsAdminUser])
def api_datasource_list_create(request):
    """List or create datasource configs."""
    use_case = make_manage_provider_config_use_case()

    if request.method == "GET":
        providers = use_case.list_all()
        serializer = DataSourceConfigSerializer([item.to_dict() for item in providers], many=True)
        return Response({"results": serializer.data})

    serializer = DataSourceConfigSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    payload = serializer.validated_data
    created = use_case.create(
        CreateProviderRequest(
            name=payload["name"],
            source_type=payload["source_type"],
            is_active=payload.get("is_active", True),
            priority=payload.get("priority", 100),
            api_key=payload.get("api_key", ""),
            api_secret=payload.get("api_secret", ""),
            http_url=payload.get("http_url", ""),
            api_endpoint=payload.get("api_endpoint", ""),
            extra_config=payload.get("extra_config", {}),
            description=payload.get("description", ""),
        )
    )
    refresh_registry()
    from shared.config.secrets import clear_secrets_cache

    clear_secrets_cache()
    return Response(created.to_dict(), status=201)


@api_view(["GET", "PATCH", "PUT"])
@permission_classes([IsAdminUser])
def api_datasource_detail(request, source_id: int):
    """Retrieve or update a datasource config."""
    use_case = make_manage_provider_config_use_case()

    if request.method == "GET":
        provider = use_case.get(source_id)
        if provider is None:
            return Response({"detail": "Not found."}, status=404)
        return Response(provider.to_dict())

    partial = request.method == "PATCH"
    serializer = DataSourceConfigSerializer(data=request.data, partial=partial)
    serializer.is_valid(raise_exception=True)
    payload = serializer.validated_data
    updated = use_case.update(
        UpdateProviderRequest(
            provider_id=source_id,
            name=payload.get("name"),
            source_type=payload.get("source_type"),
            is_active=payload.get("is_active"),
            priority=payload.get("priority"),
            api_key=payload.get("api_key"),
            api_secret=payload.get("api_secret"),
            http_url=payload.get("http_url"),
            api_endpoint=payload.get("api_endpoint"),
            extra_config=payload.get("extra_config"),
            description=payload.get("description"),
        )
    )
    if updated is None:
        return Response({"detail": "Not found."}, status=404)
    refresh_registry()

    from shared.config.secrets import clear_secrets_cache

    clear_secrets_cache()
    return Response(updated.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def api_datasource_test_connection(request, source_id: int):
    """Run a datasource-specific connectivity probe for the config page."""
    use_case = make_run_provider_connection_test_use_case()
    result = use_case.execute(source_id)
    if result is None:
        return Response({"detail": "Not found."}, status=404)
    return Response(result)


def api_delete_data(request):
    """
    API: 删除数据
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '仅支持 POST 请求'}, status=405)

    try:
        data = json.loads(request.body)
        indicator_code = data.get('indicator_code')
        source = data.get('source')
        start_date = data.get('start_date')
        end_date = data.get('end_date')

        # 转换日期
        if start_date:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if end_date:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

        # 至少需要一个条件
        if not any([indicator_code, source, start_date, end_date]):
            return JsonResponse({
                'success': False,
                'message': '请至少指定一个删除条件'
            }, status=400)

        # 执行删除
        delete_use_case = DeleteDataUseCase(get_repository())
        delete_request = DeleteDataRequest(
            indicator_code=indicator_code,
            source=source,
            start_date=start_date,
            end_date=end_date
        )

        response = delete_use_case.execute(delete_request)

        return JsonResponse({
            'success': response.success,
            'message': response.message,
            'deleted_count': response.deleted_count
        })

    except (json.JSONDecodeError, ValueError) as e:
        return JsonResponse({
            'success': False,
            'message': f'无效的请求数据: {str(e)}'
        }, status=400)
    except Exception as e:
        logger.exception("数据删除 API 错误")
        return JsonResponse({
            'success': False,
            'message': f'删除失败: {str(e)}'
        }, status=500)
