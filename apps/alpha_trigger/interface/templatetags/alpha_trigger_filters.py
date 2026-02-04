"""
Template filters for Alpha Trigger module
"""

import json
from django import template

register = template.Library()


@register.filter
def pprint_json(value):
    """
    Pretty print JSON value

    Usage: {{ value|pprint_json }}
    """
    if isinstance(value, str):
        try:
            obj = json.loads(value)
        except json.JSONDecodeError:
            return value
    else:
        obj = value
    return json.dumps(obj, indent=2, ensure_ascii=False)
