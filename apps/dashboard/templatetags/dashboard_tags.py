"""
Dashboard Template Tags

Custom template tags and filters for the dashboard module.
"""

import re
from collections.abc import Mapping
from typing import Any

from django import template

register = template.Library()


@register.filter
def get_item(dictionary: Mapping[Any, Any] | None, key: object) -> Any:
    """
    Get an item from a dictionary using a variable key.

    Usage: {{ mydict|get_item:key_name }}
    """
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter
def get_attr(obj: object | None, attr: object) -> Any:
    """
    Get an attribute from an object using a variable name.

    Usage: {{ myobj|get_attr:attr_name }}
    """
    attribute_name = str(attr or "").strip()
    if obj is None or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", attribute_name):
        return None
    return getattr(obj, attribute_name, None)
