"""Policy HTML page views."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import FormView, ListView

from apps.policy.application.repository_provider import (
    get_policy_page_interface_service,
    get_policy_rss_api_interface_service,
)

from .forms import PolicyEventForm, PolicyKeywordForm, RSSSourceForm

page_service = get_policy_page_interface_service()
rss_api_service = get_policy_rss_api_interface_service()

class RSSSourceListView(LoginRequiredMixin, ListView):
    """RSS源管理页面"""
    template_name = 'policy/rss_manage.html'
    context_object_name = 'sources'
    paginate_by = 20

    def get_queryset(self):
        return page_service.list_rss_sources(
            category=self.request.GET.get('category', ''),
            is_active=self.request.GET.get('is_active', ''),
            search=self.request.GET.get('search', ''),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        constants = page_service.get_page_constants()
        context['categories'] = constants['rss_source_categories']
        context['selected_category'] = self.request.GET.get('category', '')
        context['selected_active'] = self.request.GET.get('is_active', '')
        context['search_query'] = self.request.GET.get('search', '')
        return context

class RSSKeywordListView(LoginRequiredMixin, ListView):
    """关键词规则管理页面"""
    template_name = 'policy/rss_keywords.html'
    context_object_name = 'keywords'
    paginate_by = 20

    def get_queryset(self):
        return page_service.list_policy_keywords(
            level=self.request.GET.get('level', ''),
            is_active=self.request.GET.get('is_active', ''),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        constants = page_service.get_page_constants()
        context['levels'] = constants['policy_levels']
        context['selected_level'] = self.request.GET.get('level', '')
        context['selected_active'] = self.request.GET.get('is_active', '')
        return context

class RSSFetchLogListView(LoginRequiredMixin, ListView):
    """抓取日志查询页面"""
    template_name = 'policy/rss_logs.html'
    context_object_name = 'logs'
    paginate_by = 50

    def get_queryset(self):
        return page_service.list_rss_fetch_logs(
            source_id=self.request.GET.get('source', ''),
            status=self.request.GET.get('status', ''),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        summary = page_service.get_rss_fetch_log_summary(
            source_id=self.request.GET.get('source', ''),
            status=self.request.GET.get('status', ''),
        )
        context['sources'] = summary['sources']
        context['statuses'] = summary['statuses']
        context['selected_source'] = self.request.GET.get('source', '')
        context['selected_status'] = self.request.GET.get('status', '')
        context['success_count'] = summary['success_count']
        context['error_count'] = summary['error_count']
        return context

class RSSReaderView(LoginRequiredMixin, ListView):
    """RSS阅读器页面 - 显示抓取的文章"""
    template_name = 'policy/rss_reader.html'
    context_object_name = 'items'
    paginate_by = 20

    def get_queryset(self):
        return page_service.list_rss_reader_items(
            source_id=self.request.GET.get('source', ''),
            level=self.request.GET.get('level', ''),
            category=self.request.GET.get('category', ''),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        summary = page_service.get_rss_reader_summary(
            source_id=self.request.GET.get('source', ''),
            level=self.request.GET.get('level', ''),
            category=self.request.GET.get('category', ''),
        )
        context['sources'] = summary['sources']
        context['levels'] = summary['levels']
        context['categories'] = summary['categories']
        context['selected_source'] = self.request.GET.get('source', '')
        context['selected_level'] = self.request.GET.get('level', '')
        context['selected_category'] = self.request.GET.get('category', '')
        context['total_items'] = summary['total_items']
        context['today_items'] = summary['today_items']
        context['p3_items'] = summary['p3_items']
        return context

class PolicyEventsPageView(LoginRequiredMixin, ListView):
    """Policy events list page (HTML)"""
    template_name = 'policy/policy_events.html'
    context_object_name = 'events'
    paginate_by = 20

    def get_queryset(self):
        return page_service.list_policy_events(
            level=self.request.GET.get('level', ''),
            start_date=self.request.GET.get('start_date', ''),
            end_date=self.request.GET.get('end_date', ''),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        constants = page_service.get_page_constants()
        context['levels'] = constants['policy_levels']
        context['selected_level'] = self.request.GET.get('level', '')
        context['selected_start'] = self.request.GET.get('start_date', '')
        context['selected_end'] = self.request.GET.get('end_date', '')
        return context

class PolicyEventCreateView(LoginRequiredMixin, FormView):
    """Create policy event without Django admin."""

    form_class = PolicyEventForm
    template_name = "policy/policy_event_form.html"
    success_url = reverse_lazy("policy:events-page")

    def form_valid(self, form):
        page_service.create_policy_event(form.to_payload())
        messages.success(self.request, "政策事件已创建")
        return super().form_valid(form)


class RSSSourceCreateView(LoginRequiredMixin, FormView):
    """Create RSS source without Django admin."""

    form_class = RSSSourceForm
    template_name = "policy/rss_source_form.html"
    success_url = reverse_lazy("policy:rss-manage")

    def form_valid(self, form):
        rss_api_service.create_rss_source_config(form.to_payload())
        messages.success(self.request, "RSS 源已创建")
        return super().form_valid(form)


class RSSSourceUpdateView(LoginRequiredMixin, FormView):
    """Update RSS source without Django admin."""

    form_class = RSSSourceForm
    template_name = "policy/rss_source_form.html"
    success_url = reverse_lazy("policy:rss-manage")
    pk_url_kwarg = "source_id"

    def dispatch(self, request, *args, **kwargs):
        self.source = rss_api_service.get_rss_source_config(kwargs[self.pk_url_kwarg])
        if self.source is None:
            raise Http404("RSS source not found")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.source
        return kwargs

    def form_valid(self, form):
        rss_api_service.update_rss_source_config(self.source.id, form.to_payload())
        messages.success(self.request, "RSS 源已更新")
        return super().form_valid(form)


class PolicyKeywordCreateView(LoginRequiredMixin, FormView):
    """Create policy keyword rule without Django admin."""

    form_class = PolicyKeywordForm
    template_name = "policy/keyword_form.html"
    success_url = reverse_lazy("policy:rss-keywords")

    def form_valid(self, form):
        rss_api_service.create_policy_level_keyword(form.to_payload())
        messages.success(self.request, "关键词规则已创建")
        return super().form_valid(form)


class PolicyKeywordUpdateView(LoginRequiredMixin, FormView):
    """Update policy keyword rule without Django admin."""

    form_class = PolicyKeywordForm
    template_name = "policy/keyword_form.html"
    success_url = reverse_lazy("policy:rss-keywords")
    pk_url_kwarg = "keyword_id"

    def dispatch(self, request, *args, **kwargs):
        self.keyword = rss_api_service.get_policy_level_keyword(kwargs[self.pk_url_kwarg])
        if self.keyword is None:
            raise Http404("Policy keyword not found")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.keyword
        return kwargs

    def form_valid(self, form):
        rss_api_service.update_policy_level_keyword(self.keyword.id, form.to_payload())
        messages.success(self.request, "关键词规则已更新")
        return super().form_valid(form)

class WorkbenchView(LoginRequiredMixin, ListView):
    """
    工作台页面视图

    GET /policy/workbench/ - 工作台页面
    """
    template_name = "policy/workbench.html"
    context_object_name = "events"
    paginate_by = 50

    @method_decorator(ensure_csrf_cookie)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_queryset(self):
        return []

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        constants = page_service.get_page_constants()
        context['title'] = "工作台"
        context['event_types'] = constants['event_types']
        context['levels'] = constants['policy_levels']
        context['gate_levels'] = constants['gate_levels']
        return context

