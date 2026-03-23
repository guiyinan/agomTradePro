"""
AgomTradePro - HTMX 视图基类

提供基于 HTMX 的视图基类，简化 HTMX 请求处理。
"""

from typing import Any, Dict, Optional

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.paginator import Paginator
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView


def is_htmx(request: HttpRequest) -> bool:
    """
    检查请求是否来自 HTMX

    Args:
        request: HTTP 请求对象

    Returns:
        是否为 HTMX 请求
    """
    return request.headers.get('HX-Request') == 'true'


class HtmxTemplateView(TemplateView):
    """
    HTMX 模板视图基类

    对于 HTMX 请求返回部分模板，对于普通请求返回完整页面。
    """

    htmx_template_name: str | None = None
    """HTMX 请求使用的模板（部分内容）"""

    def get_template_names(self) -> list[str]:
        """
        根据 HTMX 请求返回不同的模板名称

        Returns:
            模板名称列表
        """
        if is_htmx(self.request) and self.htmx_template_name:
            return [self.htmx_template_name]
        return super().get_template_names()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """
        获取模板上下文数据

        Args:
            **kwargs: 额外的上下文变量

        Returns:
            模板上下文字典
        """
        context = super().get_context_data(**kwargs)
        context['is_htmx'] = is_htmx(self.request)
        return context

    def render_to_response(self, context: dict[str, Any], **response_kwargs: Any) -> HttpResponse:
        """
        渲染模板响应

        Args:
            context: 模板上下文
            **response_kwargs: 额外的响应参数

        Returns:
            HTTP 响应
        """
        if is_htmx(self.request):
            # HTMX 请求：添加自定义响应头
            response = super().render_to_response(context, **response_kwargs)
            response['HX-Trigger'] = 'contentUpdated'
            return response
        return super().render_to_response(context, **response_kwargs)


class HtmxListView(ListView):
    """
    HTMX 列表视图基类

    支持分页、搜索、排序，对 HTMX 友好。
    """

    paginate_by: int = 20
    """每页数量"""

    htmx_template_name: str | None = None
    """HTMX 请求使用的模板（通常是表格内容）"""

    search_fields: list[str] = []
    """可搜索的字段列表"""

    ordering_fields: dict[str, str] = {}
    """可排序的字段映射（字段名 -> 模型字段路径）"""

    def get_queryset(self) -> QuerySet:
        """
        获取查询集，应用搜索和排序

        Returns:
            过滤后的查询集
        """
        queryset = super().get_queryset()

        # 应用搜索
        search_query = self.request.GET.get('q', '').strip()
        if search_query and self.search_fields:
            from django.db.models import Q

            q_objects = Q()
            for field in self.search_fields:
                q_objects |= Q(**{f'{field}__icontains': search_query})
            queryset = queryset.filter(q_objects)

        # 应用排序
        sort_by = self.request.GET.get('sort', '')
        if sort_by and sort_by in self.ordering_fields:
            order_field = self.ordering_fields[sort_by]
            sort_order = self.request.GET.get('order', 'asc')
            queryset = queryset.order_by(
                f'-{order_field}' if sort_order == 'desc' else order_field
            )

        return queryset

    def get_template_names(self) -> list[str]:
        """
        根据 HTMX 请求返回不同的模板

        Returns:
            模板名称列表
        """
        if is_htmx(self.request) and self.htmx_template_name:
            return [self.htmx_template_name]
        return super().get_template_names()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """
        获取模板上下文

        Args:
            **kwargs: 额外的上下文变量

        Returns:
            模板上下文字典
        """
        context = super().get_context_data(**kwargs)
        context['is_htmx'] = is_htmx(self.request)
        context['search_query'] = self.request.GET.get('q', '')
        context['sort_by'] = self.request.GET.get('sort', '')
        context['sort_order'] = self.request.GET.get('order', 'asc')
        return context


class HtmxFormView(FormView):
    """
    HTMX 表单视图基类

    支持 HTMX 表单提交，返回验证错误或成功消息。
    """

    htmx_template_name: str | None = None
    """HTMX 请求使用的模板（通常是表单片段）"""

    success_message: str = '操作成功'
    """成功消息"""

    def get_template_names(self) -> list[str]:
        """
        根据 HTMX 请求返回不同的模板

        Returns:
            模板名称列表
        """
        if is_htmx(self.request) and self.htmx_template_name:
            return [self.htmx_template_name]
        return super().get_template_names()

    def form_valid(self, form: Any) -> HttpResponse:
        """
        表单验证成功处理

        Args:
            form: 表单实例

        Returns:
            HTTP 响应
        """
        response = super().form_valid(form)

        if is_htmx(self.request):
            # HTMX 请求：返回成功消息
            return JsonResponse({
                'success': True,
                'message': self.success_message,
                'redirect_url': self.get_success_url()
            }, headers={
                'X-Success-Message': self.success_message
            })

        return response

    def form_invalid(self, form: Any) -> HttpResponse:
        """
        表单验证失败处理

        Args:
            form: 表单实例

        Returns:
            HTTP 响应
        """
        if is_htmx(self.request):
            # HTMX 请求：返回表单错误
            errors = {
                field: errors[0]['message'] if isinstance(errors, list) else str(errors)
                for field, errors in form.errors.items()
            }
            return JsonResponse({
                'success': False,
                'errors': errors
            }, status=400, headers={
                'X-Error-Title': '表单验证失败',
                'X-Error-Message': '; '.join(f'{k}: {v}' for k, v in errors.items())
            })

        return super().form_invalid(form)


