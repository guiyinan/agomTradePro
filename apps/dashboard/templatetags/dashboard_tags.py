"""
Dashboard Template Tags

Custom template tags and filters for the dashboard module.
"""

from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """
    Get an item from a dictionary using a variable key.

    Usage: {{ mydict|get_item:key_name }}
    """
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter
def get_attr(obj, attr):
    """
    Get an attribute from an object using a variable name.

    Usage: {{ myobj|get_attr:attr_name }}
    """
    if obj is None:
        return None
    return getattr(obj, attr, None)
