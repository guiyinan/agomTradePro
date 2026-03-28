"""
Config API Views for Macro Data.

Handles data deletion and configuration operations.
"""

import json
import logging
from datetime import datetime

from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from apps.macro.application.data_management import DeleteDataRequest, DeleteDataUseCase
from apps.macro.infrastructure.models import DataSourceConfig
from apps.macro.interface.serializers import DataSourceConfigSerializer

from .helpers import get_repository

logger = logging.getLogger(__name__)


@api_view(["GET", "POST"])
@permission_classes([IsAdminUser])
def api_datasource_list_create(request):
    """List or create datasource configs."""
    if request.method == "GET":
        queryset = DataSourceConfig._default_manager.all().order_by("priority", "name")
        serializer = DataSourceConfigSerializer(queryset, many=True)
        return Response({"results": serializer.data})

    serializer = DataSourceConfigSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    instance = serializer.save()
    from shared.config.secrets import clear_secrets_cache

    clear_secrets_cache()
    return Response(DataSourceConfigSerializer(instance).data, status=201)


@api_view(["GET", "PATCH", "PUT"])
@permission_classes([IsAdminUser])
def api_datasource_detail(request, source_id: int):
    """Retrieve or update a datasource config."""
    instance = get_object_or_404(DataSourceConfig, id=source_id)

    if request.method == "GET":
        return Response(DataSourceConfigSerializer(instance).data)

    partial = request.method == "PATCH"
    serializer = DataSourceConfigSerializer(instance, data=request.data, partial=partial)
    serializer.is_valid(raise_exception=True)
    updated = serializer.save()

    from shared.config.secrets import clear_secrets_cache

    clear_secrets_cache()
    return Response(DataSourceConfigSerializer(updated).data)


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

    except Exception as e:
        logger.exception("数据删除 API 错误")
        return JsonResponse({
            'success': False,
            'message': f'删除失败: {str(e)}'
        }, status=500)
