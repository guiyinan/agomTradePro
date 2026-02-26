"""
Fetch API Views for Macro Data.

Handles data fetching, scheduling, and quick sync operations.
"""

from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods
from django.core.management import call_command
from apps.macro.infrastructure.adapters import AKShareAdapter
from apps.macro.application.data_management import (
    FetchDataUseCase,
    ScheduleDataFetchUseCase,
    FetchDataRequest,
)
from datetime import datetime, timedelta, date
from io import StringIO
import json
import logging

from .helpers import get_repository, get_sync_use_case

logger = logging.getLogger(__name__)


def api_fetch_data_stream(request):
    """
    API: 手动触发数据抓取（带进度推送）

    使用 Server-Sent Events (SSE) 实时推送抓取进度
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '仅支持 POST 请求'}, status=405)

    # 先读取请求体（request.body只能读取一次）
    try:
        request_data = json.loads(request.body)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'无效的请求数据: {e}'}, status=400)

    indicators = request_data.get('indicators')
    start_date_str = request_data.get('start_date')
    end_date_str = request_data.get('end_date')

    # 转换日期
    if start_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    else:
        start_date = None
    if end_date_str:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
        end_date = None

    def generate_progress():
        """生成SSE进度事件流"""
        nonlocal indicators, start_date, end_date
        try:
            # 获取要抓取的指标列表
            sync_use_case = get_sync_use_case()

            if indicators:
                indicator_list = indicators
            else:
                # 获取默认指标列表
                indicator_list = sync_use_case._get_default_indicators()

            total_indicators = len(indicator_list)

            # 发送开始事件
            start_data = json.dumps({'total': total_indicators, 'indicators': indicator_list})
            yield f"event: start\ndata: {start_data}\n\n"

            # 逐个抓取指标
            synced_count = 0
            errors = []

            for i, indicator_code in enumerate(indicator_list, 1):
                try:
                    # 发送进度事件
                    progress_data = json.dumps({
                        'current': i,
                        'total': total_indicators,
                        'indicator': indicator_code,
                        'status': 'fetching'
                    })
                    yield f"event: progress\ndata: {progress_data}\n\n"
                    logger.info(f"正在抓取 {indicator_code} ({i}/{total_indicators})")

                    # 抓取单个指标
                    from apps.macro.application.use_cases import SyncMacroDataRequest
                    sync_request = SyncMacroDataRequest(
                        start_date=start_date or date.today() - timedelta(days=90),
                        end_date=end_date or date.today(),
                        indicators=[indicator_code],
                        force_refresh=True
                    )

                    response = sync_use_case.execute(sync_request)

                    if response.success:
                        synced_count += response.synced_count
                        success_data = json.dumps({
                            'current': i,
                            'total': total_indicators,
                            'indicator': indicator_code,
                            'status': 'success',
                            'count': response.synced_count
                        })
                        yield f"event: progress\ndata: {success_data}\n\n"
                        logger.info(f"✓ {indicator_code} 抓取成功: {response.synced_count} 条数据")
                    else:
                        error_msg = str(response.errors)[:100] if response.errors else '未知错误'
                        error_data = json.dumps({
                            'current': i,
                            'total': total_indicators,
                            'indicator': indicator_code,
                            'status': 'error',
                            'error': error_msg
                        })
                        yield f"event: progress\ndata: {error_data}\n\n"
                        logger.warning(f"✗ {indicator_code} 抓取失败: {response.errors}")
                        errors.extend(response.errors)

                except Exception as e:
                    error_msg = str(e)[:100]
                    error_data = json.dumps({
                        'current': i,
                        'total': total_indicators,
                        'indicator': indicator_code,
                        'status': 'error',
                        'error': error_msg
                    })
                    yield f"event: progress\ndata: {error_data}\n\n"
                    logger.error(f"✗ {indicator_code} 抓取异常: {e}")
                    errors.append(f"{indicator_code}: {str(e)}")

            # 发送完成事件
            success = len(errors) == 0
            complete_data = json.dumps({
                'success': success,
                'synced_count': synced_count,
                'total': total_indicators,
                'errors': errors
            })
            yield f"event: complete\ndata: {complete_data}\n\n"
            logger.info(f"抓取完成: 共 {total_indicators} 个指标，成功 {synced_count} 条数据，{len(errors)} 个错误")

        except Exception as e:
            logger.exception("数据抓取流式 API 错误")
            error_data = json.dumps({'message': str(e)})
            yield f"event: error\ndata: {error_data}\n\n"

    return StreamingHttpResponse(
        generate_progress(),
        content_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


def api_get_supported_indicators(request):
    """
    API: 获取支持的指标列表
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '仅支持 GET 请求'}, status=405)

    try:
        # 从适配器获取支持的指标列表
        try:
            adapter = AKShareAdapter()
            indicators = [
                {'code': code, 'name': name}
                for code, name in adapter.SUPPORTED_INDICATORS.items()
            ]
            # 按代码排序
            indicators.sort(key=lambda x: x['code'])
        except Exception as e:
            logger.error(f"获取适配器指标列表失败: {e}")
            indicators = []

        return JsonResponse({
            'success': True,
            'indicators': indicators,
            'count': len(indicators)
        })

    except Exception as e:
        logger.exception("获取支持指标列表 API 错误")
        return JsonResponse({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }, status=500)