class HtmxDetailView(DetailView):
    """
    HTMX 详情视图基类
    """

    htmx_template_name: str | None = None
    """HTMX 请求使用的模板（通常是详情片段）"""

    def get_template_names(self) -> list[str]:
        """
        根据 HTMX 请求返回不同的模板

        Returns:
            模板名称列表
        """
        if is_htmx(self.request) and self.htmx_template_name:
            return [self.htmx_template_name]
        return super().get_template_names()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """
        获取模板上下文

        Args:
            **kwargs: 额外的上下文变量

        Returns:
            模板上下文字典
        """
        context = super().get_context_data(**kwargs)
        context['is_htmx'] = is_htmx(self.request)
        return context


class HtmxDeleteView(View):
    """
    HTMX 删除视图基类

    支持删除确认和操作。
    """

    model = None
    """要删除的模型类"""

    success_url: str = None
    """删除成功后的重定向 URL"""

    success_message: str = '删除成功'
    """成功消息"""

    def get_object(self, queryset: QuerySet | None = None) -> Any:
        """
        获取要删除的对象

        Args:
            queryset: 查询集（可选）

        Returns:
            模型实例
        """
        pk = self.kwargs.get('pk')
        return self.model.objects.get(pk=pk)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """
        处理 POST 请求

        Args:
            request: HTTP 请求
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            HTTP 响应
        """
        obj = self.get_object()
        obj.delete()

        if is_htmx(request):
            return JsonResponse({
                'success': True,
                'message': self.success_message
            }, headers={
                'X-Success-Message': self.success_message
            })

        if request.headers.get('HX-Trigger') == 'delete-confirm':
            return JsonResponse({'success': True})

        return redirect(self.success_url)


class HtmxPartialView(View):
    """
    HTMX 部分内容视图

    用于返回可被 HTMX 替换的部分 HTML 内容。
    """

    template_name: str = None
    """模板名称"""

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """
        处理 GET 请求

        Args:
            request: HTTP 请求
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            HTTP 响应
        """
        context = self.get_context_data(**kwargs)
        return render(request, self.template_name, context)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """
        处理 POST 请求

        Args:
            request: HTTP 请求
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            HTTP 响应
        """
        context = self.get_context_data(**kwargs)
        return render(request, self.template_name, context)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """
        获取模板上下文

        Args:
            **kwargs: 额外的上下文变量

        Returns:
            模板上下文字典
        """
        context = {
            'params': kwargs,
            'request': self.request
        }
        context['is_htmx'] = is_htmx(self.request)
        return context


# 混合类（Mixins）

class StaffRequiredMixin(UserPassesTestMixin):
    """
    要求用户为工作人员（staff）的混合类
    """

    def test_func(self) -> bool:
        """
        测试用户是否为 staff

        Returns:
            用户是否为 staff
        """
        return self.request.user.is_staff

    def handle_no_permission(self) -> HttpResponse:
        """
        处理无权限情况

        Returns:
            HTTP 响应
        """
        if is_htmx(self.request):
            return JsonResponse({
                'success': False,
                'message': '需要管理员权限'
            }, status=403, headers={
                'X-Error-Title': '权限不足',
                'X-Error-Message': '此操作需要管理员权限'
            })

        return super().handle_no_permission()


class SuperuserRequiredMixin(UserPassesTestMixin):
    """
    要求用户为超级用户的混合类
    """

    def test_func(self) -> bool:
        """
        测试用户是否为超级用户

        Returns:
            用户是否为超级用户
        """
        return self.request.user.is_superuser

    def handle_no_permission(self) -> HttpResponse:
        """
        处理无权限情况

        Returns:
            HTTP 响应
        """
        if is_htmx(self.request):
            return JsonResponse({
                'success': False,
                'message': '需要超级管理员权限'
            }, status=403, headers={
                'X-Error-Title': '权限不足',
                'X-Error-Message': '此操作需要超级管理员权限'
            })

        return super().handle_no_permission()


class HtmxResponseMixin:
    """
    HTMX 响应混合类

    为视图添加 HTMX 响应头支持。
    """

    def render_to_response(self, context: dict[str, Any], **response_kwargs: Any) -> HttpResponse:
        """
        渲染响应并添加 HTMX 头部

        Args:
            context: 模板上下文
            **response_kwargs: 额外的响应参数

        Returns:
            HTTP 响应
        """
        response = super().render_to_response(context, **response_kwargs)

        if is_htmx(self.request):
            # 触发客户端事件
            response['HX-Trigger'] = 'contentUpdated'

            # 可以添加其他自定义头部
            if hasattr(self, 'htmx_trigger'):
                response['HX-Trigger'] = self.htmx_trigger

        return response
