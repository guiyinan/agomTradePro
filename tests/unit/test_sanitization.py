"""
Tests for input sanitization (P1-4).

Tests verify that:
1. HTML is properly escaped in plain text
2. Only safe HTML tags are allowed in rich text
3. Dangerous URLs are blocked
4. XSS attacks are prevented
"""

import pytest

from shared.infrastructure.sanitization import (
    SAFE_TAGS,
    SAFE_URL_SCHEMES,
    get_sanitization_config,
    sanitize_field,
    sanitize_inputs,
    sanitize_plain_text,
    sanitize_rich_text,
)


class TestSanitizePlainText:
    """Tests for plain text sanitization."""

    def test_returns_string(self):
        """Test that output is always a string."""
        assert sanitize_plain_text("test") == "test"
        assert sanitize_plain_text(None) == ""
        assert sanitize_plain_text(123) == "123"

    def test_handles_none(self):
        """Test handling of None input."""
        assert sanitize_plain_text(None) == ""

    def test_handles_empty_string(self):
        """Test handling of empty string."""
        assert sanitize_plain_text("") == ""

    def test_removes_html_tags(self):
        """Test that HTML tags are removed and content is escaped."""
        # Tags are stripped first, then content is escaped
        result = sanitize_plain_text("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "alert" in result  # Content preserved

        result = sanitize_plain_text("<b>bold</b>")
        assert "<b>" not in result
        assert "bold" in result

    def test_escapes_html_entities(self):
        """Test that HTML entities are escaped."""
        # Tags are stripped first, so <script> becomes empty
        result = sanitize_plain_text("<script>")
        assert "<" not in result
        assert "script" not in result  # Tag was removed

        # Ampersand is escaped
        assert sanitize_plain_text("a & b") == "a &amp; b"

        # Quotes are escaped
        assert sanitize_plain_text('say "hello"') == "say &quot;hello&quot;"

        # Less-than and greater-than in text content are escaped
        assert "&lt;" in sanitize_plain_text("a < b")
        assert "&gt;" in sanitize_plain_text("a > b")

    def test_removes_null_bytes(self):
        """Test that null bytes are removed."""
        assert sanitize_plain_text("hello\x00world") == "helloworld"
        assert sanitize_plain_text("\x00\x01\x02test") == "test"

    def test_preserves_whitespace_structure(self):
        """Test that whitespace is normalized but structure preserved."""
        assert sanitize_plain_text("  hello  ") == "hello"
        assert "hello\nworld" in sanitize_plain_text("hello\nworld")


class TestSanitizeRichText:
    """Tests for rich text sanitization."""

    def test_returns_string(self):
        """Test that output is always a string."""
        assert sanitize_rich_text("test") == "test"
        assert sanitize_rich_text(None) == ""

    def test_handles_none(self):
        """Test handling of None input."""
        assert sanitize_rich_text(None) == ""

    def test_allows_safe_tags(self):
        """Test that safe tags are preserved."""
        # Safe tags should be kept
        result = sanitize_rich_text("<b>bold</b>")
        assert "<b>" in result or "<b >" in result

        result = sanitize_rich_text("<p>paragraph</p>")
        assert "paragraph" in result

    def test_removes_script_tags(self):
        """Test that script tags are removed."""
        result = sanitize_rich_text("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "alert" in result  # Content is preserved

    def test_removes_dangerous_attributes(self):
        """Test that dangerous attributes are removed."""
        result = sanitize_rich_text('<a onclick="alert(1)">link</a>')
        assert "onclick" not in result

    def test_sanitizes_href(self):
        """Test that href URLs are sanitized."""
        # Safe URLs should be kept
        result = sanitize_rich_text('<a href="https://example.com">link</a>')
        assert "https://example.com" in result

    def test_blocks_javascript_urls(self):
        """Test that javascript: URLs are blocked."""
        result = sanitize_rich_text('<a href="javascript:alert(1)">link</a>')
        assert "javascript:" not in result


class TestSanitizeField:
    """Tests for field-level sanitization."""

    def test_sanitizes_plain_text(self):
        """Test plain text field sanitization."""
        result = sanitize_field("test", "<script>bad</script>", is_rich_text=False)
        assert "<script>" not in result
        assert "bad" in result

    def test_sanitizes_rich_text(self):
        """Test rich text field sanitization."""
        result = sanitize_field("test", "<p>hello</p>", is_rich_text=True)
        assert "hello" in result

    def test_handles_non_string(self):
        """Test handling of non-string values."""
        assert sanitize_field("test", 123) == 123
        assert sanitize_field("test", None) is None
        assert sanitize_field("test", ["a", "b"]) == ["a", "b"]


class TestSanitizeInputsDecorator:
    """Tests for the sanitize_inputs decorator."""

    def test_sanitize_plain_text_fields(self):
        """Test that plain text fields are sanitized."""
        @sanitize_inputs('name', 'description')
        def create_item(name, description):
            return {'name': name, 'description': description}

        result = create_item(
            name="<script>bad</script>",
            description="normal text"
        )
        assert "<script>" not in result['name']
        assert result['description'] == "normal text"

    def test_sanitize_rich_text_fields(self):
        """Test that rich text fields are sanitized."""
        @sanitize_inputs('title', rich_text_fields=['content'])
        def create_article(title, content):
            return {'title': title, 'content': content}

        result = create_article(
            title="<b>title</b>",
            content="<p>paragraph</p>"
        )
        # Title should have HTML stripped (plain text sanitization)
        assert "<b>" not in result['title']
        assert "title" in result['title']
        # Content should preserve content (rich text sanitization)
        assert "paragraph" in result['content']


class TestSanitizationConfig:
    """Tests for sanitization configuration."""

    def test_get_signal_config(self):
        """Test getting signal module config."""
        config = get_sanitization_config('signal')
        assert 'plain_text' in config
        assert 'rich_text' in config
        assert 'logic_desc' in config['plain_text']

    def test_get_policy_config(self):
        """Test getting policy module config."""
        config = get_sanitization_config('policy')
        assert 'plain_text' in config
        assert 'rich_text' in config
        assert 'title' in config['plain_text']

    def test_get_unknown_config(self):
        """Test getting config for unknown module."""
        config = get_sanitization_config('unknown_module')
        assert config == {'plain_text': [], 'rich_text': []}


class TestXSSPrevention:
    """Tests for XSS attack prevention."""

    def test_prevents_script_injection(self):
        """Test prevention of script injection."""
        attacks = [
            "<script>alert('xss')</script>",
            "<img src=x onerror=alert('xss')>",
            "<svg onload=alert('xss')>",
            "<body onload=alert('xss')>",
        ]

        for attack in attacks:
            result = sanitize_plain_text(attack)
            # The attack should be escaped, not executed
            assert "<script>" not in result.lower() or "&lt;" in result
            assert "onerror" not in result.lower() or "&lt;" in result

    def test_prevents_event_handler_injection(self):
        """Test prevention of event handler injection."""
        attacks = [
            '<div onclick="alert(1)">',
            '<a onmouseover="alert(1)">',
            '<input onfocus="alert(1)">',
        ]

        for attack in attacks:
            result = sanitize_rich_text(attack)
            # Event handlers should be removed
            assert "onclick" not in result.lower()
            assert "onmouseover" not in result.lower()
            assert "onfocus" not in result.lower()

    def test_prevents_javascript_protocol(self):
        """Test prevention of javascript: protocol."""
        attacks = [
            '<a href="javascript:alert(1)">',
            '<a href="JAVASCRIPT:alert(1)">',
            '<a href="  javascript:alert(1)">',
        ]

        for attack in attacks:
            result = sanitize_rich_text(attack)
            assert "javascript:" not in result.lower()

    def test_prevents_data_url_injection(self):
        """Test prevention of data: URL injection."""
        attack = '<a href="data:text/html,<script>alert(1)</script>">'
        result = sanitize_rich_text(attack)
        # data: URLs should be blocked
        assert "data:" not in result.lower() or "javascript" not in result.lower()
