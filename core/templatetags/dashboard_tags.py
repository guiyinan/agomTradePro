"""
Custom Template Tags for Dashboard

提供数学运算和其他有用的模板过滤器。
"""

import json
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def multiply(value, arg):
    """
    将值乘以参数

    Usage:
        {{ 5|multiply:3 }}  # 15
        {{ growth_z|multiply:80 }}
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def divide(value, arg):
    """
    将值除以参数

    Usage:
        {{ 10|divide:2 }}  # 5.0
    """
    try:
        if float(arg) == 0:
            return 0
        return float(value) / float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def add(value, arg):
    """
    将值加上参数

    Usage:
        {{ 5|add:3 }}  # 8
        {{ growth_z|add:3 }}
    """
    try:
        return float(value) + float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def subtract(value, arg):
    """
    从值中减去参数

    Usage:
        {{ 5|subtract:2 }}  # 3
    """
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def percentage(value, decimals=1):
    """
    将小数转换为百分比字符串

    Usage:
        {{ 0.156|percentage }}  # 15.6%
        {{ 0.156|percentage:2 }}  # 15.60%
    """
    try:
        return f"{float(value) * 100:.{decimals}f}%"
    except (ValueError, TypeError):
        return "0%"


@register.filter
def abs_filter(value):
    """
    返回绝对值

    Usage:
        {{ -5|abs_filter }}  # 5
    """
    try:
        return abs(float(value))
    except (ValueError, TypeError):
        return 0


@register.filter
def clamp(value, min_val=None, max_val=None):
    """
    将值限制在指定范围内

    Usage:
        {{ 150|clamp:0:100 }}  # 100
    """
    try:
        val = float(value)
        if min_val is not None:
            val = max(val, float(min_val))
        if max_val is not None:
            val = min(val, float(max_val))
        return val
    except (ValueError, TypeError):
        return value


@register.filter
def range_filter(start, end=None):
    """
    生成范围（类似 Python 的 range）

    Usage:
        {% for i in 5|range_filter %}
            {{ i }}  {# 0, 1, 2, 3, 4 #}
        {% endfor %}

        {% for i in 1|range_filter:5 %}
            {{ i }}  {# 1, 2, 3, 4 #}
        {% endfor %}
    """
    try:
        if end is None:
            return range(int(start))
        else:
            return range(int(start), int(end))
    except (ValueError, TypeError):
        return []


@register.simple_tag
def define(value=None):
    """
    定义一个变量（用于复杂逻辑）

    Usage:
        {% define as my_var %}
        {% define 42 as answer %}
    """
    return value


@register.filter
def to_int(value):
    """
    转换为整数

    Usage:
        {{ 3.14|to_int }}  # 3
    """
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0


@register.filter
def round_filter(value, precision=0):
    """
    四舍五入到指定精度

    Usage:
        {{ 3.14159|round_filter:2 }}  # 3.14
    """
    try:
        return round(float(value), int(precision))
    except (ValueError, TypeError):
        return value


@register.filter
def sign(value):
    """
    返回数字的符号（-1, 0, 1）

    Usage:
        {{ -5|sign }}  # -1
        {{ 0|sign }}   # 0
        {{ 5|sign }}   # 1
    """
    try:
        val = float(value)
        if val > 0:
            return 1
        elif val < 0:
            return -1
        return 0
    except (ValueError, TypeError):
        return 0


@register.filter
def safe_divide(value, arg, default=0):
    """
    安全除法，除以零时返回默认值

    Usage:
        {{ 10|safe_divide:2 }}      # 5.0
        {{ 10|safe_divide:0 }}      # 0
        {{ 10|safe_divide:0:"N/A" }} # "N/A"
    """
    try:
        if float(arg) == 0:
            return default
        return float(value) / float(arg)
    except (ValueError, TypeError):
        return default


@register.filter
def min_filter(value, arg):
    """
    返回两个值中的较小值

    Usage:
        {{ 5|min_filter:10 }}  # 5
    """
    try:
        return min(float(value), float(arg))
    except (ValueError, TypeError):
        return value


@register.filter
def max_filter(value, arg):
    """
    返回两个值中的较大值

    Usage:
        {{ 5|max_filter:10 }}  # 10
    """
    try:
        return max(float(value), float(arg))
    except (ValueError, TypeError):
        return value


@register.filter
def json_serialize(value):
    """
    将值序列化为 JSON 字符串（用于 JavaScript）

    Usage:
        {{ asset_allocation|json_serialize }}
        {{ my_dict|json_serialize }}
    """
    try:
        return mark_safe(json.dumps(value))
    except (TypeError, ValueError):
        return mark_safe('[]')


@register.filter
def offset_and_scale(value, args):
    """
    对值进行偏移和缩放：base + value * scale
    args 格式: "base,scale"

    Usage:
        {{ growth_z|offset_and_scale:"200,80" }}  # 200 + growth_z * 80
    """
    try:
        parts = args.split(',')
        if len(parts) != 2:
            return 0
        base = float(parts[0])
        scale = float(parts[1])
        return base + float(value) * scale
    except (ValueError, TypeError, AttributeError):
        return 0
