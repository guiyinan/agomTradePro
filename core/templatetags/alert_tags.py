"""
Alert Template Tags

提供告警横幅的渲染模板标签。
"""

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def render_alerts(alerts):
    """
    渲染告警横幅

    用法: {% render_alerts global_alerts %}
    """
    if not alerts:
        return ''

    html = '<div class="global-alerts-container">'

    for alert in alerts:
        alert_type = alert.get('type', 'info')
        icon = alert.get('icon', 'ℹ️')
        title = alert.get('title', '')
        message = alert.get('message', '')
        action_url = alert.get('action_url', '')
        action_text = alert.get('action_text', '查看')
        dismissible = alert.get('dismissible', True)

        html += f'''
        <div class="alert alert-{alert_type}" data-dismissible="{str(dismissible).lower()}">
            <span class="alert-icon">{icon}</span>
            <div class="alert-content">
                <strong>{title}</strong>
                <span>{message}</span>
            </div>
        '''

        if action_url:
            html += f'''
            <a href="{action_url}" class="alert-action">{action_text}</a>
            '''

        if dismissible:
            html += '''
            <button class="alert-close" onclick="dismissAlert(this)">&times;</button>
            '''

        html += '</div>'

    html += '</div>'

    return mark_safe(html)


@register.inclusion_tag('components/alert_banner.html')
def alert_banner(alerts):
    """
    渲染告警横幅（使用独立模板）

    用法: {% alert_banner global_alerts %}
    """
    return {'alerts': alerts}


@register.filter
def alert_type_class(alert_type):
    """获取告警类型对应的 CSS 类名"""
    type_map = {
        'danger': 'alert-danger',
        'warning': 'alert-warning',
        'success': 'alert-success',
        'info': 'alert-info',
    }
    return type_map.get(alert_type, 'alert-info')


@register.filter
def alert_icon_bg(alert_type):
    """获取告警类型对应的图标背景色"""
    color_map = {
        'danger': '#FFEBEE',
        'warning': '#FFF3E0',
        'success': '#E8F5E9',
        'info': '#E3F2FD',
    }
    return color_map.get(alert_type, '#E3F2FD')
