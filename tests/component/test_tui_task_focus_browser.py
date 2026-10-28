"""Local TUX-10 browser acceptance based on the TUX-09 journeys.

The cases use real local Django models and the real TUI/owner endpoints.  They
use an isolated test database and establish no production or human-acceptance
claim.  This file deliberately does not mock successful
owner responses, provider calls, portfolio authorization, or browser state.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from django.conf import settings
from django.db import connections
from django.test import Client
from django.utils import timezone
from playwright.sync_api import Page, Response, Route, expect, sync_playwright

from apps.account.infrastructure.models import (
    AssetCategoryModel,
    CurrencyModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
)
from apps.decision_rhythm.application.decision_model_param_use_cases import GetModelParamsUseCase
from apps.decision_rhythm.application.decision_recommendation_use_cases import (
    FeatureFreshnessContract,
    GenerateRecommendationsRequest,
    GenerateUnifiedRecommendationsUseCase,
)
from apps.decision_rhythm.application.dtos import UnifiedRecommendationDTO
from apps.decision_rhythm.domain.model_param_entities import ModelParamConfig
from apps.decision_rhythm.infrastructure.feature_providers import CompositeFeatureProvider
from apps.decision_rhythm.infrastructure.models import (
    DecisionModelParamConfigModel,
    UnifiedRecommendationModel,
)
from apps.decision_rhythm.infrastructure.unified_repositories import (
    DecisionModelParamConfigRepository,
    UnifiedRecommendationRepository,
)
from apps.equity.application import query_services as equity_query_services
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy

TODAY_SCREEN = "task.today-focus"
PORTFOLIO_SCREEN = "task.portfolio-check"
MARKET_CONTEXT_ACTION = "today-focus.market-context"
ACCOUNT_SELECTOR_ACTION = "today-focus.account-selector"
TODAY_QUEUE_ACTION = "today-focus.queue"
UNIFIED_RECOMMENDATIONS_ACTION = "auto.api.get.api.decision.workspace.recommendations"
PORTFOLIO_SELECTOR_ACTION = "portfolio-check.portfolios"
RECORDED_FACTS_ACTION = "portfolio-check.recorded-facts"
PORTFOLIO_SELECTOR_PANEL = "portfolio-check-selector"
ACCOUNT_SELECTOR_PANEL = "today-focus-account-selector"
ACTION_PATH_PREFIX = "/api/tui/actions/"
_TUX10_RAW_RUN_LABEL = os.environ.get("TUX10_RUN_LABEL", "candidate")
_TUX10_SAFE_RUN_LABEL = "".join(
    char for char in _TUX10_RAW_RUN_LABEL if char.isalnum() or char in "-_."
)
TUX10_RUN_LABEL = f"{_TUX10_SAFE_RUN_LABEL or 'candidate'}-{uuid4().hex}-focus"


@dataclass(frozen=True)
class TuiTaskBrowserData:
    """Actual local records used by the browser journeys."""

    owner: object
    observer: object
    foreign: object
    portfolios: tuple[PortfolioModel, ...]
    selected_portfolio: PortfolioModel
    foreign_portfolio: PortfolioModel
    grant: PortfolioObserverGrantModel
    owner_accounts: tuple[SimulatedAccountModel, ...]
    observer_accounts: tuple[SimulatedAccountModel, ...]


def _action_path(action_key: str) -> str:
    """Return the TUI action POST path for one registered action."""

    return f"{ACTION_PATH_PREFIX}{action_key}/run/"


def _make_account(user: object, name: str, account_type: str) -> SimulatedAccountModel:
    """Create a real active account with explicit Decimal stored values."""

    return SimulatedAccountModel._default_manager.create(
        user=user,
        account_name=name,
        account_type=account_type,
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("100000.00"),
        is_active=True,
    )


@pytest.fixture
def subprocess_policy() -> Iterator[None]:
    """Use the repository's Windows subprocess policy without async DB bypasses."""

    original = asyncio.get_event_loop_policy()
    changed = ensure_subprocess_event_loop_policy()
    try:
        yield
    finally:
        if changed:
            asyncio.set_event_loop_policy(original)


