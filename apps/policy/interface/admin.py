"""
Django Admin for Policy Events.

增强的管理界面，提供统计、筛选和快速操作功能。
"""

from django.apps import apps as django_apps
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from ..application.repository_provider import get_policy_admin_interface_service
from ..domain.entities import PolicyLevel

PolicyAuditQueue = django_apps.get_model("policy", "PolicyAuditQueue")
PolicyLevelKeywordModel = django_apps.get_model("policy", "PolicyLevelKeywordModel")
PolicyLog = django_apps.get_model("policy", "PolicyLog")
RSSFetchLog = django_apps.get_model("policy", "RSSFetchLog")
RSSHubGlobalConfig = django_apps.get_model("policy", "RSSHubGlobalConfig")
RSSSourceConfigModel = django_apps.get_model("policy", "RSSSourceConfigModel")


def _policy_admin_service():
    """Return the policy admin interface service."""

    return get_policy_admin_interface_service()


@admin.register(PolicyLog)
class PolicyLogAdmin(admin.ModelAdmin):
    """政策事件管理界面（增强版）"""

    # 列表页配置
    list_display = [
        'event_date',
        'level_badge',
        'category_badge',
        'title',
        'audit_status_badge',
        'ai_confidence_display',
        'evidence_link',
        'created_at',
    ]
    list_filter = [
        'level',
        'info_category',
        'audit_status',
        'risk_impact',
        'is_blacklist',
        'is_whitelist',
        'event_date',
        'created_at'
    ]
    search_fields = ['title', 'description', 'evidence_url']
    date_hierarchy = 'event_date'
    ordering = ['-event_date']

    # 详情页配置
    fieldsets = (
        ('基本信息', {
            'fields': ('event_date', 'level', 'title', 'info_category')
        }),
        ('详细内容', {
            'fields': ('description', 'evidence_url'),
            'classes': ('collapse',)
        }),
        ('AI分类信息', {
            'fields': (
                'audit_status',
                'ai_confidence',
                'structured_data',
                'risk_impact'
            ),
            'classes': ('collapse',)
        }),
        ('审核信息', {
            'fields': ('reviewed_by', 'reviewed_at', 'review_notes'),
            'classes': ('collapse',)
        }),
        ('RSS来源', {
            'fields': ('rss_source', 'rss_item_guid'),
            'classes': ('collapse',)
        }),
        ('风险控制', {
            'fields': ('is_blacklist', 'is_whitelist'),
            'classes': ('collapse',)
        }),
        ('元数据', {
            'fields': ('processing_metadata',),
            'classes': ('collapse',)
        }),
        ('系统信息', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'processing_metadata', 'rss_item_guid']

    # 列表页操作
    actions = [
        'mark_as_p0', 'mark_as_p1', 'mark_as_p2', 'mark_as_p3',
        'approve_selected', 'reject_selected',
        'add_to_whitelist', 'add_to_blacklist',
        'auto_assign_audits'
    ]

    # 每页显示数量
    list_per_page = 25

    def level_badge(self, obj):
        """带颜色的档位标签"""
        colors = {
            'P0': '#6c757d',  # 灰色
            'P1': '#ffc107',  # 黄色
            'P2': '#fd7e14',  # 橙色
            'P3': '#dc3545',  # 红色
        }
        color = colors.get(obj.level, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px; font-weight: bold;">{}</span>',
            color, obj.get_level_display()
        )
    level_badge.short_description = '档位'
    level_badge.admin_order_field = 'level'

    def category_badge(self, obj):
        """信息分类标签"""
        colors = {
            'macro': '#007bff',
            'sector': '#28a745',
            'individual': '#fd7e14',
            'sentiment': '#6f42c1',
            'other': '#6c757d',
        }
        color = colors.get(obj.info_category, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px;">{}</span>',
            color, obj.get_info_category_display()
        )
    category_badge.short_description = '分类'
    category_badge.admin_order_field = 'info_category'

    def audit_status_badge(self, obj):
        """审核状态标签"""
        colors = {
            'pending_review': '#ffc107',
            'auto_approved': '#17a2b8',
            'manual_approved': '#28a745',
            'rejected': '#dc3545',
        }
        color = colors.get(obj.audit_status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px;">{}</span>',
            color, obj.get_audit_status_display()
        )
    audit_status_badge.short_description = '审核状态'
    audit_status_badge.admin_order_field = 'audit_status'

    def ai_confidence_display(self, obj):
        """AI置信度显示"""
        if obj.ai_confidence is None:
            return '-'

        confidence = obj.ai_confidence
        if confidence >= 0.75:
            color = '#28a745'
            label = f'{confidence:.2f} ✅'
        elif confidence >= 0.5:
            color = '#ffc107'
            label = f'{confidence:.2f} ⚠️'
        else:
            color = '#dc3545'
            label = f'{confidence:.2f} ❌'

        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, label
        )
    ai_confidence_display.short_description = 'AI置信度'
    ai_confidence_display.admin_order_field = 'ai_confidence'

    def evidence_link(self, obj):
        """证据链接"""
        if obj.evidence_url:
            return format_html(
                '<a href="{}" target="_blank" title="{}">'
                '<span style="font-size: 16px;">🔗</span> 查看证据</a>',
                obj.evidence_url,
                obj.evidence_url
            )
        return '-'
    evidence_link.short_description = '证据'

    # 批量操作
    def mark_as_p0(self, request, queryset):
        """批量标记为 P0"""
        updated = _policy_admin_service().mark_policy_logs_level(
            list(queryset.values_list('id', flat=True)),
            level='P0',
        )
        self.message_user(request, f'{updated} 条事件已标记为 P0（常态）')
    mark_as_p0.short_description = '标记为 P0（常态）'

    def mark_as_p1(self, request, queryset):
        """批量标记为 P1"""
        updated = _policy_admin_service().mark_policy_logs_level(
            list(queryset.values_list('id', flat=True)),
            level='P1',
        )
        self.message_user(request, f'{updated} 条事件已标记为 P1（预警）')
    mark_as_p1.short_description = '标记为 P1（预警）'

    def mark_as_p2(self, request, queryset):
        """批量标记为 P2"""
        updated = _policy_admin_service().mark_policy_logs_level(
            list(queryset.values_list('id', flat=True)),
            level='P2',
        )
        self.message_user(request, f'{updated} 条事件已标记为 P2（干预）')
    mark_as_p2.short_description = '标记为 P2（干预）'

    def mark_as_p3(self, request, queryset):
        """批量标记为 P3"""
        updated = _policy_admin_service().mark_policy_logs_level(
            list(queryset.values_list('id', flat=True)),
            level='P3',
        )
        self.message_user(request, f'{updated} 条事件已标记为 P3（危机）')
    mark_as_p3.short_description = '标记为 P3（危机）'

    def approve_selected(self, request, queryset):
        """批量通过"""
        count = _policy_admin_service().approve_policy_logs(
            list(queryset.values_list('id', flat=True)),
            reviewer_id=request.user.id,
        )
        self.message_user(request, f'✅ 已通过 {count} 条政策')
    approve_selected.short_description = '✅ 批量通过选中项'

    def reject_selected(self, request, queryset):
        """批量拒绝"""
        count = _policy_admin_service().reject_policy_logs(
            list(queryset.values_list('id', flat=True)),
            reviewer_id=request.user.id,
            review_notes='批量拒绝',
        )
        self.message_user(request, f'❌ 已拒绝 {count} 条政策')
    reject_selected.short_description = '❌ 批量拒绝选中项'

    def add_to_whitelist(self, request, queryset):
        """加入白名单"""
        updated = _policy_admin_service().set_policy_list_flags(
            list(queryset.values_list('id', flat=True)),
            is_whitelist=True,
            is_blacklist=False,
        )
        self.message_user(request, f'⭐ 已将 {updated} 条政策加入白名单')
    add_to_whitelist.short_description = '⭐ 加入白名单'

    def add_to_blacklist(self, request, queryset):
        """加入黑名单"""
        updated = _policy_admin_service().set_policy_list_flags(
            list(queryset.values_list('id', flat=True)),
            is_whitelist=False,
            is_blacklist=True,
        )
        self.message_user(request, f'🚫 已将 {updated} 条政策加入黑名单')
    add_to_blacklist.short_description = '🚫 加入黑名单'

    def auto_assign_audits(self, request, queryset):
        """自动分配审核任务"""
        from ..application.use_cases import AutoAssignAuditsUseCase

        use_case = AutoAssignAuditsUseCase()
        results = use_case.execute(max_per_user=10)

        self.message_user(
            request,
            f'🔄 已分配 {results["assigned"]} 条审核任务 '
            f'给 {results["auditors"]} 位审核人员'
        )
    auto_assign_audits.short_description = '🔄 自动分配审核任务'

    def changelist_view(self, request, extra_context=None):
        """自定义列表页，添加统计信息"""
        response = super().changelist_view(request, extra_context)

        try:
            # 获取统计数据
            stats = _policy_admin_service().get_policy_log_statistics()
            total = stats['total']
            level_counts = stats['level_counts']
            category_counts = stats['category_counts']
            audit_counts = stats['audit_counts']

            # 构建统计信息
            stats_html = '<div style="padding: 15px; background: #f8f9fa; '
            stats_html += 'border-radius: 8px; margin-bottom: 20px;">'
            stats_html += '<h3 style="margin-top: 0; color: #495057;">'
            stats_html += '📊 政策事件统计</h3>'

            # 添加多个表格
            stats_html += '<div style="display: flex; gap: 20px;">'

            # 档位统计
            stats_html += '<div style="flex: 1;"><h4>按档位</h4><table style="width: 100%;">'
            for level_code, level_name in PolicyLog.POLICY_LEVELS:
                count = level_counts.get(level_code, 0)
                pct = (count / total * 100) if total > 0 else 0
                colors = {'P0': '#6c757d', 'P1': '#ffc107', 'P2': '#fd7e14', 'P3': '#dc3545'}
                color = colors.get(level_code, '#6c757d')
                stats_html += f'<tr><td style="padding: 4px;"><span style="color: {color};">●</span> {level_name}</td>'
                stats_html += f'<td style="padding: 4px;"><strong>{count}</strong></td><td style="padding: 4px;">{pct:.1f}%</td></tr>'
            stats_html += '</table></div>'

            # 分类统计
            stats_html += '<div style="flex: 1;"><h4>按分类</h4><table style="width: 100%;">'
            for cat_code, count in category_counts.items():
                cat_name = dict(PolicyLog.INFO_CATEGORY_CHOICES).get(cat_code, cat_code)
                pct = (count / total * 100) if total > 0 else 0
                stats_html += f'<tr><td style="padding: 4px;">{cat_name}</td>'
                stats_html += f'<td style="padding: 4px;"><strong>{count}</strong></td><td style="padding: 4px;">{pct:.1f}%</td></tr>'
            stats_html += '</table></div>'

            # 审核状态统计
            stats_html += '<div style="flex: 1;"><h4>审核状态</h4><table style="width: 100%;">'
            for status_code, count in audit_counts.items():
                status_name = dict(PolicyLog.AUDIT_STATUS_CHOICES).get(status_code, status_code)
                pct = (count / total * 100) if total > 0 else 0
                stats_html += f'<tr><td style="padding: 4px;">{status_name}</td>'
                stats_html += f'<td style="padding: 4px;"><strong>{count}</strong></td><td style="padding: 4px;">{pct:.1f}%</td></tr>'
            stats_html += '</table></div>'

            stats_html += '</div>'  # 关闭 flex 容器
            stats_html += f'<p style="margin-top: 10px;"><strong>总计:</strong> {total} 条</p>'
            stats_html += '</div>'

            # 将统计信息添加到页面
            if response is not None and hasattr(response, 'context_data'):
                response.context_data['stats_html'] = mark_safe(stats_html)

        except Exception as e:
            # 统计失败不影响页面显示
            pass

        return response

    def get_queryset(self, request):
        """优化查询"""
        qs = super().get_queryset(request)
        return qs.select_related('rss_source', 'reviewed_by')


