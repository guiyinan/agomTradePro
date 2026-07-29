"""
Alert Template Tags

提供告警横幅的渲染模板标签。
"""

from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit

from django import template
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString

register = template.Library()


@register.simple_tag
def render_alerts(alerts: Iterable[Mapping[str, object]] | None) -> SafeString:
    """
    渲染告警横幅

    用法: {% render_alerts global_alerts %}
    """
    if not alerts:
        return SafeString("")

    rendered_alerts: list[SafeString] = []

    for alert in alerts:
        alert_type = str(alert.get("type", "info"))
        if alert_type not in {"danger", "warning", "success", "info"}:
            alert_type = "info"
        icon = alert.get("icon", "ℹ️")
        title = alert.get("title", "")
        message = alert.get("message", "")
        action_url = _safe_action_url(alert.get("action_url", ""))
        action_text = alert.get("action_text", "查看")
        dismissible = alert.get("dismissible", True) is True
        action_html = (
            format_html('<a href="{}" class="alert-action">{}</a>', action_url, action_text)
            if action_url
            else SafeString("")
        )
        close_html = (
            format_html(
                '<button class="alert-close" onclick="dismissAlert(this)">{}</button>',
                "×",
            )
            if dismissible
            else SafeString("")
        )
        rendered_alerts.append(
            format_html(
                """
        <div class="alert alert-{}" data-dismissible="{}">
            <span class="alert-icon">{}</span>
            <div class="alert-content">
                <strong>{}</strong>
                <span>{}</span>
            </div>
            {}
            {}
        </div>
        """,
                alert_type,
                str(dismissible).lower(),
                icon,
                title,
                message,
                action_html,
                close_html,
            )
        )

    return format_html(
        '<div class="global-alerts-container">{}</div>',
        format_html_join("", "{}", ((item,) for item in rendered_alerts)),
    )


def _safe_action_url(value: object) -> str:
    """Allow local or HTTP(S) alert links without credentials."""

    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 2048 or any(ord(char) < 32 for char in candidate):
        return ""
    parsed = urlsplit(candidate)
    if parsed.username or parsed.password:
        return ""
    if parsed.scheme:
        return candidate if parsed.scheme in {"http", "https"} and parsed.hostname else ""
    return candidate if candidate.startswith("/") and not candidate.startswith("//") else ""


@register.inclusion_tag("components/alert_banner.html")
def alert_banner(
    alerts: Iterable[Mapping[str, object]] | None,
) -> dict[str, Iterable[Mapping[str, object]] | None]:
    """
    渲染告警横幅（使用独立模板）

    用法: {% alert_banner global_alerts %}
    """
    return {"alerts": alerts}


@register.filter
def alert_type_class(alert_type: object) -> str:
    """获取告警类型对应的 CSS 类名"""
    type_map = {
        "danger": "alert-danger",
        "warning": "alert-warning",
        "success": "alert-success",
        "info": "alert-info",
    }
    return type_map.get(str(alert_type), "alert-info")


@register.filter
def alert_icon_bg(alert_type: object) -> str:
    """获取告警类型对应的图标背景色"""
    color_map = {
        "danger": "#FFEBEE",
        "warning": "#FFF3E0",
        "success": "#E8F5E9",
        "info": "#E3F2FD",
    }
    return color_map.get(str(alert_type), "#E3F2FD")
