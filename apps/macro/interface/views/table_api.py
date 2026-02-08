"""
Table API Views for Macro Data.

Handles table data operations including CRUD operations.
"""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from apps.macro.infrastructure.models import MacroIndicator
from apps.macro.application.indicator_service import UnitDisplayService
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


def _format_indicator_for_display(item: MacroIndicator) -> dict:
    """
    将指标数据格式化为展示格式

    将存储值（元）转换为展示值（原始单位）

    Args:
        item: MacroIndicator ORM 对象

    Returns:
        dict: 格式化后的数据
    """
    # 转换为展示值（原始单位）
    display_value, display_unit = UnitDisplayService.convert_for_display(
        float(item.value),
        item.unit,  # 存储单位
        item.original_unit or item.unit  # 原始单位（如果为空则使用存储单位）
    )

    return {
        'id': item.id,
        'code': item.code,
        'value': display_value,  # 展示值（原始单位）
        'unit': display_unit,  # 展示单位（原始单位）
        'storage_value': float(item.value),  # 存储值（元）
        'storage_unit': item.unit,  # 存储单位（元）
        'reporting_period': item.reporting_period.isoformat(),
        'period_type': item.period_type,
        'period_type_display': item.get_period_type_display(),
        'observed_at': item.observed_at.isoformat(),  # 兼容旧 API
        'published_at': item.published_at.isoformat() if item.published_at else None,
        'source': item.source,
        'revision_number': item.revision_number,
        'publication_lag_days': item.publication_lag_days,
    }


def api_get_indicator_data(request):
    """
    API: 获取指标数据详情
    支持参数: code, limit, start_date, end_date
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '仅支持 GET 请求'}, status=405)

    try:
        code = request.GET.get('code')
        limit = int(request.GET.get('limit', 500))  # 增加默认值
        start_date = request.GET.get('start_date', '')
        end_date = request.GET.get('end_date', '')

        if not code:
            return JsonResponse({
                'success': False,
                'message': '请指定指标代码'
            }, status=400)

        # 构建查询
        queryset = MacroIndicator._default_manager.filter(code=code)

        # 时间范围过滤
        if start_date:
            queryset = queryset.filter(reporting_period__gte=start_date)
        if end_date:
            queryset = queryset.filter(reporting_period__lte=end_date)

        # 排序并限制数量
        queryset = queryset.order_by('reporting_period', 'revision_number')[:limit]

        data = [_format_indicator_for_display(item) for item in queryset]

        return JsonResponse({
            'success': True,
            'data': data,
            'count': len(data)
        })

    except Exception as e:
        logger.exception("获取指标数据 API 错误")
        return JsonResponse({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }, status=500)


def api_table_data(request):
    """
    API: 获取表格数据（支持分页和过滤）
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '仅支持 GET 请求'}, status=405)

    try:
        # 获取查询参数
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 50))
        code_filter = request.GET.get('code', '')
        source_filter = request.GET.get('source', '')
        period_type_filter = request.GET.get('period_type', '')
        start_date = request.GET.get('start_date', '')
        end_date = request.GET.get('end_date', '')
        sort_field = request.GET.get('sort_field', '-reporting_period')

        # 构建查询
        queryset = MacroIndicator._default_manager.all()

        if code_filter:
            queryset = queryset.filter(code__icontains=code_filter)
        if source_filter:
            queryset = queryset.filter(source=source_filter)
        if period_type_filter:
            queryset = queryset.filter(period_type=period_type_filter)
        if start_date:
            queryset = queryset.filter(reporting_period__gte=start_date)
        if end_date:
            queryset = queryset.filter(reporting_period__lte=end_date)

        # 排序
        queryset = queryset.order_by(sort_field)

        # 总数
        total = queryset.count()

        # 分页
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        records = queryset[start_idx:end_idx]

        data = [_format_indicator_for_display(item) for item in records]

        return JsonResponse({
            'success': True,
            'data': data,
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size
        })

    except Exception as e:
        logger.exception("获取表格数据 API 错误")
        return JsonResponse({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }, status=500)


