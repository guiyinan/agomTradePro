"""M5 live-server UAT for the Web-to-TUI migration exit criteria."""

from __future__ import annotations

import csv
import hashlib
import ipaddress
import json
import os
import re
import time
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from datetime import date, datetime
from decimal import Decimal
from math import isclose
from pathlib import Path
from typing import Protocol, TypedDict, TypeVar
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import uuid4

import playwright.sync_api as playwright_api
import pytest
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    Request,
    Response,
    expect,
)

from tests.support.tui_research.m5_playwright_fixture_guard import (
    require_m5_valuation_fixture_database,
)
from tests.support.tui_research.m5_valuation_consumer_state import (
    M5PublishedValuationFixture,
    cleanup_m5_published_valuation_fixture,
    prepare_m5_published_valuation_fixture,
)

VIEWPORTS = (
    pytest.param(1440, 900, id="desktop-1440x900"),
    pytest.param(1024, 768, id="tablet-1024x768"),
    pytest.param(390, 844, id="mobile-390x844"),
)
PASSWORD = os.environ.get("AGOM_M5_UAT_PASSWORD", "CodexM5Uat!2026")
REMOTE_ACTORS_READY = os.environ.get("AGOM_M5_REMOTE_ACTORS_READY", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EXTERNAL_AI_UAT_ENABLED = os.environ.get("AGOM_M5_EXTERNAL_AI_UAT", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EXTERNAL_AI_UAT_SKIP_REASON = (
    "requires AGOM_M5_EXTERNAL_AI_UAT=1 and a controlled live AI provider "
    "configured in the disposable Playwright database"
)
REMOTE_ACCOUNT_ID = int(os.environ.get("AGOM_M5_REMOTE_ACCOUNT_ID", "2"))
REMOTE_UAT_RUN_ID = os.environ.get("AGOM_REMOTE_UAT_RUN_ID", "").strip()
UAT_RECEIPT_PATH = os.environ.get("AGOM_M5_UAT_RECEIPT_PATH", "").strip()
CONFIRMED_MUTATION_SETTLEMENT_TIMEOUT_MS = 60_000
PRODUCTION_READ_SETTLEMENT_TIMEOUT_MS = 60_000
_READ_SETTLED_STATUSES = (
    "读取完成",
    "操作完成",
    "操作完成，列表已刷新",
    "读取失败，请检查结果后重试",
    "操作未完成，请检查结果后重试",
    "结果受阻，未形成可用结果",
    "结果受限，未形成可用事实；请查看限制后再决定是否重新读取",
    "结果已返回，治理工作区已更新",
    "详情已在当前页面打开",
    "等待补填",
    "等待确认",
    "等待验密",
    "等待重新准备",
    "交接未完成",
    "任务未找到",
    "请求已取消",
    "链接中的任务在当前账号下不可用",
    "链接中的任务暂时无法定位",
    "服务器端任务状态暂时不可用",
)
_M5_MAX_DIAGNOSTIC_EVENTS = 8
_M5_SAFE_JS_ERROR_NAMES = frozenset(
    {
        "AggregateError",
        "Error",
        "EvalError",
        "RangeError",
        "ReferenceError",
        "SyntaxError",
        "TypeError",
        "URIError",
    }
)
_M5_SAFE_REQUEST_FAILURES = frozenset(
    {
        "net::ERR_ABORTED",
        "net::ERR_BLOCKED_BY_CLIENT",
        "net::ERR_CONNECTION_ABORTED",
        "net::ERR_CONNECTION_CLOSED",
        "net::ERR_CONNECTION_REFUSED",
        "net::ERR_CONNECTION_RESET",
        "net::ERR_CONNECTION_TIMED_OUT",
        "net::ERR_FAILED",
        "net::ERR_HTTP2_PROTOCOL_ERROR",
        "net::ERR_INTERNET_DISCONNECTED",
        "net::ERR_NAME_NOT_RESOLVED",
        "net::ERR_NETWORK_CHANGED",
        "net::ERR_TIMED_OUT",
    }
)
_M5_SAFE_TUI_STATIC_JS_PATHS = frozenset(
    {
        "/static/js/agomtui-runtime-core.js",
        "/static/js/tui-agomtradepro-adapter.js",
        "/static/js/tui-workbench.js",
    }
)
_M5_STATIC_JS_FRAME_PATTERN = re.compile(
    r"(?P<path>/static/js/[A-Za-z0-9_.-]+\.js):"
    r"(?P<line>[1-9][0-9]{0,6}):(?P<column>[1-9][0-9]{0,6})(?![0-9])"
)


def _expected_disposable_playwright_settings_module() -> str:
    """Match settings identity to either explicit M5-only fixture opt-in."""

    if (
        os.environ.get("AGOM_M5_SYNTHETIC_CALENDAR", "").strip() == "1"
        or os.environ.get("AGOM_M5_PUBLISHED_VALUATION_FIXTURE", "").strip() == "1"
    ):
        return "tests.settings.m5_playwright"
    return "core.settings.playwright"


def _m5_uat_suffix() -> str:
    """Return a stable remote run suffix and a random local suffix."""

    if REMOTE_UAT_RUN_ID:
        return re.sub(r"[^A-Za-z0-9]", "", REMOTE_UAT_RUN_ID)[:8]
    return uuid4().hex[:8]


def _persist_controlled_write_receipt(receipt: dict[str, object]) -> None:
    """Append one secret-free controlled write receipt when recording is enabled."""

    if not UAT_RECEIPT_PATH:
        return
    if not REMOTE_UAT_RUN_ID:
        pytest.fail("controlled write receipt recording requires AGOM_REMOTE_UAT_RUN_ID")
    path = Path(UAT_RECEIPT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "web-to-tui-controlled-write-receipt.v1",
        "run_id": REMOTE_UAT_RUN_ID,
        **receipt,
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


ROOT = Path(__file__).resolve().parents[4]
MATRIX_PATH = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"


def _is_local_target(base_url: str) -> bool:
    """Return whether the browser target uses a local hostname."""

    hostname = (urlparse(base_url).hostname or "").lower()
    return hostname in {"127.0.0.1", "localhost", "::1", "testserver"}


def _is_literal_loopback_http_target(base_url: str) -> bool:
    """Return whether the URL is an explicit HTTP IPv4 loopback origin."""

    try:
        parsed = urlparse(base_url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and port is not None
        and 1 <= port <= 65535
        and parsed.netloc == f"127.0.0.1:{port}"
        and parsed.path in {"", "/"}
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _require_local_ci_owned_account_database(base_url: str) -> None:
    """Require the exact disposable GitHub Actions SQLite target before local ORM writes."""

    if not _is_literal_loopback_http_target(base_url):
        raise RuntimeError("local owned-account fixture requires literal http://127.0.0.1:<port>")
    if os.environ.get("CI", "").lower() != "true":
        raise RuntimeError("local owned-account fixture requires CI=true")
    if os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
        raise RuntimeError("local owned-account fixture requires GitHub Actions")
    runner_temp_value = os.environ.get("RUNNER_TEMP", "").strip()
    if not runner_temp_value:
        raise RuntimeError("local owned-account fixture requires RUNNER_TEMP")
    runner_temp = Path(runner_temp_value).expanduser()
    if not runner_temp.is_absolute():
        raise RuntimeError("RUNNER_TEMP must be an absolute path")
    expected_path = runner_temp.resolve() / "agomtradepro-rc-playwright.sqlite3"
    configured_path = os.environ.get("AGOM_PLAYWRIGHT_DB_PATH", "").strip()
    if not configured_path:
        raise RuntimeError("local owned-account fixture requires AGOM_PLAYWRIGHT_DB_PATH")
    try:
        explicit_path = Path(configured_path).expanduser().resolve()
    except (OSError, RuntimeError, TypeError):
        raise RuntimeError("AGOM_PLAYWRIGHT_DB_PATH cannot be resolved") from None
    if explicit_path != expected_path:
        raise RuntimeError("AGOM_PLAYWRIGHT_DB_PATH must be the fixed RUNNER_TEMP RC database")

    expected_settings_module = _expected_disposable_playwright_settings_module()
    if os.environ.get("DJANGO_SETTINGS_MODULE", "").strip() != expected_settings_module:
        raise RuntimeError("local owned-account fixture has the wrong isolated settings module")
    from django.conf import settings

    if getattr(settings, "SETTINGS_MODULE", "") != expected_settings_module:
        raise RuntimeError("active Django settings differ from the selected isolated module")
    databases = getattr(settings, "DATABASES", None)
    database = databases.get("default") if isinstance(databases, dict) else None
    if not isinstance(database, dict):
        raise RuntimeError("active default database configuration is unavailable")
    if database.get("ENGINE") != "django.db.backends.sqlite3":
        raise RuntimeError("local owned-account fixture requires SQLite")
    database_name = database.get("NAME")
    test_config = database.get("TEST")
    test_name = test_config.get("NAME") if isinstance(test_config, dict) else None
    if not isinstance(database_name, (str, os.PathLike)) or not isinstance(
        test_name, (str, os.PathLike)
    ):
        raise RuntimeError("active SQLite database paths are unavailable")
    try:
        default_path = Path(database_name).expanduser().resolve()
        test_path = Path(test_name).expanduser().resolve()
    except (OSError, RuntimeError, TypeError):
        raise RuntimeError("active SQLite database paths cannot be resolved") from None
    if default_path != expected_path or test_path != expected_path:
        raise RuntimeError("active SQLite NAME and TEST.NAME must match the fixed RC database")


def _require_remote_actors(base_url: str, username: str) -> None:
    """Skip role-specific remote tests until actors are explicitly provisioned."""

    if (
        username.startswith("m5_uat_")
        and not _is_local_target(base_url)
        and not REMOTE_ACTORS_READY
    ):
        pytest.skip(
            "remote M5 role actors are not provisioned; set "
            "AGOM_M5_REMOTE_ACTORS_READY=1 and AGOM_M5_UAT_PASSWORD explicitly"
        )


_DbResult = TypeVar("_DbResult")


class _DjangoDbBlocker(Protocol):
    def unblock(self) -> AbstractContextManager[None]:
        """Temporarily allow ORM access inside a worker thread."""
        ...


def _run_m5_db_operation(
    django_db_blocker: _DjangoDbBlocker,
    operation: Callable[[], _DbResult],
) -> _DbResult:
    """Run one local M5 ORM unit outside Playwright's active event loop."""

    def run() -> _DbResult:
        from django.db import close_old_connections, connections

        with django_db_blocker.unblock():
            try:
                close_old_connections()
                return operation()
            finally:
                connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(run).result()


class _LocalOwnedAccount(TypedDict):
    account_id: int
    account_name: str
    owner_id: int


class _LocalM5PoolSentimentReceipt(TypedDict):
    model_id: int
    index_date: date
    news_sentiment: float
    policy_sentiment: float
    composite_index: float
    confidence_level: float
    data_sufficient: bool
    sector_sentiment: dict[str, float]
    news_count: int
    policy_events_count: int
    created_at: datetime
    updated_at: datetime


@pytest.fixture(scope="function")
def local_m5_owned_account_fixture(
    request: pytest.FixtureRequest,
    base_url: str,
    ensure_m5_uat_users: None,
) -> Generator[_LocalOwnedAccount | None, None, None]:
    """Create and precisely clean one local simulated account for owned-read coverage."""

    del ensure_m5_uat_users
    if not _is_local_target(base_url):
        yield None
        return

    _require_local_ci_owned_account_database(base_url)
    request.getfixturevalue("django_db_setup")
    django_db_blocker = request.getfixturevalue("django_db_blocker")
    account_name = f"M5 local owner fixture {uuid4().hex}"

    def create_account() -> _LocalOwnedAccount:
        from django.contrib.auth import get_user_model

        from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
            SimulatedAccountModel,
        )

        owner = get_user_model().objects.get(username="m5_uat_regular")
        if SimulatedAccountModel.objects.filter(account_name=account_name).exists():
            raise AssertionError("generated local owned-account name is not unique")
        account = SimulatedAccountModel.objects.create(
            user=owner,
            account_name=account_name,
            account_type="simulated",
            initial_capital=Decimal("1000.00"),
            current_cash=Decimal("1000.00"),
            total_value=Decimal("1000.00"),
            auto_trading_enabled=False,
        )
        if account.pk is None or account.user_id != owner.pk:
            raise AssertionError("local owned-account fixture was not saved for its owner")
        return {
            "account_id": int(account.pk),
            "account_name": account_name,
            "owner_id": int(owner.pk),
        }

    local_account: _LocalOwnedAccount | None = None
    try:
        local_account = _run_m5_db_operation(django_db_blocker, create_account)
        yield local_account
    finally:
        created_account = local_account
        if created_account is not None:

            def delete_account() -> None:
                from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
                    SimulatedAccountModel,
                )

                exact_account = SimulatedAccountModel.objects.filter(
                    pk=created_account["account_id"],
                    user_id=created_account["owner_id"],
                    account_name=created_account["account_name"],
                )
                if exact_account.count() != 1:
                    raise AssertionError(
                        "local owned-account cleanup requires the exact created row"
                    )
                exact_account.delete()
                if SimulatedAccountModel.objects.filter(
                    account_name=created_account["account_name"]
                ).exists():
                    raise AssertionError("local owned-account fixture left a database row")

            _run_m5_db_operation(django_db_blocker, delete_account)


def _delete_local_m5_pool_sentiment(
    receipt: _LocalM5PoolSentimentReceipt,
) -> None:
    """Delete only the exact sentiment row owned by this local fixture."""

    from apps.sentiment.infrastructure.models import SentimentIndexModel

    manager = SentimentIndexModel._default_manager
    exact_rows = manager.filter(pk=receipt["model_id"], index_date=receipt["index_date"])
    if exact_rows.count() != 1:
        raise AssertionError("local sentiment cleanup requires the exact created row")
    row = exact_rows.get()
    stored_content = (
        row.news_sentiment,
        row.policy_sentiment,
        row.composite_index,
        row.confidence_level,
        row.data_sufficient,
        row.sector_sentiment,
        row.news_count,
        row.policy_events_count,
        row.created_at,
        row.updated_at,
    )
    owned_content = (
        receipt["news_sentiment"],
        receipt["policy_sentiment"],
        receipt["composite_index"],
        receipt["confidence_level"],
        receipt["data_sufficient"],
        receipt["sector_sentiment"],
        receipt["news_count"],
        receipt["policy_events_count"],
        receipt["created_at"],
        receipt["updated_at"],
    )
    if stored_content != owned_content:
        raise AssertionError("local sentiment cleanup refused a row whose content changed")
    row.delete()
    if manager.filter(pk=receipt["model_id"], index_date=receipt["index_date"]).exists():
        raise AssertionError("local sentiment cleanup left the created row")
    if manager.filter(index_date=receipt["index_date"]).exists():
        raise AssertionError("local sentiment cleanup found another row on the owned date")


@pytest.fixture(scope="function")
def local_m5_pool_sentiment_fixture(
    request: pytest.FixtureRequest,
    base_url: str,
) -> Generator[Callable[[], None], None, None]:
    """Lazily seed one calculated fresh sentiment row on the opt-in RC SQLite target."""

    opt_in = os.environ.get("AGOM_M5_POOL_SENTIMENT_FIXTURE")
    if opt_in is None:

        def do_not_seed() -> None:
            return

        yield do_not_seed
        return
    if opt_in != "1":
        raise RuntimeError("AGOM_M5_POOL_SENTIMENT_FIXTURE must be exactly 1 when set")

    expected_base_url = os.environ.get("AGOM_M5_POOL_SENTIMENT_BASE_URL", "").strip()
    if expected_base_url != base_url or not _is_literal_loopback_http_target(base_url):
        raise RuntimeError("local sentiment fixture requires its exact literal loopback base URL")
    _require_local_ci_owned_account_database(base_url)
    request.getfixturevalue("django_db_setup")
    django_db_blocker = request.getfixturevalue("django_db_blocker")
    owned_rows: list[_LocalM5PoolSentimentReceipt] = []

    def create_current_sentiment() -> _LocalM5PoolSentimentReceipt:
        from django.utils import timezone

        from apps.sentiment.application.current_sentiment import resolve_current_sentiment
        from apps.sentiment.application.repository_provider import (
            get_sentiment_index_repository,
        )
        from apps.sentiment.application.services import SentimentIndexCalculator

        repository = get_sentiment_index_repository()
        target_date = date.today()
        if repository.get_by_date(target_date) is not None:
            raise RuntimeError("refusing to overwrite an existing current-date sentiment row")
        latest = repository.get_latest()
        if latest is not None and latest.index_date.date() > target_date:
            raise RuntimeError("refusing to seed behind a later sentiment observation")

        source_clock = timezone.now().astimezone()
        if not timezone.is_aware(source_clock) or source_clock.date() != target_date:
            raise RuntimeError("sentiment fixture source clock must be aware and on today's date")
        news_scores = [0.15, 0.20, 0.25]
        policy_scores = [0.05, 0.10]
        calculated = SentimentIndexCalculator().calculate_index(
            news_scores=news_scores,
            policy_scores=policy_scores,
            index_date=source_clock,
        )
        if (
            not timezone.is_aware(calculated.index_date)
            or calculated.index_date.date() != target_date
            or not calculated.data_sufficient
            or calculated.news_count != len(news_scores)
            or calculated.policy_events_count != len(policy_scores)
            or not isclose(calculated.confidence_level, 0.5, abs_tol=1e-12)
        ):
            raise AssertionError("sentiment calculator did not derive the expected fixture result")

        receipt: _LocalM5PoolSentimentReceipt | None = None
        try:
            saved = repository.save(calculated)
            if saved.pk is None:
                raise AssertionError("sentiment repository did not return the created row ID")
            receipt = {
                "model_id": int(saved.pk),
                "index_date": target_date,
                "news_sentiment": calculated.news_sentiment,
                "policy_sentiment": calculated.policy_sentiment,
                "composite_index": calculated.composite_index,
                "confidence_level": calculated.confidence_level,
                "data_sufficient": calculated.data_sufficient,
                "sector_sentiment": dict(calculated.sector_sentiment),
                "news_count": calculated.news_count,
                "policy_events_count": calculated.policy_events_count,
                "created_at": saved.created_at,
                "updated_at": saved.updated_at,
            }
            if (
                saved.index_date != target_date
                or saved.news_sentiment != calculated.news_sentiment
                or saved.policy_sentiment != calculated.policy_sentiment
                or saved.composite_index != calculated.composite_index
                or saved.confidence_level != calculated.confidence_level
                or saved.data_sufficient is not calculated.data_sufficient
                or saved.sector_sentiment != calculated.sector_sentiment
                or saved.news_count != calculated.news_count
                or saved.policy_events_count != calculated.policy_events_count
            ):
                raise AssertionError("sentiment repository save did not persist calculator output")

            persisted = repository.get_by_date(target_date)
            if (
                persisted is None
                or persisted.index_date.date() != target_date
                or persisted.news_sentiment != calculated.news_sentiment
                or persisted.policy_sentiment != calculated.policy_sentiment
                or persisted.composite_index != calculated.composite_index
                or persisted.confidence_level != calculated.confidence_level
                or persisted.data_sufficient is not calculated.data_sufficient
                or persisted.sector_sentiment != calculated.sector_sentiment
                or persisted.news_count != calculated.news_count
                or persisted.policy_events_count != calculated.policy_events_count
            ):
                raise AssertionError(
                    "sentiment repository readback did not match calculated output"
                )

            resolved = resolve_current_sentiment(as_of_date=target_date)
            if (
                resolved.index is None
                or resolved.freshness_status != "fresh"
                or resolved.must_not_use_for_decision
                or resolved.blocked_reason
                or resolved.observed_at != target_date
                or resolved.index.index_date.date() != target_date
                or resolved.index.composite_index != calculated.composite_index
            ):
                raise AssertionError("current sentiment resolver did not accept the fresh fixture")
            return receipt
        except BaseException:
            if receipt is not None:
                _delete_local_m5_pool_sentiment(receipt)
            raise

    def seed_once() -> None:
        if owned_rows:
            return
        owned_rows.append(_run_m5_db_operation(django_db_blocker, create_current_sentiment))

    try:
        yield seed_once
    finally:
        if owned_rows:
            receipt = owned_rows[0]

            def remove_current_sentiment() -> None:
                _delete_local_m5_pool_sentiment(receipt)

            _run_m5_db_operation(django_db_blocker, remove_current_sentiment)


@pytest.fixture(scope="session", autouse=True)
def ensure_m5_uat_users(
    request: pytest.FixtureRequest,
    base_url: str,
    ensure_playwright_admin_user: None,
) -> None:
    """Seed the least-privileged M5 actors in the shared browser-test database."""

    del ensure_playwright_admin_user
    if not _is_local_target(base_url):
        if REMOTE_ACTORS_READY and "AGOM_M5_UAT_PASSWORD" not in os.environ:
            pytest.fail(
                "AGOM_M5_REMOTE_ACTORS_READY requires an explicit AGOM_M5_UAT_PASSWORD",
                pytrace=False,
            )
        return

    request.getfixturevalue("django_db_setup")
    django_db_blocker = request.getfixturevalue("django_db_blocker")

    def seed() -> None:
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group

        from apps.account.infrastructure.models import AccountProfileModel

        operator_group, _ = Group.objects.get_or_create(name="operator")
        user_model = get_user_model()
        for username, is_operator in (
            ("m5_uat_operator", True),
            ("m5_uat_regular", False),
        ):
            user, _ = user_model.objects.get_or_create(username=username)
            user.is_active = True
            user.is_staff = False
            user.is_superuser = False
            user.set_password(PASSWORD)
            user.save(update_fields=["password", "is_active", "is_staff", "is_superuser"])
            user.groups.clear()
            if is_operator:
                user.groups.add(operator_group)

            AccountProfileModel.objects.update_or_create(
                user=user,
                defaults={
                    "display_name": username,
                    "approval_status": "approved",
                    "rbac_role": "owner",
                    "mcp_enabled": True,
                    "user_agreement_accepted": True,
                    "risk_warning_acknowledged": True,
                },
            )

    _run_m5_db_operation(django_db_blocker, seed)


def _matrix_deep_links() -> tuple[tuple[str, str, str, str], ...]:
    """Return one reviewed primary TUI deep link per migrated route page."""

    links: list[tuple[str, str, str, str]] = []
    with MATRIX_PATH.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if not (
                row.get("status") == "migrated"
                and row.get("template_role") == "route_page"
                and row.get("destination_class") in {"A", "B"}
            ):
                continue
            template_path = str(row.get("template_path") or "").strip()
            screen_key = next(
                (
                    value.strip()
                    for value in str(row.get("target_screen_key") or "").split(";")
                    if value.strip()
                ),
                "",
            )
            redirect_target = str(row.get("redirect_target") or "").strip()
            redirect_actions = parse_qs(urlparse(redirect_target).query).get("action") or []
            action_key = next(
                (
                    value.strip()
                    for value in redirect_actions
                    if value.strip() and "{" not in value and "}" not in value
                ),
                "",
            )
            if not action_key:
                action_key = next(
                    (
                        value.strip()
                        for value in str(row.get("target_action_keys") or "").split(";")
                        if value.strip() and "{" not in value and "}" not in value
                    ),
                    "",
                )
            if not template_path or not screen_key or not action_key:
                raise AssertionError(f"Incomplete migrated deep link: {template_path}")
            links.append(
                (
                    template_path,
                    screen_key,
                    action_key,
                    str(row.get("audience") or "authenticated").strip(),
                )
            )
    return tuple(sorted(links))


MATRIX_DEEP_LINKS = _matrix_deep_links()

PARAMETERIZED_READ_CASES: tuple[tuple[str, str, str, str, dict[str, str | int]], ...] = (
    (
        "core/templates/asset_analysis/screen.html",
        "research.asset-lab",
        "asset-analysis.pool-screen",
        "regular",
        {"asset_type": "equity", "regime": "Recovery"},
    ),
    (
        "core/templates/dashboard/alpha_ranking.html",
        "research.signals",
        "dashboard.alpha-ranking",
        "regular",
        {"format": "json"},
    ),
    (
        "apps/risk_center/templates/risk_center/console.html",
        "macro-regime.strategy",
        "risk-center.effective-policy",
        "admin",
        {"account_id": REMOTE_ACCOUNT_ID},
    ),
    (
        "core/templates/equity/detail.html",
        "research.asset-lab",
        "equity.valuation-overview",
        "regular",
        {"stock_code": "000001.SZ"},
    ),
    (
        "core/templates/filter/dashboard.html",
        "research.asset-lab",
        "macro.trend-filter-summary",
        "regular",
        {"indicator_code": "PMI"},
    ),
    (
        "core/templates/policy/policy_events.html",
        "policy.workbench",
        "policy.event-list",
        "regular",
        {"start_date": "2026-06-27", "end_date": "2026-07-27"},
    ),
    (
        "core/templates/simulated_trading/inspection_notify.html",
        "execution.accounts",
        "simulated-trading.inspection-notification",
        "regular",
        {"account_id": REMOTE_ACCOUNT_ID},
    ),
    (
        "core/templates/simulated_trading/my_positions.html",
        "execution.accounts",
        "simulated-trading.positions",
        "regular",
        {"account_id": REMOTE_ACCOUNT_ID},
    ),
    (
        "core/templates/simulated_trading/my_trades.html",
        "execution.accounts",
        "simulated-trading.trades",
        "regular",
        {"account_id": REMOTE_ACCOUNT_ID},
    ),
)


def _login(page: Page, base_url: str, *, username: str, target: str) -> None:
    """Log one isolated UAT user into an explicit TUI deep link."""

    _require_remote_actors(base_url, username)
    page.goto(
        f"{base_url}/account/login/?next={target}",
        wait_until="domcontentloaded",
    )
    page.get_by_role("textbox", name="用户名", exact=True).fill(username)
    page.get_by_role("textbox", name="密码", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="登录", exact=True).click()
    expect(page).to_have_url(re.compile(r".*/tui/\?.*"))


@pytest.mark.uat
def test_account_read_missing_fields_and_confirmation_cancel(
    authenticated_page: Page,
    base_url: str,
) -> None:
    """Read/detail flows work and a write cannot bypass input or confirmation."""

    page = authenticated_page
    account_name = "M5 浏览器演练账户"
    page.goto(
        f"{base_url}/tui/?screen=execution.accounts&action=simulated-trading.accounts",
        wait_until="domcontentloaded",
    )

    expect(page.locator("[data-workbench-status]")).to_have_text("读取完成", timeout=60_000)
    expect(page.get_by_role("grid", name="查看我的投资账户")).to_be_visible()
    result_summary = page.get_by_text(
        re.compile(r"^查看我的投资账户：\d+ 行。$"),
        exact=True,
    )
    expect(result_summary).to_be_visible()
    summary_text = result_summary.text_content()
    summary_match = re.fullmatch(r"查看我的投资账户：(\d+) 行。", summary_text or "")
    assert summary_match is not None
    assert int(summary_match.group(1)) >= 1
    assert page.locator("html").evaluate(
        "(element) => element.scrollWidth <= element.clientWidth + 1"
    )

    page.keyboard.press("F9")
    expect(page.get_by_role("searchbox", name="任务", exact=True)).to_be_visible()
    create_form = page.locator("form:has(#tui-simulated-trading\\.account-create-account_name)")
    expect(create_form).to_have_count(1)
    expect(create_form).to_be_visible()
    create_button = create_form.get_by_role("button", name="创建", exact=True)
    expect(create_button).to_be_visible()
    create_button.click()

    missing_dialog = page.get_by_role("dialog", name="补填参数", exact=True)
    expect(missing_dialog).to_be_visible()
    missing_dialog.get_by_placeholder("请输入账户名称", exact=True).fill(account_name)
    missing_dialog.get_by_role("spinbutton").fill("500000")
    missing_dialog.get_by_role("button", name="继续", exact=True).click()

    confirmation = page.get_by_role("dialog", name="确认操作", exact=True)
    expect(confirmation).to_be_visible()
    expect(
        confirmation.get_by_text(
            "此操作会修改系统状态：创建投资账户。确认后才会执行。",
            exact=True,
        )
    ).to_be_visible()
    confirmation.get_by_role("button", name="取消", exact=True).click()
    expect(confirmation).to_be_hidden()
    expect(page.get_by_text("已取消", exact=True)).to_be_visible()

    page.goto(
        f"{base_url}/tui/?screen=execution.accounts&action=simulated-trading.accounts",
        wait_until="domcontentloaded",
    )
    restored_summary = page.get_by_text(summary_text or "", exact=True)
    try:
        expect(restored_summary).to_be_visible(timeout=10_000)
    except AssertionError:
        # A preceding dashboard fan-out may still own the bounded remote action
        # slots. Exercise the published recovery path instead of treating
        # intentional backpressure as a missing business result.
        retry = page.get_by_role("button", name="重试", exact=True)
        expect(retry).to_be_visible(timeout=10_000)
        page.wait_for_timeout(5_000)
        retry.click()
        expect(restored_summary).to_be_visible(timeout=60_000)
    expect(page.get_by_text(account_name, exact=True)).to_have_count(0)

    page.keyboard.press("F9")
    detail_form = page.locator("form:has(#tui-simulated-trading\\.account-detail-account_id)")
    account_select = detail_form.locator("select")
    options = account_select.locator("option").evaluate_all(
        "elements => elements.map(option => ({value: option.value, label: option.textContent.trim()}))"
    )
    selected_account = next(option for option in options if option["value"])
    account_select.select_option(selected_account["value"])
    detail_form.get_by_role("button", name="查看", exact=True).click()
    expect(page.get_by_text("账户 / 账户名称", exact=True)).to_be_visible()
    selected_account_name = selected_account["label"].split(" · ", 1)[0]
    expect(page.get_by_text(selected_account_name, exact=True).last).to_be_visible()


@pytest.mark.uat
def test_operator_group_can_open_queue_but_regular_user_cannot(
    page: Page,
    base_url: str,
) -> None:
    """TUI visibility and the owner API preserve the operator role boundary."""

    target = "/tui/%3Fscreen%3Dai-ops.terminal%26action%3Dagent-runtime.operator-task-list"

    _login(page, base_url, username="m5_uat_operator", target=target)
    expect(page.get_by_text("读取完成", exact=True)).to_be_visible(
        timeout=PRODUCTION_READ_SETTLEMENT_TIMEOUT_MS
    )
    assert page.get_by_role("grid", name="智能任务队列").is_visible()

    page.goto(f"{base_url}/account/logout/", wait_until="domcontentloaded")
    _login(page, base_url, username="m5_uat_regular", target=target)
    expect(page.get_by_text("链接中的任务在当前账号下不可用", exact=True)).to_be_visible(
        timeout=PRODUCTION_READ_SETTLEMENT_TIMEOUT_MS
    )
    assert page.get_by_role("grid", name="智能任务队列").count() == 0


@pytest.mark.uat
@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_tui_core_layout_has_no_horizontal_overflow(
    authenticated_page: Page,
    base_url: str,
    width: int,
    height: int,
) -> None:
    """The migrated core workspace remains usable at the reviewed breakpoints."""

    page = authenticated_page
    page.set_viewport_size({"width": width, "height": height})
    page.goto(
        f"{base_url}/tui/?screen=execution.accounts&action=simulated-trading.accounts",
        wait_until="domcontentloaded",
    )
    expect(page.get_by_role("grid", name="查看我的投资账户")).to_be_visible()
    page.keyboard.press("F9")
    expect(page.get_by_role("searchbox", name="任务", exact=True)).to_be_visible()

    layout = page.evaluate("""() => ({
            documentWidth: document.documentElement.scrollWidth,
            viewportWidth: document.documentElement.clientWidth,
            workspaceVisible: getComputedStyle(
                document.querySelector('[aria-label="TUI workspace"]')
            ).display !== 'none',
            unnamedButtons: Array.from(document.querySelectorAll('button')).filter(
                (element) => !(
                    element.getAttribute('aria-label')
                    || (element.textContent || '').trim()
                    || element.getAttribute('title')
                )
            ).length,
        })""")
    assert layout["documentWidth"] <= layout["viewportWidth"] + 1
    assert layout["workspaceVisible"] is True
    assert layout["unnamedButtons"] == 0


@pytest.mark.uat
def test_every_migrated_route_resolves_its_reviewed_tui_deep_link(
    authenticated_page: Page,
    base_url: str,
) -> None:
    """All migrated route pages resolve an admin-visible screen/action pair."""

    page = authenticated_page
    failures: list[str] = []
    assert len(MATRIX_DEEP_LINKS) == 108
    page.route(
        re.compile(r".*/api/tui/actions/.*/run/$"),
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"response":{"status_code":200,"body":{}}}',
        ),
    )

    for template_path, screen_key, action_key, _audience in MATRIX_DEEP_LINKS:
        query = urlencode({"screen": screen_key, "action": action_key})
        try:
            page.goto(
                f"{base_url}/tui/?{query}",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            page.locator(
                "[data-actions-panel] [data-action-ui-key], [data-dashboard-panel]"
            ).first.wait_for(state="attached", timeout=30_000)
            page.wait_for_timeout(100)
            status = page.locator("[data-workbench-status]").inner_text()
            if "链接中的任务在当前账号下不可用" in status:
                failures.append(f"{template_path}: action unavailable: {screen_key} / {action_key}")
            elif "链接中的任务暂时无法定位" in status:
                failures.append(
                    f"{template_path}: action not locatable: {screen_key} / {action_key}"
                )
        except Exception as exc:
            failures.append(
                f"{template_path}: {screen_key} / {action_key}: {type(exc).__name__}: {exc}"
            )

    assert failures == [], "\n".join(failures)


def _uat_role(audience: str) -> str:
    """Choose the least-privileged planned role for one route page."""

    normalized = audience.lower()
    if "operator" in normalized:
        return "operator"
    if "admin" in normalized and "authenticated" not in normalized:
        return "admin"
    return "regular"


def _login_context(
    context: BrowserContext,
    base_url: str,
    *,
    username: str,
    password: str,
) -> Page:
    """Authenticate one reusable browser context for matrix UAT."""

    _require_remote_actors(base_url, username)
    page = context.new_page()
    page.goto(f"{base_url}/account/login/?next=/tui/", wait_until="domcontentloaded")
    page.get_by_role("textbox", name="用户名", exact=True).fill(username)
    page.get_by_role("textbox", name="密码", exact=True).fill(password)
    page.get_by_role("button", name="登录", exact=True).click()
    expect(page).to_have_url(re.compile(r".*/tui/.*"))
    return page


@pytest.fixture(scope="session")
def local_route_uat_fixture_ids(
    request: pytest.FixtureRequest,
    base_url: str,
) -> dict[str, int | str]:
    """Seed deterministic local-only records consumed through the live TUI server."""

    if not _is_local_target(base_url):
        raw_fixture_ids = os.environ.get("AGOM_M5_REMOTE_FIXTURE_IDS", "").strip()
        if not raw_fixture_ids:
            pytest.skip("remote route fixtures are not provisioned; set AGOM_M5_REMOTE_FIXTURE_IDS")
        payload = json.loads(raw_fixture_ids)
        return {str(key): value for key, value in payload.items()}

    request.getfixturevalue("django_db_setup")
    django_db_blocker = request.getfixturevalue("django_db_blocker")

    def seed() -> dict[str, int | str]:
        from django.contrib.auth import get_user_model

        from apps.agent_runtime.infrastructure.models import AgentProposalModel, AgentTaskModel
        from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel
        from apps.audit.infrastructure.models import AttributionReport
        from apps.backtest.infrastructure.models import BacktestResultModel
        from apps.factor.infrastructure.models import FactorPortfolioConfigModel

        user_model = get_user_model()
        operator = user_model.objects.get(username="m5_uat_operator")
        regular = user_model.objects.get(username="m5_uat_regular")
        task, _ = AgentTaskModel.objects.update_or_create(
            request_id="m5-uat-agent-task-detail",
            defaults={
                "task_domain": "research",
                "task_type": "m5_route_uat",
                "status": "awaiting_approval",
                "input_payload": {"asset_code": "000001.SZ"},
                "requires_human": True,
                "created_by": operator,
            },
        )
        proposal, _ = AgentProposalModel.objects.update_or_create(
            request_id="m5-uat-agent-proposal-detail",
            defaults={
                "task": task,
                "proposal_type": "signal_write",
                "status": "submitted",
                "risk_level": "medium",
                "approval_required": True,
                "approval_status": "pending",
                "proposal_payload": {"asset_code": "000001.SZ", "side": "hold"},
                "created_by": operator,
            },
        )
        candidate, _ = AlphaCandidateModel.objects.update_or_create(
            candidate_id="m5-uat-alpha-candidate-detail",
            defaults={
                "trigger_id": "m5-uat-alpha-candidate-trigger",
                "asset_code": "000001.SZ",
                "asset_class": "a_share",
                "direction": "LONG",
                "strength": "STRONG",
                "confidence": 0.82,
                "status": "ACTIONABLE",
                "thesis": "M5 candidate route evidence",
                "entry_zone": {"low": 10.0, "high": 11.0},
                "exit_zone": {"target": 13.0},
                "time_horizon": 30,
                "expected_return": 0.12,
                "risk_level": "MEDIUM",
            },
        )
        attribution_backtest, _ = BacktestResultModel.objects.update_or_create(
            user=regular,
            name="M5 attribution route fixture",
            defaults={
                "status": "completed",
                "start_date": "2026-01-01",
                "end_date": "2026-03-31",
                "initial_capital": "1000000.00",
                "rebalance_frequency": "monthly",
                "final_capital": "1060000.00",
                "total_return": 0.06,
            },
        )
        report, _ = AttributionReport.objects.update_or_create(
            backtest=attribution_backtest,
            period_start="2026-01-01",
            period_end="2026-03-31",
            defaults={
                "attribution_method": "heuristic",
                "regime_timing_pnl": 0.02,
                "asset_selection_pnl": 0.03,
                "interaction_pnl": 0.01,
                "total_pnl": 0.06,
                "regime_accuracy": 0.75,
                "regime_predicted": "recovery",
                "regime_actual": "recovery",
            },
        )
        factor_config, _ = FactorPortfolioConfigModel.objects.update_or_create(
            name="M5 factor calculation fixture",
            defaults={
                "description": "Local route-task UAT fixture",
                "factor_weights": {"quality": 1.0},
                "universe": "all_a",
                "top_n": 5,
                "is_active": True,
            },
        )

        return {
            "agent_task_id": task.id,
            "agent_proposal_id": proposal.id,
            "candidate_id": candidate.candidate_id,
            "attribution_report_id": report.id,
            "factor_config_id": factor_config.id,
        }

    return _run_m5_db_operation(django_db_blocker, seed)


def _action_ui_key_from_screen_payload(payload: object, action_key: str) -> str:
    """Read the public UI key for exactly one action in a screen response."""

    assert isinstance(payload, dict)
    action_specs = payload.get("actions")
    assert isinstance(action_specs, list)
    matching_actions = [
        action
        for action in action_specs
        if isinstance(action, dict) and action.get("key") == action_key
    ]
    assert len(matching_actions) == 1, f"screen action {action_key} must be published once"
    ui_key = matching_actions[0].get("ui_key")
    assert isinstance(ui_key, str) and ui_key, f"screen action {action_key} ui_key"
    return ui_key


def _screen_action_ui_key(
    page: Page,
    base_url: str,
    *,
    screen_key: str,
    action_key: str,
) -> str:
    """Read one action UI key from the authenticated screen contract."""

    response = page.context.request.get(f"{base_url}/api/tui/screens/{screen_key}/")
    assert response.status == 200, f"{screen_key} metadata: {response.status}"
    return _action_ui_key_from_screen_payload(response.json(), action_key)


def _locator_visible_state(locator: Locator, count: int) -> bool | None:
    """Return a safe visibility observation for one uniquely matched locator."""

    if count != 1:
        return None
    try:
        return locator.is_visible()
    except Exception:
        return None


def _assert_one_visible_dashboard_form(
    panel: Locator,
    form: Locator,
    *,
    action_key_present: bool,
) -> None:
    """Assert one visible form and report only safe counts and visibility on failure."""

    try:
        expect(form).to_have_count(1)
        expect(form).to_be_visible()
    except Exception as exc:
        panel_count = panel.count()
        form_count = form.count()
        panel_visible = _locator_visible_state(panel, panel_count)
        form_visible = _locator_visible_state(form, form_count)
        raise AssertionError(
            "dashboard action form mismatch: "
            f"metadata_ui_key_present={action_key_present}; "
            f"panel_count={panel_count}; panel_visible={panel_visible}; "
            f"form_count={form_count}; form_visible={form_visible}"
        ) from exc


def _dashboard_panel_locator(page: Page, panel_key: str) -> Locator:
    """Wait for the unique dashboard panel identified by its validated public key."""

    assert re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*", panel_key
    ), "dashboard panel key must use the published lowercase slug format"
    panel = page.locator(f'[data-dashboard-panel="{panel_key}"]')
    expect(panel).to_have_count(1)
    expect(panel).to_be_attached()
    return panel


