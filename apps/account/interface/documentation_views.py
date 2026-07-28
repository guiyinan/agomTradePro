"""Account documentation management views."""

from __future__ import annotations

import csv
import io
import json
import logging
from urllib.parse import quote

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.uploadedfile import UploadedFile
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse, QueryDict
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.account.application.documentation_use_cases import (
    DocumentationDTO,
    DocumentationFormData,
    DocumentationService,
    get_documentation_service,
)

logger = logging.getLogger(__name__)

_MAX_IMPORT_BYTES = 5 * 1024 * 1024
_IMPORT_INPUT_EXCEPTIONS = (
    AttributeError,
    csv.Error,
    json.JSONDecodeError,
    OverflowError,
    TypeError,
    UnicodeDecodeError,
    ValueError,
)


def _service() -> DocumentationService:
    return get_documentation_service()


@staff_member_required
def docs_manage(request: HttpRequest) -> HttpResponse:
    """Render the documentation management page."""

    category_filter = request.GET.get("category", "")
    status_filter = request.GET.get("status", "")
    search_query = request.GET.get("q", "")
    service = _service()
    docs = service.list_admin_docs(
        category=category_filter,
        status=status_filter,
        search_query=search_query,
    )

    paginator = Paginator(docs, 20)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "category_filter": category_filter,
        "status_filter": status_filter,
        "search_query": search_query,
        "stats": service.get_stats(),
        "category_choices": service.get_category_choices(),
    }
    return render(request, "admin/docs_manage.html", context)


@staff_member_required
def doc_edit(request: HttpRequest, doc_id: int | None = None) -> HttpResponse:
    """Render and process the documentation edit page."""

    service = _service()
    doc = service.get_doc(doc_id) if doc_id else None

    if request.method == "POST":
        try:
            form_data = _form_data_from_post(request.POST)
        except ValueError:
            messages.error(request, "排序必须为整数")
            form_data = None

        if form_data is None:
            pass
        elif not form_data.title or not form_data.slug or not form_data.content:
            messages.error(request, "标题、Slug 和内容不能为空")
        else:
            saved_doc = service.save_doc(form_data, doc_id=doc_id)
            if doc_id:
                messages.success(request, f'文档 "{saved_doc.title}" 更新成功')
            else:
                messages.success(request, f'文档 "{saved_doc.title}" 创建成功')
            return redirect("/admin/docs/manage/")

    context = {
        "doc": doc,
        "category_choices": service.get_category_choices(),
    }
    return render(request, "admin/docs_edit.html", context)


@staff_member_required
def doc_delete(request: HttpRequest, doc_id: int) -> HttpResponse:
    """Delete one documentation record."""

    if request.method == "POST":
        title = _service().delete_doc(doc_id)
        messages.success(request, f'文档 "{title}" 已删除')

    return redirect("/admin/docs/manage/")


@staff_member_required
def doc_export_markdown(request: HttpRequest, doc_id: int) -> HttpResponse:
    """Export one documentation record as Markdown."""

    doc = _service().get_doc(doc_id)
    md_content = f"""# {doc.title}

**分类**: {doc.get_category_display()}
**更新时间**: {doc.updated_at.strftime('%Y-%m-%d %H:%M')}

{doc.summary}

---

{doc.content}
"""

    response = HttpResponse(md_content, content_type="text/markdown; charset=utf-8")
    encoded_filename = quote(f"{doc.slug}.md", safe="")
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{encoded_filename}"
    return response


@staff_member_required
def doc_export_all(request: HttpRequest) -> HttpResponse:
    """Export all documentation records."""

    docs = _service().list_all_docs()
    if request.GET.get("format", "json") == "csv":
        return _export_csv(docs)
    return _export_json(docs)


