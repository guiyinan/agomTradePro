"""Policy management form validation and credential-safety tests."""

from datetime import date
from types import SimpleNamespace

import pytest

from apps.policy.interface.forms import PolicyEventForm, PolicyKeywordForm, RSSSourceForm


def _rss_instance():
    return SimpleNamespace(
        pk=7,
        name="CSRC",
        category="csrc",
        is_active=True,
        fetch_interval_hours=6,
        extract_content=False,
        timeout_seconds=30,
        retry_times=3,
        url="https://example.com/feed.xml",
        parser_type="feedparser",
        rsshub_enabled=False,
        rsshub_route_path="",
        rsshub_use_global_config=True,
        rsshub_custom_base_url="",
        rsshub_custom_access_key="stored-rsshub-key",
        rsshub_format="",
        proxy_enabled=False,
        proxy_host="",
        proxy_port=None,
        proxy_type="http",
        proxy_username="",
        proxy_password="stored-proxy-password",
    )


def _rss_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "name": "CSRC",
        "category": "csrc",
        "is_active": "on",
        "fetch_interval_hours": "6",
        "timeout_seconds": "30",
        "retry_times": "3",
        "url": "https://example.com/feed.xml",
        "parser_type": "feedparser",
        "rsshub_use_global_config": "on",
        "rsshub_format": "",
        "proxy_type": "http",
        "rsshub_custom_access_key": "",
        "proxy_password": "",
    }
    data.update(overrides)
    return data


def test_rss_edit_form_never_renders_stored_credentials() -> None:
    """Stored RSSHub and proxy credentials must not be returned in form HTML."""

    form = RSSSourceForm(instance=_rss_instance())
    rendered = str(form)

    assert "stored-rsshub-key" not in rendered
    assert "stored-proxy-password" not in rendered
    assert "rsshub_custom_access_key" not in form.initial
    assert "proxy_password" not in form.initial
    assert form.fields["rsshub_custom_access_key"].widget.render_value is False
    assert form.fields["proxy_password"].widget.render_value is False


def test_rss_edit_form_blank_masked_credentials_preserve_existing_values() -> None:
    """Ordinary edits must not erase credentials hidden from the browser."""

    form = RSSSourceForm(data=_rss_data(), instance=_rss_instance())

    assert form.is_valid(), form.errors
    payload = form.to_payload()
    assert payload["rsshub_custom_access_key"] == "stored-rsshub-key"
    assert payload["proxy_password"] == "stored-proxy-password"


def test_rss_edit_form_accepts_explicit_replacement_credentials() -> None:
    """Non-empty masked inputs replace the corresponding stored credentials."""

    form = RSSSourceForm(
        data=_rss_data(
            rsshub_custom_access_key="new-rsshub-key",
            proxy_password="new-proxy-password",
        ),
        instance=_rss_instance(),
    )

    assert form.is_valid(), form.errors
    assert form.to_payload()["rsshub_custom_access_key"] == "new-rsshub-key"
    assert form.to_payload()["proxy_password"] == "new-proxy-password"


def test_rsshub_custom_mode_requires_base_url() -> None:
    """A custom RSSHub route cannot produce a relative or unusable fetch URL."""

    data = _rss_data(
        rsshub_enabled="on",
        rsshub_use_global_config="",
        rsshub_route_path="/gov/csrc/news",
        rsshub_custom_base_url="",
        url="",
    )
    form = RSSSourceForm(data=data)

    assert form.is_valid() is False
    assert "rsshub_custom_base_url" in form.errors


@pytest.mark.parametrize("route", ["gov/csrc/news", "//external.example/feed"])
def test_rsshub_route_requires_one_leading_slash(route: str) -> None:
    """RSSHub routes must remain paths rather than malformed or network-path values."""

    form = RSSSourceForm(
        data=_rss_data(
            rsshub_enabled="on",
            rsshub_route_path=route,
            url="",
        )
    )

    assert form.is_valid() is False
    assert "rsshub_route_path" in form.errors


def test_proxy_mode_requires_host_and_port() -> None:
    """Enabling a proxy without a complete endpoint fails validation."""

    form = RSSSourceForm(
        data=_rss_data(
            proxy_enabled="on",
            proxy_host="",
            proxy_port="",
        )
    )

    assert form.is_valid() is False
    assert "proxy_host" in form.errors
    assert "proxy_port" in form.errors


def test_policy_keyword_form_accepts_chinese_commas_and_uses_integer_step() -> None:
    """Chinese input normalizes cleanly while the integer weight UI stays truthful."""

    form = PolicyKeywordForm(
        data={
            "level": "P2",
            "keywords_text": "降准， 降息,宽松",
            "weight": "2",
            "category": "",
            "is_active": "on",
        }
    )

    assert form.is_valid(), form.errors
    assert form.to_payload()["keywords"] == ["降准", "降息", "宽松"]
    assert form.fields["weight"].widget.attrs["step"] == "1"


def test_policy_event_payload_is_an_explicit_write_whitelist() -> None:
    """Unexpected cleaned-data keys cannot leak into the Application write payload."""

    form = PolicyEventForm(
        data={
            "event_date": "2026-07-27",
            "level": "P1",
            "title": "Policy event",
            "description": "Evidence-backed event",
            "evidence_url": "https://example.com/evidence",
        }
    )

    assert form.is_valid(), form.errors
    form.cleaned_data["audit_status"] = "manual_approved"
    assert form.to_payload() == {
        "event_date": date(2026, 7, 27),
        "level": "P1",
        "title": "Policy event",
        "description": "Evidence-backed event",
        "evidence_url": "https://example.com/evidence",
    }


def test_form_initial_requires_mapping() -> None:
    """Malformed dynamic initial data fails at the form boundary."""

    with pytest.raises(TypeError, match="initial must be a mapping"):
        RSSSourceForm(initial=[("name", "invalid")])
    with pytest.raises(TypeError, match="initial must be a mapping"):
        PolicyKeywordForm(initial=[("level", "P1")])