@csrf_exempt
def api_delete_record(request, record_id):
    """
    API: 删除单条记录
    """
    if request.method != 'DELETE':
        return JsonResponse({'success': False, 'message': '仅支持 DELETE 请求'}, status=405)

    try:
        record = MacroIndicator._default_manager.get(id=record_id)
        record.delete()

        return JsonResponse({
            'success': True,
            'message': '删除成功'
        })

    except MacroIndicator.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': '记录不存在'
        }, status=404)

    except Exception as e:
        logger.exception("删除记录 API 错误")
        return JsonResponse({
            'success': False,
            'message': f'删除失败: {str(e)}'
        }, status=500)


@csrf_exempt
def api_batch_delete(request):
    """
    API: 批量删除记录
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '仅支持 POST 请求'}, status=405)

    try:
        data = json.loads(request.body)
        record_ids = data.get('ids', [])

        if not record_ids:
            return JsonResponse({
                'success': False,
                'message': '请选择要删除的记录'
            }, status=400)

        count, _ = MacroIndicator._default_manager.filter(id__in=record_ids).delete()

        return JsonResponse({
            'success': True,
            'message': f'成功删除 {count} 条记录',
            'deleted_count': count
        })

    except Exception as e:
        logger.exception("批量删除 API 错误")
        return JsonResponse({
            'success': False,
            'message': f'删除失败: {str(e)}'
        }, status=500)


@csrf_exempt
def api_create_record(request):
    """
    API: 新增记录
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '仅支持 POST 请求'}, status=405)

    try:
        data = json.loads(request.body)
        code = data.get('code')
        value = data.get('value')
        period_raw = data.get('observed_at') or data.get('reporting_period')

        if not code:
            return JsonResponse({
                'success': False,
                'message': '创建失败: 缺少必填字段 code'
            }, status=400)
        if value is None:
            return JsonResponse({
                'success': False,
                'message': '创建失败: 缺少必填字段 value'
            }, status=400)
        if not period_raw:
            return JsonResponse({
                'success': False,
                'message': '创建失败: 缺少必填字段 reporting_period'
            }, status=400)

        try:
            reporting_period = datetime.fromisoformat(period_raw).date()
        except ValueError:
            return JsonResponse({
                'success': False,
                'message': '创建失败: reporting_period 日期格式无效，应为 YYYY-MM-DD'
            }, status=400)

        record = MacroIndicator._default_manager.create(
            code=code,
            value=value,
            reporting_period=reporting_period,
            period_type=data.get('period_type', 'D'),
            published_at=datetime.fromisoformat(data['published_at']).date() if data.get('published_at') else None,
            source=data.get('source', 'manual'),
            revision_number=data.get('revision_number', 1),
        )

        return JsonResponse({
            'success': True,
            'message': '创建成功',
            'data': _format_indicator_for_display(record)
        })

    except Exception as e:
        logger.exception("创建记录 API 错误")
        return JsonResponse({
            'success': False,
            'message': f'创建失败: {str(e)}'
        }, status=500)


@csrf_exempt
def api_update_record(request, record_id):
    """
    API: 更新记录
    """
    if request.method != 'PUT':
        return JsonResponse({'success': False, 'message': '仅支持 PUT 请求'}, status=405)

    try:
        data = json.loads(request.body)
        record = MacroIndicator._default_manager.get(id=record_id)

        if 'code' in data:
            record.code = data['code']
        if 'value' in data:
            record.value = data['value']
        # 支持 observed_at 或 reporting_period
        if 'observed_at' in data or 'reporting_period' in data:
            record.reporting_period = datetime.fromisoformat(
                data.get('observed_at') or data.get('reporting_period')
            ).date()
        if 'period_type' in data:
            record.period_type = data['period_type']
        if 'published_at' in data:
            record.published_at = datetime.fromisoformat(data['published_at']).date() if data['published_at'] else None
        if 'source' in data:
            record.source = data['source']
        if 'revision_number' in data:
            record.revision_number = data['revision_number']

        record.save()

        return JsonResponse({
            'success': True,
            'message': '更新成功',
            'data': _format_indicator_for_display(record)
        })

    except MacroIndicator.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': '记录不存在'
        }, status=404)

    except Exception as e:
        logger.exception("更新记录 API 错误")
        return JsonResponse({
            'success': False,
            'message': f'更新失败: {str(e)}'
        }, status=500)