@staff_member_required
@require_http_methods(["POST"])
def doc_import(request: HttpRequest) -> JsonResponse:
    """Import documentation records from JSON or CSV."""

    import_format = request.POST.get("format", "json")
    uploaded_file = request.FILES.get("file")

    if not isinstance(uploaded_file, UploadedFile):
        return JsonResponse({"success": False, "error": "请选择要导入的文件"}, status=400)
    if uploaded_file.size is not None and uploaded_file.size > _MAX_IMPORT_BYTES:
        return JsonResponse({"success": False, "error": "导入文件不能超过 5 MB"}, status=413)

    try:
        raw_bytes = uploaded_file.read(_MAX_IMPORT_BYTES + 1)
        if len(raw_bytes) > _MAX_IMPORT_BYTES:
            return JsonResponse({"success": False, "error": "导入文件不能超过 5 MB"}, status=413)

        with transaction.atomic():
            service = _service()
            if import_format == "json":
                result = service.import_json_text(raw_bytes.decode("utf-8"))
            elif import_format == "csv":
                result = service.import_csv_text(raw_bytes.decode("utf-8-sig"))
            else:
                return JsonResponse({"success": False, "error": "不支持的导入格式"}, status=400)

        messages.success(request, f"成功导入 {result.created} 篇文档，更新 {result.updated} 篇文档")
        return JsonResponse(
            {"success": True, "data": {"created": result.created, "updated": result.updated}}
        )

    except _IMPORT_INPUT_EXCEPTIONS as exc:
        logger.warning("Documentation import rejected malformed input: %s", type(exc).__name__)
        return JsonResponse({"success": False, "error": "导入文件格式或内容无效"}, status=400)
    except (DatabaseError, OSError, RuntimeError) as exc:
        logger.error("Documentation import service failed: %s", type(exc).__name__)
        return JsonResponse({"success": False, "error": "文档导入服务暂时不可用"}, status=503)


def _form_data_from_post(post_data: QueryDict) -> DocumentationFormData:
    return DocumentationFormData(
        title=post_data.get("title", ""),
        slug=post_data.get("slug", ""),
        category=post_data.get("category", "user_guide"),
        content=post_data.get("content", ""),
        summary=post_data.get("summary", ""),
        order=_parse_order(post_data.get("order", "0")),
        is_published=post_data.get("is_published") == "on",
    )


def _parse_order(value: object) -> int:
    """Return a bounded exact integer for the admin ordering field."""

    if isinstance(value, bool):
        raise ValueError("order must be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        candidate = value.strip()
        digits = candidate[1:] if candidate.startswith("-") else candidate
        if not digits or not digits.isascii() or not digits.isdecimal():
            raise ValueError("order must be an integer")
        parsed = int(candidate)
    else:
        raise ValueError("order must be an integer")
    if not -2_147_483_648 <= parsed <= 2_147_483_647:
        raise ValueError("order is outside the supported range")
    return parsed


def _csv_safe_cell(value: object) -> object:
    """Prevent exported text cells from being interpreted as spreadsheet formulas."""

    if not isinstance(value, str):
        return value
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


def _export_json(docs: list[DocumentationDTO]) -> HttpResponse:
    data = [
        {
            "title": doc.title,
            "slug": doc.slug,
            "category": doc.category,
            "content": doc.content,
            "summary": doc.summary,
            "order": doc.order,
            "is_published": doc.is_published,
        }
        for doc in docs
    ]

    response = HttpResponse(
        json.dumps(data, ensure_ascii=False, indent=2),
        content_type="application/json; charset=utf-8",
    )
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    response["Content-Disposition"] = f"attachment; filename=docs_export_{timestamp}.json"
    return response


def _export_csv(docs: list[DocumentationDTO]) -> HttpResponse:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["标题", "Slug", "分类", "摘要", "排序", "是否发布", "内容"])

    for doc in docs:
        writer.writerow(
            [
                _csv_safe_cell(value)
                for value in [
                    doc.title,
                    doc.slug,
                    doc.category,
                    doc.summary,
                    doc.order,
                    doc.is_published,
                    doc.content.replace("\n", "\\n"),
                ]
            ]
        )

    response = HttpResponse(
        output.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8"
    )
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    response["Content-Disposition"] = f"attachment; filename=docs_export_{timestamp}.csv"
    return response