def api_fetch_data(request):
    """
    API: 手动触发数据抓取
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '仅支持 POST 请求'}, status=405)

    try:
        data = json.loads(request.body)
        indicators = data.get('indicators')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        source = data.get('source')

        # 转换日期
        if start_date:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if end_date:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

        # 执行抓取
        sync_use_case = get_sync_use_case()
        fetch_use_case = FetchDataUseCase(sync_use_case, get_repository())

        fetch_request = FetchDataRequest(
            indicators=indicators,
            start_date=start_date,
            end_date=end_date,
            source=source
        )

        response = fetch_use_case.execute(fetch_request)

        return JsonResponse({
            'success': response.success,
            'message': response.message,
            'synced_count': response.synced_count,
            'errors': response.errors
        })

    except Exception as e:
        logger.exception("数据抓取 API 错误")
        return JsonResponse({
            'success': False,
            'message': f'抓取失败: {str(e)}'
        }, status=500)


def api_get_due_indicators(request):
    """
    API: 获取到期需要抓取的指标
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '仅支持 GET 请求'}, status=405)

    try:
        schedule_use_case = ScheduleDataFetchUseCase(get_repository())
        due_indicators = schedule_use_case.get_due_indicators()

        return JsonResponse({
            'success': True,
            'due_indicators': due_indicators,
            'count': len(due_indicators)
        })

    except Exception as e:
        logger.exception("获取到期指标 API 错误")
        return JsonResponse({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }, status=500)


def api_sync_due_indicators(request):
    """
    API: 同步所有到期指标
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '仅支持 POST 请求'}, status=405)

    try:
        schedule_use_case = ScheduleDataFetchUseCase(get_repository())
        due_indicators = schedule_use_case.get_due_indicators()

        if not due_indicators:
            return JsonResponse({
                'success': True,
                'message': '没有需要抓取的指标',
                'synced_count': 0
            })

        # 执行抓取
        sync_use_case = get_sync_use_case()
        fetch_use_case = FetchDataUseCase(sync_use_case, get_repository())

        fetch_request = FetchDataRequest(indicators=due_indicators)
        response = fetch_use_case.execute(fetch_request)

        return JsonResponse({
            'success': response.success,
            'message': response.message,
            'synced_count': response.synced_count,
            'indicators': due_indicators,
            'errors': response.errors
        })

    except Exception as e:
        logger.exception("同步到期指标 API 错误")
        return JsonResponse({
            'success': False,
            'message': f'同步失败: {str(e)}'
        }, status=500)


@require_http_methods(["POST"])
def api_quick_sync(request):
    """
    API: 快速同步宏观数据（用于 Dashboard 一键同步）

    POST /macro/api/quick-sync/
    Body: {
        "source": "akshare"
    }
    """
    try:
        # 获取参数
        source = request.POST.get('source', 'akshare')

        # 捕获命令输出
        out = StringIO()

        # 调用 Django management command 同步核心指标
        call_command(
            'sync_macro_data',
            source=source,
            indicators=['CN_PMI', 'CN_CPI', 'CN_PPI'],
            years=10,
            stdout=out
        )

        output = out.getvalue()

        return JsonResponse({
            'success': True,
            'message': f'{source} 数据同步完成',
            'output': output
        })

    except Exception as e:
        logger.exception("快速同步 API 错误")
        return JsonResponse({
            'success': False,
            'message': f'同步失败: {str(e)}'
        }, status=500)