class PolicyLogAdminSite(admin.AdminSite):
    """自定义 Admin 站点（可选）"""

    site_header = 'AgomTradePro 政策管理'
    site_title = 'AgomTradePro'
    index_title = '政策事件管理'

    def get_app_list(self, request):
        """自定义应用列表"""
        app_list = super().get_app_list(request)

        # 添加快捷链接
        for app in app_list:
            if app['app_label'] == 'policy':
                app['models'].insert(0, {
                    'name': '📊 政策状态',
                    'object_name': 'policy_status',
                    'admin_url': '/admin/policy/policylog/?level__exact=P2',
                    'view_only': True,
                })
                break

        return app_list


# ========== RSS 相关 Admin ==========

@admin.register(RSSHubGlobalConfig)
class RSSHubGlobalConfigAdmin(admin.ModelAdmin):
    """RSSHub 全局配置管理（单例模式）"""

    def has_add_permission(self, request):
        """禁止手动添加（单例模式）"""
        return not _policy_admin_service().has_rsshub_global_config()

    def has_delete_permission(self, request, obj=None):
        """禁止删除配置"""
        return False

    list_display = ['enabled_badge', 'base_url', 'has_key_badge', 'default_format', 'updated_at']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('基本配置', {
            'fields': (
                'enabled',
                'base_url',
                'access_key',
                'default_format'
            )
        }),
        ('说明', {
            'fields': (),
            'description': (
                '<div style="padding: 10px; background: #f8f9fa; border-radius: 5px;">'
                '<p><strong> RSSHub 全局配置说明：</strong></p>'
                '<ul>'
                '<li><strong>基址：</strong>本地 RSSHub 服务的地址，如 http://127.0.0.1:1200</li>'
                '<li><strong>访问密钥：</strong>RSSHub 的 ACCESS_KEY，留空表示不使用鉴权</li>'
                '<li><strong>默认格式：</strong>RSS 输出格式（RSS 2.0 / Atom / JSON）</li>'
                '</ul>'
                '<p>单个 RSS 源可以选择使用全局配置或自定义配置。</p>'
                '</div>'
            )
        }),
        ('时间戳', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def enabled_badge(self, obj):
        """启用状态标签"""
        if obj.enabled:
            return format_html(
                '<span style="background-color: #28a745; color: white; '
                'padding: 3px 8px; border-radius: 4px;">✅ 已启用</span>'
            )
        return format_html(
            '<span style="background-color: #6c757d; color: white; '
            'padding: 3px 8px; border-radius: 4px;">❌ 未启用</span>'
        )
    enabled_badge.short_description = '状态'

    def has_key_badge(self, obj):
        """密钥状态标签"""
        if obj.access_key:
            return format_html(
                '<span style="background-color: #007bff; color: white; '
                'padding: 3px 8px; border-radius: 4px;">🔑 已配置</span>'
            )
        return format_html(
            '<span style="background-color: #ffc107; color: black; '
            'padding: 3px 8px; border-radius: 4px;">⚠️ 未配置</span>'
        )
    has_key_badge.short_description = '鉴权'

    def changelist_view(self, request, extra_context=None):
        """自定义列表页（单例模式）"""
        # 如果已有配置，直接跳转到编辑页
        config_id = _policy_admin_service().get_rsshub_global_config_id()
        if config_id is not None:
            return super().change_view(
                request,
                str(config_id),
                extra_context=extra_context
            )
        return super().changelist_view(request, extra_context)


@admin.register(RSSSourceConfigModel)
class RSSSourceConfigAdmin(admin.ModelAdmin):
    """RSS源配置管理"""

    list_display = [
        'name', 'category_badge', 'rsshub_badge', 'is_active',
        'fetch_interval_hours', 'proxy_enabled', 'last_fetch_at',
        'last_fetch_status_badge', 'created_at'
    ]
    list_filter = ['category', 'is_active', 'rsshub_enabled', 'proxy_enabled', 'parser_type', 'last_fetch_status']
    search_fields = ['name', 'url', 'rsshub_route_path']
    readonly_fields = ['last_fetch_at', 'last_fetch_status', 'last_error_message', 'effective_url_display', 'created_at', 'updated_at']
    list_per_page = 20

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'url', 'category', 'is_active')
        }),
        ('RSSHub 配置', {
            'fields': (
                'rsshub_enabled',
                'rsshub_route_path',
                'rsshub_use_global_config',
                'rsshub_custom_base_url',
                'rsshub_custom_access_key',
                'rsshub_format',
                'effective_url_display'
            ),
            'classes': ('collapse',),
            'description': (
                '<div style="padding: 10px; background: #e7f3ff; border-radius: 5px; margin-bottom: 10px;">'
                '<p><strong> RSSHub 模式说明：</strong></p>'
                '<ul>'
                '<li>启用后将忽略「URL」字段，使用「路由路径」构建完整 URL</li>'
                '<li>路由路径示例：/csrc/news/bwj（证监会部门文件）</li>'
                '<li>完整 URL = 基址 + 路由路径 + ?key=密钥&format=格式</li>'
                '<li>可选择使用全局配置或自定义配置</li>'
                '</ul>'
                '</div>'
            )
        }),
        ('抓取配置', {
            'fields': (
                'fetch_interval_hours', 'parser_type',
                'timeout_seconds', 'retry_times', 'extract_content'
            )
        }),
        ('代理配置', {
            'fields': (
                'proxy_enabled', 'proxy_host', 'proxy_port',
                'proxy_username', 'proxy_password', 'proxy_type'
            ),
            'classes': ('collapse',),
        }),
        ('状态监控', {
            'fields': (
                'last_fetch_at', 'last_fetch_status', 'last_error_message'
            ),
            'classes': ('collapse',),
        }),
        ('时间戳', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['test_fetch', 'enable_sources', 'disable_sources']

    def category_badge(self, obj):
        """分类标签"""
        colors = {
            'gov_docs': '#28a745',
            'central_bank': '#007bff',
            'mof': '#6610f2',
            'csrc': '#fd7e14',
            'media': '#17a2b8',
            'other': '#6c757d',
        }
        color = colors.get(obj.category, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px;">{}</span>',
            color, obj.get_category_display()
        )
    category_badge.short_description = '分类'

    def rsshub_badge(self, obj):
        """RSSHub 模式标签"""
        if obj.rsshub_enabled:
            return format_html(
                '<span style="background-color: #6f42c1; color: white; '
                'padding: 3px 8px; border-radius: 4px;">RSSHub</span>'
            )
        return format_html(
            '<span style="background-color: #e9ecef; color: #495057; '
            'padding: 3px 8px; border-radius: 4px;">普通</span>'
        )
    rsshub_badge.short_description = '模式'

    def effective_url_display(self, obj):
        """显示有效 URL（预览）"""
        url = obj.get_effective_url()
        if len(url) > 100:
            url = url[:97] + '...'
        return format_html(
            '<code style="background: #f8f9fa; padding: 5px; '
            'display: block; word-break: break-all;">{}</code>',
            url
        )
    effective_url_display.short_description = '有效 URL（预览）'

    def last_fetch_status_badge(self, obj):
        """最后抓取状态标签"""
        if not obj.last_fetch_status:
            return '-'

        colors = {
            'success': '#28a745',
            'error': '#dc3545',
            'partial': '#ffc107',
        }
        color = colors.get(obj.last_fetch_status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px;">{}</span>',
            color, obj.last_fetch_status.upper()
        )
    last_fetch_status_badge.short_description = '最后状态'

    def test_fetch(self, request, queryset):
        """测试抓取选中的源"""
        from ..application.tasks import fetch_rss_sources

        for source in queryset:
            fetch_rss_sources.delay(source_id=source.id)

        self.message_user(request, f'已启动 {queryset.count()} 个源的测试抓取任务')
    test_fetch.short_description = '🔄 测试抓取选中源'

    def enable_sources(self, request, queryset):
        """批量启用"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'已启用 {updated} 个源')
    enable_sources.short_description = '✅ 批量启用'

    def disable_sources(self, request, queryset):
        """批量禁用"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'已禁用 {updated} 个源')
    disable_sources.short_description = '❌ 批量禁用'


@admin.register(PolicyLevelKeywordModel)
class PolicyLevelKeywordAdmin(admin.ModelAdmin):
    """政策档位关键词规则管理"""

    list_display = [
        'level_badge', 'keywords_preview', 'weight',
        'category', 'is_active', 'created_at'
    ]
    list_filter = ['level', 'is_active', 'category']
    search_fields = ['keywords']
    list_per_page = 20

    def level_badge(self, obj):
        """档位标签"""
        colors = {
            'P0': '#6c757d',
            'P1': '#ffc107',
            'P2': '#fd7e14',
            'P3': '#dc3545',
        }
        color = colors.get(obj.level, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px; font-weight: bold;">{}</span>',
            color, obj.get_level_display()
        )
    level_badge.short_description = '档位'
    level_badge.admin_order_field = 'level'

    def keywords_preview(self, obj):
        """关键词预览"""
        keywords_str = ', '.join(obj.keywords[:5])
        if len(obj.keywords) > 5:
            keywords_str += f' ... (+{len(obj.keywords) - 5})'
        return keywords_str
    keywords_preview.short_description = '关键词'


@admin.register(RSSFetchLog)
class RSSFetchLogAdmin(admin.ModelAdmin):
    """RSS抓取日志管理"""

    list_display = [
        'source_name', 'fetched_at', 'status_badge',
        'items_count', 'new_items_count', 'duration_badge'
    ]
    list_filter = ['status', 'source']
    date_hierarchy = 'fetched_at'
    readonly_fields = ['fetched_at', 'source', 'status', 'items_count',
                      'new_items_count', 'error_message', 'fetch_duration_seconds']
    list_per_page = 30

    def has_add_permission(self, request):
        """禁止手动添加日志"""
        return False

    def has_change_permission(self, request, obj=None):
        """禁止修改日志"""
        return False

    def source_name(self, obj):
        """源名称"""
        return obj.source.name
    source_name.short_description = 'RSS源'
    source_name.admin_order_field = 'source__name'

    def status_badge(self, obj):
        """状态标签"""
        colors = {
            'success': '#28a745',
            'error': '#dc3545',
            'partial': '#ffc107',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = '状态'

    def duration_badge(self, obj):
        """耗时标签"""
        if obj.fetch_duration_seconds is None:
            return '-'

        duration = obj.fetch_duration_seconds
        if duration < 1:
            color = '#28a745'
            text = f'{duration*1000:.0f}ms'
        elif duration < 5:
            color = '#ffc107'
            text = f'{duration:.1f}s'
        else:
            color = '#dc3545'
            text = f'{duration:.1f}s'

        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, text
        )
    duration_badge.short_description = '耗时'
    duration_badge.admin_order_field = 'fetch_duration_seconds'


@admin.register(PolicyAuditQueue)
class PolicyAuditQueueAdmin(admin.ModelAdmin):
    """政策审核队列管理"""

    list_display = [
        'policy_title',
        'policy_level',
        'policy_category',
        'priority_badge',
        'assigned_to',
        'assigned_at',
        'created_at',
    ]
    list_filter = ['priority', 'assigned_to', 'created_at']
    search_fields = ['policy_log__title']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at']
    list_per_page = 30

    fieldsets = (
        ('基本信息', {
            'fields': ('policy_log', 'priority')
        }),
        ('分配信息', {
            'fields': ('assigned_to', 'assigned_at', 'due_date')
        }),
        ('系统信息', {
            'fields': ('created_at', 'auto_rejection_reason'),
            'classes': ('collapse',)
        }),
    )

    def policy_title(self, obj):
        """政策标题"""
        return obj.policy_log.title[:50] + '...' if len(obj.policy_log.title) > 50 else obj.policy_log.title
    policy_title.short_description = '政策标题'

    def policy_level(self, obj):
        """政策档位"""
        colors = {'P0': '#6c757d', 'P1': '#ffc107', 'P2': '#fd7e14', 'P3': '#dc3545'}
        color = colors.get(obj.policy_log.level, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px;">{}</span>',
            color, obj.policy_log.level
        )
    policy_level.short_description = '档位'

    def policy_category(self, obj):
        """政策分类"""
        return obj.policy_log.get_info_category_display()
    policy_category.short_description = '分类'

    def priority_badge(self, obj):
        """优先级标签"""
        colors = {
            'urgent': '#dc3545',
            'high': '#fd7e14',
            'normal': '#17a2b8',
            'low': '#6c757d',
        }
        color = colors.get(obj.priority, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px;">{}</span>',
            color, obj.get_priority_display()
        )
    priority_badge.short_description = '优先级'
    priority_badge.admin_order_field = 'priority'

    actions = ['approve_items', 'reject_items', 'reassign_items']

    def approve_items(self, request, queryset):
        """批量通过"""
        from django.utils import timezone

        count = 0
        for item in queryset:
            item.policy_log.audit_status = 'manual_approved'
            item.policy_log.reviewed_by = request.user
            item.policy_log.reviewed_at = timezone.now()
            item.policy_log.save()
            item.delete()
            count += 1

        self.message_user(request, f'✅ 已通过 {count} 条政策')
    approve_items.short_description = '✅ 批量通过'

    def reject_items(self, request, queryset):
        """批量拒绝"""
        from django.utils import timezone

        count = 0
        for item in queryset:
            item.policy_log.audit_status = 'rejected'
            item.policy_log.reviewed_by = request.user
            item.policy_log.reviewed_at = timezone.now()
            item.policy_log.review_notes = '批量拒绝'
            item.policy_log.save()
            item.delete()
            count += 1

        self.message_user(request, f'❌ 已拒绝 {count} 条政策')
    reject_items.short_description = '❌ 批量拒绝'

    def reassign_items(self, request, queryset):
        """取消分配"""
        count = queryset.update(assigned_to=None, assigned_at=None)
        self.message_user(request, f'🔄 已取消分配 {count} 条政策')
    reassign_items.short_description = '🔄 取消分配'

    def get_queryset(self, request):
        """优化查询"""
        qs = super().get_queryset(request)
        return qs.select_related('policy_log', 'assigned_to')

