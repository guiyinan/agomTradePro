"""
Template tags for Factor module.
"""

from django import template

register = template.Library()


@register.filter
def lookup(d, key):
    """
    Dictionary lookup filter for templates.
    Usage: {{ dict|lookup:key }}
    """
    if d is None:
        return ''
    return d.get(key, '')


@register.filter
def divide(value, arg):
    """
    Divide value by arg.
    Usage: {{ value|divide:2 }}
    """
    try:
        return float(value) / float(arg)
    except (ValueError, ZeroDivisionError):
        return 0


@register.filter
def subtract(value, arg):
    """
    Subtract arg from value.
    Usage: {{ value|subtract:1 }}
    """
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return value


@register.filter
def add(value, arg):
    """
    Add arg to value.
    Usage: {{ value|add:1 }}
    """
    try:
        return float(value) + float(arg)
    except (ValueError, TypeError):
        return value
