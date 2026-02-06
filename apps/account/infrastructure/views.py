"""
文档管理视图
"""
import json
import csv
import io
from datetime import datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.core.paginator import Paginator

from .models import DocumentationModel


@staff_member_required
def docs_manage(request):
    """文档管理主页面"""

    # 获取筛选参数
    category_filter = request.GET.get('category', '')
    status_filter = request.GET.get('status', '')
    search_query = request.GET.get('q', '')

    # 构建查询
    queryset = DocumentationModel._default_manager.all()

    if category_filter:
        queryset = queryset.filter(category=category_filter)

    if status_filter == 'published':
        queryset = queryset.filter(is_published=True)
    elif status_filter == 'draft':
        queryset = queryset.filter(is_published=False)

    if search_query:
        queryset = queryset.filter(
            title__icontains=search_query
        ) | queryset.filter(
            content__icontains=search_query
        )

    queryset = queryset.order_by('category', 'order', '-updated_at')

    # 分页
    paginator = Paginator(queryset, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # 统计信息
    stats = {
        'total': DocumentationModel._default_manager.count(),
        'published': DocumentationModel._default_manager.filter(is_published=True).count(),
        'draft': DocumentationModel._default_manager.filter(is_published=False).count(),
        'by_category': {}
    }

    for cat_code, cat_name in DocumentationModel.CATEGORY_CHOICES:
        stats['by_category'][cat_name] = DocumentationModel._default_manager.filter(category=cat_code).count()

    context = {
        'page_obj': page_obj,
        'category_filter': category_filter,
        'status_filter': status_filter,
        'search_query': search_query,
        'stats': stats,
        'category_choices': DocumentationModel.CATEGORY_CHOICES,
    }

    return render(request, 'admin/docs_manage.html', context)


@staff_member_required
def doc_edit(request, doc_id=None):
    """文档编辑页面"""

    if doc_id:
        doc = get_object_or_404(DocumentationModel, id=doc_id)
    else:
        doc = None

    if request.method == 'POST':
        title = request.POST.get('title')
        slug = request.POST.get('slug')
        category = request.POST.get('category')
        content = request.POST.get('content')
        summary = request.POST.get('summary', '')
        order = request.POST.get('order', 0)
        is_published = request.POST.get('is_published') == 'on'

        if not title or not slug or not content:
            messages.error(request, '标题、Slug 和内容不能为空')
        else:
            if doc:
                # 更新现有文档
                doc.title = title
                doc.slug = slug
                doc.category = category
                doc.content = content
                doc.summary = summary
                doc.order = int(order)
                doc.is_published = is_published
                doc.save()
                messages.success(request, f'文档 "{title}" 更新成功')
            else:
                # 创建新文档
                doc = DocumentationModel._default_manager.create(
                    title=title,
                    slug=slug,
                    category=category,
                    content=content,
                    summary=summary,
                    order=int(order),
                    is_published=is_published
                )
                messages.success(request, f'文档 "{title}" 创建成功')

            return redirect('/admin/docs/manage/')

    context = {
        'doc': doc,
        'category_choices': DocumentationModel.CATEGORY_CHOICES,
    }

    return render(request, 'admin/docs_edit.html', context)


@staff_member_required
def doc_delete(request, doc_id):
    """删除文档"""

    if request.method == 'POST':
        doc = get_object_or_404(DocumentationModel, id=doc_id)
        title = doc.title
        doc.delete()
        messages.success(request, f'文档 "{title}" 已删除')

    return redirect('/admin/docs/manage/')


@staff_member_required
def doc_export_markdown(request, doc_id):
    """导出单个文档为 Markdown 文件"""

    doc = get_object_or_404(DocumentationModel, id=doc_id)

    # 构建 Markdown 内容
    md_content = f"""# {doc.title}

**分类**: {doc.get_category_display()}
**更新时间**: {doc.updated_at.strftime('%Y-%m-%d %H:%M')}

{doc.summary}

---

{doc.content}
"""

    response = HttpResponse(
        md_content,
        content_type='text/markdown; charset=utf-8'
    )
    response['Content-Disposition'] = f'attachment; filename={doc.slug}.md'
    return response


@staff_member_required
def doc_export_all(request):
    """批量导出所有文档"""

    format_type = request.GET.get('format', 'json')
    queryset = DocumentationModel._default_manager.all()

    if format_type == 'csv':
        return _export_csv(queryset)
    else:
        return _export_json(queryset)


@staff_member_required
@csrf_exempt
@require_http_methods(['POST'])
def doc_import(request):
    """批量导入文档"""

    import_format = request.POST.get('format', 'json')
    file = request.FILES.get('file')

    if not file:
        return JsonResponse({'success': False, 'error': '请选择要导入的文件'}, status=400)

    try:
        with transaction.atomic():
            if import_format == 'json':
                result = _import_json(file)
            elif import_format == 'csv':
                result = _import_csv(file)
            else:
                return JsonResponse({'success': False, 'error': '不支持的导入格式'}, status=400)

        messages.success(request, f'成功导入 {result["created"]} 篇文档，更新 {result["updated"]} 篇文档')
        return JsonResponse({'success': True, 'data': result})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def _export_json(queryset):
    """导出为 JSON"""
    data = []
    for doc in queryset:
        data.append({
            'title': doc.title,
            'slug': doc.slug,
            'category': doc.category,
            'content': doc.content,
            'summary': doc.summary,
            'order': doc.order,
            'is_published': doc.is_published,
        })

    response = HttpResponse(
        json.dumps(data, ensure_ascii=False, indent=2),
        content_type='application/json; charset=utf-8'
    )
    response['Content-Disposition'] = f'attachment; filename=docs_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    return response


def _export_csv(queryset):
    """导出为 CSV"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['标题', 'Slug', '分类', '摘要', '排序', '是否发布', '内容'])

    for doc in queryset:
        writer.writerow([
            doc.title,
            doc.slug,
            doc.category,
            doc.summary,
            doc.order,
            doc.is_published,
            doc.content.replace('\n', '\\n'),
        ])

    response = HttpResponse(
        output.getvalue().encode('utf-8-sig'),
        content_type='text/csv; charset=utf-8'
    )
    response['Content-Disposition'] = f'attachment; filename=docs_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    return response


def _import_json(file):
    """从 JSON 导入"""
    data = json.load(file)
    created = 0
    updated = 0

    for item in data:
        slug = item.get('slug')
        if not slug:
            continue

        doc, created_flag = DocumentationModel._default_manager.update_or_create(
            slug=slug,
            defaults={
                'title': item.get('title', ''),
                'category': item.get('category', 'user_guide'),
                'content': item.get('content', ''),
                'summary': item.get('summary', ''),
                'order': item.get('order', 0),
                'is_published': item.get('is_published', True),
            }
        )

        if created_flag:
            created += 1
        else:
            updated += 1

    return {'created': created, 'updated': updated}


def _import_csv(file):
    """从 CSV 导入"""
    decoded_file = file.read().decode('utf-8-sig')
    reader = csv.DictReader(decoded_file.splitlines())
    created = 0
    updated = 0

    for row in reader:
        slug = row.get('Slug')
        if not slug:
            continue

        # 映射分类
        category_map = {
            '用户指南': 'user_guide',
            '概念说明': 'concept',
            'API 文档': 'api',
            '开发文档': 'development',
            '其他': 'other',
        }

        category = row.get('分类', 'user_guide')
        if category in category_map:
            category = category_map[category]

        doc, created_flag = DocumentationModel._default_manager.update_or_create(
            slug=slug,
            defaults={
                'title': row.get('标题', ''),
                'category': category,
                'content': row.get('内容', '').replace('\\n', '\n'),
                'summary': row.get('摘要', ''),
                'order': int(row.get('排序', 0)),
                'is_published': row.get('是否发布', 'True') == 'True',
            }
        )

        if created_flag:
            created += 1
        else:
            updated += 1

    return {'created': created, 'updated': updated}

