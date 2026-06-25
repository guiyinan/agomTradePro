from io import StringIO

import pytest
from django.core.management import call_command

from apps.policy.infrastructure.models import RSSHubGlobalConfig, RSSSourceConfigModel
from apps.policy.management.commands.init_authoritative_rss_sources import (
    AUTHORITATIVE_RSS_SOURCES,
    Command,
)


@pytest.mark.django_db
def test_init_authoritative_rss_sources_upserts_global_config_and_sources():
    out = StringIO()

    call_command(
        "init_authoritative_rss_sources",
        base_url="http://rsshub:1200",
        stdout=out,
    )

    config = RSSHubGlobalConfig._default_manager.get(singleton_id=1)
    assert config.enabled is True
    assert config.base_url == "http://rsshub:1200"
    assert config.default_format == "rss"

    active_sources = RSSSourceConfigModel._default_manager.filter(
        is_active=True,
        rsshub_enabled=True,
    )
    assert active_sources.count() == len(AUTHORITATIVE_RSS_SOURCES)

    by_route = {source.rsshub_route_path: source for source in active_sources}
    for expected in AUTHORITATIVE_RSS_SOURCES:
        source = by_route[expected.route_path]
        assert source.name == expected.name
        assert source.category == expected.category
        assert source.url == f"http://rsshub:1200{expected.route_path}"
        assert source.rsshub_use_global_config is True


@pytest.mark.django_db
def test_init_authoritative_rss_sources_disables_legacy_non_investment_sources():
    RSSSourceConfigModel._default_manager.create(
        name="V2EX",
        url="https://www.v2ex.com/index.xml",
        category="media",
        is_active=True,
    )

    call_command("init_authoritative_rss_sources", base_url="http://rsshub:1200")

    legacy = RSSSourceConfigModel._default_manager.get(name="V2EX")
    assert legacy.is_active is False
    assert "not an investment/policy news source" in legacy.last_error_message


@pytest.mark.django_db
def test_init_authoritative_rss_sources_preserves_existing_access_key_when_omitted():
    RSSHubGlobalConfig._default_manager.create(
        singleton_id=1,
        base_url="http://old-rsshub:1200",
        access_key="existing-secret",
        enabled=False,
        default_format="atom",
    )

    call_command("init_authoritative_rss_sources", base_url="http://rsshub:1200")

    config = RSSHubGlobalConfig._default_manager.get(singleton_id=1)
    assert config.base_url == "http://rsshub:1200"
    assert config.enabled is True
    assert config.default_format == "rss"
    assert config.access_key == "existing-secret"


@pytest.mark.django_db
def test_init_authoritative_rss_sources_dry_run_does_not_write_database():
    out = StringIO()

    call_command(
        "init_authoritative_rss_sources",
        base_url="http://rsshub:1200",
        dry_run=True,
        stdout=out,
    )

    assert RSSHubGlobalConfig._default_manager.count() == 0
    assert RSSSourceConfigModel._default_manager.count() == 0
    assert "[plan] upsert 国家统计局-数据发布" in out.getvalue()


def test_init_authoritative_rss_sources_resolves_env_base_url(monkeypatch):
    monkeypatch.setenv("AGOM_RSSHUB_BASE_URL", "http://rsshub:1200/")

    assert Command._resolve_base_url("") == "http://rsshub:1200"
