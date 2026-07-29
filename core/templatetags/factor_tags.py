"""
Template tags for Factor module.
"""

import math
from collections.abc import Mapping
from typing import Any, cast

from django import template

register = template.Library()


def _number(value: object) -> float:
    """Convert template input at the dynamic boundary to a finite float."""

    result = float(cast(Any, value))
    if not math.isfinite(result):
        raise ValueError("numeric template input must be finite")
    return result


def _invalid_arithmetic_fallback(value: object) -> float | object:
    """Preserve legacy text fallbacks while suppressing non-finite tokens."""

    return 0.0 if str(value).strip().lower() in {"nan", "inf", "+inf", "-inf"} else value


@register.filter
def lookup(mapping: Mapping[Any, Any] | None, key: object) -> Any:
    """
    Dictionary lookup filter for templates.
    Usage: {{ dict|lookup:key }}
    """
    if mapping is None:
        return ""
    return mapping.get(key, "")


@register.filter
def divide(value: object, arg: object) -> float:
    """
    Divide value by arg.
    Usage: {{ value|divide:2 }}
    """
    try:
        return _number(value) / _number(arg)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


@register.filter
def subtract(value: object, arg: object) -> float | object:
    """
    Subtract arg from value.
    Usage: {{ value|subtract:1 }}
    """
    try:
        return _number(value) - _number(arg)
    except (ValueError, TypeError):
        return _invalid_arithmetic_fallback(value)


@register.filter
def add(value: object, arg: object) -> float | object:
    """
    Add arg to value.
    Usage: {{ value|add:1 }}
    """
    try:
        return _number(value) + _number(arg)
    except (ValueError, TypeError):
        return _invalid_arithmetic_fallback(value)
