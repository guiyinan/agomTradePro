"""Real loopback HTTP journeys for owner-attested simulated fee corrections.

These tests use the actual TUI, Session/CSRF handling, owner APIs and isolated
ledger. A lost-response case discards an actual committed HTTP response only.
They provide no production, native PostgreSQL concurrency or broker evidence.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from hashlib import sha1, sha256
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connections
from django.test import Client
from django.utils import timezone
from playwright.sync_api import Locator, Page, Route, expect, sync_playwright

from apps.account.infrastructure.models import UserAccessTokenModel
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidenceArtifactModel,
    FeeCorrectionEvidencePolicyModel,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.terminal.infrastructure.models import TerminalAuditLogORM
from shared.config.secrets import clear_secrets_cache
from shared.infrastructure.crypto import FieldEncryptionService
from tests.api.test_fee_correction_flow_api import (  # noqa: F401
    seed_authority_generation_for_nomigrations_sqlite,
)
from tests.component.account.test_authentication import _create_profile
from tests.component.simulated_trading.test_fee_correction_repository import _csv_bytes
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)

pytestmark = pytest.mark.django_db(transaction=True)
PREFIX = "simulated-trading.fee-correction-"
T = TypeVar("T")


@dataclass(frozen=True)
class FeeBook:
    """One ordinary owner with primary and scope-switch BUYs, no policy or evidence."""

    owner: Any
    account: SimulatedAccountModel
    trade: SimulatedTradeModel
    secondary_account: SimulatedAccountModel
    secondary_trade: SimulatedTradeModel
    csv_path: Path
    csv_bytes: bytes
    readonly_token: str


def _db_call(call: Callable[[], T]) -> T:
    """Observe committed state outside Playwright's synchronous event loop."""

    def execute() -> T:
        connections.close_all()
        try:
            return call()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(execute).result()


