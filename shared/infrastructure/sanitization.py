"""
Input Sanitization Module

P1-4: XSS prevention and input sanitization for user-submitted text.

This module provides:
- Plain text sanitization (removes all HTML)
- Rich text sanitization (allows safe HTML tags)
- Field-level sanitization for serializers

Usage:
    from shared.infrastructure.sanitization import sanitize_plain_text, sanitize_rich_text

    # For plain text fields (names, descriptions, etc.)
    clean_text = sanitize_plain_text(user_input)

    # For rich text fields (comments, notes, etc.)
    clean_html = sanitize_rich_text(user_html)

Whitelist approach:
    - First batch: signal, policy (high-risk input points)
    - Uses allowlist of safe HTML tags for rich text
    - Strips all HTML for plain text
"""

import html
import logging
import re
from functools import wraps

logger = logging.getLogger(__name__)

# Safe HTML tags for rich text (allowlist)
SAFE_TAGS = {
    'p', 'br', 'b', 'i', 'u', 'strong', 'em',
    'ul', 'ol', 'li', 'blockquote',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'span', 'div', 'a',
}

# Safe HTML attributes for rich text (allowlist)
SAFE_ATTRS = {
    'href', 'title', 'class', 'id',
    'target', 'rel',
}

# URL schemes allowed in href attributes
SAFE_URL_SCHEMES = {'http', 'https', 'mailto', 'tel'}


def sanitize_plain_text(text: str | None) -> str:
    """
    Sanitize plain text by removing all HTML and dangerous characters.

    Use this for fields that should not contain any HTML:
    - Names, titles
    - Codes, identifiers
    - Short descriptions

    Args:
        text: The input text to sanitize

    Returns:
        Sanitized plain text with HTML escaped
    """
    if text is None:
        return ""

    # Convert to string if not already
    text = str(text)

    # Remove any HTML tags first
    text = re.sub(r'<[^>]+>', '', text)

    # Escape HTML entities
    text = html.escape(text)

    # Remove null bytes and other control characters (except newlines/tabs)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # Normalize whitespace (but preserve structure)
    text = text.strip()

    return text


def sanitize_rich_text(text: str | None, allowed_tags: set | None = None) -> str:
    """
    Sanitize rich text by allowing only safe HTML tags.

    Use this for fields that may contain formatted text:
    - Comments, notes
    - Long descriptions
    - Documentation

    Args:
        text: The input text to sanitize
        allowed_tags: Optional set of allowed HTML tags (defaults to SAFE_TAGS)

    Returns:
        Sanitized HTML with only safe tags
    """
    if text is None:
        return ""

    text = str(text)
    allowed_tags = allowed_tags or SAFE_TAGS

    # Simple tag stripping approach for now
    # For production, consider using bleach library for more robust sanitization
    result = []
    pos = 0

    # Pattern to match HTML tags
    tag_pattern = re.compile(r'<(/?)(\w+)([^>]*)>', re.IGNORECASE)

    while pos < len(text):
        match = tag_pattern.search(text, pos)

        if not match:
            # No more tags, append rest of text
            result.append(html.escape(text[pos:]))
            break

        # Append text before the tag
        result.append(html.escape(text[pos:match.start()]))

        is_closing, tag_name, attrs = match.groups()
        tag_name = tag_name.lower()

        if tag_name in allowed_tags:
            # Sanitize attributes
            safe_attrs = _sanitize_attributes(tag_name, attrs)
            if safe_attrs:
                result.append(f'<{"/" if is_closing else ""}{tag_name} {safe_attrs}>')
            else:
                result.append(f'<{"/" if is_closing else ""}{tag_name}>')
        else:
            # Remove disallowed tag but keep its content
            pass

        pos = match.end()

    return ''.join(result)


def _sanitize_attributes(tag_name: str, attrs_str: str) -> str:
    """
    Sanitize HTML attributes, keeping only safe ones.

    Args:
        tag_name: The HTML tag name
        attrs_str: The attribute string from the tag

    Returns:
        Sanitized attribute string
    """
    safe_attrs = []

    # Parse attributes
    attr_pattern = re.compile(r'(\w+)\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)

    for match in attr_pattern.finditer(attrs_str):
        attr_name, attr_value = match.groups()
        attr_name = attr_name.lower()

        if attr_name not in SAFE_ATTRS:
            continue

        # Special handling for href
        if attr_name == 'href':
            attr_value = _sanitize_url(attr_value)
            if attr_value is None:
                continue

        # Sanitize attribute value
        attr_value = html.escape(attr_value)
        safe_attrs.append(f'{attr_name}="{attr_value}"')

    return ' '.join(safe_attrs)


def _sanitize_url(url: str) -> str | None:
    """
    Sanitize URL, ensuring it uses a safe scheme.

    Args:
        url: The URL to sanitize

    Returns:
        Sanitized URL or None if unsafe
    """
    url = url.strip()

    # Check for javascript: and other dangerous schemes
    scheme_match = re.match(r'^([a-zA-Z][a-zA-Z0-9+.-]*):', url)
    if scheme_match:
        scheme = scheme_match.group(1).lower()
        if scheme not in SAFE_URL_SCHEMES:
            logger.warning(f"Blocked unsafe URL scheme: {scheme}")
            return None

    return url


def sanitize_field(field_name: str, value: any, is_rich_text: bool = False) -> any:
    """
    Sanitize a field value based on field type.

    Args:
        field_name: Name of the field (for logging)
        value: The value to sanitize
        is_rich_text: Whether to allow HTML

    Returns:
        Sanitized value
    """
    if value is None:
        return None

    if not isinstance(value, str):
        return value

    if is_rich_text:
        return sanitize_rich_text(value)
    else:
        return sanitize_plain_text(value)


# Decorator for automatic sanitization
def sanitize_inputs(*fields: str, rich_text_fields: list[str] | None = None):
    """
    Decorator to automatically sanitize specified fields in function arguments.

    Usage:
        @sanitize_inputs('name', 'description', rich_text_fields=['notes'])
        def create_signal(name, description, notes):
            ...

    Args:
        *fields: Field names to sanitize as plain text
        rich_text_fields: Field names to sanitize as rich text
    """
    rich_text_fields = rich_text_fields or []
    all_fields = set(fields) | set(rich_text_fields)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Sanitize kwargs
            for field in all_fields:
                if field in kwargs:
                    is_rich = field in rich_text_fields
                    kwargs[field] = sanitize_field(
                        field,
                        kwargs[field],
                        is_rich_text=is_rich
                    )

            return func(*args, **kwargs)

        return wrapper

    return decorator


# Whitelist for field sanitization
# P1-4: First batch of high-risk input points
SANITIZATION_WHITELIST = {
    # Signal module
    'signal': {
        'plain_text': ['logic_desc', 'invalidation_logic', 'asset_code', 'name'],
        'rich_text': ['notes'],
    },
    # Policy module
    'policy': {
        'plain_text': ['title', 'description', 'event_type'],
        'rich_text': ['content', 'analysis'],
    },
    # Account module
    'account': {
        'plain_text': ['name', 'code'],
        'rich_text': ['notes'],
    },
    # Regime module
    'regime': {
        'plain_text': ['description'],
        'rich_text': ['notes'],
    },
}


def get_sanitization_config(module_name: str) -> dict:
    """
    Get sanitization configuration for a module.

    Args:
        module_name: Name of the module (e.g., 'signal', 'policy')

    Returns:
        Dictionary with 'plain_text' and 'rich_text' field lists
    """
    return SANITIZATION_WHITELIST.get(module_name, {
        'plain_text': [],
        'rich_text': [],
    })