def _dashboard_action_form_from_payload(
    page: Page,
    payload: object,
    *,
    action_key: str,
    expected_priority: str,
) -> Locator:
    """Return one visible dashboard-panel form using the published action key."""

    assert isinstance(payload, dict)
    action_ui_key = _action_ui_key_from_screen_payload(payload, action_key)
    screen = payload.get("screen")
    assert isinstance(screen, dict)
    panels = screen.get("dashboard_panels")
    assert isinstance(panels, list)
    matching_specs = [
        panel
        for panel in panels
        if isinstance(panel, dict) and panel.get("action_key") == action_key
    ]
    assert len(matching_specs) == 1, f"dashboard panel for {action_key} must be published once"
    panel_spec = matching_specs[0]
    assert panel_spec.get("user_priority") == expected_priority
    assert panel_spec.get("presentation_semantic") == "next_step"
    panel_key = panel_spec.get("key")
    assert isinstance(panel_key, str) and panel_key

    panel = _dashboard_panel_locator(page, panel_key)
    expect(panel).to_have_attribute("data-panel-priority", expected_priority)
    expect(panel).to_have_attribute("data-panel-semantic", "next_step")
    action_form = panel.locator(f'form[data-action-ui-key="{action_ui_key}"]')
    _assert_one_visible_dashboard_form(
        panel,
        action_form,
        action_key_present=bool(action_ui_key),
    )
    return action_form