@pytest.fixture
def fee_book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FeeBook]:
    """Seed only ledger facts; user actions must create qualification and material."""

    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", FieldEncryptionService.generate_key())
    clear_secrets_cache()
    owner = get_user_model().objects.create_user(username=f"fee-browser-{uuid4().hex}")
    _create_profile(owner)
    _, token = UserAccessTokenModel.create_token(
        user=owner, name="readonly", access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY
    )
    account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name="费用更正浏览器验收",
        account_type="simulated",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("8992.98"),
        current_market_value=Decimal("1000.00"),
        total_value=Decimal("9992.98"),
        auto_trading_enabled=False,
    )
    executed_at = timezone.now() - timedelta(minutes=30)
    trade = SimulatedTradeModel.objects.create(
        account=account,
        asset_code="600000.SH",
        asset_name="本地测试股票",
        asset_type="equity",
        action="buy",
        quantity=Decimal("100.000000"),
        price=Decimal("10.0000"),
        amount=Decimal("1000.00"),
        commission=Decimal("7.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
        slippage=Decimal("0.02"),
        total_cost=Decimal("1007.02"),
        fee_amounts_known=True,
        cost_basis_known=True,
        order_date=executed_at.date(),
        execution_date=executed_at.date(),
        execution_time=executed_at,
        status="executed",
    )
    PositionModel.objects.create(
        account=account,
        asset_code=trade.asset_code,
        asset_name=trade.asset_name,
        asset_type="equity",
        quantity=trade.quantity,
        available_quantity=trade.quantity,
        avg_cost=Decimal("10.0702"),
        total_cost=trade.total_cost,
        cost_basis_known=True,
        current_price=trade.price,
        market_value=trade.amount,
        valuation_known=True,
        unrealized_pnl=Decimal("-7.02"),
        first_buy_date=executed_at.date(),
    )
    secondary_account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name="费用更正范围切换账户",
        account_type="simulated",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("8992.98"),
        current_market_value=Decimal("1000.00"),
        total_value=Decimal("9992.98"),
        auto_trading_enabled=False,
    )
    secondary_trade = SimulatedTradeModel.objects.create(
        account=secondary_account,
        asset_code="000001.SZ",
        asset_name="切换范围测试股票",
        asset_type="equity",
        action="buy",
        quantity=Decimal("100.000000"),
        price=Decimal("10.0000"),
        amount=Decimal("1000.00"),
        commission=Decimal("7.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
        slippage=Decimal("0.02"),
        total_cost=Decimal("1007.02"),
        fee_amounts_known=True,
        cost_basis_known=True,
        order_date=executed_at.date(),
        execution_date=executed_at.date(),
        execution_time=executed_at,
        status="executed",
    )
    PositionModel.objects.create(
        account=secondary_account,
        asset_code=secondary_trade.asset_code,
        asset_name=secondary_trade.asset_name,
        asset_type="equity",
        quantity=secondary_trade.quantity,
        available_quantity=secondary_trade.quantity,
        avg_cost=Decimal("10.0702"),
        total_cost=secondary_trade.total_cost,
        cost_basis_known=True,
        current_price=secondary_trade.price,
        market_value=secondary_trade.amount,
        valuation_known=True,
        unrealized_pnl=Decimal("-7.02"),
        first_buy_date=executed_at.date(),
    )
    csv_bytes = b"\xef\xbb\xbf" + _csv_bytes(
        account_id=account.pk,
        trade=trade,
        source_observed_at=timezone.now() - timedelta(minutes=5),
        commission=Decimal("9.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    ).replace(b"\n", b"\r\n")
    csv_path = tmp_path / "原始费用凭据.csv"
    csv_path.write_bytes(csv_bytes)
    assert not owner.is_staff and not owner.is_superuser
    assert not FeeCorrectionEvidencePolicyModel.objects.filter(account=account).exists()
    assert not FeeCorrectionEvidenceArtifactModel.objects.filter(account=account).exists()
    yield FeeBook(
        owner,
        account,
        trade,
        secondary_account,
        secondary_trade,
        csv_path,
        csv_bytes,
        token,
    )
    clear_secrets_cache()


@pytest.fixture
def fee_browser(
    live_server: Any, fee_book: FeeBook, request: pytest.FixtureRequest
) -> Iterator[Page]:
    """Serve actual pages and APIs on loopback with a genuine Django session."""

    original_policy = asyncio.get_event_loop_policy()
    changed = ensure_subprocess_event_loop_policy()
    client = Client(enforce_csrf_checks=True)
    client.force_login(fee_book.owner)
    traffic: list[dict[str, str]] = []
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.add_cookies(
            [
                {
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
                    "url": live_server.url,
                }
            ]
        )

        def local_only(route: Route) -> None:
            if urlsplit(route.request.url).netloc != urlsplit(live_server.url).netloc:
                errors.append(f"Nonlocal browser request: {route.request.url}")
                route.abort("blockedbyclient")
                return
            route.continue_()

        context.route("**/*", local_only)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: traffic.append({"method": req.method, "url": req.url}))
        try:
            page.goto(f"{live_server.url}/tui/?screen=execution.accounts", wait_until="networkidle")
            expect(page.locator("[data-main-panel]")).to_be_visible()
            page.locator('[data-experience-mode="professional"]').click()
            page.keyboard.press("F9")
            expect(page.locator("[data-actions-panel]")).to_be_visible()
            yield page
            assert errors == []
        finally:
            evidence = (
                Path(settings.BASE_DIR)
                / "artifacts/a-share-usability/ash03-fee-correction-2026-10-25/recovery-2026-10-28/tui"
                / f"browser-{uuid4().hex[:12]}"
            )
            evidence.mkdir(parents=True)
            page.screenshot(path=str(evidence / "viewport.png"))
            (evidence / "traffic.json").write_text(
                json.dumps(
                    {
                        "case": request.node.name,
                        "requests": traffic,
                        "page_errors": errors,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            context.close()
            browser.close()
            if changed:
                asyncio.set_event_loop_policy(original_policy)


def _form(page: Page, key: str) -> Locator:
    """Find and open the action's genuine rendered form."""

    digest = sha1(key.encode(), usedforsecurity=False).hexdigest()[:10]
    form = page.locator(f'[data-actions-panel] form[data-action-ui-key="task-{digest}"]')
    expect(form).to_have_count(1)
    if not form.is_visible():
        form.locator("xpath=ancestor::details[1]").locator(":scope > summary").click()
    expect(form).to_be_visible()
    return form


def _response(page: Page, key: str, click: Callable[[], object]) -> dict[str, Any]:
    """Read one actual TUI HTTP envelope after a visible interaction.

    The explicit 120s budget covers CI runners where the sqlite-backed live
    server serializes settlement writes far slower than a local machine; the
    Playwright default of 30s turned that variance into false timeouts.
    """

    with page.expect_response(
        lambda response: urlsplit(response.url).path == f"/api/tui/actions/{key}/run/",
        timeout=120_000,
    ) as pending:
        click()
    response = pending.value
    assert response.status == 200
    assert response.headers["content-type"].startswith("application/json")
    return response.json()


def _set_control_value(control: Locator, value: str) -> None:
    """Set one visible input through its native select or text interaction."""

    if control.evaluate("element => element.tagName === 'SELECT'"):
        control.select_option(value)
    else:
        control.fill(value)


def _state(book: FeeBook) -> tuple[Decimal, Decimal, Decimal, int]:
    """Read actual cash, original immutable fees and correction count."""

    def read() -> tuple[Decimal, Decimal, Decimal, int]:
        account = SimulatedAccountModel.objects.get(pk=book.account.pk)
        trade = SimulatedTradeModel.objects.get(pk=book.trade.pk)
        count = SimulatedFeeCorrectionEventModel.objects.filter(account=account).count()
        return account.current_cash, trade.commission, trade.slippage, count

    return _db_call(read)


def _artifact_snapshot(book: FeeBook) -> tuple[int, str, bytes, str]:
    """Read the upload count, exact bytes, filename and content digest."""

    def read() -> tuple[int, str, bytes, str]:
        artifacts = list(
            FeeCorrectionEvidenceArtifactModel.objects.filter(account_id=book.account.pk).order_by(
                "pk"
            )
        )
        if not artifacts:
            return 0, "", b"", ""
        artifact = artifacts[0]
        return (
            len(artifacts),
            artifact.original_filename,
            bytes(artifact.raw_bytes),
            artifact.content_sha256,
        )

    return _db_call(read)


def _policy_state(book: FeeBook) -> tuple[int, bool]:
    """Read the owner policy version and enabled state without changing either."""

    def read() -> tuple[int, bool]:
        policy = FeeCorrectionEvidencePolicyModel.objects.get(account_id=book.account.pk)
        return policy.version, policy.enabled

    return _db_call(read)


def _enable_policy(page: Page, book: FeeBook) -> None:
    """Explicitly enable owner-attested material via the policy result's next step."""

    key = PREFIX + "policy"
    form = _form(page, key)
    form.locator('[name="account_id"]').select_option(str(book.account.pk))
    result = _response(page, key, form.locator(".tui-action-submit").click)
    assert result["response"]["status_code"] == 200
    page.locator('[data-next-step-index="0"]').click()
    modal = page.locator("[data-missing-fields-form]")
    expect(modal).to_be_visible()
    for field in ("enabled", "allow_operator_attested_upload", "attestation_acknowledged"):
        modal.locator(f'[name="{field}"]').select_option("true")
    modal.locator('[name="ledger_currency"]').fill("CNY")
    save_key = PREFIX + "policy-save"
    result = _response(page, save_key, modal.locator('[type="submit"]').click)
    assert result["confirmation_required"] is True
    result = _response(page, save_key, page.locator("[data-confirm-action]").click)
    assert result["response"]["status_code"] == 200
    assert _db_call(
        lambda: FeeCorrectionEvidencePolicyModel.objects.get(account=book.account).enabled
    )


def _upload_owner_preview(page: Page, book: FeeBook) -> tuple[dict[str, Any], str]:
    """Upload one genuine CSV through the TUI and return its preview and locator."""

    trades_key = "simulated-trading.trades"
    trades_form = _form(page, trades_key)
    _set_control_value(trades_form.locator('[name="account_id"]'), str(book.account.pk))
    trades = _response(page, trades_key, trades_form.locator(".tui-action-submit").click)
    assert trades["response"]["status_code"] == 200
    page.locator('[data-main-panel] [data-row-index="0"]').click()

    preview_key = PREFIX + "preview"
    form = _form(page, preview_key)
    form.locator("[data-fill-from-row]").click()
    expect(form.locator('[name="account_id"]')).to_have_value(str(book.account.pk))
    expect(form.locator('[name="trade_id"]')).to_have_value(str(book.trade.pk))
    form.locator('[name="csv_text"]').set_input_files(str(book.csv_path))
    form.locator('[name="attestation_acknowledged"]').select_option("true")
    prompt = _response(page, preview_key, form.locator(".tui-action-submit").click)
    assert prompt["confirmation_required"] is True
    preview = _response(page, preview_key, page.locator("[data-confirm-action]").click)
    assert preview["response"]["status_code"] == 200
    recovery_copy = page.locator('[data-main-panel] [data-copy-label="费用材料编号（请保存）"]')
    expect(recovery_copy).to_be_visible()
    source_locator = recovery_copy.get_attribute("data-copy-value")
    assert source_locator
    return preview, source_locator


def _disable_policy_from_owner_ui(page: Page, book: FeeBook) -> tuple[int, bool]:
    """Read and explicitly disable the current policy through its confirmed TUI flow."""

    policy_key = PREFIX + "policy"
    policy_form = _form(page, policy_key)
    _set_control_value(policy_form.locator('[name="account_id"]'), str(book.account.pk))
    policy_result = _response(page, policy_key, policy_form.locator(".tui-action-submit").click)
    assert policy_result["response"]["status_code"] == 200
    disable_key = PREFIX + "policy-disable"
    prompt = _response(
        page, disable_key, page.locator('[data-main-panel] [data-next-step-index="1"]').click
    )
    assert prompt["confirmation_required"] is True
    result = _response(page, disable_key, page.locator("[data-confirm-action]").click)
    assert result["response"]["status_code"] == 200
    return _policy_state(book)


@pytest.mark.parametrize("lose_response,reopen", [(False, False), (True, False), (True, True)])
def test_owner_fee_correction_browser_preserves_material_and_applies_once(
    fee_browser: Page,
    fee_book: FeeBook,
    lose_response: bool,
    reopen: bool,
) -> None:
    """Preview is inert; explicit confirmation and original-key recovery apply once."""

    page, book = fee_browser, fee_book
    before = _state(book)
    _enable_policy(page, book)
    assert _state(book) == before
    preview_key, confirm_key, head_key = (
        PREFIX + suffix for suffix in ("preview", "confirm", "head")
    )
    submitted_keys: list[str] = []

    def remember_key(request: Any) -> None:
        if any(
            f"/actions/{key}/run/" in request.url for key in (preview_key, confirm_key, head_key)
        ):
            submitted_keys.append(request.headers.get("idempotency-key", ""))

    page.on("request", remember_key)
    trades_key = "simulated-trading.trades"
    trades_form = _form(page, trades_key)
    trades_form.locator('[name="account_id"]').select_option(str(book.account.pk))
    trades = _response(page, trades_key, trades_form.locator(".tui-action-submit").click)
    assert trades["response"]["status_code"] == 200
    page.locator('[data-main-panel] [data-row-index="0"]').click()
    form = _form(page, preview_key)
    form.locator("[data-fill-from-row]").click()
    expect(form.locator('[name="account_id"]')).to_have_value(str(book.account.pk))
    expect(form.locator('[name="trade_id"]')).to_have_value(str(book.trade.pk))
    form.locator('[name="csv_text"]').set_input_files(str(book.csv_path))
    form.locator('[name="attestation_acknowledged"]').select_option("true")
    preview_prompt = _response(page, preview_key, form.locator(".tui-action-submit").click)
    assert preview_prompt["confirmation_required"] is True
    preview = _response(page, preview_key, page.locator("[data-confirm-action]").click)
    assert preview["response"]["status_code"] == 200
    assert _state(book) == before
    recovery_copy = page.locator('[data-main-panel] [data-copy-label="费用材料编号（请保存）"]')
    expect(recovery_copy).to_be_visible()
    source_locator = recovery_copy.get_attribute("data-copy-value")
    assert source_locator

    def material() -> tuple[str, bytes, str]:
        artifact = FeeCorrectionEvidenceArtifactModel.objects.get(account=book.account)
        return artifact.original_filename, bytes(artifact.raw_bytes), artifact.content_sha256

    assert _db_call(material) == (
        book.csv_path.name,
        book.csv_bytes,
        sha256(book.csv_bytes).hexdigest(),
    )
    expect(page.locator("[data-main-panel]")).to_contain_text("7.00")
    expect(page.locator("[data-main-panel]")).to_contain_text("9.00")
    target_prompt = _response(
        page, confirm_key, page.locator("[data-result-continuation] button").click
    )
    assert target_prompt["confirmation_required"] is True
    assert _state(book) == before
    commits: list[dict[str, Any]] = []
    keys: list[str] = []

    def lose_committed_response(route: Route) -> None:
        # The upstream request reaches the genuine server and commits before loss.
        upstream = route.fetch()
        commits.append(upstream.json())
        keys.append(route.request.headers["idempotency-key"])
        route.abort("failed")

    if lose_response:
        page.route(f"**/actions/{confirm_key}/run/", lose_committed_response)
        page.locator("[data-confirm-action]").click()
        expect(page.locator("[data-continuation-readback]")).to_be_visible()
        assert len(commits) == 1 and commits[0]["response"]["status_code"] == 200
        if reopen:
            committed_state = _state(book)
            page.reload()
            page.locator('[data-experience-mode="professional"]').click()
            if not page.locator("[data-actions-panel]").is_visible():
                page.keyboard.press("F9")
            recovery_key = PREFIX + "recover"
            recovery_form = _form(page, recovery_key)
            recovery_form.locator('[name="account_id"]').select_option(str(book.account.pk))
            recovery_form.locator('[name="trade_id"]').fill(str(book.trade.pk))
            recovery_form.locator('[name="source_locator"]').fill(source_locator)
            with page.expect_request(
                lambda req: f"/actions/{recovery_key}/run/" in req.url
            ) as readback:
                result = _response(
                    page, recovery_key, recovery_form.locator(".tui-action-submit").click
                )
            assert not readback.value.headers.get("idempotency-key")
            expect(page.locator("[data-main-panel]")).to_contain_text("原请求已入账")
            assert _state(book) == committed_state
            assert len(commits) == 1
        else:
            with page.expect_request(
                lambda req: f"/actions/{head_key}/run/" in req.url
            ) as readback:
                result = _response(
                    page, head_key, page.locator("[data-continuation-readback]").click
                )
            assert readback.value.headers["idempotency-key"] == keys[0]
    else:
        result = _response(page, confirm_key, page.locator("[data-confirm-action]").click)
    assert result["response"]["status_code"] == 200
    assert result["outcome"] == "success"
    assert len(submitted_keys) >= 4 and len(set(submitted_keys)) == 1
    assert submitted_keys[0]
    assert _state(book) == (before[0] - Decimal("2.00"), before[1], before[2], 1)

    def audit_params() -> list[dict[str, Any]]:
        summaries = TerminalAuditLogORM.objects.filter(
            user_id=book.owner.pk, command_name=preview_key[:50]
        ).values_list("params_summary", flat=True)
        return [json.loads(summary)["params"] for summary in summaries]

    recorded_params = _db_call(audit_params)
    assert recorded_params
    assert all(params.get("csv_text") == "***" for params in recorded_params)
    assert all(params.get("original_filename") == "***" for params in recorded_params)


def test_owner_fee_http_rejects_missing_csrf_readonly_token_and_other_owner(
    fee_browser: Page,
    fee_book: FeeBook,
    live_server: Any,
) -> None:
    """Use genuine HTTP to prove denied actors cannot create policy or material."""

    page, book = fee_browser, fee_book
    url = f"{live_server.url}/api/simulated-trading/accounts/{book.account.pk}/trades/{book.trade.pk}/fee-correction-preview/"
    payload = {
        "original_filename": book.csv_path.name,
        "csv_text": book.csv_bytes.decode("utf-8"),
        "attestation_acknowledged": True,
    }
    before = _state(book)
    missing_csrf = page.request.post(url, data=payload, headers={"Idempotency-Key": "missing-csrf"})
    assert missing_csrf.status == 403
    assert "CSRF" in missing_csrf.json()["error"]
    browser = page.context.browser
    assert browser is not None
    token_context = browser.new_context()
    try:
        assert token_context.cookies() == []
        readonly = token_context.request.post(
            url,
            data=payload,
            headers={
                "Authorization": f"Token {book.readonly_token}",
                "Idempotency-Key": "readonly",
            },
        )
        assert readonly.status == 403
        assert "read-only" in readonly.json()["error"]
    finally:
        token_context.close()

    def other_session() -> str:
        other = get_user_model().objects.create_user(username=f"other-fee-{uuid4().hex}")
        _create_profile(other)
        client = Client(enforce_csrf_checks=True)
        client.force_login(other)
        return client.cookies[settings.SESSION_COOKIE_NAME].value

    cookie = _db_call(other_session)
    page.context.add_cookies(
        [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
    )
    page.reload(wait_until="networkidle")
    csrf = next(
        item["value"]
        for item in page.context.cookies()
        if item["name"] == settings.CSRF_COOKIE_NAME
    )
    other = page.request.post(
        url,
        data=payload,
        headers={"X-CSRFToken": csrf, "Origin": live_server.url, "Idempotency-Key": "other-owner"},
    )
    assert other.status == 403
    assert _state(book) == before
    assert (
        _db_call(
            lambda: FeeCorrectionEvidenceArtifactModel.objects.filter(account=book.account).count()
        )
        == 0
    )


def test_owner_fee_correction_restores_unknown_material_after_reload_and_reads_receipt(
    fee_browser: Page,
    fee_book: FeeBook,
) -> None:
    """Recover one persisted unresolved material after reload, then read its exact receipt."""

    page, book = fee_browser, fee_book
    before = _state(book)
    _enable_policy(page, book)
    preview_key = PREFIX + "preview"
    confirm_key = PREFIX + "confirm"
    head_key = PREFIX + "head"
    action_keys = (preview_key, confirm_key, head_key)
    requests: list[dict[str, Any]] = []

    def remember_action_request(request: Any) -> None:
        path = urlsplit(request.url).path
        action_key = next(
            (key for key in action_keys if path == f"/api/tui/actions/{key}/run/"),
            None,
        )
        if action_key is None:
            return
        requests.append(
            {
                "action_key": action_key,
                "idempotency_key": request.headers.get("idempotency-key", ""),
                "body": json.loads(request.post_data or "{}"),
            }
        )

    page.on("request", remember_action_request)
    uploaded_preview, source_locator = _upload_owner_preview(page, book)
    original_deadline = uploaded_preview["continuation"]["expires_at"]
    assert _state(book) == before
    original_artifact = _artifact_snapshot(book)
    assert original_artifact == (
        1,
        book.csv_path.name,
        book.csv_bytes,
        sha256(book.csv_bytes).hexdigest(),
    )

    page.reload(wait_until="networkidle")
    page.locator('[data-experience-mode="professional"]').click()
    if not page.locator("[data-actions-panel]").is_visible():
        page.keyboard.press("F9")
    discover_key = PREFIX + "discover"
    discover_form = _form(page, discover_key)
    _set_control_value(discover_form.locator('[name="account_id"]'), str(book.account.pk))
    _set_control_value(discover_form.locator('[name="trade_id"]'), str(book.trade.pk))
    discovery = _response(page, discover_key, discover_form.locator(".tui-action-submit").click)
    rows = discovery["view_model"]["sections"][0]["rows"]
    assert discovery["outcome"] == "success"
    assert len(rows) == 1 and rows[0]["owner_state"] == "unresolved"
    expect(page.locator("[data-main-panel]")).to_contain_text("原材料仍待核对或确认")
    restore_prompt = _response(
        page, preview_key, page.locator('[data-main-panel] [data-next-step-index="0"]').click
    )
    assert restore_prompt["confirmation_required"] is True
    restored_preview = _response(page, preview_key, page.locator("[data-confirm-action]").click)
    restored_continuation = restored_preview["continuation"]
    assert restored_preview["response"]["status_code"] == 200
    assert restored_continuation["expires_at"] == original_deadline
    assert restored_continuation["readback_scope"] == {"source_locator": source_locator}
    assert _artifact_snapshot(book) == original_artifact
    assert _state(book) == before

    target_prompt = _response(
        page, confirm_key, page.locator("[data-result-continuation] button").click
    )
    assert target_prompt["confirmation_required"] is True
    commits: list[dict[str, Any]] = []
    confirmation_keys: list[str] = []

    def lose_committed_response(route: Route) -> None:
        upstream = route.fetch()
        commits.append(upstream.json())
        confirmation_keys.append(route.request.headers["idempotency-key"])
        route.abort("failed")

    page.route(f"**/actions/{confirm_key}/run/", lose_committed_response)
    page.locator("[data-confirm-action]").click()
    expect(page.locator("[data-continuation-readback]")).to_be_visible()
    assert len(commits) == 1
    assert commits[0]["response"]["status_code"] == 200
    assert commits[0]["outcome"] == "success"

    preview_requests = [item for item in requests if item["action_key"] == preview_key]
    confirm_requests = [item for item in requests if item["action_key"] == confirm_key]
    assert len(preview_requests) == 4
    upload_key = preview_requests[0]["idempotency_key"]
    recovered_key = preview_requests[2]["idempotency_key"]
    assert upload_key and upload_key == preview_requests[1]["idempotency_key"]
    assert recovered_key and recovered_key == preview_requests[3]["idempotency_key"]
    assert recovered_key != upload_key
    assert str(preview_requests[2]["body"]["params"]["account_id"]) == str(book.account.pk)
    assert str(preview_requests[2]["body"]["params"]["trade_id"]) == str(book.trade.pk)
    assert preview_requests[2]["body"]["params"]["source_locator"] == source_locator
    assert len(confirm_requests) == 2
    assert all(item["idempotency_key"] == recovered_key for item in confirm_requests)
    assert len(confirmation_keys) == 1 and confirmation_keys[0] == recovered_key
    assert all("source_locator" not in item["body"].get("params", {}) for item in confirm_requests)

    page.unroute(f"**/actions/{confirm_key}/run/", lose_committed_response)
    committed_state = _state(book)
    assert committed_state == (before[0] - Decimal("2.00"), before[1], before[2], 1)
    with page.expect_request(
        lambda request: f"/actions/{head_key}/run/" in request.url
    ) as readback_request:
        receipt = _response(page, head_key, page.locator("[data-continuation-readback]").click)
    assert readback_request.value.headers["idempotency-key"] == recovered_key
    assert receipt["response"]["status_code"] == 200
    assert receipt["outcome"] == "success"
    expect(page.locator("[data-main-panel]")).to_contain_text("原请求已入账")
    assert _state(book) == committed_state
    assert _artifact_snapshot(book) == original_artifact


def test_policy_fences_unknown_confirmation_after_scope_switch_and_requires_local_end(
    fee_browser: Page,
    fee_book: FeeBook,
) -> None:
    """Keep an aborted confirmation unknown across scope clearing and policy fencing."""

    page, book = fee_browser, fee_book
    before = _state(book)
    _enable_policy(page, book)
    binding_version, enabled = _policy_state(book)
    assert enabled

    preview_key = PREFIX + "preview"
    confirm_key = PREFIX + "confirm"
    discover_key = PREFIX + "discover"
    recover_key = PREFIX + "recover"
    action_keys = (preview_key, confirm_key, discover_key, recover_key)
    requests: list[dict[str, Any]] = []

    def remember_action_request(request: Any) -> None:
        path = urlsplit(request.url).path
        action_key = next(
            (key for key in action_keys if path == f"/api/tui/actions/{key}/run/"),
            None,
        )
        if action_key is None:
            return
        requests.append(
            {
                "action_key": action_key,
                "body": json.loads(request.post_data or "{}"),
            }
        )

    page.on("request", remember_action_request)
    uploaded_preview, source_locator = _upload_owner_preview(page, book)
    continuation = uploaded_preview["continuation"]
    confirmation_token = continuation["input"]["confirmation_token"]
    original_artifact = _artifact_snapshot(book)
    assert original_artifact == (
        1,
        book.csv_path.name,
        book.csv_bytes,
        sha256(book.csv_bytes).hexdigest(),
    )
    assert _state(book) == before

    prompt = _response(page, confirm_key, page.locator("[data-result-continuation] button").click)
    assert prompt["confirmation_required"] is True
    aborted: list[dict[str, Any]] = []

    def abort_before_owner(route: Route) -> None:
        # Abort the browser request before the TUI server or owner endpoint runs.
        aborted.append(
            {
                "body": json.loads(route.request.post_data or "{}"),
                "idempotency_key": route.request.headers.get("idempotency-key", ""),
            }
        )
        route.abort("failed")

    confirm_route = f"**/actions/{confirm_key}/run/"
    page.route(confirm_route, abort_before_owner)
    page.locator("[data-confirm-action]").click()
    expect(page.locator("[data-continuation-readback]")).to_be_visible()
    assert len(aborted) == 1 and aborted[0]["idempotency_key"]
    assert "source_locator" not in aborted[0]["body"].get("params", {})
    assert _state(book) == before
    assert _artifact_snapshot(book) == original_artifact

    # Changing both visible scope fields clears the on-screen recovery control and secret.
    discover_form = _form(page, discover_key)
    _set_control_value(discover_form.locator('[name="account_id"]'), str(book.secondary_account.pk))
    _set_control_value(discover_form.locator('[name="trade_id"]'), str(book.secondary_trade.pk))
    expect(page.locator("[data-main-panel]")).to_contain_text(
        "账户或成交已变化，请重新读取费用材料"
    )
    expect(page.locator("[data-continuation-readback]")).to_have_count(0)
    assert source_locator not in page.locator("[data-main-panel]").inner_text()
    assert confirmation_token not in page.locator("body").inner_text()
    secondary = _response(page, discover_key, discover_form.locator(".tui-action-submit").click)
    assert secondary["response"]["status_code"] == 200
    expect(page.locator("[data-continuation-readback]")).to_have_count(0)
    secondary_text = page.locator("[data-main-panel]").inner_text()
    assert source_locator not in secondary_text
    assert confirmation_token not in page.locator("body").inner_text()

    # The browser outcome is unknown; the owner still has valid unresolved material.
    discover_form = _form(page, discover_key)
    _set_control_value(discover_form.locator('[name="account_id"]'), str(book.account.pk))
    _set_control_value(discover_form.locator('[name="trade_id"]'), str(book.trade.pk))
    original_scope = _response(
        page, discover_key, discover_form.locator(".tui-action-submit").click
    )
    assert original_scope["response"]["status_code"] == 200
    assert original_scope["view_model"]["sections"][0]["rows"][0]["owner_state"] == "unresolved"
    assert _state(book) == before
    assert _artifact_snapshot(book) == original_artifact

    disabled_version, disabled = _disable_policy_from_owner_ui(page, book)
    assert not disabled and disabled_version == binding_version + 1
    fenced_form = _form(page, discover_key)
    _set_control_value(fenced_form.locator('[name="account_id"]'), str(book.account.pk))
    _set_control_value(fenced_form.locator('[name="trade_id"]'), str(book.trade.pk))
    fenced = _response(page, discover_key, fenced_form.locator(".tui-action-submit").click)
    assert fenced["response"]["status_code"] == 200
    assert len(fenced["fee_recovery"]) == 1
    proof = fenced["fee_recovery"][0]
    assert proof == {
        "account_id": str(book.account.pk),
        "trade_id": str(book.trade.pk),
        "source_locator": source_locator,
        "state": "fenced",
        "reason_code": "FEE_CORRECTION_RECOVERY_POLICY_SUPERSEDED",
        "binding_policy_version": binding_version,
        "current_policy_version": disabled_version,
    }
    assert fenced["view_model"]["sections"][0]["rows"][0]["owner_state"] == "fenced"
    expect(page.locator("[data-fee-end-fenced]")).to_have_text(
        "结束这份旧材料的确认，继续核对或准备新材料"
    )
    page.locator("[data-fee-end-fenced]").click()
    modal = page.locator("[data-fee-ack-fenced]")
    expect(modal).to_be_visible()
    before_local_end = len(requests)
    modal.click()
    expect(page.locator("[data-main-panel]")).to_contain_text("历史入账状态仍待核对")
    assert len(requests) == before_local_end
    assert _state(book) == before
    assert _artifact_snapshot(book) == original_artifact

    # Explicitly query the retained locator after ending only the page confirmation.
    with page.expect_request(
        lambda request: f"/actions/{recover_key}/run/" in request.url
    ) as readonly_recovery:
        receipt = _response(
            page,
            recover_key,
            page.locator('[data-main-panel] [data-next-step-index="0"]').click,
        )
    assert not readonly_recovery.value.headers.get("idempotency-key")
    assert receipt["response"]["status_code"] == 200
    assert receipt["outcome"] == "partial"
    expect(page.locator("[data-main-panel]")).to_contain_text("尚未找到原请求回执")
    recovered_request = next(item for item in requests if item["action_key"] == recover_key)
    assert recovered_request["body"]["params"] == {
        "account_id": str(book.account.pk),
        "trade_id": str(book.trade.pk),
        "source_locator": source_locator,
    }
    assert _state(book) == before
    assert _artifact_snapshot(book) == original_artifact
    assert sum(item["action_key"] == preview_key for item in requests) == 2
    assert sum(item["action_key"] == confirm_key for item in requests) == 2
    assert len(aborted) == 1
