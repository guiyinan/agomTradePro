"""Audit module template filters."""

from django import template

register = template.Library()


@register.filter
def percentage(value, decimals=2):
    """Format a float as a percentage string.

    Usage: {{ 0.1234|percentage:2 }} → "+12.34%"
    """
    try:
        value = float(value)
        decimals = int(decimals)
    except (TypeError, ValueError):
        return "-"

    pct = value * 100
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.{decimals}f}%"


@register.filter
def absolute_width(value, max_width=100):
    """Convert a float value to absolute percentage width for progress bars.

    Usage: {{ 0.05|absolute_width:100 }} → "50"
    Maps abs(value)*100 to a 0-max_width range, capped at max_width.
    """
    try:
        value = float(value)
        max_width = int(max_width)
    except (TypeError, ValueError):
        return "0"

    width = min(abs(value) * 100, max_width)
    return f"{width:.0f}"
