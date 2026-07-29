"""Audit module template filters."""

from math import isfinite
from typing import Any

from django import template

register = template.Library()


@register.filter
def percentage(value: Any, decimals: Any = 2) -> str:
    """Format a float as a percentage string.

    Usage: {{ 0.1234|percentage:2 }} → "+12.34%"
    """
    try:
        numeric_value = float(value)
        decimal_places = int(decimals)
    except (OverflowError, TypeError, ValueError):
        return "-"
    if not isfinite(numeric_value) or not 0 <= decimal_places <= 8:
        return "-"

    pct = numeric_value * 100
    if not isfinite(pct):
        return "-"
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.{decimal_places}f}%"


@register.filter
def absolute_width(value: Any, max_width: Any = 100) -> str:
    """Convert a float value to absolute percentage width for progress bars.

    Usage: {{ 0.05|absolute_width:100 }} → "50"
    Maps abs(value)*100 to a 0-max_width range, capped at max_width.
    """
    try:
        numeric_value = float(value)
        width_limit = int(max_width)
    except (OverflowError, TypeError, ValueError):
        return "0"
    if not isfinite(numeric_value) or not 0 <= width_limit <= 10_000:
        return "0"

    width = min(abs(numeric_value) * 100, width_limit)
    return f"{width:.0f}"
