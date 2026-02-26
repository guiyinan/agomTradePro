"""
Config API Views for Macro Data.

Handles data deletion and configuration operations.
"""

from django.http import JsonResponse
from apps.macro.application.data_management import DeleteDataUseCase, DeleteDataRequest
from datetime import datetime
import json
import logging

from .helpers import get_repository

logger = logging.getLogger(__name__)


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