@pytest.fixture(autouse=True)
def forbid_external_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Allow only local loopback sockets used by the live test server/browser."""

    attempts: list[str] = []
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo

    def is_local_host(host: object) -> bool:
        if host is None:
            return True
        if isinstance(host, bytes):
            host = host.decode("ascii", errors="ignore")
        if not isinstance(host, str):
            return False
        if host.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def host_from_address(address: object) -> object | None:
        if isinstance(address, tuple) and address:
            return address[0]
        return None

    def blocked(kind: str, host: object) -> None:
        attempts.append(f"{kind}:{host!r}")
        raise AssertionError(f"TUX-09 browser fixture attempted external network: {kind}:{host!r}")

    def guarded_connect(sock: socket.socket, address: object) -> object:
        host = host_from_address(address)
        if not is_local_host(host):
            blocked("connect", host)
        return original_connect(sock, address)

    def guarded_create_connection(
        address: object, *args: object, **kwargs: object
    ) -> socket.socket:
        host = host_from_address(address)
        if not is_local_host(host):
            blocked("create_connection", host)
        return original_create_connection(address, *args, **kwargs)

    def guarded_getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
        if not is_local_host(host):
            blocked("getaddrinfo", host)
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    yield
    assert attempts == []


@pytest.fixture
def task_browser_data(django_user_model) -> TuiTaskBrowserData:
    """Build real owner, observer, account, portfolio, and position records."""

    owner = django_user_model.objects.create_user(
        username="tux09-task-owner",
        password="owner-pass",
        is_staff=True,
    )
    observer = django_user_model.objects.create_user(
        username="tux09-task-observer",
        password="observer-pass",
    )
    foreign = django_user_model.objects.create_user(
        username="tux09-task-foreign",
        password="foreign-pass",
    )
    currency, _ = CurrencyModel._default_manager.get_or_create(
        code="CNY",
        defaults={"name": "人民币", "symbol": "¥", "is_base": True},
    )
    category, _ = AssetCategoryModel._default_manager.get_or_create(
        code="equity",
        defaults={"name": "股票", "level": 1, "path": "股票"},
    )

    portfolios: list[PortfolioModel] = []
    for index in range(45):
        portfolios.append(
            PortfolioModel._default_manager.create(
                user=owner,
                name=f"TUX09组合-{index + 1:02d}",
                base_currency=currency,
                is_active=True,
            )
        )
    # The local owner list is ordered newest-first; the latest portfolio stays
    # on page one while the other 44 rows still exercise page three.
    selected_portfolio = portfolios[-1]
    foreign_portfolio = PortfolioModel._default_manager.create(
        user=foreign, name="TUX09外部私有组合", base_currency=currency, is_active=True
    )
    _make_account(foreign, "TUX09外部私有账户", "simulated")
    inactive_account = _make_account(owner, "TUX09已停用账户", "simulated")
    inactive_account.is_active = False
    inactive_account.save(update_fields=["is_active"])

    for index in range(25):
        no_price = index == 1
        no_currency = index == 2
        legal_zero = index == 3
        price = None if no_price else Decimal("12.3400")
        shares = 0.0 if legal_zero else float(index + 1)
        market_value = Decimal("0.00") if legal_zero else Decimal("12.34") * Decimal(str(index + 1))
        PositionModel._default_manager.create(
            portfolio=selected_portfolio,
            asset_code=f"TUX09-{index + 1:03d}.SZ",
            category=category,
            currency=None if no_currency else currency,
            asset_class="equity",
            region="CN",
            cross_border="domestic",
            shares=shares,
            avg_cost=Decimal("10.5000"),
            current_price=price,
            market_value=market_value,
            unrealized_pnl=Decimal("0.00") if legal_zero else Decimal("1.84"),
            unrealized_pnl_pct=0.0 if legal_zero else 17.52,
            source="manual",
            source_id=None,
            is_closed=False,
        )

    grant = PortfolioObserverGrantModel._default_manager.create(
        owner_user_id=owner,
        observer_user_id=observer,
        scope="portfolio_read",
        status="active",
        expires_at=None,
    )
    owner_accounts = tuple(
        _make_account(
            owner,
            f"TUX09实仓-{index + 1:02d}" if index == 0 else f"TUX09模拟-{index + 1:02d}",
            "real" if index == 0 else "simulated",
        )
        for index in range(25)
    )
    observer_accounts = tuple(
        _make_account(
            observer,
            f"TUX09观察账户-{index + 1:02d}",
            "simulated",
        )
        for index in range(25)
    )
    # User creation also creates normal default accounts. Include those real
    # owner records rather than assuming only explicitly named fixtures exist.
    owner_accounts = tuple(
        SimulatedAccountModel._default_manager.filter(user=owner, is_active=True)
    )
    observer_accounts = tuple(
        SimulatedAccountModel._default_manager.filter(user=observer, is_active=True)
    )
    return TuiTaskBrowserData(
        owner=owner,
        observer=observer,
        foreign=foreign,
        portfolios=tuple(portfolios),
        selected_portfolio=selected_portfolio,
        foreign_portfolio=foreign_portfolio,
        grant=grant,
        owner_accounts=owner_accounts,
        observer_accounts=observer_accounts,
    )


@pytest.fixture
def roe_browser_recommendations(
    task_browser_data: TuiTaskBrowserData,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Callable[[str, object], None],
) -> list[UnifiedRecommendationDTO]:
    """Generate real persisted results from explicitly synthetic development sources.

    The financial publication payload, stock master and unrelated features are
    synthetic. The Equity public query, fundamental provider, composite scoring,
    generation, parameter repository, recommendation/snapshot storage and live
    owner reads remain real. This establishes no provider or production claim.
    """

    owner = task_browser_data.owner
    owner.is_staff = False
    owner.save(update_fields=["is_staff"])
    account_id = str(task_browser_data.owner_accounts[0].pk)
    observed_at = "2026-08-03T01:00:00+00:00"
    valuation_observed_at = "2026-08-04T02:00:00+00:00"

    def publications(codes: list[str], **options: object) -> dict[str, object]:
        """Supply finite financial facts whose latest period has no ROE."""

        return {
            code: {
                name: {
                    "publication_id": f"synthetic-roe-browser-{name}",
                    "freshness_status": "fresh",
                    "observed_at": observed_at if name == "financial" else valuation_observed_at,
                    "must_not_use_for_decision": False,
                    "blocked_reason": "",
                    "rows": rows,
                }
                for name, rows in {
                    "financial": [
                        {"period_end": "2026-03-31", "metric_code": "roe", "value": 30.0},
                        {"period_end": "2026-06-30", "metric_code": "debt_ratio", "value": 45.0},
                    ],
                    "valuation": [
                        {
                            "val_date": "2026-08-04",
                            "pe_ttm": 10.0,
                            "observed_at": valuation_observed_at,
                        }
                    ],
                }.items()
                if options.get(f"include_{name}", True)
            }
            for code in codes
        }

    monkeypatch.setattr(
        equity_query_services,
        "get_equity_stock_repository",
        lambda: SimpleNamespace(
            get_stock_master_rows=lambda codes: {
                code: {"asset_code": code, "name": code, "market": "SZ"} for code in codes
            }
        ),
    )
    monkeypatch.setattr(
        equity_query_services, "get_published_equity_context_payloads", publications
    )
    provider = CompositeFeatureProvider()
    monkeypatch.setattr(
        provider, "get_regime", lambda: {"regime": "GROWTH_INFLATION", "confidence": 0.85}
    )
    monkeypatch.setattr(provider, "get_policy_level", lambda: "LEVEL_2")
    monkeypatch.setattr(provider, "check_beta_gate", lambda code: True)
    for method, score in (
        ("get_sentiment_score", 0.7),
        ("get_flow_score", 0.65),
        ("get_technical_score", 0.75),
        ("get_alpha_model_score", 0.85),
    ):
        monkeypatch.setattr(provider, method, lambda code, value=score: value)
    provider._technical_freshness["000003.SZ"] = FeatureFreshnessContract(
        observed_at=observed_at,
        freshness_status="unavailable",
        must_not_use_for_decision=True,
        blocked_reason="source_unavailable",
    )
    repository = UnifiedRecommendationRepository()
    params = DecisionModelParamConfigRepository()
    generator = GenerateUnifiedRecommendationsUseCase(
        feature_provider=provider,
        valuation_provider=SimpleNamespace(get_valuation=lambda code: None),
        signal_provider=SimpleNamespace(get_active_signals=lambda code: []),
        candidate_provider=SimpleNamespace(get_active_candidates=lambda account: []),
        recommendation_repo=repository,
        param_use_case=GetModelParamsUseCase(params, default_env="test"),
    )
    outputs: list[UnifiedRecommendationDTO] = []
    for code, configured, expected_confidence, expected_side, explanation in (
        ("000001.SZ", True, 0.4, "BUY", "扣减已应用"),
        ("000002.SZ", False, 0.5, "BUY", "参数未配置"),
        ("000003.SZ", True, 0.0, "HOLD", "硬阻断优先"),
    ):
        DecisionModelParamConfigModel._default_manager.filter(
            env="test", param_key="missing_feature_confidence_penalty"
        ).delete()
        if configured:
            params.save_param(
                ModelParamConfig(
                    config_id=f"roe-browser-{code}",
                    param_key="missing_feature_confidence_penalty",
                    param_value="0.10",
                    env="test",
                    updated_by="development-browser-fixture",
                    updated_reason="Synthetic-source ROE presentation acceptance",
                )
            )
        response = generator.execute(
            GenerateRecommendationsRequest(account_id=account_id, security_codes=[code])
        )
        assert response.success is True, response.error
        assert len(response.recommendations) == 1
        result = response.recommendations[0]
        assert result.confidence == pytest.approx(expected_confidence)
        assert result.side == expected_side
        assert explanation in result.human_rationale
        persisted = UnifiedRecommendationModel._default_manager.select_related(
            "feature_snapshot"
        ).get(recommendation_id=result.recommendation_id)
        assert persisted.human_rationale == result.human_rationale
        assert persisted.feature_snapshot is not None
        fundamental = persisted.feature_snapshot.extra_features["feature_freshness"]["fundamental"]
        assert fundamental["missing_inputs"][0]["reason"] == "roe_missing"
        assert fundamental["missing_inputs"][0]["observed_at"] == observed_at
        outputs.append(UnifiedRecommendationDTO.from_domain(result))
    record_property(
        "roe_development_owner_results",
        json.dumps(
            {
                "synthetic_boundary": "publication payload, stock master, unrelated feature/provider inputs",
                "source_observed_at": observed_at,
                "valuation_observed_at": valuation_observed_at,
                "owner_is_staff": owner.is_staff,
                "recommendations": [result.to_dict() for result in outputs],
            },
            ensure_ascii=False,
        ),
    )
    return outputs


def _session_cookie(user: object) -> str:
    """Create a normal Django session cookie for a real browser context."""

    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def _new_context(
    playwright: Any,
    live_server: Any,
    session_cookie: str,
    width: int,
    height: int,
) -> Any:
    """Create a local browser context authenticated by a pre-created session."""

    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": width, "height": height})
    context.add_cookies(
        [
            {
                "name": settings.SESSION_COOKIE_NAME,
                "value": session_cookie,
                "url": live_server.url,
            }
        ]
    )
    return browser, context


def _capture_requests(page: Page) -> list[tuple[str, str, object | None]]:
    """Capture browser requests and decode action JSON without changing them."""

    requests: list[tuple[str, str, object | None]] = []

    def record(request: Any) -> None:
        body: object | None = None
        if request.method == "POST" and request.post_data:
            try:
                body = json.loads(request.post_data)
            except (TypeError, ValueError):
                body = request.post_data
        requests.append((request.method, request.url, body))

    page.on("request", record)
    return requests


def _save_browser_evidence(
    page: Page, label: str, requests: list[tuple[str, str, object | None]]
) -> None:
    """Save actual viewport pixels and local request facts for review."""

    directory = (
        Path(
            getattr(
                settings,
                "TUX10_ARTIFACT_ROOT",
                Path(settings.BASE_DIR) / ".tmp/tux10-browser-next-candidate-bbc7d69ff/artifacts",
            )
        )
        / TUX10_RUN_LABEL
    )
    directory.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(directory / f"{label}.png"), full_page=False)
    (directory / f"{label}.json").write_text(
        json.dumps(
            {"url": page.url, "viewport": page.viewport_size, "requests": requests},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf8",
    )


def _assert_local_read_traffic(
    requests: list[tuple[str, str, object | None]], live_server: Any
) -> None:
    """Ensure the browser stayed on the test server and did not send writes."""

    expected_netloc = urlsplit(live_server.url).netloc
    for method, url, _body in requests:
        parsed = urlsplit(url)
        assert parsed.netloc == expected_netloc
        assert method in {"GET", "HEAD", "OPTIONS", "POST"}
        if method == "POST":
            assert parsed.path.startswith(ACTION_PATH_PREFIX)
            assert parsed.path.endswith("/run/")


def _open_task(page: Page, live_server: Any, screen: str) -> None:
    """Open one task screen and wait for its dashboard shell."""

    page.goto(f"{live_server.url}/tui/?screen={screen}", wait_until="networkidle")
    expect(page.locator("[data-main-panel]")).to_be_visible()


def _row_action(page: Page, action_key: str, parameter: tuple[str, int] | None = None) -> Any:
    """Find an action row by key and, when requested, its integer parameter."""

    buttons = page.locator(f'[data-dashboard-row-action][data-row-action-key="{action_key}"]')
    for index in range(buttons.count()):
        button = buttons.nth(index)
        if parameter is None:
            return button
        raw = button.get_attribute("data-row-action-params")
        if not raw:
            continue
        try:
            params = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(params, dict) and str(params.get(parameter[0])) == str(parameter[1]):
            return button
    raise AssertionError(f"No {action_key} row action matched {parameter!r}")


def _click_action(page: Page, button: Any, action_key: str) -> Response:
    """Click one row action and return its real TUI action response."""

    with page.expect_response(
        lambda response: urlsplit(response.url).path == _action_path(action_key)
    ) as response_info:
        button.click()
    return response_info.value


def _tampered_unified_account_read(
    page: Page,
    button: Any,
    form: Any,
    foreign_account_id: int,
    record_property: Callable[[str, object], None],
    *,
    explicit_refresh: bool = False,
) -> dict[str, Any]:
    """Probe a malicious client body against the real backend and UI error path.

    The foreign account is not a normal selectable option. Only one outgoing
    request parameter is changed; the real Session/CSRF and response are untouched.
    """

    selector = form.locator('select[name="account_id"]')
    expect(selector).to_be_visible()
    expect(selector.locator(f'option[value="{foreign_account_id}"]')).to_have_count(0)
    pattern = f"**{_action_path(UNIFIED_RECOMMENDATIONS_ACTION)}"
    sent: list[dict[str, Any]] = []

    def tamper(route: Route) -> None:
        """Continue the original request with one unauthorized account parameter."""

        assert route.request.method == "POST"
        payload = route.request.post_data_json
        assert isinstance(payload, dict)
        params = payload.get("params")
        assert isinstance(params, dict)
        changed = {**payload, "params": {**params, "account_id": foreign_account_id}}
        sent.append(changed["params"])
        route.continue_(post_data=json.dumps(changed))

    page.route(pattern, tamper, times=1)
    try:
        if explicit_refresh:
            with page.expect_response(
                lambda response: urlsplit(response.url).path
                == _action_path(UNIFIED_RECOMMENDATIONS_ACTION)
            ) as response:
                page.keyboard.press("F5")
            result = _envelope(response.value)
        else:
            result = _envelope(_click_action(page, button, UNIFIED_RECOMMENDATIONS_ACTION))
        assert len(sent) == 1
        assert _action_status(result) == 403
        record_property(
            "malicious_account_parameter_probe",
            json.dumps({"params": sent[0], "actual_owner_status": 403}),
        )
        return result
    finally:
        page.unroute(pattern, tamper)


def _envelope(response: Response) -> dict[str, Any]:
    """Decode the bounded TUI action envelope."""

    assert response.headers.get("content-type", "").split(";", 1)[0] == "application/json"
    value = response.json()
    assert isinstance(value, dict)
    return value


def _view_model(result: dict[str, Any]) -> dict[str, Any]:
    """Return the typed view model emitted by the action envelope."""

    value = result.get("view_model")
    assert isinstance(value, dict)
    return value


def _action_status(result: dict[str, Any]) -> int:
    """Read the owner HTTP status retained by the TUI envelope."""

    response = result.get("response")
    assert isinstance(response, dict)
    status = response.get("status_code")
    assert isinstance(status, int)
    return status


def _field_value(result: dict[str, Any], key: str) -> object:
    """Find one detail field by its stable projection key."""

    fields = result.get("fields")
    assert isinstance(fields, list)
    for field in fields:
        if isinstance(field, dict) and field.get("key") == key:
            return field.get("value")
    raise AssertionError(f"Missing projected field {key!r}")


def _detail_table_row(section: Any, column: str, expected: str) -> dict[str, str]:
    """Read one rendered detail row by its actual column labels and value."""

    headers = section.locator("thead th").all_inner_texts()
    assert headers
    rows = section.locator("tbody > tr")
    for index in range(rows.count()):
        values = rows.nth(index).locator("td").all_inner_texts()
        if column not in headers:
            raise AssertionError(f"Missing rendered detail column {column!r}")
        column_index = headers.index(column)
        if column_index < len(values) and values[column_index] == expected:
            return dict(zip(headers, values, strict=True))
    raise AssertionError(f"Missing rendered detail row {column}={expected!r}")


def _posted_params(
    requests: list[tuple[str, str, object | None]], action_key: str
) -> list[dict[str, Any]]:
    """Return JSON parameter bodies posted for one action."""

    path = _action_path(action_key)
    values: list[dict[str, Any]] = []
    for method, url, body in requests:
        if method != "POST" or urlsplit(url).path != path or not isinstance(body, dict):
            continue
        params = body.get("params", body)
        if isinstance(params, dict):
            values.append(params)
    return values


@pytest.mark.django_db(transaction=True)
def test_owner_portfolio_server_paging_native_facts_and_retry(
    live_server: Any,
    task_browser_data: TuiTaskBrowserData,
    subprocess_policy: None,
) -> None:
    """Admin desktop/mobile users reach page three and retry the selected facts read."""

    before_portfolios = PortfolioModel._default_manager.count()
    before_positions = PositionModel._default_manager.count()
    before_accounts = SimulatedAccountModel._default_manager.count()
    owner_cookie = _session_cookie(task_browser_data.owner)
    with sync_playwright() as playwright:
        browser = None
        try:
            for width, height in ((1440, 1000), (390, 844)):
                browser, context = _new_context(
                    playwright, live_server, owner_cookie, width, height
                )
                page = context.new_page()
                requests = _capture_requests(page)
                page_errors: list[str] = []
                page.on(
                    "pageerror", lambda error, recorded=page_errors: recorded.append(str(error))
                )
                _open_task(page, live_server, PORTFOLIO_SCREEN)
                expect(page.locator("[data-rail-panel]")).to_be_hidden()
                before_mode_requests = len(requests)
                page.locator('[data-experience-mode="professional"]').click()
                expect(page.locator("[data-rail-panel]")).to_be_visible()
                assert len(requests) == before_mode_requests
                page.locator('[data-experience-mode="task"]').click()
                expect(page.locator("[data-rail-panel]")).to_be_hidden()
                assert len(requests) == before_mode_requests
                expect(
                    page.locator(f'[data-dashboard-panel="{PORTFOLIO_SELECTOR_PANEL}"]')
                ).to_be_visible()

                for expected_page in (2, 3):
                    with page.expect_response(
                        lambda response: urlsplit(response.url).path
                        == _action_path(PORTFOLIO_SELECTOR_ACTION)
                    ) as response_info:
                        page.locator(
                            f'[data-dashboard-panel="{PORTFOLIO_SELECTOR_PANEL}"] '
                            '[data-panel-page-delta="1"]'
                        ).click()
                    response = response_info.value
                    assert response.status == 200
                    result = _envelope(response)
                    assert _action_status(result) == 200
                    model = _view_model(result)
                    pager = model.get("pager")
                    assert isinstance(pager, dict)
                    assert pager["page"] == expected_page
                    assert pager["page_size"] == 20
                    assert pager["total_rows"] == 45
                    assert pager["has_next"] == (expected_page == 2)
                portfolio_rows = page.locator(
                    f'[data-dashboard-panel="{PORTFOLIO_SELECTOR_PANEL}"] tbody > tr'
                )
                assert portfolio_rows.count() == 5

                for _ in range(2):
                    with page.expect_response(
                        lambda response: urlsplit(response.url).path
                        == _action_path(PORTFOLIO_SELECTOR_ACTION)
                    ):
                        page.locator(
                            f'[data-dashboard-panel="{PORTFOLIO_SELECTOR_PANEL}"] '
                            '[data-panel-page-delta="-1"]'
                        ).click()
                selected = _row_action(
                    page,
                    RECORDED_FACTS_ACTION,
                    ("pk", task_browser_data.selected_portfolio.id),
                )
                facts_response = _click_action(page, selected, RECORDED_FACTS_ACTION)
                assert facts_response.status == 200
                facts_result = _envelope(facts_response)
                assert _action_status(facts_result) == 200
                facts = _view_model(facts_result)
                assert facts["status"] == "结果状态未提供"
                assert (
                    _field_value(facts, "portfolio_name")
                    == task_browser_data.selected_portfolio.name
                )
                page_text = page.locator("[data-main-panel]").inner_text()
                assert "未提供" in page_text
                assert "原始单位" in page_text
                assert "/api/" not in page_text
                summary = page.locator("[data-task-result-summary]")
                expect(summary).to_contain_text("结果状态未提供")
                expect(summary).to_contain_text("跨币种换算")
                expect(summary).to_contain_text("源观测时间")
                summary_box = summary.bounding_box()
                assert summary_box is not None
                assert summary_box["y"] >= 0
                assert summary_box["y"] + summary_box["height"] <= height
                first_section = page.locator("[data-detail-section]").first
                expect(first_section.locator("summary")).to_be_visible()
                assert first_section.get_attribute("open") is None
                _save_browser_evidence(page, f"portfolio-{width}-facts", requests)
                first_section.locator("summary").click()
                cny_row = _detail_table_row(first_section, "标的代码", "TUX09-001.SZ")
                assert cny_row["币种代码"] == "CNY"
                assert cny_row["源观测时间"] in {"未提供", "—", ""}
                missing_price_row = _detail_table_row(first_section, "标的代码", "TUX09-002.SZ")
                assert missing_price_row["记录现价"] == "未知"
                assert missing_price_row["源观测时间"] in {"未提供", "—", ""}
                missing_currency_row = _detail_table_row(first_section, "标的代码", "TUX09-003.SZ")
                assert missing_currency_row["币种代码"] in {"未提供", "—", ""}
                zero_row = _detail_table_row(first_section, "标的代码", "TUX09-004.SZ")
                assert zero_row["记录数量"] in {"0", "0.0", "0.0000"}
                assert zero_row["记录市值"] == "未知"

                with page.expect_response(
                    lambda response: urlsplit(response.url).path
                    == _action_path(RECORDED_FACTS_ACTION)
                ) as page_two_info:
                    page.locator('[data-result-page-delta="1"]').click()
                page_two_response = page_two_info.value
                assert page_two_response.status == 200
                page_two = _envelope(page_two_response)
                assert _action_status(page_two) == 200
                posted = _posted_params(requests, RECORDED_FACTS_ACTION)
                assert posted[-1]["pk"] == task_browser_data.selected_portfolio.id
                assert posted[-1]["page"] == 2
                facts_page_two = _view_model(page_two)
                assert facts_page_two["pager"]["page"] == 2
                assert facts_page_two["pager"]["total_rows"] == 25
                positions_section = next(
                    section
                    for section in facts_page_two["sections"]
                    if section.get("key") == "positions"
                )
                assert len(positions_section["rows"]) == 5
                page_two_section = page.locator("[data-detail-section]").first
                page_two_section.locator("summary").click()
                _detail_table_row(page_two_section, "标的代码", "TUX09-025.SZ")

                # The result occupies the target panel. Re-open the dashboard
                # to restore its selector before exercising the retry path;
                # no unsupported dashboard-return button is assumed here.
                page.goto(
                    f"{live_server.url}/tui/?screen={PORTFOLIO_SCREEN}", wait_until="networkidle"
                )
                expect(
                    page.locator(f'[data-dashboard-panel="{PORTFOLIO_SELECTOR_PANEL}"]')
                ).to_be_visible()
                page.route(
                    f"**{_action_path(RECORDED_FACTS_ACTION)}",
                    lambda route: route.abort("connectionfailed"),
                    times=1,
                )
                selected = _row_action(
                    page,
                    RECORDED_FACTS_ACTION,
                    ("pk", task_browser_data.selected_portfolio.id),
                )
                selected.click()
                expect(page.locator("[data-panel-retry][data-targeted-read-retry]")).to_be_visible()
                expect(page.locator("[data-main-panel]")).not_to_contain_text("TUX09-001.SZ")
                _save_browser_evidence(page, f"portfolio-{width}-retry", requests)
                retry_button = page.locator("[data-panel-retry][data-targeted-read-retry]")
                retry_count_before = len(_posted_params(requests, RECORDED_FACTS_ACTION))
                retry_button.focus()
                with page.expect_response(
                    lambda response: urlsplit(response.url).path
                    == _action_path(RECORDED_FACTS_ACTION)
                ) as retry_info:
                    page.keyboard.press("Enter")
                retry_result = _envelope(retry_info.value)
                assert _action_status(retry_result) == 200
                assert (
                    len(_posted_params(requests, RECORDED_FACTS_ACTION)) == retry_count_before + 1
                )
                retry_params = _posted_params(requests, RECORDED_FACTS_ACTION)[-1]
                assert retry_params["pk"] == task_browser_data.selected_portfolio.id
                professional_target = page.locator("[data-next-step-index]")
                expect(professional_target).to_have_count(1)
                before_professional = len(
                    _posted_params(requests, "account.portfolio-recorded-facts")
                )
                with page.expect_response(
                    lambda response: urlsplit(response.url).path
                    == "/api/tui/screens/execution.accounts/"
                ) as target_metadata:
                    professional_target.first.click()
                page.wait_for_url("**screen=execution.accounts**")
                assert (
                    len(_posted_params(requests, "account.portfolio-recorded-facts"))
                    == before_professional
                )
                target = next(
                    action
                    for action in target_metadata.value.json()["actions"]
                    if action["key"] == "account.portfolio-recorded-facts"
                )
                target_form = page.locator(f'[data-action-ui-key="{target["ui_key"]}"]')
                expect(target_form).to_be_visible()
                _save_browser_evidence(page, f"portfolio-{width}-professional", requests)
                assert target_form.locator('[name="pk"]').input_value() == str(
                    task_browser_data.selected_portfolio.id
                )
                expect(page.locator("[data-next-step-return]")).to_be_visible()
                with page.expect_response(
                    lambda response: urlsplit(response.url).path
                    == _action_path(RECORDED_FACTS_ACTION)
                ) as returned:
                    page.locator("[data-next-step-return]").click()
                assert _action_status(_envelope(returned.value)) == 200
                expect(page.locator("[data-return-dashboard-workspace]")).to_be_visible()
                returned_facts_count = len(_posted_params(requests, RECORDED_FACTS_ACTION))
                page.locator("[data-return-dashboard-workspace]").click()
                expect(
                    page.locator(f'[data-dashboard-panel="{PORTFOLIO_SELECTOR_PANEL}"]')
                ).to_be_visible()
                returned_query = parse_qs(urlsplit(page.url).query)
                assert returned_query.get("screen") == [PORTFOLIO_SCREEN]
                assert returned_query.get("action") == [RECORDED_FACTS_ACTION]
                assert len(_posted_params(requests, RECORDED_FACTS_ACTION)) == returned_facts_count
                page.go_back()
                page.wait_for_url("**screen=execution.accounts**")
                expect(page.locator("[data-main-panel]")).to_be_visible()
                assert len(_posted_params(requests, RECORDED_FACTS_ACTION)) == returned_facts_count
                page.go_forward()
                page.wait_for_url(f"**screen={PORTFOLIO_SCREEN}**")
                assert parse_qs(urlsplit(page.url).query).get("action") == [RECORDED_FACTS_ACTION]
                assert len(_posted_params(requests, RECORDED_FACTS_ACTION)) == returned_facts_count
                expect(page.locator("[data-main-panel]")).to_be_visible()
                expect(page.locator(".tui-application-error")).to_have_count(0)
                assert not page_errors
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                _assert_local_read_traffic(requests, live_server)
                context.close()
                browser.close()
                browser = None
        finally:
            if browser is not None:
                browser.close()
    assert PortfolioModel._default_manager.count() == before_portfolios
    assert PositionModel._default_manager.count() == before_positions
    assert SimulatedAccountModel._default_manager.count() == before_accounts


@pytest.mark.django_db(transaction=True)
def test_late_cancelled_facts_response_cannot_replace_new_portfolio(
    live_server: Any,
    task_browser_data: TuiTaskBrowserData,
    subprocess_policy: None,
) -> None:
    """A fetched old owner response cannot overwrite a later selected portfolio."""

    owner_cookie = _session_cookie(task_browser_data.owner)
    old_portfolio = task_browser_data.selected_portfolio
    new_portfolio = task_browser_data.portfolios[-2]
    captured: dict[str, Any] = {}
    with sync_playwright() as playwright:
        browser, context = _new_context(playwright, live_server, owner_cookie, 1440, 1000)
        try:
            page = context.new_page()
            requests = _capture_requests(page)
            page_errors: list[str] = []
            page.on("pageerror", lambda error, recorded=page_errors: recorded.append(str(error)))
            _open_task(page, live_server, PORTFOLIO_SCREEN)

            def intercept_old(route: Any) -> None:
                actual_response = route.fetch()
                captured["route"] = route
                captured["response"] = actual_response
                captured["fetch_status"] = actual_response.status
                page.evaluate("window.__tux09OldOwnerFetched = true")
                # Deliberately do not abort or fulfill here. The production
                # generation guard should cancel this old request when the
                # user selects another row; no sleep is used to stage it.

            page.route(
                f"**{_action_path(RECORDED_FACTS_ACTION)}",
                intercept_old,
                times=1,
            )
            old_button = _row_action(page, RECORDED_FACTS_ACTION, ("pk", old_portfolio.id))
            old_button.click()
            page.wait_for_function("() => window.__tux09OldOwnerFetched === true")
            assert captured.get("fetch_status") == 200
            new_button = _row_action(page, RECORDED_FACTS_ACTION, ("pk", new_portfolio.id))
            new_response = _click_action(page, new_button, RECORDED_FACTS_ACTION)
            assert new_response.status == 200
            new_result = _envelope(new_response)
            assert _action_status(new_result) == 200
            new_model = _view_model(new_result)
            assert _field_value(new_model, "portfolio_name") == new_portfolio.name

            late_error: str | None = None
            try:
                captured["route"].fulfill(response=captured["response"])
            except Exception as exc:  # pragma: no cover - formal browser QA observes this
                late_error = str(exc)
            if late_error is not None:
                normalized_error = late_error.lower()
                assert any(
                    marker in normalized_error
                    for marker in ("already handled", "request was aborted", "request aborted")
                )
            page.evaluate(
                "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
            )
            result_panel = page.locator('[data-dashboard-panel="portfolio-check-recorded-facts"]')
            expect(result_panel).to_contain_text(new_portfolio.name)
            expect(result_panel).not_to_contain_text("TUX09-001.SZ")
            assert not page_errors
            _assert_local_read_traffic(requests, live_server)
        finally:
            context.close()
            browser.close()


@pytest.mark.django_db(transaction=True)
def test_observer_revocation_clears_recorded_facts_and_returns_forbidden(
    live_server: Any,
    task_browser_data: TuiTaskBrowserData,
    subprocess_policy: None,
) -> None:
    """An observer loses the old facts view after a real grant revocation."""

    observer_cookie = _session_cookie(task_browser_data.observer)
    with sync_playwright() as playwright:
        browser, context = _new_context(playwright, live_server, observer_cookie, 390, 844)
        try:
            page = context.new_page()
            requests = _capture_requests(page)
            page_errors: list[str] = []
            page.on("pageerror", lambda error, recorded=page_errors: recorded.append(str(error)))
            page.goto(f"{live_server.url}/tui/", wait_until="networkidle")
            expect(page.locator("[data-task-home]")).to_be_visible()
            portfolio_entry = page.locator(
                f'[data-experience-entry][data-experience-screen-key="{PORTFOLIO_SCREEN}"]'
            )
            expect(portfolio_entry).to_have_count(1)
            portfolio_entry.click()
            page.wait_for_url(f"**screen={PORTFOLIO_SCREEN}**")
            expect(
                page.locator(f'[data-dashboard-panel="{PORTFOLIO_SELECTOR_PANEL}"]')
            ).to_be_visible()
            expect(
                page.locator(
                    f'[data-dashboard-row-action][data-row-action-key="{RECORDED_FACTS_ACTION}"]'
                ).first
            ).to_be_visible()
            selected = _row_action(page, RECORDED_FACTS_ACTION)
            first = _click_action(page, selected, RECORDED_FACTS_ACTION)
            assert first.status == 200
            assert _action_status(_envelope(first)) == 200
            first_section = page.locator("[data-detail-section]").first
            first_section.locator("summary").click()
            _detail_table_row(first_section, "标的代码", "TUX09-001.SZ")
            expect(first_section).to_contain_text("TUX09-001.SZ", use_inner_text=True)
            expect(
                page.locator(f'[data-dashboard-panel="{PORTFOLIO_SELECTOR_PANEL}"]')
            ).to_be_visible()

            def revoke() -> None:
                try:
                    PortfolioObserverGrantModel._default_manager.filter(
                        pk=task_browser_data.grant.pk
                    ).update(status="revoked", revoked_at=timezone.now())
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(revoke).result()
            selected = _row_action(page, RECORDED_FACTS_ACTION)
            with page.expect_response(
                lambda response: urlsplit(response.url).path == _action_path(RECORDED_FACTS_ACTION)
            ) as forbidden_info:
                selected.click()
            forbidden_response = forbidden_info.value
            assert forbidden_response.status == 200
            assert forbidden_response.headers.get("content-type", "").startswith("application/json")
            forbidden_result = _envelope(forbidden_response)
            assert _action_status(forbidden_result) == 403
            main_text = page.locator("[data-main-panel]").inner_text()
            assert "TUX09-001.SZ" not in main_text
            assert "12.34" not in main_text
            assert "重新选择" in main_text or "无权" in main_text
            page.go_back()
            expect(page.locator("[data-task-home]")).to_be_visible()
            page.go_forward()
            page.wait_for_url(f"**screen={PORTFOLIO_SCREEN}**")
            page.wait_for_load_state("networkidle")
            expect(
                page.locator(f'[data-dashboard-panel="{PORTFOLIO_SELECTOR_PANEL}"]')
            ).to_be_visible()
            history_main_text = page.locator("[data-main-panel]").inner_text()
            assert "TUX09-001.SZ" not in history_main_text
            assert "12.34" not in history_main_text
            assert not page_errors
            _assert_local_read_traffic(requests, live_server)
        finally:
            context.close()
            browser.close()


@pytest.mark.django_db(transaction=True)
def test_today_focus_accounts_are_client_paged_and_queue_is_passive(
    live_server: Any,
    task_browser_data: TuiTaskBrowserData,
    subprocess_policy: None,
    record_property: Callable[[str, object], None],
) -> None:
    """Both roles use local account facts; an empty queue never auto-runs a professional action."""

    task_browser_data.owner.is_staff = False
    task_browser_data.owner.save(update_fields=["is_staff"])
    foreign_account = SimulatedAccountModel._default_manager.get(
        user=task_browser_data.foreign, account_name="TUX09外部私有账户"
    )
    for user in (task_browser_data.observer, task_browser_data.owner):
        assert not user.is_staff
        session_cookie = _session_cookie(user)
        for width, height in ((1440, 1000), (390, 844)):
            with sync_playwright() as playwright:
                browser, context = _new_context(
                    playwright, live_server, session_cookie, width, height
                )
                try:
                    page = context.new_page()
                    requests = _capture_requests(page)
                    page_errors: list[str] = []
                    page.on(
                        "pageerror", lambda error, recorded=page_errors: recorded.append(str(error))
                    )
                    with page.expect_response(
                        lambda response: urlsplit(response.url).path
                        == _action_path(MARKET_CONTEXT_ACTION)
                    ) as initial_market:
                        _open_task(page, live_server, TODAY_SCREEN)
                    initial_market_result = _envelope(initial_market.value)
                    if _action_status(initial_market_result) == 200:
                        market_model = _view_model(initial_market_result)
                        market_summary = page.locator(
                            '[data-dashboard-panel="today-focus-market-context"] '
                            "[data-task-result-summary]"
                        )
                        expect(market_summary).to_contain_text(market_model["business_summary"])
                    account_selector = page.locator(
                        f'[data-dashboard-panel="{ACCOUNT_SELECTOR_PANEL}"]'
                    )
                    expect(account_selector).to_be_visible()
                    _save_browser_evidence(page, f"today-{width}-{user.pk}-selector", requests)
                    expect(account_selector.locator("tbody > tr")).to_have_count(20)
                    selector_requests_before = len(
                        _posted_params(requests, ACCOUNT_SELECTOR_ACTION)
                    )
                    queue_button = _row_action(page, TODAY_QUEUE_ACTION)
                    row_params = json.loads(queue_button.get_attribute("data-row-action-params"))
                    account_id = row_params["account_id"]
                    allowed_accounts = (
                        task_browser_data.observer_accounts
                        if user == task_browser_data.observer
                        else task_browser_data.owner_accounts
                    )
                    assert account_id in {account.pk for account in allowed_accounts}
                    queue_response = _click_action(page, queue_button, TODAY_QUEUE_ACTION)
                    assert queue_response.status == 200
                    queue_result = _envelope(queue_response)
                    assert _action_status(queue_result) == 200
                    queue_model = _view_model(queue_result)
                    assert queue_model["status"] == "结果状态未提供"
                    assert _field_value(queue_model, "queue_count") == "0"
                    assert "事项时间" in str(queue_model)
                    assert "记录/生成时间" in str(queue_model)
                    assert (
                        _posted_params(requests, TODAY_QUEUE_ACTION)[-1]["account_id"] == account_id
                    )

                    page.locator(
                        f'[data-dashboard-panel="{ACCOUNT_SELECTOR_PANEL}"] '
                        '[data-panel-page-delta="1"]'
                    ).click()
                    expect(account_selector.locator("tbody > tr")).to_have_count(
                        len(allowed_accounts) - 20
                    )
                    assert (
                        len(_posted_params(requests, ACCOUNT_SELECTOR_ACTION))
                        == selector_requests_before
                    )
                    assert (
                        page.locator(
                            f'[data-dashboard-panel="{ACCOUNT_SELECTOR_PANEL}"] '
                            '[data-row-action-key="today-focus.queue"]'
                        ).count()
                        == len(allowed_accounts) - 20
                    )

                    market = page.locator(
                        f'[data-dashboard-row-action][data-row-action-key="{MARKET_CONTEXT_ACTION}"]'
                    )
                    if market.count():
                        market_response = _click_action(page, market.first, MARKET_CONTEXT_ACTION)
                        assert market_response.status in {200, 403, 404, 502, 503}
                        if market_response.status == 200:
                            market_result = _envelope(market_response)
                            market_status = _action_status(market_result)
                            assert market_status in {200, 403, 404, 502, 503}
                            if market_status == 200:
                                market_model = _view_model(market_result)
                                assert market_model["status"] == "结果状态未提供"
                                assert "确定" not in page.locator("[data-main-panel]").inner_text()

                    professional_target = page.locator("[data-next-step-index]")
                    expect(professional_target).to_have_count(1)
                    _save_browser_evidence(page, f"today-{width}-{user.pk}-queue", requests)
                    before_professional = len(
                        _posted_params(requests, UNIFIED_RECOMMENDATIONS_ACTION)
                    )
                    with page.expect_response(
                        lambda response: urlsplit(response.url).path
                        == "/api/tui/screens/command-center.decision-flow/"
                    ) as target_metadata:
                        professional_target.first.click()
                    page.wait_for_url("**screen=command-center.decision-flow**")
                    assert (
                        len(_posted_params(requests, UNIFIED_RECOMMENDATIONS_ACTION))
                        == before_professional
                    )
                    target = next(
                        action
                        for action in target_metadata.value.json()["actions"]
                        if action["key"] == UNIFIED_RECOMMENDATIONS_ACTION
                    )
                    target_form = page.locator(f'[data-action-ui-key="{target["ui_key"]}"]')
                    expect(target_form).to_be_visible()
                    assert target_form.locator('[name="account_id"]').input_value() == str(
                        account_id
                    )
                    with page.expect_response(
                        lambda response: urlsplit(response.url).path
                        == _action_path(UNIFIED_RECOMMENDATIONS_ACTION)
                    ) as explicit_read:
                        target_form.locator(".tui-action-button").click()
                    assert _action_status(_envelope(explicit_read.value)) == 200
                    assert str(
                        _posted_params(requests, UNIFIED_RECOMMENDATIONS_ACTION)[-1]["account_id"]
                    ) == str(account_id)
                    # A response event precedes rendering. Wait for real readiness,
                    # then use the existing explicit refresh instead of a rapid
                    # same-form click suppressed by the 250 ms duplicate guard.
                    expect(page.locator("[data-workbench-status]")).to_have_text("读取完成")
                    expect(page.locator("[data-main-panel] .tui-view-status")).to_contain_text(
                        "查看账户统一推荐"
                    )
                    account_selector = target_form.locator('select[name="account_id"]')
                    account_selector.select_option(str(account_id))
                    assert account_selector.input_value() == str(account_id)
                    forbidden_result = _tampered_unified_account_read(
                        page,
                        target_form.locator(".tui-action-button"),
                        target_form,
                        foreign_account.pk,
                        record_property,
                        explicit_refresh=True,
                    )
                    assert foreign_account.account_name not in str(forbidden_result)
                    expect(page.locator("[data-next-step-return]")).to_be_visible()
                    with page.expect_response(
                        lambda response: urlsplit(response.url).path
                        == _action_path(TODAY_QUEUE_ACTION)
                    ) as returned:
                        page.locator("[data-next-step-return]").click()
                    assert _action_status(_envelope(returned.value)) == 200
                    expect(page.locator("[data-return-dashboard-workspace]")).to_be_visible()
                    page.locator("[data-return-dashboard-workspace]").click()
                    expect(page.locator("[data-main-panel]")).to_be_visible()
                    assert not page_errors
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    _assert_local_read_traffic(requests, live_server)
                finally:
                    context.close()
                    browser.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(("width", "height"), [(1440, 1000), (390, 844)])
def test_roe_owner_results_are_readable_after_the_ordinary_account_handoff(
    live_server: Any,
    task_browser_data: TuiTaskBrowserData,
    roe_browser_recommendations: list[UnifiedRecommendationDTO],
    subprocess_policy: None,
    width: int,
    height: int,
    record_property: Callable[[str, object], None],
) -> None:
    """Read actual generated rows; synthetic sources do not prove live eligibility."""

    owner = task_browser_data.owner
    assert not owner.is_staff
    account_id = int(roe_browser_recommendations[0].account_id)
    foreign_account = SimulatedAccountModel._default_manager.get(
        user=task_browser_data.foreign, account_name="TUX09外部私有账户"
    )
    session_cookie = _session_cookie(owner)
    with sync_playwright() as playwright:
        browser, context = _new_context(playwright, live_server, session_cookie, width, height)
        try:
            page = context.new_page()
            requests = _capture_requests(page)
            failures: list[str] = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            _open_task(page, live_server, TODAY_SCREEN)
            response = _click_action(
                page,
                _row_action(page, TODAY_QUEUE_ACTION, ("account_id", account_id)),
                TODAY_QUEUE_ACTION,
            )
            assert _action_status(_envelope(response)) == 200
            step = page.locator("[data-next-step-index]")
            expect(step).to_have_count(1)
            with page.expect_response(
                lambda response: urlsplit(response.url).path
                == "/api/tui/screens/command-center.decision-flow/"
            ) as metadata_response:
                step.click()
            action = next(
                action
                for action in metadata_response.value.json()["actions"]
                if action["key"] == UNIFIED_RECOMMENDATIONS_ACTION
            )
            assert not _posted_params(requests, UNIFIED_RECOMMENDATIONS_ACTION)
            form = page.locator(f'[data-action-ui-key="{action["ui_key"]}"]')
            expect(form).to_be_visible()
            assert form.locator('[name="account_id"]').input_value() == str(account_id)
            result = _envelope(
                _click_action(page, form.locator(".tui-action-button"), action["key"])
            )
            assert _action_status(result) == 200
            model = _view_model(result)
            assert model["pager"]["total_rows"] == 3
            grid = page.locator(".tui-datagrid")
            headers = grid.locator("thead th").all_inner_texts()
            assert "推荐依据与限制" in headers
            assert "置信度（0–1）" in headers
            for owner_result in roe_browser_recommendations:
                row = grid.locator("tbody > tr").filter(has_text=owner_result.security_code)
                expect(row).to_have_count(1)
                cells = row.locator("td")
                confidence = cells.nth(headers.index("置信度（0–1）"))
                rationale = cells.nth(headers.index("推荐依据与限制"))
                expect(confidence).to_have_text(str(owner_result.confidence))
                expect(rationale).to_have_text(owner_result.human_rationale)
                row.dblclick()
                modal = page.locator("[data-tui-modal]")
                expect(modal).to_be_visible()
                body = modal.locator("[data-modal-body]")
                expect(body).to_contain_text(owner_result.security_code)
                detail_confidence = body.get_by_text("置信度（0–1）", exact=True).locator(
                    "xpath=following-sibling::dd[1]"
                )
                detail_rationale = body.get_by_text("推荐依据与限制", exact=True).locator(
                    "xpath=following-sibling::dd[1]"
                )
                expect(detail_confidence).to_have_text(str(owner_result.confidence))
                expect(detail_rationale).to_have_text(owner_result.human_rationale)
                detail_confidence.scroll_into_view_if_needed()
                _save_browser_evidence(
                    page, f"roe-{width}-{owner_result.security_code}-detail-confidence", requests
                )
                detail_rationale.evaluate(
                    "element => element.scrollIntoView({block: 'start', inline: 'nearest'})"
                )
                _save_browser_evidence(
                    page, f"roe-{width}-{owner_result.security_code}-detail-head", requests
                )
                detail_rationale.evaluate(
                    "element => element.scrollIntoView({block: 'end', inline: 'nearest'})"
                )
                marker = {
                    "000001.SZ": "0.50→0.40",
                    "000002.SZ": "参数未配置",
                    "000003.SZ": "硬阻断优先",
                }[owner_result.security_code]
                # Inspect actual text geometry after native scrolling; never inject markup/CSS.
                fragment = detail_rationale.evaluate(
                    """(element, marker) => {
                        const node = element.firstChild;
                        const start = node.textContent.indexOf(marker);
                        if (start < 0) throw new Error('Missing owner explanation marker');
                        const range = document.createRange();
                        range.setStart(node, start);
                        range.setEnd(node, start + marker.length);
                        const rect = range.getBoundingClientRect();
                        return {top: rect.top, bottom: rect.bottom,
                                left: rect.left, right: rect.right};
                    }""",
                    marker,
                )
                bounds = body.bounding_box()
                assert bounds is not None
                assert bounds["y"] - 1 <= fragment["top"] < fragment["bottom"]
                assert fragment["bottom"] <= min(bounds["y"] + bounds["height"], height) + 1
                assert bounds["x"] - 1 <= fragment["left"] < fragment["right"]
                assert fragment["right"] <= min(bounds["x"] + bounds["width"], width) + 1
                record_property(
                    f"visible_owner_explanation_{width}_{owner_result.security_code}",
                    json.dumps({"marker": marker, "fragment": fragment, "body": bounds}),
                )
                _save_browser_evidence(
                    page, f"roe-{width}-{owner_result.security_code}-detail-tail", requests
                )
                modal.locator("[data-modal-close]").click()
                expect(modal).not_to_be_visible()
            assert not _posted_params(requests, "decision.workspace.summary")
            denied = _tampered_unified_account_read(
                page,
                form.locator(".tui-action-button"),
                form,
                foreign_account.pk,
                record_property,
            )
            assert _action_status(denied) == 403
            for owner_result in roe_browser_recommendations:
                expect(page.locator("[data-main-panel]")).not_to_contain_text(
                    owner_result.human_rationale
                )
            returned = _envelope(
                _click_action(page, page.locator("[data-next-step-return]"), TODAY_QUEUE_ACTION)
            )
            assert _action_status(returned) == 200
            assert _posted_params(requests, TODAY_QUEUE_ACTION)[-1]["account_id"] == account_id
            assert not failures
            _assert_local_read_traffic(requests, live_server)
        finally:
            context.close()
            browser.close()


@pytest.mark.django_db(transaction=True)
def test_professional_read_rejects_a_foreign_portfolio_without_stale_facts(
    live_server: Any,
    task_browser_data: TuiTaskBrowserData,
    subprocess_policy: None,
) -> None:
    """An ordinary observer can inspect an allowed portfolio, never a foreign one."""

    observer_cookie = _session_cookie(task_browser_data.observer)
    with sync_playwright() as playwright:
        browser, context = _new_context(playwright, live_server, observer_cookie, 390, 844)
        try:
            page = context.new_page()
            requests = _capture_requests(page)
            failures: list[str] = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            _open_task(page, live_server, PORTFOLIO_SCREEN)
            selector = page.locator(f'[data-dashboard-panel="{PORTFOLIO_SELECTOR_PANEL}"]')
            expect(selector).not_to_contain_text(task_browser_data.foreign_portfolio.name)
            own_read = _click_action(
                page, _row_action(page, RECORDED_FACTS_ACTION), RECORDED_FACTS_ACTION
            )
            assert _action_status(_envelope(own_read)) == 200
            section = page.locator("[data-detail-section]").first
            section.locator("summary").click()
            _detail_table_row(section, "标的代码", "TUX09-001.SZ")
            with page.expect_response(
                lambda response: urlsplit(response.url).path
                == "/api/tui/screens/execution.accounts/"
            ) as metadata:
                page.locator("[data-next-step-index]").click()
            assert metadata.value.status == 200
            target = next(
                action
                for action in metadata.value.json()["actions"]
                if action["key"] == "account.portfolio-recorded-facts"
            )
            form = page.locator(f'[data-action-ui-key="{target["ui_key"]}"]')
            expect(form).to_be_visible()
            form.locator('[name="pk"]').fill(str(task_browser_data.foreign_portfolio.pk))
            with page.expect_response(
                lambda response: urlsplit(response.url).path
                == _action_path("account.portfolio-recorded-facts")
            ) as forbidden:
                form.locator(".tui-action-button").click()
            assert forbidden.value.status == 200
            result = _envelope(forbidden.value)
            assert _action_status(result) == 403
            assert "TUX09-001.SZ" not in str(result)
            assert task_browser_data.foreign_portfolio.name not in str(result)
            main = page.locator("[data-main-panel]")
            expect(main).not_to_contain_text("TUX09-001.SZ")
            expect(main).not_to_contain_text(task_browser_data.foreign_portfolio.name)
            expect(page.locator(".tui-application-error")).to_be_visible()
            assert not failures
            _assert_local_read_traffic(requests, live_server)
        finally:
            context.close()
            browser.close()
