"""Shared text sanitization helpers safe for interface-layer imports."""

import html
import logging
import re
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

SAFE_TAGS = {
    "p",
    "br",
    "b",
    "i",
    "u",
    "strong",
    "em",
    "ul",
    "ol",
    "li",
    "blockquote",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "span",
    "div",
    "a",
}

SAFE_ATTRS = {
    "href",
    "title",
    "class",
    "id",
    "target",
    "rel",
}

SAFE_URL_SCHEMES = {"http", "https", "mailto", "tel"}


def sanitize_plain_text(text: str | None) -> str:
    """Sanitize plain text by removing HTML and unsafe control characters."""
    if text is None:
        return ""

    text = str(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.escape(text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text.strip()


def sanitize_rich_text(text: str | None, allowed_tags: set[str] | None = None) -> str:
    """Sanitize rich text by allowing only a safe subset of HTML tags."""
    if text is None:
        return ""

    text = str(text)
    allowed_tags = allowed_tags or SAFE_TAGS
    result: list[str] = []
    pos = 0
    tag_pattern = re.compile(r"<(/?)(\w+)([^>]*)>", re.IGNORECASE)

    while pos < len(text):
        match = tag_pattern.search(text, pos)
        if not match:
            result.append(html.escape(text[pos:]))
            break

        result.append(html.escape(text[pos:match.start()]))
        is_closing, tag_name, attrs = match.groups()
        tag_name = tag_name.lower()

        if tag_name in allowed_tags:
            safe_attrs = _sanitize_attributes(attrs)
            if safe_attrs:
                result.append(f'<{"/" if is_closing else ""}{tag_name} {safe_attrs}>')
            else:
                result.append(f'<{"/" if is_closing else ""}{tag_name}>')

        pos = match.end()

    return "".join(result)


def _sanitize_attributes(attrs_str: str) -> str:
    """Keep only safe HTML attributes."""
    safe_attrs: list[str] = []
    attr_pattern = re.compile(r"(\w+)\s*=\s*[\"']([^\"']*)[\"']", re.IGNORECASE)

    for match in attr_pattern.finditer(attrs_str):
        attr_name, attr_value = match.groups()
        attr_name = attr_name.lower()
        if attr_name not in SAFE_ATTRS:
            continue
        if attr_name == "href":
            attr_value = _sanitize_url(attr_value)
            if attr_value is None:
                continue
        safe_attrs.append(f'{attr_name}="{html.escape(attr_value)}"')

    return " ".join(safe_attrs)


def _sanitize_url(url: str) -> str | None:
    """Reject unsafe URL schemes."""
    url = url.strip()
    scheme_match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*):", url)
    if scheme_match:
        scheme = scheme_match.group(1).lower()
        if scheme not in SAFE_URL_SCHEMES:
            logger.warning("Blocked unsafe URL scheme: %s", scheme)
            return None
    return url


def sanitize_field(field_name: str, value: Any, is_rich_text: bool = False) -> Any:
    """Sanitize a field value if it is string-like."""
    del field_name
    if value is None or not isinstance(value, str):
        return value
    if is_rich_text:
        return sanitize_rich_text(value)
    return sanitize_plain_text(value)


def sanitize_inputs(*fields: str, rich_text_fields: list[str] | None = None):
    """Decorator that sanitizes selected keyword arguments."""
    rich_text_fields = rich_text_fields or []
    all_fields = set(fields) | set(rich_text_fields)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for field in all_fields:
                if field in kwargs:
                    kwargs[field] = sanitize_field(
                        field,
                        kwargs[field],
                        is_rich_text=field in rich_text_fields,
                    )
            return func(*args, **kwargs)

        return wrapper

    return decorator


SANITIZATION_WHITELIST = {
    "signal": {
        "plain_text": ["logic_desc", "invalidation_logic", "asset_code", "name"],
        "rich_text": ["notes"],
    },
    "policy": {
        "plain_text": ["title", "description", "event_type"],
        "rich_text": ["content", "analysis"],
    },
    "account": {
        "plain_text": ["name", "code"],
        "rich_text": ["notes"],
    },
    "regime": {
        "plain_text": ["description"],
        "rich_text": ["notes"],
    },
}


def get_sanitization_config(module_name: str) -> dict[str, list[str]]:
    """Return configured sanitization fields for the given module."""
    return SANITIZATION_WHITELIST.get(
        module_name,
        {
            "plain_text": [],
            "rich_text": [],
        },
    )