def _dashboard_action_form(
    page: Page,
    base_url: str,
    *,
    screen_key: str,
    action_key: str,
    expected_priority: str,
) -> Locator:
    """Locate an action form inside its published dashboard panel."""

    response = page.context.request.get(f"{base_url}/api/tui/screens/{screen_key}/")
    assert response.status == 200, f"{screen_key} metadata: {response.status}"
    return _dashboard_action_form_from_payload(
        page,
        response.json(),
        action_key=action_key,
        expected_priority=expected_priority,
    )


def _open_owned_accounts_dashboard_panel(page: Page, base_url: str) -> Locator:
    """Load the visible accounts panel and wait for its successful dashboard response."""

    response = page.context.request.get(f"{base_url}/api/tui/screens/execution.accounts/")
    assert response.status == 200, f"execution.accounts metadata: {response.status}"
    payload = response.json()
    assert isinstance(payload, dict)
    screen = payload.get("screen")
    assert isinstance(screen, dict)
    panels = screen.get("dashboard_panels")
    assert isinstance(panels, list)
    matching_specs = [
        panel
        for panel in panels
        if isinstance(panel, dict) and panel.get("action_key") == "simulated-trading.accounts"
    ]
    assert len(matching_specs) == 1, "owned accounts dashboard panel must be published once"
    panel_spec = matching_specs[0]
    assert panel_spec.get("user_priority") == "p0"
    assert panel_spec.get("presentation_semantic") == "primary_list"
    panel_key = panel_spec.get("key")
    assert isinstance(panel_key, str) and panel_key

    page.goto(f"{base_url}/tui/?screen=execution.accounts", wait_until="domcontentloaded")
    panel = _dashboard_panel_locator(page, panel_key)
    expect(panel).to_have_attribute("data-panel-priority", "p0")
    loaded_content = panel.locator("table.tui-mini-table, .tui-panel-placeholder")
    expect(loaded_content).to_have_count(1, timeout=PRODUCTION_READ_SETTLEMENT_TIMEOUT_MS)
    expect(loaded_content).to_be_visible()
    expect(panel.locator(".tui-panel-error")).to_have_count(0)
    expect(page.locator(".tui-error")).to_have_count(0)
    return panel


