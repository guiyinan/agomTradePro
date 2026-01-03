"""
Core Views for AgomSAAF

项目级视图函数
"""

from django.shortcuts import render
from django.contrib.auth.decorators import login_required


def index_view(request):
    """首页视图 - 重定向到 Dashboard"""
    from django.shortcuts import redirect
    return redirect('/dashboard/')


@login_required
def health_view(request):
    """健康检查"""
    from django.http import JsonResponse
    return JsonResponse({'status': 'healthy'})


def chat_example_view(request):
    """聊天组件示例页面"""
    return render(request, 'components/chat_example.html')


@login_required
def policy_dashboard_view(request):
    """
    政策跟踪仪表盘

    显示当前政策档位、响应配置和最近事件
    """
    from apps.policy.infrastructure.models import PolicyLog
    from apps.policy.domain.entities import PolicyLevel
    from apps.policy.domain.rules import get_policy_response, get_recommendations_for_level

    # 获取最新事件
    latest_event = PolicyLog.objects.order_by('-event_date').first()

    # 获取最近 10 个事件
    recent_events = PolicyLog.objects.order_by('-event_date')[:10]

    # 获取当前档位
    current_level = PolicyLevel.P0
    status_name = "P0 - 常态"
    status_class = "p0"
    recommendations = []

    if latest_event:
        try:
            current_level = PolicyLevel(latest_event.level)
            response = get_policy_response(current_level)
            status_name = f"{current_level.value} - {response.name}"
            status_class = current_level.value.lower()
            recommendations = get_recommendations_for_level(current_level)
        except ValueError:
            pass

    context = {
        'latest_event': latest_event,
        'recent_events': recent_events,
        'status_level': status_class,
        'status_name': status_name,
        'recommendations': recommendations,
    }

    return render(request, 'policy/dashboard.html', context)


def docs_view(request, doc_slug=''):
    """文档查看视图"""
    from django.http import Http404
    from apps.account.infrastructure.models import DocumentationModel

    if doc_slug:
        # 显示具体文档
        try:
            doc = DocumentationModel.objects.get(slug=doc_slug, is_published=True)
        except DocumentationModel.DoesNotExist:
            raise Http404(f"文档 {doc_slug} 不存在")

        context = {
            'doc': doc,
            'slug': doc_slug,
            'all_docs': DocumentationModel.objects.filter(is_published=True).order_by('category', 'order'),
        }
        return render(request, 'docs/detail.html', context)
    else:
        # 显示文档列表
        docs = DocumentationModel.objects.filter(is_published=True).order_by('category', 'order')

        # 按分类分组
        categories = {
            'user_guide': {'name': '用户指南', 'docs': []},
            'concept': {'name': '概念说明', 'docs': []},
            'api': {'name': 'API 文档', 'docs': []},
            'development': {'name': '开发文档', 'docs': []},
            'other': {'name': '其他', 'docs': []},
        }

        for doc in docs:
            if doc.category in categories:
                categories[doc.category]['docs'].append(doc)

        context = {
            'categories': categories,
        }
        return render(request, 'docs/list.html', context)
