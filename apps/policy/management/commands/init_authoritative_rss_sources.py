from __future__ import annotations

import os
from dataclasses import dataclass

from django.core.management.base import BaseCommand

from apps.policy.infrastructure.models import RSSHubGlobalConfig, RSSSourceConfigModel


@dataclass(frozen=True)
class AuthoritativeRssSource:
    name: str
    category: str
    route_path: str
    description: str


AUTHORITATIVE_RSS_SOURCES: tuple[AuthoritativeRssSource, ...] = (
    AuthoritativeRssSource(
        name="国家统计局-数据发布",
        category="gov_docs",
        route_path="/gov/stats/sj/zxfb",
        description="国家统计局数据发布，作为宏观数据和政策解读真源补充。",
    ),
    AuthoritativeRssSource(
        name="国家统计局-数据解读",
        category="gov_docs",
        route_path="/gov/stats/sj/sjjd",
        description="国家统计局数据解读，辅助判断宏观数据含义。",
    ),
    AuthoritativeRssSource(
        name="发改委-新闻发布",
        category="gov_docs",
        route_path="/gov/ndrc/xwdt/xwfb",
        description="国家发改委新闻发布，覆盖宏观政策和产业政策。",
    ),
    AuthoritativeRssSource(
        name="发改委-通知公告",
        category="gov_docs",
        route_path="/gov/ndrc/xwdt/tzgg",
        description="国家发改委通知公告，覆盖政策执行口径和项目公告。",
    ),
    AuthoritativeRssSource(
        name="证监会-要闻",
        category="csrc",
        route_path="/gov/csrc/news/c100028/common_xq_list.shtml",
        description="证监会要闻，覆盖资本市场监管政策。",
    ),
    AuthoritativeRssSource(
        name="上交所-科创板审核",
        category="csrc",
        route_path="/sse/inquire",
        description="上交所科创板审核动态，作为资本市场监管和融资环境参考。",
    ),
    AuthoritativeRssSource(
        name="深交所-问询函件",
        category="csrc",
        route_path="/szse/inquire",
        description="深交所问询函件，作为上市公司监管和风险事件参考。",
    ),
    AuthoritativeRssSource(
        name="财联社-热门文章",
        category="media",
        route_path="/cls/hot",
        description="财联社热门文章，覆盖市场关注度和热点新闻。",
    ),
    AuthoritativeRssSource(
        name="财联社-头条深度",
        category="media",
        route_path="/cls/depth/1000",
        description="财联社头条深度，覆盖宏观、产业和市场专题。",
    ),
    AuthoritativeRssSource(
        name="格隆汇-市场快讯",
        category="media",
        route_path="/gelonghui/live",
        description="格隆汇 7x24 市场快讯。",
    ),
)


LEGACY_NON_INVESTMENT_SOURCE_NAMES: tuple[str, ...] = (
    "IT之家",
    "V2EX",
    "少数派",
    "金十数据-快讯",
)


class Command(BaseCommand):
    help = "Initialize authoritative RSSHub sources for policy and market news ingestion."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--base-url",
            default="",
            help="RSSHub base URL. Defaults to AGOM_RSSHUB_BASE_URL/RSSHUB_BASE_URL, "
            "http://rsshub:1200 in production, otherwise http://127.0.0.1:1200.",
        )
        parser.add_argument(
            "--access-key",
            default=None,
            help="Optional RSSHub ACCESS_KEY. Omit to keep an existing key.",
        )
        parser.add_argument(
            "--keep-legacy-tech-sources",
            action="store_true",
            help="Keep existing IT/V2EX/Sspai-style sources active.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print intended changes without writing to the database.",
        )

    def handle(self, *args, **options):
        base_url = self._resolve_base_url(str(options.get("base_url") or ""))
        access_key = options.get("access_key")
        dry_run = bool(options.get("dry_run"))
        keep_legacy = bool(options.get("keep_legacy_tech_sources"))

        self.stdout.write("Authoritative RSSHub source initialization")
        self.stdout.write(f"  base_url: {base_url}")
        self.stdout.write(f"  sources: {len(AUTHORITATIVE_RSS_SOURCES)}")
        self.stdout.write(f"  dry_run: {dry_run}")

        if dry_run:
            for source in AUTHORITATIVE_RSS_SOURCES:
                self.stdout.write(f"[plan] upsert {source.name}: {source.route_path}")
            if not keep_legacy:
                self.stdout.write(
                    "[plan] disable legacy non-investment sources: "
                    + ", ".join(LEGACY_NON_INVESTMENT_SOURCE_NAMES)
                )
            return

        global_config = self._upsert_global_config(base_url=base_url, access_key=access_key)
        created_count = 0
        updated_count = 0
        for source in AUTHORITATIVE_RSS_SOURCES:
            _, created = RSSSourceConfigModel._default_manager.update_or_create(
                name=source.name,
                defaults={
                    "url": f"{base_url.rstrip('/')}{source.route_path}",
                    "category": source.category,
                    "is_active": True,
                    "fetch_interval_hours": 6,
                    "extract_content": False,
                    "proxy_enabled": False,
                    "parser_type": "feedparser",
                    "timeout_seconds": 45,
                    "retry_times": 2,
                    "rsshub_enabled": True,
                    "rsshub_route_path": source.route_path,
                    "rsshub_use_global_config": True,
                    "rsshub_custom_base_url": "",
                    "rsshub_custom_access_key": "",
                    "rsshub_format": "",
                    "last_error_message": "",
                },
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        disabled_count = 0
        if not keep_legacy:
            disabled_count = RSSSourceConfigModel._default_manager.filter(
                name__in=LEGACY_NON_INVESTMENT_SOURCE_NAMES
            ).update(
                is_active=False,
                last_error_message=(
                    "Disabled by init_authoritative_rss_sources: not an investment/policy news source "
                    "or not parseable by the RSS pipeline."
                ),
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Authoritative RSSHub sources ready: "
                f"created={created_count}, updated={updated_count}, disabled={disabled_count}, "
                f"global_enabled={global_config.enabled}"
            )
        )

    def _upsert_global_config(self, *, base_url: str, access_key: str | None) -> RSSHubGlobalConfig:
        defaults = {
            "base_url": base_url,
            "enabled": True,
            "default_format": "rss",
        }
        if access_key is not None:
            defaults["access_key"] = access_key
        elif not RSSHubGlobalConfig._default_manager.filter(singleton_id=1).exists():
            defaults["access_key"] = ""

        global_config, _ = RSSHubGlobalConfig._default_manager.update_or_create(
            singleton_id=1,
            defaults=defaults,
        )
        return global_config

    @staticmethod
    def _resolve_base_url(raw_value: str) -> str:
        explicit_value = raw_value.strip()
        if explicit_value:
            return explicit_value.rstrip("/")

        env_value = os.environ.get("AGOM_RSSHUB_BASE_URL") or os.environ.get("RSSHUB_BASE_URL")
        if env_value:
            return env_value.strip().rstrip("/")

        settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
        if "production" in settings_module:
            return "http://rsshub:1200"
        return "http://127.0.0.1:1200"