def _visible_action_form(page: Page, selector: str) -> Locator:
    """Return one attached form after opening the task panel when required."""

    form = page.locator(selector)
    try:
        form.wait_for(state="attached")
    except Exception as exc:
        action_panel = page.locator("[data-actions-panel]")
        panel_count = action_panel.count()
        form_count = form.count()
        raise AssertionError(
            "action form did not attach: "
            f"metadata_ui_key_selector={'data-action-ui-key' in selector}; "
            f"action_panel_count={panel_count}; "
            f"action_panel_visible={_locator_visible_state(action_panel, panel_count)}; "
            f"form_count={form_count}; form_visible={_locator_visible_state(form, form_count)}"
        ) from exc
    if not form.is_visible():
        page.keyboard.press("F9")
    try:
        expect(form).to_be_visible()
    except Exception as exc:
        action_panel = page.locator("[data-actions-panel]")
        panel_count = action_panel.count()
        form_count = form.count()
        raise AssertionError(
            "action form is not visible: "
            f"metadata_ui_key_selector={'data-action-ui-key' in selector}; "
            f"action_panel_count={panel_count}; "
            f"action_panel_visible={_locator_visible_state(action_panel, panel_count)}; "
            f"form_count={form_count}; form_visible={_locator_visible_state(form, form_count)}"
        ) from exc
    return form


def _fill_visible_action_parameters(
    form: Locator,
    params: dict[str, str | int | float | bool],
) -> None:
    """Fill explicit parameters through the unique visible form controls."""

    for field_key, value in params.items():
        assert re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_.-]*", field_key
        ), f"unsupported action field name: {field_key!r}"
        field = form.locator(f'[name="{field_key}"]')
        expect(field).to_have_count(1)
        tag_name = str(field.evaluate("element => element.tagName.toLowerCase()"))
        input_type = (field.get_attribute("type") or "text").lower() if tag_name == "input" else ""
        assert input_type not in {
            "hidden",
            "password",
            "file",
        }, f"refusing to fill a non-user-facing field: {field_key}"
        expect(field).to_be_visible()

        if tag_name == "select":
            field.select_option(value=str(value))
            expect(field).to_have_value(str(value))
        elif tag_name == "textarea":
            field.fill(str(value))
            expect(field).to_have_value(str(value))
        elif tag_name == "input" and input_type == "checkbox":
            assert type(value) is bool, f"checkbox parameter must be boolean: {field_key}"
            field.check() if value else field.uncheck()
            if value:
                expect(field).to_be_checked()
            else:
                expect(field).not_to_be_checked()
        elif tag_name == "input" and input_type in {
            "text",
            "number",
            "date",
            "email",
            "search",
            "tel",
            "url",
        }:
            field.fill(str(value))
            expect(field).to_have_value(str(value))
        else:
            raise AssertionError(
                f"unsupported visible action control: {field_key} ({tag_name}/{input_type})"
            )

    required_fields = form.locator("input[required], select[required], textarea[required]")
    for index in range(required_fields.count()):
        field = required_fields.nth(index)
        field_name = field.get_attribute("name") or f"required-field-{index}"
        expect(field).to_be_visible()
        is_valid = bool(field.evaluate("element => element.checkValidity()"))
        assert is_valid, f"required action field remains invalid: {field_name}"


def _safe_required_field_states(form: Locator) -> list[dict[str, object]]:
    """Describe required controls without exposing their values."""

    controls = form.locator("input[required], select[required], textarea[required]")
    states: list[dict[str, object]] = []
    for index in range(controls.count()):
        control = controls.nth(index)
        tag_name = str(control.evaluate("element => element.tagName.toLowerCase()"))
        input_type = (
            (control.get_attribute("type") or "text").lower() if tag_name == "input" else ""
        )
        if input_type in {"password", "file"}:
            has_value: bool | None = None
        else:
            has_value = bool(
                control.evaluate(
                    "element => element.type === 'checkbox' "
                    "? element.checked "
                    ": String(element.value ?? '').trim() !== ''"
                )
            )
        states.append(
            {
                "name": control.get_attribute("name") or "",
                "tag": tag_name,
                "type": input_type,
                "visible": control.is_visible(),
                "valid": bool(control.evaluate("element => element.checkValidity()")),
                "has_value": has_value,
            }
        )
    return states


