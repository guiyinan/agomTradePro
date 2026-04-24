"""Table API views for macro data."""

import json
import logging
from datetime import date, datetime
from json import JSONDecodeError
from typing import Any

from django.http import HttpRequest, JsonResponse

from apps.macro.application.interface_services import (
    batch_delete_macro_records,
    create_macro_record,
    delete_macro_record,
    get_macro_indicator_data,
    get_macro_table_page,
    update_macro_record,
)

logger = logging.getLogger(__name__)


def _parse_iso_date(value: str, *, field_name: str) -> date:
    """Parse an ISO date or datetime string into a date."""

    try:
        return datetime.fromisoformat(value).date()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 日期格式无效，应为 YYYY-MM-DD") from exc


def _load_json_body(request: HttpRequest) -> dict[str, Any]:
    """Parse a request JSON body into a dictionary payload."""

    try:
        payload = json.loads(request.body)
    except JSONDecodeError as exc:
        raise ValueError("请求体不是有效的 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return payload


def api_get_indicator_data(request: HttpRequest) -> JsonResponse:
    """API: 获取指标数据详情。"""

    if request.method != "GET":
        return JsonResponse({"success": False, "message": "仅支持 GET 请求"}, status=405)

    try:
        code = (
            request.GET.get("code")
            or request.GET.get("indicator_code")
            or request.GET.get("indicator")
        )
        limit = int(request.GET.get("limit", 500))
        start_date_raw = request.GET.get("start_date", "")
        end_date_raw = request.GET.get("end_date", "")

        if not code:
            return JsonResponse(
                {"success": False, "message": "请指定指标代码"},
                status=400,
            )

        start_date = _parse_iso_date(start_date_raw, field_name="start_date") if start_date_raw else None
        end_date = _parse_iso_date(end_date_raw, field_name="end_date") if end_date_raw else None
        data = get_macro_indicator_data(
            code=code,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
        )
        return JsonResponse({"success": True, "data": data, "count": len(data)})
    except ValueError as exc:
        return JsonResponse({"success": False, "message": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("获取指标数据 API 错误")
        return JsonResponse({"success": False, "message": f"获取失败: {exc}"}, status=500)


def api_table_data(request: HttpRequest) -> JsonResponse:
    """API: 获取表格数据。"""

    if request.method != "GET":
        return JsonResponse({"success": False, "message": "仅支持 GET 请求"}, status=405)

    try:
        page = int(request.GET.get("page", 1))
        page_size = int(request.GET.get("page_size", 50))
        code_filter = request.GET.get("code", "")
        source_filter = request.GET.get("source", "")
        period_type_filter = request.GET.get("period_type", "")
        start_date_raw = request.GET.get("start_date", "")
        end_date_raw = request.GET.get("end_date", "")
        sort_field = request.GET.get("sort_field", "-reporting_period")

        start_date = _parse_iso_date(start_date_raw, field_name="start_date") if start_date_raw else None
        end_date = _parse_iso_date(end_date_raw, field_name="end_date") if end_date_raw else None
        payload = get_macro_table_page(
            page=page,
            page_size=page_size,
            code_filter=code_filter,
            source_filter=source_filter,
            period_type_filter=period_type_filter,
            start_date=start_date,
            end_date=end_date,
            sort_field=sort_field,
        )
        return JsonResponse({"success": True, **payload})
    except ValueError as exc:
        return JsonResponse({"success": False, "message": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("获取表格数据 API 错误")
        return JsonResponse({"success": False, "message": f"获取失败: {exc}"}, status=500)


def api_delete_record(request: HttpRequest, record_id: int) -> JsonResponse:
    """API: 删除单条记录。"""

    if request.method != "DELETE":
        return JsonResponse({"success": False, "message": "仅支持 DELETE 请求"}, status=405)

    try:
        deleted = delete_macro_record(record_id)
        if not deleted:
            return JsonResponse({"success": False, "message": "记录不存在"}, status=404)
        return JsonResponse({"success": True, "message": "删除成功"})
    except Exception as exc:
        logger.exception("删除记录 API 错误")
        return JsonResponse({"success": False, "message": f"删除失败: {exc}"}, status=500)


def api_batch_delete(request: HttpRequest) -> JsonResponse:
    """API: 批量删除记录。"""

    if request.method != "POST":
        return JsonResponse({"success": False, "message": "仅支持 POST 请求"}, status=405)

    try:
        data = _load_json_body(request)
        record_ids = data.get("ids", [])
        if not record_ids:
            return JsonResponse({"success": False, "message": "请选择要删除的记录"}, status=400)

        deleted_count = batch_delete_macro_records(record_ids)
        return JsonResponse(
            {
                "success": True,
                "message": f"成功删除 {deleted_count} 条记录",
                "deleted_count": deleted_count,
            }
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "message": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("批量删除 API 错误")
        return JsonResponse({"success": False, "message": f"删除失败: {exc}"}, status=500)


def api_create_record(request: HttpRequest) -> JsonResponse:
    """API: 新增记录。"""

    if request.method != "POST":
        return JsonResponse({"success": False, "message": "仅支持 POST 请求"}, status=405)

    try:
        data = _load_json_body(request)
        code = data.get("code")
        value = data.get("value")
        period_raw = data.get("observed_at") or data.get("reporting_period")

        if not code:
            return JsonResponse({"success": False, "message": "创建失败: 缺少必填字段 code"}, status=400)
        if value is None:
            return JsonResponse({"success": False, "message": "创建失败: 缺少必填字段 value"}, status=400)
        if not period_raw:
            return JsonResponse(
                {"success": False, "message": "创建失败: 缺少必填字段 reporting_period"},
                status=400,
            )

        record = create_macro_record(
            code=code,
            value=float(value),
            reporting_period=_parse_iso_date(period_raw, field_name="reporting_period"),
            period_type=data.get("period_type", "D"),
            published_at=(
                _parse_iso_date(data["published_at"], field_name="published_at")
                if data.get("published_at")
                else None
            ),
            source=data.get("source", "manual"),
            revision_number=int(data.get("revision_number", 1)),
        )
        return JsonResponse({"success": True, "message": "创建成功", "data": record})
    except ValueError as exc:
        return JsonResponse({"success": False, "message": f"创建失败: {exc}"}, status=400)
    except Exception as exc:
        logger.exception("创建记录 API 错误")
        return JsonResponse({"success": False, "message": f"创建失败: {exc}"}, status=500)


def api_update_record(request: HttpRequest, record_id: int) -> JsonResponse:
    """API: 更新记录。"""

    if request.method != "PUT":
        return JsonResponse({"success": False, "message": "仅支持 PUT 请求"}, status=405)

    try:
        data = _load_json_body(request)
        update_kwargs: dict[str, Any] = {}
        if "code" in data:
            update_kwargs["code"] = data["code"]
        if "value" in data:
            update_kwargs["value"] = float(data["value"]) if data["value"] is not None else None
        if "observed_at" in data or "reporting_period" in data:
            update_kwargs["reporting_period"] = _parse_iso_date(
                data.get("observed_at") or data.get("reporting_period"),
                field_name="reporting_period",
            )
        if "period_type" in data:
            update_kwargs["period_type"] = data["period_type"]
        if "published_at" in data:
            update_kwargs["published_at"] = (
                _parse_iso_date(data["published_at"], field_name="published_at")
                if data["published_at"]
                else None
            )
        if "source" in data:
            update_kwargs["source"] = data["source"]
        if "revision_number" in data:
            update_kwargs["revision_number"] = (
                int(data["revision_number"])
                if data["revision_number"] is not None
                else None
            )

        record = update_macro_record(record_id, **update_kwargs)
        if record is None:
            return JsonResponse({"success": False, "message": "记录不存在"}, status=404)

        return JsonResponse({"success": True, "message": "更新成功", "data": record})
    except ValueError as exc:
        return JsonResponse({"success": False, "message": f"更新失败: {exc}"}, status=400)
    except Exception as exc:
        logger.exception("更新记录 API 错误")
        return JsonResponse({"success": False, "message": f"更新失败: {exc}"}, status=500)
