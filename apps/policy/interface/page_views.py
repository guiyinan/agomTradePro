"""Policy HTML page views."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import CreateView, ListView, UpdateView

from ..infrastructure.models import (
    PolicyLevelKeywordModel,
    PolicyLog,
    RSSFetchLog,
    RSSSourceConfigModel,
)
from .forms import PolicyEventForm, PolicyKeywordForm, RSSSourceForm

class RSSSourceListView(LoginRequiredMixin, ListView):
    """RSS源管理页面"""
    model = RSSSourceConfigModel
    template_name = 'policy/rss_manage.html'
    context_object_name = 'sources'
    paginate_by = 20

    def get_queryset(self):
        queryset = RSSSourceConfigModel._default_manager.all()
        category = self.request.GET.get('category')
        is_active = self.request.GET.get('is_active')
        search = self.request.GET.get('search')

        if category:
            queryset = queryset.filter(category=category)
        if is_active:
            queryset = queryset.filter(is_active=is_active == 'true')
        if search:
            queryset = queryset.filter(name__icontains=search)

        return queryset.order_by('category', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = RSSSourceConfigModel.CATEGORY_CHOICES
        context['selected_category'] = self.request.GET.get('category', '')
        context['selected_active'] = self.request.GET.get('is_active', '')
        context['search_query'] = self.request.GET.get('search', '')
        return context

class RSSKeywordListView(LoginRequiredMixin, ListView):
    """关键词规则管理页面"""
    model = PolicyLevelKeywordModel
    template_name = 'policy/rss_keywords.html'
    context_object_name = 'keywords'
    paginate_by = 20

    def get_queryset(self):
        queryset = PolicyLevelKeywordModel._default_manager.all()
        level = self.request.GET.get('level')
        is_active = self.request.GET.get('is_active')

        if level:
            queryset = queryset.filter(level=level)
        if is_active:
            queryset = queryset.filter(is_active=is_active == 'true')

        return queryset.order_by('-weight', 'level')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['levels'] = PolicyLevelKeywordModel.POLICY_LEVELS
        context['selected_level'] = self.request.GET.get('level', '')
        context['selected_active'] = self.request.GET.get('is_active', '')
        return context

class RSSFetchLogListView(LoginRequiredMixin, ListView):
    """抓取日志查询页面"""
    model = RSSFetchLog
    template_name = 'policy/rss_logs.html'
    context_object_name = 'logs'
    paginate_by = 50

    def get_queryset(self):
        queryset = RSSFetchLog._default_manager.select_related('source').all()
        source_id = self.request.GET.get('source')
        status_filter = self.request.GET.get('status')

        if source_id:
            queryset = queryset.filter(source_id=source_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset.order_by('-fetched_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sources'] = RSSSourceConfigModel._default_manager.all()
        context['statuses'] = RSSFetchLog.STATUS_CHOICES
        context['selected_source'] = self.request.GET.get('source', '')
        context['selected_status'] = self.request.GET.get('status', '')

        # 添加统计数据
        queryset = self.get_queryset()
        context['success_count'] = queryset.filter(status='success').count()
        context['error_count'] = queryset.filter(status='error').count()

        return context

class RSSReaderView(LoginRequiredMixin, ListView):
    """RSS阅读器页面 - 显示抓取的文章"""
    model = PolicyLog
    template_name = 'policy/rss_reader.html'
    context_object_name = 'items'
    paginate_by = 20

    def get_queryset(self):
        # 使用 rss_source 作为外键
        queryset = PolicyLog._default_manager.select_related('rss_source').all()
        source_id = self.request.GET.get('source')
        level = self.request.GET.get('level')
        category = self.request.GET.get('category')

        if source_id:
            queryset = queryset.filter(rss_source_id=source_id)
        if level:
            queryset = queryset.filter(level=level)
        if category:
            queryset = queryset.filter(info_category=category)

        # 按事件日期排序，最新的在前
        return queryset.order_by('-event_date', '-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sources'] = RSSSourceConfigModel._default_manager.all()
        context['levels'] = PolicyLog.POLICY_LEVELS
        context['categories'] = PolicyLog.INFO_CATEGORY_CHOICES
        context['selected_source'] = self.request.GET.get('source', '')
        context['selected_level'] = self.request.GET.get('level', '')
        context['selected_category'] = self.request.GET.get('category', '')

        # 统计数据
        queryset = self.get_queryset()
        from django.utils import timezone
        today = timezone.now().date()
        context['total_items'] = queryset.count()
        context['today_items'] = queryset.filter(created_at__date=today).count()
        context['p3_items'] = queryset.filter(level='P3').count()

        return context

class PolicyEventsPageView(LoginRequiredMixin, ListView):
    """Policy events list page (HTML)"""
    model = PolicyLog
    template_name = 'policy/policy_events.html'
    context_object_name = 'events'
    paginate_by = 20

    def get_queryset(self):
        queryset = PolicyLog._default_manager.all()
        level = self.request.GET.get('level')
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')

        if level:
            queryset = queryset.filter(level=level)
        if start_date:
            queryset = queryset.filter(event_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(event_date__lte=end_date)

        return queryset.order_by('-event_date', '-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['levels'] = PolicyLog.POLICY_LEVELS
        context['selected_level'] = self.request.GET.get('level', '')
        context['selected_start'] = self.request.GET.get('start_date', '')
        context['selected_end'] = self.request.GET.get('end_date', '')
        return context

class PolicyEventCreateView(LoginRequiredMixin, CreateView):
    """Create policy event without Django admin."""

    model = PolicyLog
    form_class = PolicyEventForm
    template_name = "policy/policy_event_form.html"
    success_url = reverse_lazy("policy:events-page")

    def form_valid(self, form):
        messages.success(self.request, "政策事件已创建")
        return super().form_valid(form)

class RSSSourceCreateView(LoginRequiredMixin, CreateView):
    """Create RSS source without Django admin."""

    model = RSSSourceConfigModel
    form_class = RSSSourceForm
    template_name = "policy/rss_source_form.html"
    success_url = reverse_lazy("policy:rss-manage")

    def form_valid(self, form):
        messages.success(self.request, "RSS 源已创建")
        return super().form_valid(form)

class RSSSourceUpdateView(LoginRequiredMixin, UpdateView):
    """Update RSS source without Django admin."""

    model = RSSSourceConfigModel
    form_class = RSSSourceForm
    template_name = "policy/rss_source_form.html"
    success_url = reverse_lazy("policy:rss-manage")
    pk_url_kwarg = "source_id"

    def form_valid(self, form):
        messages.success(self.request, "RSS 源已更新")
        return super().form_valid(form)

class PolicyKeywordCreateView(LoginRequiredMixin, CreateView):
    """Create policy keyword rule without Django admin."""

    model = PolicyLevelKeywordModel
    form_class = PolicyKeywordForm
    template_name = "policy/keyword_form.html"
    success_url = reverse_lazy("policy:rss-keywords")

    def form_valid(self, form):
        messages.success(self.request, "关键词规则已创建")
        return super().form_valid(form)

class PolicyKeywordUpdateView(LoginRequiredMixin, UpdateView):
    """Update policy keyword rule without Django admin."""

    model = PolicyLevelKeywordModel
    form_class = PolicyKeywordForm
    template_name = "policy/keyword_form.html"
    success_url = reverse_lazy("policy:rss-keywords")
    pk_url_kwarg = "keyword_id"

    def form_valid(self, form):
        messages.success(self.request, "关键词规则已更新")
        return super().form_valid(form)

class WorkbenchView(LoginRequiredMixin, ListView):
    """
    工作台页面视图

    GET /policy/workbench/ - 工作台页面
    """
    template_name = "policy/workbench.html"
    model = PolicyLog
    context_object_name = "events"
    paginate_by = 50

    @method_decorator(ensure_csrf_cookie)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = "工作台"
        context['event_types'] = PolicyLog.EVENT_TYPE_CHOICES
        context['levels'] = PolicyLog.POLICY_LEVELS
        context['gate_levels'] = PolicyLog.GATE_LEVEL_CHOICES
        return context