def _safe_action_response_summary(response: Response | None) -> dict[str, object]:
    """Return only safe envelope status fields, never the action payload."""

    if response is None:
        return {"captured": False}
    summary: dict[str, object] = {"captured": True, "http_status": response.status}
    try:
        payload = response.json()
    except Exception:
        summary["json_object"] = False
        return summary
    if not isinstance(payload, dict):
        summary["json_object"] = False
        return summary

    summary["json_object"] = True
    outcome = payload.get("outcome")
    summary["outcome"] = (
        outcome
        if isinstance(outcome, str)
        and outcome in {"success", "partial", "noop", "blocked", "failed"}
        else "other"
    )
    confirmation_required = payload.get("confirmation_required")
    summary["confirmation_required"] = (
        confirmation_required if isinstance(confirmation_required, bool) else None
    )
    response_summary = payload.get("response")
    response_status = (
        response_summary.get("status_code") if isinstance(response_summary, dict) else None
    )
    summary["business_status"] = response_status if type(response_status) is int else None
    missing_fields = payload.get("missing_fields")
    summary["missing_field_keys"] = (
        [
            field["key"]
            for field in missing_fields
            if isinstance(field, dict) and isinstance(field.get("key"), str)
        ]
        if isinstance(missing_fields, list)
        else []
    )
    view_model = payload.get("view_model")
    error_code = payload.get("error_code")
    if not isinstance(error_code, str) and isinstance(view_model, dict):
        error_code = view_model.get("user_error_code")
    summary["error_code"] = (
        error_code
        if isinstance(error_code, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", error_code)
        else None
    )
    summary["has_error"] = bool(
        payload.get("error")
        or payload.get("error_code")
        or (isinstance(view_model, dict) and view_model.get("user_error_code"))
    )
    return summary


def _is_m5_action_post(request: Request, action_key: str) -> bool:
    """Match only the exact action POST without retaining its URL or payload."""

    return (
        request.method == "POST"
        and urlparse(request.url).path == f"/api/tui/actions/{action_key}/run/"
    )


def _safe_m5_request_failure(request: Request) -> dict[str, object]:
    """Expose only a safe failure category and a bounded hash of its raw reason."""

    failure = request.failure
    if not isinstance(failure, str) or not failure:
        return {"category": "unknown", "failure_sha256": None}
    category = failure if failure in _M5_SAFE_REQUEST_FAILURES else "other"
    failure_hash = hashlib.sha256(failure[:512].encode("utf-8", errors="replace")).hexdigest()
    return {"category": category, "failure_sha256": failure_hash}


def _safe_m5_static_js_frames(stack: str) -> list[dict[str, int | str]]:
    """Keep only line and column data from repository-owned TUI JavaScript files."""

    frames: list[dict[str, int | str]] = []
    for match in _M5_STATIC_JS_FRAME_PATTERN.finditer(stack[:8192]):
        path = match.group("path")
        if path not in _M5_SAFE_TUI_STATIC_JS_PATHS:
            continue
        frames.append(
            {
                "path": path,
                "line": int(match.group("line")),
                "column": int(match.group("column")),
            }
        )
        if len(frames) >= 4:
            break
    return frames


def _safe_m5_page_error(error: playwright_api.Error) -> dict[str, object]:
    """Report an allowlisted JavaScript error name, message hash, and safe frames."""

    error_name = error.name
    safe_name = error_name if error_name in _M5_SAFE_JS_ERROR_NAMES else "other"
    message_hash = hashlib.sha256(
        error.message[:2048].encode("utf-8", errors="replace")
    ).hexdigest()
    stack = error.stack if isinstance(error.stack, str) else ""
    return {
        "name": safe_name,
        "message_sha256": message_hash,
        "static_js_frames": _safe_m5_static_js_frames(stack),
    }


def _wait_for_declared_read_terminal(page: Page, timeout_ms: int) -> None:
    """Wait for success or a published terminal state without treating failure as success."""

    settled_json = json.dumps(_READ_SETTLED_STATUSES, ensure_ascii=False)
    page.wait_for_function(
        f"""() => {{
            const status = document.querySelector('[data-workbench-status]')
                ?.textContent?.trim() || '';
            const settled = new Set({settled_json});
            return settled.has(status)
                || status.startsWith('已定位到 ')
                || Boolean(document.querySelector('.tui-error'));
        }}""",
        timeout=timeout_ms,
    )


def _listen_for_tui_action_response(
    page: Page, action_key: str
) -> tuple[Callable[[Response], None], list[Response]]:
    """Capture only the exact TUI action response for safe failure diagnostics."""

    responses: list[Response] = []

    def capture(response: Response) -> None:
        if (
            urlparse(response.url).path == f"/api/tui/actions/{action_key}/run/"
            and response.request.method == "POST"
        ):
            responses.append(response)

    page.on("response", capture)
    return capture, responses


def _assert_m5_published_valuation_result(
    page: Page,
    responses: list[Response],
    fixture: M5PublishedValuationFixture,
) -> None:
    """Assert the exact public result and visible value for the controlled valuation read."""

    assert responses, "the TUI valuation action response was not captured"
    response = responses[-1]
    assert response.status == 200
    envelope = response.json()
    assert isinstance(envelope, dict)
    assert envelope.get("outcome") == "success"
    response_summary = envelope.get("response")
    assert isinstance(response_summary, dict)
    assert response_summary.get("status_code") == 200

    view_model = envelope.get("view_model")
    assert isinstance(view_model, dict)
    assert view_model.get("kind") == "detail"
    raw_fields = view_model.get("fields")
    assert isinstance(raw_fields, list)
    field_values = {
        field["key"]: str(field.get("value") or "")
        for field in raw_fields
        if isinstance(field, dict) and isinstance(field.get("key"), str)
    }
    assert field_values.get("stock_code", "").startswith(fixture.requested_asset_code)
    assert field_values.get("current_pe") == "8.0"
    assert field_values.get("latest_valuation.pe") == "8.0"
    assert field_values.get("latest_valuation.price") == "12.34"
    assert field_values.get("financial_data.revenue") == "1000000.0"
    assert field_values.get("financial_data.net_profit") == "200000.0"
    assert field_values.get("financial_data.roe") == "18.5"
    assert field_values.get("financial_data.debt_ratio") == "16.7"

    # The serializer exposes four of the seven required financial metrics. The other three
    # remain independently verified as exact selected-member fixture inputs below.
    metric_states = fixture.financial_state.metric_states
    source_metrics = {state.seed.metric_code: state.seed.value for state in metric_states}
    expected_source_metrics = {
        "revenue": Decimal("1000000.0000"),
        "net_profit": Decimal("200000.0000"),
        "total_assets": Decimal("3000000.0000"),
        "total_liabilities": Decimal("500000.0000"),
        "equity": Decimal("2500000.0000"),
        "roe": Decimal("18.5000"),
        "debt_ratio": Decimal("16.7000"),
    }
    assert len(metric_states) == len(expected_source_metrics)
    assert source_metrics == expected_source_metrics
    publication_id = str(fixture.financial_state.publication.publication_id)
    assert fixture.financial_state.publication.member_count == len(metric_states)
    assert str(fixture.financial_state.pointer.publication_id) == publication_id
    assert (
        fixture.financial_state.pointer.publication_hash
        == fixture.financial_state.publication.publication_hash
    )
    for state in metric_states:
        assert state.fact.asset_code == fixture.requested_asset_code
        assert state.fact.metric_code == state.seed.metric_code
        assert state.fact.value == state.seed.value
        assert state.member_model.dataset_key == "equity.financial.fact"
        assert str(state.member_model.publication_id) == publication_id
        assert state.member_model.fact_pk == str(state.fact.pk)
        assert state.member_model.raw_payload_hash == state.source.body_sha256
        assert state.member.fact_pk == str(state.fact.pk)
        assert state.member.fact_content_hash == state.member_model.fact_content_hash
        assert state.member.fact_content_hash

    valuation_field = next(
        (
            field
            for field in raw_fields
            if isinstance(field, dict) and field.get("key") == "current_pe"
        ),
        None,
    )
    assert valuation_field is not None
    valuation_label = str(valuation_field.get("label") or "")
    assert valuation_label
    main = page.locator("[data-main-panel]")
    valuation_label_locator = main.locator(".tui-detail-grid > dt").filter(
        has_text=re.compile(f"^{re.escape(valuation_label)}$")
    )
    expect(valuation_label_locator).to_have_count(1)
    expect(valuation_label_locator).to_be_visible()
    valuation_value = valuation_label_locator.locator("xpath=following-sibling::dd[1]")
    expect(valuation_value).to_be_visible()
    expect(valuation_value).to_have_text(re.compile(r"^8\.0$"))


def _safe_read_terminal_diagnostic(page: Page, responses: list[Response]) -> dict[str, object]:
    """Return a safe terminal state and allowlisted action outcome fields only."""

    status_locator = page.locator("[data-workbench-status]")
    status_count = status_locator.count()
    workbench_status: str | None = None
    if status_count == 1:
        raw_status = status_locator.inner_text().strip()
        if raw_status in _READ_SETTLED_STATUSES:
            workbench_status = raw_status
        elif raw_status.startswith("已定位到 "):
            workbench_status = "已定位到 <action>"
        elif raw_status:
            workbench_status = "unrecognized"

    return {
        "workbench_status_count": status_count,
        "workbench_status": workbench_status,
        "tui_error_count": page.locator(".tui-error").count(),
        "entry_state_count": page.locator("[data-main-panel] .tui-entry-state").count(),
        "action_response": _safe_action_response_summary(responses[-1] if responses else None),
    }


_M5_VALUATION_DIAGNOSTIC_FIELD_KEYS = (
    "stock_code",
    "current_pe",
    "latest_valuation.pe",
    "latest_valuation.price",
    "financial_data.revenue",
    "financial_data.net_profit",
    "financial_data.roe",
    "financial_data.debt_ratio",
)


def _safe_valuation_diagnostic_label(value: object) -> str | None:
    """Keep only bounded, plain user-facing labels for allowlisted fields."""

    if not isinstance(value, str) or len(value) > 160:
        return None
    label = " ".join(value.split())
    if not label or re.fullmatch(r"[\w .:/()（）%+\-·]{1,80}", label) is None:
        return None
    return label


def _safe_valuation_diagnostic_value(key: str, value: object) -> str | None:
    """Return bounded stock identifiers or numeric values for exact field keys."""

    if key not in _M5_VALUATION_DIAGNOSTIC_FIELD_KEYS or isinstance(value, bool):
        return None
    if isinstance(value, str):
        candidate = value
    elif isinstance(value, int) and abs(value) <= 10**18:
        candidate = str(value)
    elif isinstance(value, float):
        candidate = str(value)
    else:
        return None
    if len(candidate) > 40:
        return None
    if key == "stock_code":
        return candidate if re.fullmatch(r"[A-Za-z0-9._-]{1,32}", candidate) else None
    return candidate if re.fullmatch(r"-?\d{1,18}(?:\.\d{1,12})?", candidate) else None


def _valuation_failure_diagnostic(page: Page, responses: list[Response]) -> dict[str, object]:
    """Capture only valuation allowlist fields and a screenshot of the owning page."""

    response = responses[-1] if responses else None
    view_model_kind: str | None = None
    matched_fields: dict[str, list[dict[str, str | None]]] = {
        key: [] for key in _M5_VALUATION_DIAGNOSTIC_FIELD_KEYS
    }
    if response is not None:
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            view_model = payload.get("view_model")
            if isinstance(view_model, dict):
                kind = view_model.get("kind")
                if (
                    isinstance(kind, str)
                    and len(kind) <= 64
                    and re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", kind)
                ):
                    view_model_kind = kind
                raw_fields = view_model.get("fields")
                if isinstance(raw_fields, list):
                    for field in raw_fields[:256]:
                        if not isinstance(field, dict):
                            continue
                        key = field.get("key")
                        if not isinstance(key, str) or key not in matched_fields:
                            continue
                        matched_fields[key].append(
                            {
                                "label": _safe_valuation_diagnostic_label(field.get("label")),
                                "value": _safe_valuation_diagnostic_value(key, field.get("value")),
                            }
                        )

    screenshot: str | None = None
    screenshot_error: str | None = None
    try:
        repository_root = ROOT.resolve()
        repository_tmp = (ROOT / ".tmp").resolve()
        if not repository_tmp.is_relative_to(repository_root):
            raise RuntimeError("repository .tmp escaped the repository root")
        diagnostic_dir = repository_tmp / "m5-valuation-diagnostics"
        diagnostic_dir.mkdir(parents=True, exist_ok=True)
        resolved_dir = diagnostic_dir.resolve()
        if resolved_dir == repository_tmp or not resolved_dir.is_relative_to(repository_tmp):
            raise RuntimeError("valuation diagnostic path escaped repository .tmp")
        screenshot_path = resolved_dir / f"valuation-overview-{uuid4().hex}.png"
        if screenshot_path.resolve().parent != resolved_dir:
            raise RuntimeError("valuation diagnostic screenshot path escaped its directory")
        page.screenshot(path=str(screenshot_path), full_page=True)
        screenshot = str(screenshot_path.relative_to(repository_root)).replace("\\", "/")
    except Exception as exc:
        screenshot_error = type(exc).__name__

    return {
        "response_captured": response is not None,
        "view_model_kind": view_model_kind,
        "allowlisted_fields": matched_fields,
        "owning_page_screenshot": screenshot,
        "screenshot_error": screenshot_error,
    }


def _confirmation_failure_diagnostic(
    page: Page,
    form: Locator,
    confirmation: Locator,
    action_key: str,
    responses: list[Response],
    confirmed: bool,
    action_request_count: int,
    action_request_count_capped: bool,
    request_failures: list[dict[str, object]],
    request_failures_capped: bool,
    page_errors: list[dict[str, object]],
    page_errors_capped: bool,
) -> dict[str, object]:
    """Capture a screenshot and bounded, secret-free action readiness diagnostics."""

    diagnostic_dir = ROOT / ".tmp" / "m5-confirmation-diagnostics"
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    safe_action_key = re.sub(r"[^A-Za-z0-9_-]", "_", action_key)
    screenshot_path = diagnostic_dir / f"{safe_action_key}-{uuid4().hex[:8]}.png"
    screenshot_error: str | None = None
    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception as exc:
        screenshot_error = type(exc).__name__
    form_count = form.count()
    screen_values = parse_qs(urlparse(page.url).query).get("screen", [])
    screen_key = (
        screen_values[0]
        if screen_values and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", screen_values[0])
        else None
    )
    return {
        "action_key": action_key,
        "confirmation_count": confirmation.count(),
        "current_task": {
            "screen_key": screen_key,
            "action_key": action_key,
            "form_present": form_count > 0,
            "form_visible": _locator_visible_state(form, form_count),
        },
        "confirmed": confirmed,
        "action_request_count": action_request_count,
        "action_request_count_capped": action_request_count_capped,
        "request_failures": request_failures[:_M5_MAX_DIAGNOSTIC_EVENTS],
        "request_failures_capped": request_failures_capped,
        "terminal": _safe_read_terminal_diagnostic(page, responses),
        "required_fields": _safe_required_field_states(form)[:32],
        "page_errors": page_errors[:_M5_MAX_DIAGNOSTIC_EVENTS],
        "page_errors_capped": page_errors_capped,
        "screenshot": (
            str(screenshot_path.relative_to(ROOT)).replace("\\", "/")
            if screenshot_error is None
            else None
        ),
        "screenshot_error": screenshot_error,
    }


def _run_confirmed_action(
    page: Page,
    base_url: str,
    *,
    screen_key: str,
    action_key: str,
    params: dict[str, str | int | float | bool],
    form_selector: str | None = None,
    result_timeout_ms: int = CONFIRMED_MUTATION_SETTLEMENT_TIMEOUT_MS,
    completion_status: str = "操作完成",
) -> Locator:
    """Submit one visible TUI action and retain its completion and error guards."""

    query = urlencode({"screen": screen_key, "action": action_key, **params})
    page.goto(f"{base_url}/tui/?{query}", wait_until="domcontentloaded")
    if form_selector is None:
        action_ui_key = _screen_action_ui_key(
            page,
            base_url,
            screen_key=screen_key,
            action_key=action_key,
        )
        form_selector = f'[data-actions-panel] form[data-action-ui-key="{action_ui_key}"]'
    assert isinstance(form_selector, str) and form_selector
    form = _visible_action_form(page, form_selector)
    confirmation = page.get_by_role("dialog", name="确认操作", exact=True)
    action_responses: list[Response] = []
    action_request_count = 0
    action_request_count_capped = False
    request_failures: list[dict[str, object]] = []
    request_failures_capped = False
    page_errors: list[dict[str, object]] = []
    page_errors_capped = False
    confirmed = False

    def capture_action_response(response: Response) -> None:
        if _is_m5_action_post(response.request, action_key):
            action_responses.append(response)

    def capture_action_request(request: Request) -> None:
        nonlocal action_request_count, action_request_count_capped
        if not _is_m5_action_post(request, action_key):
            return
        if action_request_count < _M5_MAX_DIAGNOSTIC_EVENTS:
            action_request_count += 1
        else:
            action_request_count_capped = True

    def capture_request_failed(request: Request) -> None:
        nonlocal request_failures_capped
        if not _is_m5_action_post(request, action_key):
            return
        if len(request_failures) < _M5_MAX_DIAGNOSTIC_EVENTS:
            request_failures.append(_safe_m5_request_failure(request))
        else:
            request_failures_capped = True

    def capture_page_error(error: playwright_api.Error) -> None:
        nonlocal page_errors_capped
        if len(page_errors) < _M5_MAX_DIAGNOSTIC_EVENTS:
            page_errors.append(_safe_m5_page_error(error))
        else:
            page_errors_capped = True

    page.on("request", capture_action_request)
    page.on("requestfailed", capture_request_failed)
    page.on("response", capture_action_response)
    page.on("pageerror", capture_page_error)
    try:
        try:
            form.locator("button[type='submit']").click()
            expect(confirmation).to_be_visible()
        except (AssertionError, playwright_api.TimeoutError) as exc:
            diagnostic = _confirmation_failure_diagnostic(
                page,
                form,
                confirmation,
                action_key,
                action_responses,
                confirmed,
                action_request_count,
                action_request_count_capped,
                request_failures,
                request_failures_capped,
                page_errors,
                page_errors_capped,
            )
            serialized_diagnostic = json.dumps(diagnostic, ensure_ascii=False, sort_keys=True)
            raise AssertionError(
                "action confirmation dialog did not appear; "
                f"safe_diagnostic={serialized_diagnostic}"
            ) from exc

        try:
            confirmation.get_by_role("button", name="确认执行", exact=True).click()
            confirmed = True
            expect(page.locator("[data-workbench-status]")).to_have_text(
                completion_status, timeout=result_timeout_ms
            )
            expect(page.locator(".tui-error")).to_have_count(0)
            expect(page.locator("[data-main-panel] .tui-entry-state")).to_have_count(0)
            main = page.locator("[data-main-panel]")
            view_status_pattern = r"^(?:正常|暂无数据|已读取) / "
            expect(main.locator(".tui-view-status")).to_contain_text(
                re.compile(view_status_pattern)
            )
            return main
        except (AssertionError, playwright_api.TimeoutError) as exc:
            diagnostic = _confirmation_failure_diagnostic(
                page,
                form,
                confirmation,
                action_key,
                action_responses,
                confirmed,
                action_request_count,
                action_request_count_capped,
                request_failures,
                request_failures_capped,
                page_errors,
                page_errors_capped,
            )
            serialized_diagnostic = json.dumps(diagnostic, ensure_ascii=False, sort_keys=True)
            raise AssertionError(
                f"confirmed action did not reach {completion_status!r}; "
                f"safe_diagnostic={serialized_diagnostic}"
            ) from exc
    finally:
        page.remove_listener("request", capture_action_request)
        page.remove_listener("requestfailed", capture_request_failed)
        page.remove_listener("response", capture_action_response)
        page.remove_listener("pageerror", capture_page_error)


def _run_read_deep_link(
    page: Page,
    base_url: str,
    *,
    screen_key: str,
    action_key: str,
    params: dict[str, str | int | float | bool] | None = None,
) -> Locator:
    """Execute one parameter-complete read deep link and return its rendered result."""

    query = urlencode({"screen": screen_key, "action": action_key, **(params or {})})
    response_handler, action_responses = _listen_for_tui_action_response(page, action_key)
    action_request_count = 0
    action_request_count_capped = False
    request_failures: list[dict[str, object]] = []
    request_failures_capped = False
    page_errors: list[dict[str, object]] = []
    page_errors_capped = False

    def capture_action_request(request: Request) -> None:
        nonlocal action_request_count, action_request_count_capped
        if not _is_m5_action_post(request, action_key):
            return
        if action_request_count < _M5_MAX_DIAGNOSTIC_EVENTS:
            action_request_count += 1
        else:
            action_request_count_capped = True

    def capture_request_failed(request: Request) -> None:
        nonlocal request_failures_capped
        if not _is_m5_action_post(request, action_key):
            return
        if len(request_failures) < _M5_MAX_DIAGNOSTIC_EVENTS:
            request_failures.append(_safe_m5_request_failure(request))
        else:
            request_failures_capped = True

    def capture_page_error(error: playwright_api.Error) -> None:
        nonlocal page_errors_capped
        if len(page_errors) < _M5_MAX_DIAGNOSTIC_EVENTS:
            page_errors.append(_safe_m5_page_error(error))
        else:
            page_errors_capped = True

    page.on("request", capture_action_request)
    page.on("requestfailed", capture_request_failed)
    page.on("pageerror", capture_page_error)
    phase = "navigate"
    try:
        page.goto(f"{base_url}/tui/?{query}", wait_until="domcontentloaded")
        phase = "wait_for_read_status"
        expect(page.locator("[data-workbench-status]")).to_have_text("读取完成")
        phase = "assert_no_tui_error"
        expect(page.locator(".tui-error")).to_have_count(0)
        return page.locator("[data-main-panel]")
    except (AssertionError, playwright_api.TimeoutError) as exc:
        diagnostic = {
            "phase": phase,
            "action_key": action_key,
            "action_request_count": action_request_count,
            "action_request_count_capped": action_request_count_capped,
            "request_failures": request_failures[:_M5_MAX_DIAGNOSTIC_EVENTS],
            "request_failures_capped": request_failures_capped,
            "terminal": _safe_read_terminal_diagnostic(page, action_responses),
            "page_errors": page_errors[:_M5_MAX_DIAGNOSTIC_EVENTS],
            "page_errors_capped": page_errors_capped,
        }
        serialized_diagnostic = json.dumps(diagnostic, ensure_ascii=False, sort_keys=True)
        raise AssertionError(
            "read deep link did not reach its declared terminal state; "
            f"safe_diagnostic={serialized_diagnostic}"
        ) from exc
    finally:
        page.remove_listener("request", capture_action_request)
        page.remove_listener("requestfailed", capture_request_failed)
        page.remove_listener("response", response_handler)
        page.remove_listener("pageerror", capture_page_error)


@pytest.mark.uat
def test_role_appropriate_direct_read_primary_tasks_complete(
    browser: Browser,
    base_url: str,
    m5_synthetic_calendar_transport: None,
    m5_synthetic_universe_config: None,
) -> None:
    """Execute every fixture-free primary read through its least-privileged role."""

    contexts = {
        role: browser.new_context(base_url=base_url) for role in ("regular", "operator", "admin")
    }
    try:
        pages = {
            "regular": _login_context(
                contexts["regular"],
                base_url,
                username="m5_uat_regular",
                password=PASSWORD,
            ),
            "operator": _login_context(
                contexts["operator"],
                base_url,
                username="m5_uat_operator",
                password=PASSWORD,
            ),
            "admin": _login_context(
                contexts["admin"],
                base_url,
                username="admin",
                password="Aa123456",
            ),
        }
        screen_cache: dict[tuple[str, str], dict[str, object]] = {}
        direct_routes: list[tuple[str, str, str, str]] = []
        metadata_failures: list[str] = []

        for template_path, screen_key, action_key, audience in MATRIX_DEEP_LINKS:
            role = _uat_role(audience)
            cache_key = (role, screen_key)
            if cache_key not in screen_cache:
                response = contexts[role].request.get(f"{base_url}/api/tui/screens/{screen_key}/")
                if not response.ok:
                    metadata_failures.append(
                        f"{template_path}: {role} cannot load {screen_key}: {response.status}"
                    )
                    continue
                screen_cache[cache_key] = response.json()
            payload = screen_cache[cache_key]
            actions = payload.get("actions")
            action_values = actions if isinstance(actions, list) else []
            action = next(
                (
                    item
                    for item in action_values
                    if isinstance(item, dict) and item.get("key") == action_key
                ),
                None,
            )
            if action is None:
                metadata_failures.append(
                    f"{template_path}: {role} cannot see {screen_key} / {action_key}"
                )
                continue
            fields = action.get("fields")
            has_required_fields = bool(
                isinstance(fields, list)
                and any(isinstance(field, dict) and field.get("required") for field in fields)
            )
            is_direct_read = (
                str(action.get("risk") or "read") in {"read", "admin"}
                and str(action.get("method") or "GET").upper() == "GET"
                and not has_required_fields
                and action.get("confirmation_required") is not True
            )
            if is_direct_read:
                direct_routes.append((template_path, screen_key, action_key, role))

        assert metadata_failures == [], "\n".join(metadata_failures)
        unique_tasks = {
            (screen_key, action_key, role) for _, screen_key, action_key, role in direct_routes
        }
        assert len(direct_routes) >= 65
        assert len(unique_tasks) >= 60

        execution_failures: list[str] = []
        for screen_key, action_key, role in sorted(unique_tasks):
            page = pages[role]
            query = urlencode({"screen": screen_key, "action": action_key})
            response_handler, action_responses = _listen_for_tui_action_response(page, action_key)
            try:
                page.goto(
                    f"{base_url}/tui/?{query}",
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                _wait_for_declared_read_terminal(page, timeout_ms=60_000)
                status = page.locator("[data-workbench-status]").inner_text()
                error_count = page.locator(".tui-error").count()
                if error_count or not (status == "读取完成" or status.startswith("已定位到 ")):
                    diagnostic = _safe_read_terminal_diagnostic(page, action_responses)
                    execution_failures.append(
                        f"{role}: {screen_key} / {action_key}: "
                        f"terminal={json.dumps(diagnostic, ensure_ascii=False, sort_keys=True)}"
                    )
            except Exception as exc:
                diagnostic = _safe_read_terminal_diagnostic(page, action_responses)
                execution_failures.append(
                    f"{role}: {screen_key} / {action_key}: {type(exc).__name__}; "
                    f"terminal={json.dumps(diagnostic, ensure_ascii=False, sort_keys=True)}"
                )
            finally:
                page.remove_listener("response", response_handler)

        assert execution_failures == [], "\n".join(execution_failures)
    finally:
        for context in contexts.values():
            context.close()


def _create_m5_valuation_artifact_root() -> Path:
    """Create one exact, unique evidence directory below repository .tmp."""

    repository_tmp = (ROOT / ".tmp").resolve()
    parent = (repository_tmp / "m5-valuation-fixtures").resolve()
    if not parent.is_relative_to(repository_tmp):
        raise RuntimeError("valuation artifact parent escaped repository .tmp")
    parent.mkdir(parents=True, exist_ok=True)
    artifact_root = (parent / uuid4().hex).resolve()
    if artifact_root == repository_tmp or not artifact_root.is_relative_to(repository_tmp):
        raise RuntimeError("valuation artifact directory escaped repository .tmp")
    artifact_root.mkdir(parents=False, exist_ok=False)
    return artifact_root


def _remove_m5_valuation_artifact_root(artifact_root: Path) -> None:
    """Remove only files created directly under this unique fixture directory."""

    repository_tmp = (ROOT / ".tmp").resolve()
    resolved_root = artifact_root.resolve()
    if (
        resolved_root == repository_tmp
        or not resolved_root.is_relative_to(repository_tmp)
        or resolved_root.name == "m5-valuation-fixtures"
    ):
        raise RuntimeError("refusing to remove an unbounded valuation artifact path")
    for child in resolved_root.iterdir():
        if child.is_file() and child.resolve().parent == resolved_root:
            child.unlink()
        else:
            raise RuntimeError("valuation fixture artifact directory contains an unexpected entry")
    resolved_root.rmdir()


@pytest.fixture
def local_m5_published_valuation_fixture(
    base_url: str,
    django_db_blocker: _DjangoDbBlocker,
) -> Generator[M5PublishedValuationFixture | None, None, None]:
    """Install exact selected valuation members only in the explicit M5 CI database."""

    if os.environ.get("AGOM_M5_PUBLISHED_VALUATION_FIXTURE", "").strip() != "1":
        yield None
        return
    require_m5_valuation_fixture_database(base_url=base_url)
    artifact_root = _create_m5_valuation_artifact_root()
    state: M5PublishedValuationFixture | None = None
    try:
        state = _run_m5_db_operation(
            django_db_blocker,
            lambda: prepare_m5_published_valuation_fixture(
                artifact_root=artifact_root,
                governance_root=ROOT / "governance",
                base_url=base_url,
                requested_asset_code="000001.SZ",
            ),
        )
        yield state
    finally:
        try:
            if state is not None:
                _run_m5_db_operation(
                    django_db_blocker,
                    lambda: cleanup_m5_published_valuation_fixture(
                        base_url=base_url,
                        state=state,
                    ),
                )
        finally:
            _remove_m5_valuation_artifact_root(artifact_root)


@pytest.mark.uat
def test_parameterized_read_primary_tasks_complete(
    browser: Browser,
    base_url: str,
    local_m5_owned_account_fixture: _LocalOwnedAccount | None,
    m5_synthetic_calendar_transport: None,
    local_m5_pool_sentiment_fixture: Callable[[], None],
    local_m5_published_valuation_fixture: M5PublishedValuationFixture | None,
) -> None:
    """Execute reviewed parameterized reads through their least-privileged role."""

    contexts = {role: browser.new_context(base_url=base_url) for role in ("regular", "admin")}
    local_account_id: int | None = None
    try:
        pages = {
            "regular": _login_context(
                contexts["regular"],
                base_url,
                username="m5_uat_regular",
                password=PASSWORD,
            ),
            "admin": _login_context(
                contexts["admin"],
                base_url,
                username="admin",
                password="Aa123456",
            ),
        }
        failures: list[str] = []
        if local_m5_owned_account_fixture is not None:
            owned_accounts = _open_owned_accounts_dashboard_panel(pages["regular"], base_url)
            owned_row = owned_accounts.locator("tbody tr").filter(
                has_text=local_m5_owned_account_fixture["account_name"]
            )
            expect(owned_row).to_have_count(1)
            visible_account_id = int(owned_row.locator("td").nth(0).inner_text())
            assert visible_account_id == local_m5_owned_account_fixture["account_id"]
            assert local_m5_owned_account_fixture["owner_id"] > 0
            local_account_id = visible_account_id

        for template_path, screen_key, action_key, role, params in PARAMETERIZED_READ_CASES:
            page = pages[role]
            case_params = dict(params)
            if action_key == "equity.valuation-overview":
                requested_asset = str(case_params.get("stock_code", ""))
                assert requested_asset == "000001.SZ"
                if local_m5_published_valuation_fixture is not None:
                    assert (
                        local_m5_published_valuation_fixture.requested_asset_code == requested_asset
                    )
            if local_account_id is not None and action_key in {
                "simulated-trading.positions",
                "simulated-trading.trades",
                "simulated-trading.inspection-notification",
            }:
                case_params["account_id"] = local_account_id
            if action_key == "asset-analysis.pool-screen":
                local_m5_pool_sentiment_fixture()
            query = urlencode({"screen": screen_key, "action": action_key, **case_params})
            response_handler, action_responses = _listen_for_tui_action_response(page, action_key)
            try:
                page.goto(
                    f"{base_url}/tui/?{query}",
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                if action_key == "asset-analysis.pool-screen":
                    form = _dashboard_action_form(
                        page,
                        base_url,
                        screen_key=screen_key,
                        action_key=action_key,
                        expected_priority="p0",
                    )
                    _fill_visible_action_parameters(form, case_params)
                    form.locator("button[type='submit']").click()
                _wait_for_declared_read_terminal(page, timeout_ms=90_000)
                status = page.locator("[data-workbench-status]").inner_text()
                error_count = page.locator(".tui-error").count()
                if error_count or status != "读取完成":
                    diagnostic = _safe_read_terminal_diagnostic(page, action_responses)
                    if (
                        action_key == "equity.valuation-overview"
                        and local_m5_published_valuation_fixture is not None
                    ):
                        diagnostic["valuation_failure"] = _valuation_failure_diagnostic(
                            page, action_responses
                        )
                    failures.append(
                        f"{template_path}: {role}: {screen_key} / {action_key}: "
                        f"terminal={json.dumps(diagnostic, ensure_ascii=False, sort_keys=True)}"
                    )
                elif action_key == "asset-analysis.pool-screen":
                    main = page.locator("[data-main-panel]")
                    expect(main.locator(".tui-view-status")).to_be_visible()
                    expect(main.locator(".tui-datagrid table, .tui-empty-state")).to_have_count(1)
                elif (
                    action_key == "equity.valuation-overview"
                    and local_m5_published_valuation_fixture is not None
                ):
                    _assert_m5_published_valuation_result(
                        page,
                        action_responses,
                        local_m5_published_valuation_fixture,
                    )
            except Exception as exc:
                diagnostic = _safe_read_terminal_diagnostic(page, action_responses)
                if (
                    action_key == "equity.valuation-overview"
                    and local_m5_published_valuation_fixture is not None
                ):
                    diagnostic["valuation_failure"] = _valuation_failure_diagnostic(
                        page, action_responses
                    )
                failures.append(
                    f"{template_path}: {role}: {screen_key} / {action_key}: "
                    f"{type(exc).__name__}; "
                    f"terminal={json.dumps(diagnostic, ensure_ascii=False, sort_keys=True)}"
                )
            finally:
                page.remove_listener("response", response_handler)

        assert failures == [], "\n".join(failures)
    finally:
        for context in contexts.values():
            context.close()


@pytest.mark.uat
def test_strategy_create_detail_update_lifecycle_completes(
    browser: Browser,
    base_url: str,
) -> None:
    """Create, read, and update one user-owned strategy through confirmed TUI writes."""

    context = browser.new_context(base_url=base_url)
    try:
        page = _login_context(
            context,
            base_url,
            username="m5_uat_regular",
            password=PASSWORD,
        )
        strategy_name = f"M5 UAT 策略 {_m5_uat_suffix()}"
        create_query = urlencode(
            {
                "screen": "macro-regime.strategy",
                "action": "strategy.workbench-create",
                "name": strategy_name,
                "strategy_type": "rule_based",
            }
        )
        page.goto(f"{base_url}/tui/?{create_query}", wait_until="domcontentloaded")
        create_form = _visible_action_form(page, "form:has(#tui-strategy\\.workbench-create-name)")
        expect(create_form.locator("#tui-strategy\\.workbench-create-name")).to_have_value(
            strategy_name
        )
        create_form.locator("button[type='submit']").click()
        confirmation = page.get_by_role("dialog", name="确认操作", exact=True)
        expect(confirmation).to_be_visible()
        create_started = time.monotonic()
        confirmation.get_by_role("button", name="确认执行", exact=True).click()
        expect(page.locator("[data-workbench-status]")).to_have_text(
            "操作完成", timeout=CONFIRMED_MUTATION_SETTLEMENT_TIMEOUT_MS
        )
        create_settlement_ms = round((time.monotonic() - create_started) * 1000)
        main = page.locator("[data-main-panel]")
        expect(main.get_by_text(strategy_name, exact=True)).to_be_visible()
        strategy_id = int(
            main.get_by_text("ID", exact=True)
            .locator("xpath=following-sibling::dd[1]")
            .inner_text()
        )
        assert strategy_id > 0

        detail_query = urlencode(
            {
                "screen": "macro-regime.strategy",
                "action": "strategy.workbench-detail",
                "strategy_id": strategy_id,
            }
        )
        page.goto(f"{base_url}/tui/?{detail_query}", wait_until="domcontentloaded")
        expect(page.locator("[data-workbench-status]")).to_have_text("读取完成")
        expect(
            page.locator("[data-main-panel]").get_by_text(strategy_name, exact=True)
        ).to_be_visible()

        updated_description = "M5 UAT 已验证详情与确认式更新"
        update_query = urlencode(
            {
                "screen": "macro-regime.strategy",
                "action": "strategy.workbench-update",
                "strategy_id": strategy_id,
                "description": updated_description,
            }
        )
        page.goto(f"{base_url}/tui/?{update_query}", wait_until="domcontentloaded")
        update_form = _visible_action_form(
            page, "form:has(#tui-strategy\\.workbench-update-strategy_id)"
        )
        update_form.locator("button[type='submit']").click()
        confirmation = page.get_by_role("dialog", name="确认操作", exact=True)
        expect(confirmation).to_be_visible()
        update_started = time.monotonic()
        confirmation.get_by_role("button", name="确认执行", exact=True).click()
        expect(page.locator("[data-workbench-status]")).to_have_text(
            "操作完成", timeout=CONFIRMED_MUTATION_SETTLEMENT_TIMEOUT_MS
        )
        update_settlement_ms = round((time.monotonic() - update_started) * 1000)
        expect(
            page.locator("[data-main-panel]").get_by_text(updated_description, exact=True)
        ).to_be_visible()
        expect(page.locator(".tui-error")).to_have_count(0)

        _run_confirmed_action(
            page,
            base_url,
            screen_key="macro-regime.strategy",
            action_key="strategy.workbench-delete",
            params={"strategy_id": strategy_id},
            form_selector="form:has(#tui-strategy\\.workbench-delete-strategy_id)",
        )
        main = _run_read_deep_link(
            page,
            base_url,
            screen_key="macro-regime.strategy",
            action_key="strategy.workbench-list",
        )
        expect(main.get_by_text(strategy_name, exact=True)).to_have_count(0)
        _persist_controlled_write_receipt(
            {
                "entity_type": "strategy",
                "entity_id": strategy_id,
                "entity_name": strategy_name,
                "actor_username": "m5_uat_regular",
                "owner_username": "m5_uat_regular",
                "confirmation": {"create": True, "update": True, "cleanup": True},
                "write_actions": [
                    "strategy.workbench-create",
                    "strategy.workbench-update",
                    "strategy.workbench-delete",
                ],
                "readback": {
                    "created": True,
                    "updated": True,
                    "updated_description": updated_description,
                },
                "settlement": {
                    "slo_ms": CONFIRMED_MUTATION_SETTLEMENT_TIMEOUT_MS,
                    "create_ms": create_settlement_ms,
                    "update_ms": update_settlement_ms,
                },
                "cleanup": {
                    "action": "strategy.workbench-delete",
                    "deleted": True,
                    "residual_count": 0,
                },
            }
        )
    finally:
        context.close()


@pytest.mark.uat
def test_personal_ai_provider_detail_update_lifecycle_completes(
    browser: Browser,
    base_url: str,
) -> None:
    """Create, read, and update one user-owned AI provider through the TUI."""

    context = browser.new_context(base_url=base_url)
    try:
        page = _login_context(
            context,
            base_url,
            username="m5_uat_regular",
            password=PASSWORD,
        )
        provider_name = f"M5 UAT 服务商 {_m5_uat_suffix()}"
        provider_api_key = f"m5-uat-placeholder-{_m5_uat_suffix()}"
        create_query = urlencode(
            {
                "screen": "ai-ops.providers",
                "action": "ai-ops.create-my-provider",
                "name": provider_name,
                "provider_type": "custom",
                "base_url": "https://example.invalid/v1",
                "is_active": "false",
            }
        )
        page.goto(f"{base_url}/tui/?{create_query}", wait_until="domcontentloaded")
        create_form = _visible_action_form(
            page,
            "form:has(#tui-ai-ops\\.create-my-provider-name)",
        )
        create_form.locator("button[type='submit']").click()
        missing_dialog = page.get_by_role("dialog", name="补填参数", exact=True)
        # Credential fields are deliberately excluded from URL prefill.  Wait
        # for the browser prompt, then use an inert run-scoped placeholder.
        expect(missing_dialog).to_be_visible(timeout=10_000)
        missing_dialog.locator("input[type='password']").fill(provider_api_key)
        missing_dialog.get_by_role("button", name="继续", exact=True).click()
        confirmation = page.get_by_role("dialog", name="确认操作", exact=True)
        expect(confirmation).to_be_visible()
        create_started = time.monotonic()
        confirmation.get_by_role("button", name="确认执行", exact=True).click()
        expect(page.locator("[data-workbench-status]")).to_have_text(
            "操作完成", timeout=CONFIRMED_MUTATION_SETTLEMENT_TIMEOUT_MS
        )
        create_settlement_ms = round((time.monotonic() - create_started) * 1000)
        main = page.locator("[data-main-panel]")
        expect(main.get_by_text(provider_name, exact=True)).to_be_visible()
        provider_id = int(
            main.get_by_text("ID", exact=True)
            .locator("xpath=following-sibling::dd[1]")
            .inner_text()
        )
        assert provider_id > 0

        detail_query = urlencode(
            {
                "screen": "ai-ops.providers",
                "action": "ai-ops.my-provider-detail",
                "provider_id": provider_id,
            }
        )
        page.goto(f"{base_url}/tui/?{detail_query}", wait_until="domcontentloaded")
        expect(page.locator("[data-workbench-status]")).to_have_text("读取完成")
        expect(
            page.locator("[data-main-panel]").get_by_text(provider_name, exact=True)
        ).to_be_visible()

        updated_description = "M5 UAT 已验证用户归属和确认式更新"
        update_query = urlencode(
            {
                "screen": "ai-ops.providers",
                "action": "ai-ops.update-my-provider",
                "provider_id": provider_id,
                "description": updated_description,
            }
        )
        page.goto(f"{base_url}/tui/?{update_query}", wait_until="domcontentloaded")
        update_form = _visible_action_form(
            page,
            "form:has(#tui-ai-ops\\.update-my-provider-provider_id)",
        )
        update_form.locator("button[type='submit']").click()
        confirmation = page.get_by_role("dialog", name="确认操作", exact=True)
        expect(confirmation).to_be_visible()
        update_started = time.monotonic()
        confirmation.get_by_role("button", name="确认执行", exact=True).click()
        expect(page.locator("[data-workbench-status]")).to_have_text(
            "操作完成", timeout=CONFIRMED_MUTATION_SETTLEMENT_TIMEOUT_MS
        )
        update_settlement_ms = round((time.monotonic() - update_started) * 1000)
        expect(
            page.locator("[data-main-panel]").get_by_text(updated_description, exact=True)
        ).to_be_visible()
        expect(page.locator(".tui-error")).to_have_count(0)

        _run_confirmed_action(
            page,
            base_url,
            screen_key="ai-ops.providers",
            action_key="ai-ops.delete-my-provider",
            params={"provider_id": provider_id},
            form_selector="form:has(#tui-ai-ops\\.delete-my-provider-provider_id)",
        )
        main = _run_read_deep_link(
            page,
            base_url,
            screen_key="ai-ops.providers",
            action_key="ai-ops.list-my-providers",
        )
        expect(main.get_by_text(provider_name, exact=True)).to_have_count(0)
        _persist_controlled_write_receipt(
            {
                "entity_type": "ai_provider",
                "entity_id": provider_id,
                "entity_name": provider_name,
                "actor_username": "m5_uat_regular",
                "owner_username": "m5_uat_regular",
                "confirmation": {"create": True, "update": True, "cleanup": True},
                "write_actions": [
                    "ai-ops.create-my-provider",
                    "ai-ops.update-my-provider",
                    "ai-ops.delete-my-provider",
                ],
                "readback": {
                    "created": True,
                    "updated": True,
                    "updated_description": updated_description,
                },
                "settlement": {
                    "slo_ms": CONFIRMED_MUTATION_SETTLEMENT_TIMEOUT_MS,
                    "create_ms": create_settlement_ms,
                    "update_ms": update_settlement_ms,
                },
                "cleanup": {
                    "action": "ai-ops.delete-my-provider",
                    "deleted": True,
                    "residual_count": 0,
                },
            }
        )
    finally:
        context.close()


@pytest.mark.uat
def test_policy_admin_create_flows_complete(
    browser: Browser,
    base_url: str,
) -> None:
    """Create a policy event, keyword rule, and RSS source through confirmed writes."""

    context = browser.new_context(base_url=base_url)
    try:
        page = _login_context(
            context,
            base_url,
            username="admin",
            password="Aa123456",
        )
        suffix = _m5_uat_suffix()

        event_title = f"M5 UAT 政策事件 {suffix}"
        _run_confirmed_action(
            page,
            base_url,
            screen_key="policy.workbench",
            action_key="policy.event-create",
            params={
                "event_date": "2026-07-27",
                "level": "P3",
                "title": event_title,
                "description": "M5 UAT 已完成管理员确认式政策事件创建和持久化验证",
                "evidence_url": f"https://example.invalid/evidence/{suffix}",
            },
            form_selector="form:has(#tui-policy\\.event-create-event_date)",
        )
        main = _run_read_deep_link(
            page,
            base_url,
            screen_key="policy.workbench",
            action_key="policy.event-list",
            params={"start_date": "2026-07-27", "end_date": "2026-07-27"},
        )
        expect(main.get_by_text(event_title, exact=True)).to_be_visible()

        keyword = f"m5-uat-{suffix}"
        keyword_category = f"uat-{suffix}"
        _run_confirmed_action(
            page,
            base_url,
            screen_key="policy.workbench",
            action_key="policy.rss-keyword-create",
            params={
                "level": "P3",
                "keywords": f'["{keyword}"]',
                "weight": 1,
                "category": keyword_category,
                "is_active": True,
            },
            form_selector="form:has(#tui-policy\\.rss-keyword-create-level)",
        )
        main = _run_read_deep_link(
            page,
            base_url,
            screen_key="policy.workbench",
            action_key="policy.rss-keyword-list",
        )
        expect(main.get_by_text(keyword_category, exact=True)).to_be_visible()

        source_name = f"M5 UAT RSS {suffix}"
        _run_confirmed_action(
            page,
            base_url,
            screen_key="policy.workbench",
            action_key="policy.rss-source-create",
            params={
                "name": source_name,
                "url": f"https://example.invalid/feed/{suffix}.xml",
                "category": "other",
                "is_active": True,
                "fetch_interval_hours": 24,
            },
            form_selector="form:has(#tui-policy\\.rss-source-create-name)",
        )
        main = _run_read_deep_link(
            page,
            base_url,
            screen_key="policy.workbench",
            action_key="policy.rss-source-list",
        )
        expect(main.get_by_text(source_name, exact=True)).to_be_visible()
    finally:
        context.close()


@pytest.mark.uat
def test_governance_and_screening_confirmed_flows_complete(
    browser: Browser,
    base_url: str,
) -> None:
    """Complete quota, Beta Gate, and fund confirmed workflows."""

    contexts = {role: browser.new_context(base_url=base_url) for role in ("regular", "admin")}
    try:
        pages = {
            "regular": _login_context(
                contexts["regular"],
                base_url,
                username="m5_uat_regular",
                password=PASSWORD,
            ),
            "admin": _login_context(
                contexts["admin"],
                base_url,
                username="admin",
                password="Aa123456",
            ),
        }
        suffix = _m5_uat_suffix()

        quota_params = {
            "account_id": REMOTE_ACCOUNT_ID,
            "period": "daily",
            "max_decisions": 12,
            "max_executions": 6,
        }
        main = _run_confirmed_action(
            pages["admin"],
            base_url,
            screen_key="command-center.decision-flow",
            action_key="decision-rhythm.quota-update",
            params=quota_params,
            form_selector="form:has(#tui-decision-rhythm\\.quota-update-period)",
        )
        expect(main.get_by_text("daily", exact=True)).to_be_visible()
        quota_readback = _run_read_deep_link(
            pages["admin"],
            base_url,
            screen_key="command-center.decision-flow",
            action_key="decision-rhythm.quota-list",
            params={
                "account_id": quota_params["account_id"],
                "period": quota_params["period"],
            },
        )
        quota_row = (
            quota_readback.get_by_role("row")
            .filter(has_text=str(quota_params["account_id"]))
            .filter(has_text=str(quota_params["period"]))
        )
        expect(quota_row).to_have_count(1)
        expect(quota_row.locator("td").nth(0)).to_have_text(str(quota_params["account_id"]))
        expect(quota_row.locator("td").nth(1)).to_have_text(str(quota_params["period"]))
        expect(quota_row.locator("td").nth(3)).to_have_text(str(quota_params["max_decisions"]))
        expect(quota_row.locator("td").nth(5)).to_have_text(str(quota_params["max_executions"]))

        config_id = f"m5-{suffix}"
        config_params = {
            "config_id": config_id,
            "risk_profile": "balanced",
        }
        main = _run_confirmed_action(
            pages["admin"],
            base_url,
            screen_key="macro-regime.strategy",
            action_key="beta-gate.config-create",
            params=config_params,
            form_selector="form:has(#tui-beta-gate\\.config-create-risk_profile)",
        )
        expect(main.get_by_text(config_id, exact=True)).to_be_visible()
        config_readback = _run_read_deep_link(
            pages["admin"],
            base_url,
            screen_key="macro-regime.strategy",
            action_key="beta-gate.config-list",
            params={"active_only": "false"},
        )
        config_row = config_readback.get_by_role("row").filter(has_text=config_id)
        expect(config_row).to_have_count(1)
        expect(config_row.locator("td").nth(0)).to_have_text(config_id)
        expect(config_row.locator("td").nth(1)).to_have_text(config_params["risk_profile"])

        beta_test_params = {
            "asset_codes": '["000001.SZ"]',
            "asset_class": "equity",
            "current_regime": "Recovery",
            "regime_confidence": 0.8,
            "policy_level": 1,
        }
        beta_test_main = _run_confirmed_action(
            pages["regular"],
            base_url,
            screen_key="macro-regime.strategy",
            action_key="beta-gate.test-assets",
            params=beta_test_params,
            form_selector="form:has(#tui-beta-gate\\.test-assets-asset_codes)",
        )
        beta_asset_code = json.loads(beta_test_params["asset_codes"])[0]
        beta_result_row = beta_test_main.get_by_role("row").filter(has_text=beta_asset_code)
        expect(beta_result_row).to_have_count(1)
        expect(beta_result_row.locator("td").nth(0)).to_contain_text(beta_asset_code)
        expect(beta_result_row.locator("td").nth(1)).to_have_text(beta_test_params["asset_class"])
        passed_label = beta_result_row.locator("td").nth(2).inner_text().strip()
        gate_status = beta_result_row.locator("td").nth(3).inner_text().strip()
        assert passed_label in {"是", "否"}, "Beta Gate must expose its passed decision."
        assert gate_status in {
            "passed",
            "blocked_regime",
            "blocked_policy",
            "blocked_risk",
            "blocked_confidence",
            "blocked_portfolio",
            "watch",
        }, "Beta Gate must expose one declared business status."
        assert (passed_label == "是") is (
            gate_status == "passed"
        ), "Beta Gate passed must agree with its declared status."

        with pages["regular"].expect_response(
            lambda response: (
                urlparse(response.url).path == "/api/tui/actions/fund.multidim-screen/run/"
                and response.request.method == "POST"
                and response.request.post_data_json.get("confirmed") is True
            ),
            timeout=CONFIRMED_MUTATION_SETTLEMENT_TIMEOUT_MS,
        ) as fund_execution_response:
            fund_main = _run_confirmed_action(
                pages["regular"],
                base_url,
                screen_key="research.asset-lab",
                action_key="fund.multidim-screen",
                params={
                    "regime": "Recovery",
                    "policy_level": "P1",
                    "sentiment_index": 0.0,
                },
                form_selector="form:has(#tui-fund\\.multidim-screen-fund_type)",
            )
        fund_envelope = fund_execution_response.value.json()
        assert (
            fund_envelope.get("outcome") == "success"
        ), "Fund screening must retain its owner success outcome."
        fund_response = fund_envelope.get("response")
        assert isinstance(fund_response, dict), "Fund action envelope must expose response status."
        assert (
            fund_response.get("status_code") == 200
        ), "Fund screening must complete with the owner's documented 200 response."
        fund_view_model = fund_envelope.get("view_model")
        assert isinstance(
            fund_view_model, dict
        ), "Fund action envelope must expose its result view."
        assert (
            fund_view_model.get("kind") == "datagrid"
        ), "Fund screening must retain its declared result grid."
        fund_pager = fund_view_model.get("pager")
        assert isinstance(fund_pager, dict), "Fund result grid must expose its row count."
        fund_total = fund_pager.get("total_rows")
        assert (
            type(fund_total) is int and fund_total >= 0
        ), "Fund result grid must expose a nonnegative integer row count."
        fund_table_rows = fund_main.locator(".tui-datagrid tbody tr")
        expect(fund_table_rows).to_have_count(fund_total)
        if fund_total == 0:
            assert (
                fund_view_model.get("status") == "暂无数据"
            ), "Only the owner's successful zero-row result is valid no-data."
            expect(fund_main.locator(".tui-view-status")).to_contain_text(
                re.compile(r"^暂无数据 / ")
            )
        else:
            expect(fund_main.get_by_role("columnheader", name="基金代码")).to_be_visible()
            expect(fund_main.get_by_role("columnheader", name="综合分")).to_be_visible()
            first_fund_row = fund_table_rows.first
            expect(first_fund_row.locator("td").nth(0)).to_have_text(re.compile(r"\S"))
            expect(first_fund_row.locator("td").nth(4)).to_have_text(re.compile(r"\S"))

    finally:
        for context in contexts.values():
            context.close()


@pytest.fixture
def local_equity_no_publication_scope(base_url: str) -> None:
    """Admit the no-publication probe only on the disposable RC Playwright database."""

    hostname = (urlparse(base_url).hostname or "").lower()
    try:
        is_literal_loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        is_literal_loopback = False
    if not is_literal_loopback:
        pytest.skip(
            "equity no-publication case is local-RC-only; remote targets need a separately "
            "admitted controlled fixture and are not production UAT"
        )

    if (
        os.environ.get("GITHUB_ACTIONS", "").strip().lower() != "true"
        or os.environ.get("CI", "").strip().lower() != "true"
    ):
        pytest.skip("equity no-publication case requires the isolated GitHub Actions RC job")

    if (
        REMOTE_UAT_RUN_ID
        or REMOTE_ACTORS_READY
        or os.environ.get("AGOM_REMOTE_UAT_ACCOUNT_IDS", "").strip()
    ):
        pytest.fail(
            "equity no-publication case refuses remote UAT credentials or scope",
            pytrace=False,
        )

    expected_settings_module = _expected_disposable_playwright_settings_module()
    if os.environ.get("DJANGO_SETTINGS_MODULE", "").strip() != expected_settings_module:
        pytest.fail(
            "equity no-publication case requires the selected isolated settings module",
            pytrace=False,
        )

    runner_temp = os.environ.get("RUNNER_TEMP", "").strip()
    configured_path = os.environ.get("AGOM_PLAYWRIGHT_DB_PATH", "").strip()
    if not runner_temp or not configured_path:
        pytest.fail(
            "equity no-publication case requires the disposable Playwright database path",
            pytrace=False,
        )

    runner_temp_path = Path(runner_temp).expanduser().resolve()
    expected_database_path = (runner_temp_path / "agomtradepro-rc-playwright.sqlite3").resolve()
    if Path(configured_path).expanduser().resolve() != expected_database_path:
        pytest.fail(
            "equity no-publication case requires the fixed SQLite file under RUNNER_TEMP",
            pytrace=False,
        )

    from django.conf import settings

    database = settings.DATABASES.get("default", {})
    test_database = database.get("TEST", {})
    default_name = str(database.get("NAME", "")).strip()
    test_name = str(test_database.get("NAME", "")).strip()
    default_path = Path(default_name).expanduser().resolve() if default_name else None
    test_path = Path(test_name).expanduser().resolve() if test_name else None
    if (
        settings.SETTINGS_MODULE != expected_settings_module
        or database.get("ENGINE") != "django.db.backends.sqlite3"
        or default_path != expected_database_path
        or test_path != expected_database_path
    ):
        pytest.fail(
            "equity no-publication case refused a non-disposable Playwright database",
            pytrace=False,
        )


@pytest.mark.uat
def test_local_isolated_ci_equity_screening_without_publication_is_blocked(
    browser: Browser,
    base_url: str,
    local_equity_no_publication_scope: None,
) -> None:
    """Verify blocked no-publication behavior on isolated local CI only."""

    del local_equity_no_publication_scope
    context = browser.new_context(base_url=base_url)
    try:
        page = _login_context(
            context,
            base_url,
            username="m5_uat_regular",
            password=PASSWORD,
        )
        query = urlencode(
            {
                "screen": "research.asset-lab",
                "action": "equity.screen-stocks",
                "regime": "Recovery",
            }
        )
        page.goto(f"{base_url}/tui/?{query}", wait_until="domcontentloaded")
        form = _visible_action_form(
            page,
            "form:has(#tui-equity\\.screen-stocks-regime)",
        )
        form.locator("button[type='submit']").click()
        confirmation = page.get_by_role("dialog", name="确认操作", exact=True)
        expect(confirmation).to_be_visible()
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and response.url.endswith("/api/tui/actions/equity.screen-stocks/run/")
                and response.request.post_data_json.get("confirmed") is True
            )
        ) as confirmed_response_info:
            confirmation.get_by_role("button", name="确认执行", exact=True).click()
        confirmed_response = confirmed_response_info.value
        assert (
            confirmed_response.status == 200
        ), "The ordinary TUI action endpoint should return its business outcome envelope."
        envelope = confirmed_response.json()
        assert isinstance(envelope, dict), "The TUI action response must be an object."
        assert (
            envelope.get("outcome") == "blocked"
        ), "A published stock screening without publication inputs must remain blocked."
        transport = envelope.get("response")
        assert isinstance(
            transport, dict
        ), "The TUI envelope must preserve transport status metadata."
        assert (
            transport.get("status_code") == 200
        ), "The owner block is an HTTP 200 business outcome, not an action timeout."
        view_model = envelope.get("view_model")
        assert isinstance(view_model, dict), "The blocked outcome must retain its safe result view."
        assert view_model.get("kind") == "datagrid"
        assert view_model.get("outcome") == "blocked"
        assert view_model.get("must_not_use_for_decision") is True
        assert view_model.get("status") == "不可用于决策"
        assert view_model.get("business_summary") == "股票筛选已阻断；当前结果不可用于决策。"
        assert view_model.get("blocking_reason") == "所需筛选数据当前不可用。"
        assert view_model.get("empty_message") == "筛选已阻断，未生成可用结果。"
        pager = view_model.get("pager")
        assert isinstance(pager, dict), "The blocked grid must retain its row-count contract."
        assert pager.get("total_rows") == 0

        expect(page.locator("[data-workbench-status]")).to_have_text("结果受阻，未形成可用结果")
        expect(page.locator(".tui-error")).to_have_count(0)
        expect(page.locator("[data-main-panel] .tui-entry-state")).to_have_count(0)
        main = page.locator("[data-main-panel]")
        expect(main.locator(".tui-view-status")).to_contain_text(re.compile(r"^不可用于决策 / "))
        expect(main.locator(".tui-datagrid tbody tr")).to_have_count(0)
    finally:
        context.close()


@pytest.mark.uat
def test_local_fixture_detail_and_lifecycle_routes_complete(
    browser: Browser,
    base_url: str,
    local_route_uat_fixture_ids: dict[str, int | str],
) -> None:
    """Complete the remaining detail and lifecycle routes without external AI calls."""

    contexts = {role: browser.new_context(base_url=base_url) for role in ("regular", "operator")}
    try:
        pages = {
            "regular": _login_context(
                contexts["regular"],
                base_url,
                username="m5_uat_regular",
                password=PASSWORD,
            ),
            "operator": _login_context(
                contexts["operator"],
                base_url,
                username="m5_uat_operator",
                password=PASSWORD,
            ),
        }

        main = _run_read_deep_link(
            pages["operator"],
            base_url,
            screen_key="ai-ops.terminal",
            action_key="agent-runtime.operator-task-detail",
            params={"task_id": int(local_route_uat_fixture_ids["agent_task_id"])},
        )
        expect(main.get_by_text("m5-uat-agent-task-detail", exact=True)).to_be_visible()
        main = _run_read_deep_link(
            pages["operator"],
            base_url,
            screen_key="ai-ops.terminal",
            action_key="agent-runtime.operator-proposal-detail",
            params={"proposal_id": int(local_route_uat_fixture_ids["agent_proposal_id"])},
        )
        expect(main.get_by_text("m5-uat-agent-proposal-detail", exact=True)).to_be_visible()

        main = _run_read_deep_link(
            pages["regular"],
            base_url,
            screen_key="research.signals",
            action_key="alpha-trigger.candidate-detail",
            params={"candidate_id": str(local_route_uat_fixture_ids["candidate_id"])},
        )
        expect(main.get_by_text("m5-uat-alpha-candidate-detail", exact=True)).to_be_visible()

        suffix = _m5_uat_suffix()
        trigger_thesis = f"M5 alpha lifecycle evidence {suffix}"
        updated_thesis = f"M5 alpha lifecycle updated {suffix}"
        main = _run_confirmed_action(
            pages["regular"],
            base_url,
            screen_key="research.signals",
            action_key="alpha-trigger.create",
            params={
                "trigger_type": "momentum_signal",
                "asset_code": "000001.SZ",
                "asset_class": "a_share",
                "direction": "LONG",
                "trigger_condition": '{"signal":"cross_up"}',
                "invalidation_conditions": (
                    '[{"condition_type":"threshold_cross",'
                    '"indicator_code":"CN_PMI_MANUFACTURING",'
                    '"threshold":50.0,"direction":"below"}]'
                ),
                "confidence": 0.82,
                "thesis": trigger_thesis,
                "expires_in_days": 30,
            },
            form_selector="form:has(#tui-alpha-trigger\\.create-asset_code)",
        )
        trigger_match = re.search(r"trigger_[0-9a-f]{12}", main.inner_text())
        assert trigger_match is not None
        trigger_id = trigger_match.group(0)

        main = _run_read_deep_link(
            pages["regular"],
            base_url,
            screen_key="research.signals",
            action_key="alpha-trigger.trigger-detail",
            params={"trigger_id": trigger_id},
        )
        expect(main.get_by_text(trigger_id, exact=True)).to_be_visible()

        main = _run_confirmed_action(
            pages["regular"],
            base_url,
            screen_key="research.signals",
            action_key="alpha-trigger.update",
            params={
                "trigger_id": trigger_id,
                "confidence": 0.86,
                "thesis": updated_thesis,
            },
            form_selector="form:has(#tui-alpha-trigger\\.update-trigger_id)",
        )
        expect(main.get_by_text(updated_thesis, exact=True)).to_be_visible()

        _run_confirmed_action(
            pages["regular"],
            base_url,
            screen_key="research.signals",
            action_key="alpha-trigger.check-invalidation",
            params={
                "trigger_id": trigger_id,
                "current_indicator_values": '{"CN_PMI_MANUFACTURING":55.0}',
                "current_regime": "Recovery",
            },
            form_selector=("form:has(#tui-alpha-trigger\\.check-invalidation-trigger_id)"),
        )

        main = _run_read_deep_link(
            pages["regular"],
            base_url,
            screen_key="execution.audit",
            action_key="audit.attribution-detail",
            params={"report_id": int(local_route_uat_fixture_ids["attribution_report_id"])},
        )
        expect(main.get_by_text("0.06", exact=True)).to_be_visible()

        backtest_name = f"M5 UAT 回测 {_m5_uat_suffix()}"
        main = _run_confirmed_action(
            pages["regular"],
            base_url,
            screen_key="research.asset-lab",
            action_key="backtest.run",
            params={
                "name": backtest_name,
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "initial_capital": 100000,
                "rebalance_frequency": "monthly",
                "transaction_cost_bps": 10,
                "trust_status": "exploratory",
            },
            form_selector="form:has(#tui-backtest\\.run-name)",
        )
        backtest_receipt = main.inner_text()
        backtest_match = re.search(r"回测ID\s+(\d+)", backtest_receipt)
        assert backtest_match is not None, backtest_receipt
        backtest_id = int(backtest_match.group(1))
        main = _run_read_deep_link(
            pages["regular"],
            base_url,
            screen_key="research.asset-lab",
            action_key="backtest.detail",
            params={"pk": backtest_id},
        )
        expect(main.get_by_text(backtest_name, exact=True)).to_be_visible()

        _run_confirmed_action(
            pages["regular"],
            base_url,
            screen_key="research.asset-lab",
            action_key="factor.calculate-config",
            params={
                "config_id": int(local_route_uat_fixture_ids["factor_config_id"]),
                "trade_date": "2026-07-27",
                "top_n": 5,
            },
            form_selector="form:has(#tui-factor\\.calculate-config-config_id)",
        )
    finally:
        for context in contexts.values():
            context.close()


@pytest.mark.uat
@pytest.mark.live_required
@pytest.mark.skipif(
    not EXTERNAL_AI_UAT_ENABLED,
    reason=EXTERNAL_AI_UAT_SKIP_REASON,
)
def test_sentiment_external_ai_primary_task_completes(
    browser: Browser,
    base_url: str,
) -> None:
    """Analyze uncached text through a controlled real AI provider and the TUI."""

    context = browser.new_context(base_url=base_url)
    try:
        page = _login_context(
            context,
            base_url,
            username="m5_uat_regular",
            password=PASSWORD,
        )
        main = _run_confirmed_action(
            page,
            base_url,
            screen_key="research.signals",
            action_key="sentiment.analyze-text",
            params={
                "text": (
                    "M5 受控外部 AI 验收：盈利改善、现金流增强且风险保持可控。"
                    f" 唯一批次 {_m5_uat_suffix()}."
                ),
                "use_cache": False,
            },
            form_selector="form:has(#tui-sentiment\\.analyze-text-text)",
            result_timeout_ms=120_000,
        )
        receipt = main.inner_text()
        assert "情绪评分" in receipt, receipt
        assert "置信度" in receipt, receipt
        assert "分类" in receipt, receipt
        assert "AI 调用失败" not in receipt, receipt
    finally:
        context.close()


@pytest.mark.uat
@pytest.mark.live_required
@pytest.mark.skipif(
    not EXTERNAL_AI_UAT_ENABLED,
    reason=EXTERNAL_AI_UAT_SKIP_REASON,
)
def test_terminal_external_ai_primary_task_completes(
    browser: Browser,
    base_url: str,
) -> None:
    """Receive a non-empty Terminal Agent reply through a controlled real provider."""

    context = browser.new_context(base_url=base_url)
    try:
        page = _login_context(
            context,
            base_url,
            username="admin",
            password="Aa123456",
        )
        query = urlencode(
            {
                "screen": "ai-ops.terminal",
                "action": "terminal.agent_chat",
                "message": "请用一句中文说明风险预算的作用，不要调用工具。",
            }
        )
        page.goto(f"{base_url}/tui/?{query}", wait_until="domcontentloaded")
        form = _visible_action_form(
            page,
            "form:has(#tui-terminal\\.agent_chat-message)",
        )
        form.locator("button[type='submit']").click()
        expect(page.locator("[data-workbench-status]")).to_have_text("读取完成", timeout=120_000)
        expect(page.locator(".tui-error")).to_have_count(0)
        main = page.locator("[data-main-panel]")
        expect(main.locator(".tui-view-status")).to_contain_text("正常 / ")
        reply = (
            main.get_by_text("回复", exact=True)
            .locator("xpath=following-sibling::dd[1]")
            .inner_text()
            .strip()
        )
        assert reply not in {"", "-"}
    finally:
        context.close()
