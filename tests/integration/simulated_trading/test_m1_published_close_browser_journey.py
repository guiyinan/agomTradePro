"""Live-browser M1 preview using a published close in an isolated DEV database.

This is synthetic development evidence. It exercises the ordinary-owner TUI
journey and a read-only preview; it is not evidence for production account 613.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import re
from collections.abc import Iterator
from decimal import Decimal
from hashlib import sha1
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, connections
from django.test import Client
from playwright.sync_api import Page, Route, expect, sync_playwright
from pytest_django.plugin import DjangoDbBlocker
from rest_framework.test import APIClient

from apps.data_center.application.public_published_queries import (
    get_published_price_bar_series,
)
from apps.data_center.infrastructure.models import PriceBarModel
from apps.data_center.infrastructure.publication_rollback_models import (
    PublicationMemberModel,
)
from apps.risk_center.infrastructure.m1_rebalance_risk_policy_models import (
    M1RebalanceRiskPolicyRevisionModel,
)
from apps.simulated_trading.infrastructure.models import (
    DailyInspectionReportModel,
    RebalanceProposalModel,
)
from apps.terminal.infrastructure.tui_adapters import TuiInternalActionExecutor
from tests.integration.simulated_trading import test_m1_published_close_owner_api as owner_case
from tests.integration.simulated_trading.test_fee_correction_confirmation_browser import (
    _db_call,
)
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connections[DEFAULT_DB_ALIAS].vendor != "postgresql",
        reason="live-server published-close journey requires PostgreSQL",
    ),
]

_SCREEN_KEY = "task.account-inspection"
_ACTION_KEY = "account-inspection.run"
_ACTION_PATH = f"/api/tui/actions/{_ACTION_KEY}/run/"
_DASHBOARD_PANEL_KEY = "account-inspection-run"
_M1_IMMUTABILITY_MIGRATION = importlib.import_module(
    "apps.risk_center.migrations.0012_m1_rebalance_risk_policy_immutable"
)


@pytest.fixture
def isolated_m1_revision_table(
    transactional_db: None,
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[None]:
    """Keep this live-server journey's immutable policy rows in a disposable schema."""

    del transactional_db
    database = connections[DEFAULT_DB_ALIAS]
    assert database.vendor == "postgresql"
    with django_db_blocker.unblock():
        assert_native_postgres_test_database()
    quote = database.ops.quote_name
    original_table = M1RebalanceRiskPolicyRevisionModel._meta.db_table
    schema_name = f"m1_browser_{uuid4().hex[:20]}"
    qualified_table = f"{quote(schema_name)}.{quote(original_table)}"
    schema_created = False

    def select_policy_table(table_name: str) -> None:
        model_options = M1RebalanceRiskPolicyRevisionModel._meta
        model_options.db_table = table_name
        # Django's cached Col keeps the alias of the previous disposable table.
        for field in model_options.concrete_fields:
            field.__dict__.pop("cached_col", None)

    try:
        with django_db_blocker.unblock():
            database.ensure_connection()
            with database.cursor() as cursor:
                cursor.execute(f"SELECT 1 FROM {quote(original_table)} LIMIT 1")
                assert cursor.fetchone() is None, "Public M1 revision table must remain empty."
                cursor.execute(f"CREATE SCHEMA {quote(schema_name)}")
            schema_created = True

            select_policy_table(qualified_table)
            with database.cursor() as cursor:
                cursor.execute(f"SET search_path TO {quote(schema_name)}, public")
            with database.schema_editor() as schema_editor:
                schema_editor.create_model(M1RebalanceRiskPolicyRevisionModel)
                _M1_IMMUTABILITY_MIGRATION.install_revision_immutability(
                    django_apps,
                    schema_editor,
                )
            with database.cursor() as cursor:
                cursor.execute("RESET search_path")
                cursor.execute(
                    """
                    SELECT tgname, tgenabled
                      FROM pg_catalog.pg_trigger
                     WHERE tgrelid = %s::regclass
                       AND NOT tgisinternal
                       AND tgname IN (%s, %s)
                    """,
                    [
                        qualified_table,
                        "risk_m1_revision_immutable_dml",
                        "risk_m1_revision_immutable_truncate",
                    ],
                )
                triggers = cursor.fetchall()
            assert set(triggers) == {
                ("risk_m1_revision_immutable_dml", "A"),
                ("risk_m1_revision_immutable_truncate", "A"),
            }

        yield None
    finally:
        select_policy_table(original_table)
        if schema_created:
            with django_db_blocker.unblock():
                database.ensure_connection()
                assert_native_postgres_test_database()
                with database.cursor() as cursor:
                    cursor.execute("RESET search_path")
                    cursor.execute(f"DROP SCHEMA {quote(schema_name)} CASCADE")


@pytest.mark.parametrize("held_sell", [False, True], ids=["buy", "held-sell"])
def test_ordinary_owner_sees_published_close_preview_through_live_tui_http(
    live_server: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_m1_revision_table: None,
    held_sell: bool,
) -> None:
    """Show an ordinary-owner close preview without changing financial ledgers."""

    del isolated_m1_revision_table
    assert_native_postgres_test_database()
    owner_case._install_session_clock(monkeypatch)
    owner, account = owner_case._create_owner_account(
        username="m1-published-close-live-browser",
        positions=(
            ((owner_case.ASSET_BUY, "Local fixture held security", True),) if held_sell else ()
        ),
        cash=Decimal("100000.00"),
        max_position_pct=100.0,
        max_total_position_pct=100.0,
        position_quantity=Decimal("10000.000000"),
        position_price=Decimal("10.0000"),
    )
    assert owner.is_staff is False
    assert owner.is_superuser is False
    target_text = f"{owner_case.ASSET_BUY},{0 if held_sell else 10}"

    foreign_account_id: int | None = None
    if held_sell:
        foreign_owner, foreign_account = owner_case._create_owner_account(
            username=f"m1-published-close-foreign-{uuid4().hex}",
            positions=(),
            cash=Decimal("100000.00"),
            max_position_pct=100.0,
            max_total_position_pct=100.0,
        )
        assert foreign_owner.is_staff is False
        assert foreign_owner.is_superuser is False
        foreign_account_id = foreign_account.pk
        assert type(foreign_account_id) is int

    owner_case._install_published_close_builder(
        monkeypatch,
        account=account,
        user_id=owner.pk,
    )
    publication_id = owner_case._publish_reference_bar()
    policy_client = APIClient()
    owner_case._publish_m1_policy_for_preview(
        monkeypatch,
        client=policy_client,
        owner=owner,
        account=account,
        strategy=None,
    )
    owner_case._install_published_close_builder(
        monkeypatch,
        account=account,
        user_id=owner.pk,
    )

    published = get_published_price_bar_series(
        owner_case.ASSET_BUY,
        publication_key=owner_case.M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        start=owner_case._SESSION,
        end=owner_case._SESSION,
        knowledge_cutoff=owner_case._CUTOFF,
    )
    assert published["publication_id"] == publication_id
    rows = published["rows"]
    assert isinstance(rows, list) and len(rows) == 1
    assert rows[0]["close"] == owner_case._PRICE
    member = PublicationMemberModel.objects.get(
        publication_id=publication_id,
        fact_table=PriceBarModel._meta.db_table,
    )
    assert PriceBarModel.objects.get(pk=member.fact_pk).source == (
        "fixture:published-close-owner-api"
    )

    financial_before = owner_case._financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()

    original_policy = asyncio.get_event_loop_policy()
    changed_policy = ensure_subprocess_event_loop_policy()
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner)
    browser_errors: list[str] = []
    observed_requests: list[dict[str, object]] = []
    owner_route_responses: list[dict[str, object]] = []
    owner_api_agreement: dict[str, str] = {}
    separate_owner_api_request: dict[str, object] | None = None
    separate_owner_api_status: int | None = None
    separate_owner_api_payload: dict[str, Any] | None = None
    fee_fragment_observations: list[dict[str, object]] = []
    evidence_dir = tmp_path / "published-close-browser"
    evidence_dir.mkdir()

    original_execute = TuiInternalActionExecutor.execute

    def observe_owner_route_response(
        executor: TuiInternalActionExecutor,
        *,
        method: str,
        endpoint: str,
        params: dict[str, Any],
        body: dict[str, Any],
        user: Any,
        session: Any | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Capture owner-route responses while delegating to the production executor."""

        result = original_execute(
            executor,
            method=method,
            endpoint=endpoint,
            params=params,
            body=body,
            user=user,
            session=session,
            idempotency_key=idempotency_key,
        )
        if endpoint.endswith("/inspections/run/"):
            owner_route_responses.append(
                {
                    "method": method,
                    "endpoint": endpoint,
                    "body": dict(body),
                    "status_code": result.get("status_code"),
                    "payload": result.get("payload"),
                }
            )
        return result

    monkeypatch.setattr(TuiInternalActionExecutor, "execute", observe_owner_route_response)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            context.tracing.start(screenshots=True, snapshots=True, sources=False)
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
                    browser_errors.append("Browser attempted a non-loopback request.")
                    route.abort("blockedbyclient")
                    return
                route.continue_()

            context.route("**/*", local_only)
            page: Page = context.new_page()
            page.on("pageerror", lambda error: browser_errors.append(str(error)))

            def observe_request(request: Any) -> None:
                parsed = urlsplit(request.url)
                headers = request.all_headers()
                observed_requests.append(
                    {
                        "method": request.method,
                        "path": parsed.path,
                        "loopback": parsed.netloc == urlsplit(live_server.url).netloc,
                        "session_cookie": settings.SESSION_COOKIE_NAME in headers.get("cookie", ""),
                        "csrf_header": bool(headers.get("x-csrftoken")),
                    }
                )

            page.on("request", observe_request)
            connections.close_all()
            page.goto(
                f"{live_server.url}/tui/?screen={_SCREEN_KEY}",
                wait_until="networkidle",
            )
            expect(page.locator("[data-main-panel]")).to_be_visible()
            page.locator('[data-experience-mode="professional"]').click()
            page.keyboard.press("F9")
            expect(page.locator("[data-actions-panel]")).to_be_visible()

            action_ui_key = (
                "task-" + sha1(_ACTION_KEY.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
            )
            form = page.locator(
                f'[data-main-panel] [data-dashboard-panel="{_DASHBOARD_PANEL_KEY}"] '
                f'form[data-action-ui-key="{action_ui_key}"]'
            )
            expect(form).to_have_count(1)
            account_select = form.locator('[name="account_id"]')
            expect(account_select.locator(f'option[value="{account.pk}"]')).to_have_count(1)
            account_select.select_option(str(account.pk))
            price_basis = form.locator('[name="reference_price_basis"]')
            expect(price_basis.locator("option")).to_have_count(2)
            price_basis.select_option("published_close")
            target = form.locator('[name="temporary_target_weights"]')
            target.fill(target_text)

            with page.expect_response(
                lambda response: urlsplit(response.url).path == _ACTION_PATH
            ) as first_response_info:
                form.locator(".tui-action-submit").click()
            first_response = first_response_info.value
            assert first_response.status == 200
            assert first_response.json()["confirmation_required"] is True
            assert (
                _db_call(
                    lambda: DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
                )
                == report_count_before
            )

            with page.expect_response(
                lambda response: urlsplit(response.url).path == _ACTION_PATH
            ) as result_response_info:
                page.locator("[data-confirm-action]").click()
            result_response = result_response_info.value
            assert result_response.status == 200
            envelope = result_response.json()
            assert envelope["confirmation_required"] is False
            assert envelope["response"]["status_code"] == 200
            view_model = envelope["view_model"]
            assert isinstance(view_model, dict)
            assert view_model["kind"] == "detail"
            assert view_model["outcome"] in {"success", "partial"}
            assert len(owner_route_responses) == 1
            tui_owner_response = owner_route_responses[0]
            assert tui_owner_response["method"] == "POST"
            assert tui_owner_response["endpoint"] == (
                f"/api/account/accounts/{account.pk}/inspections/run/"
            )
            assert tui_owner_response["body"]["temporary_target_weights"] == target_text
            assert tui_owner_response["body"]["reference_price_basis"] == "published_close"
            assert tui_owner_response["status_code"] == 200
            tui_owner_payload = tui_owner_response["payload"]
            assert isinstance(tui_owner_payload, dict)
            tui_reports = tui_owner_payload["reports"]
            assert isinstance(tui_reports, list) and len(tui_reports) == 1
            tui_report = tui_reports[0]
            assert isinstance(tui_report, dict)
            assert tui_report["account_id"] == account.pk
            tui_plan = tui_report["plan"]
            assert isinstance(tui_plan, dict)
            assert tui_plan["plan_kind"] == "rebalance_preview"
            assert tui_plan["read_only"] is True
            assert tui_plan["execution_submitted"] is False

            sections = {
                section["key"]: section
                for section in view_model["sections"]
                if isinstance(section, dict) and isinstance(section.get("key"), str)
            }
            asset_section = sections["asset_quantity_plan"]
            asset_rows = asset_section["rows"]
            assert isinstance(asset_rows, list) and len(asset_rows) == 1
            asset_fields = {
                field["key"]: field["value"]
                for field in asset_rows[0]["fields"]
                if isinstance(field, dict)
            }
            assert asset_fields["asset_code"] == owner_case.ASSET_BUY
            assert Decimal(asset_fields["actionable"]) > 0
            assert tui_plan["asset_items"][0]["action"] == ("sell" if held_sell else "buy")

            fee_rows = sections["asset_cost_identity_review"]["rows"]
            assert isinstance(fee_rows, list) and len(fee_rows) == 1
            fee_fields = {
                field["key"]: field["value"]
                for field in fee_rows[0]["fields"]
                if isinstance(field, dict)
            }
            fee_summary = fee_fields["fees"]
            fee_match = re.search(r"费用合计 ([0-9]+(?:\.[0-9]+)?)", fee_summary)
            assert fee_match is not None
            assert Decimal(fee_match.group(1)) > 0

            cash_fields = {
                field["key"]: field["value"]
                for field in sections["cash_and_cost_estimates"]["fields"]
                if isinstance(field, dict)
            }
            cash_before = Decimal(cash_fields["cash_before"])
            if held_sell:
                sell_gross = Decimal(cash_fields["estimated_sell_gross"])
                sell_fees = Decimal(cash_fields["estimated_sell_fees"])
                sell_net = Decimal(cash_fields["estimated_sell_net"])
                cash_after = Decimal(cash_fields["projected_cash_after_sells"])
                assert cash_before == Decimal("100000.00")
                assert sell_gross > 0
                assert sell_fees > 0
                assert sell_net == sell_gross - sell_fees
                assert cash_after == cash_before + sell_net
                assert cash_after > cash_before
                projected_cash_key = "projected_cash_after_sells"
            else:
                buy_fees = Decimal(cash_fields["estimated_buy_fees"])
                cash_after = Decimal(cash_fields["projected_cash_after_buys"])
                assert cash_before == Decimal("100000.00")
                assert buy_fees > 0
                assert Decimal(cash_fields["estimated_buy_gross"]) > 0
                assert Decimal(cash_fields["estimated_buy_total"]) > buy_fees
                assert Decimal("0") < cash_after < cash_before
                projected_cash_key = "projected_cash_after_buys"

            reference_context = sections["reference_price_context"]
            publication_rows = reference_context["rows"]
            assert isinstance(publication_rows, list) and len(publication_rows) == 1
            publication_fields = {
                field["key"]: field["value"]
                for field in publication_rows[0]["fields"]
                if isinstance(field, dict)
            }
            assert publication_fields["bar_date"] == owner_case._SESSION.isoformat()
            assert publication_fields["verification"] == "已核验"
            assert publication_fields["source_observed_at"] == owner_case._CLOSE_UTC.isoformat()

            detail_sections = page.locator("[data-main-panel] [data-detail-section]")
            quantity_section_opened = False
            for index in range(detail_sections.count()):
                detail = detail_sections.nth(index)
                if "单标的数量建议" not in detail.locator("summary").inner_text():
                    continue
                if detail.get_attribute("open") is None:
                    detail.locator(":scope > summary").click()
                quantity_section_opened = True
                break
            assert quantity_section_opened, "Quantity suggestion section is missing."
            fee_section_opened = False
            for index in range(detail_sections.count()):
                detail = detail_sections.nth(index)
                if "单标的费用、来源与限制" not in detail.locator("summary").inner_text():
                    continue
                if detail.get_attribute("open") is None:
                    detail.locator(":scope > summary").click()
                fee_section_opened = True
                break
            assert fee_section_opened, "Fee and source details section is missing."

            panel_text = page.locator("[data-main-panel]").inner_text()
            assert "已核验日终收盘价（仅本次只读预览）" in panel_text
            assert owner_case._SESSION.isoformat() in panel_text
            assert owner_case._CLOSE_UTC.isoformat() in panel_text
            assert fee_summary in panel_text
            assert cash_fields[projected_cash_key] in panel_text
            if held_sell:
                assert "Local fixture held security" in panel_text
                assert asset_fields["actionable"] in panel_text
            assert browser_errors == []

            if held_sell:
                assert foreign_account_id is not None
                browser_cookies = {
                    cookie["name"]: cookie["value"] for cookie in context.cookies(live_server.url)
                }
                session_cookie = browser_cookies[settings.SESSION_COOKIE_NAME]
                csrf_cookie = browser_cookies[settings.CSRF_COOKIE_NAME]
                comparison_request_body = {
                    "temporary_target_weights": target_text,
                    "reference_price_basis": "published_close",
                }
                comparison_path = f"/api/account/accounts/{account.pk}/inspections/run/"
                comparison_response = context.request.post(
                    f"{live_server.url}{comparison_path}",
                    data=comparison_request_body,
                    headers={
                        "Content-Type": "application/json",
                        "Cookie": (
                            f"{settings.SESSION_COOKIE_NAME}={session_cookie}; "
                            f"{settings.CSRF_COOKIE_NAME}={csrf_cookie}"
                        ),
                        "X-CSRFToken": csrf_cookie,
                    },
                )
                assert comparison_response.status == 200
                comparison_payload = comparison_response.json()
                separate_owner_api_request = {
                    "method": "POST",
                    "path": comparison_path,
                    "body": comparison_request_body,
                }
                separate_owner_api_status = comparison_response.status
                separate_owner_api_payload = comparison_payload
                comparison_reports = comparison_payload["reports"]
                assert isinstance(comparison_reports, list) and len(comparison_reports) == 1
                comparison_report = comparison_reports[0]
                assert comparison_report["account_id"] == account.pk
                assert comparison_report["report_id"] == tui_report["report_id"]
                comparison_plan = comparison_report["plan"]
                assert isinstance(comparison_plan, dict)
                assert comparison_plan["plan_kind"] == "rebalance_preview"
                assert comparison_plan["read_only"] is True
                assert comparison_plan["execution_submitted"] is False
                ui_as_of = tui_plan["as_of"]
                api_as_of = comparison_plan["as_of"]
                assert isinstance(ui_as_of, str) and ui_as_of
                assert isinstance(api_as_of, str) and api_as_of
                owner_api_agreement = {
                    "tui_as_of": ui_as_of,
                    "separate_owner_post_as_of": api_as_of,
                }
                assert (
                    tui_report["inspection_date"]
                    == comparison_report["inspection_date"]
                    == (owner_case._SESSION.isoformat())
                )
                ui_sell_item = next(
                    item
                    for item in tui_plan["asset_items"]
                    if item["asset_code"] == owner_case.ASSET_BUY
                )
                api_sell_item = next(
                    item
                    for item in comparison_plan["asset_items"]
                    if item["asset_code"] == owner_case.ASSET_BUY
                )
                assert ui_sell_item["action"] == api_sell_item["action"] == "sell"
                for key, expected in (
                    ("current_quantity", Decimal("10000.000000")),
                    ("sellable_quantity", Decimal("10000.000000")),
                    ("target_quantity", Decimal("0.000000")),
                    ("suggested_quantity", Decimal("10000.000000")),
                    ("actionable_quantity", Decimal("10000.000000")),
                    ("current_amount", Decimal("100000.00")),
                    ("target_amount", Decimal("0.00")),
                    ("suggested_amount", Decimal("100000.00")),
                    ("actionable_amount", Decimal("100000.00")),
                    ("reference_price", Decimal("10.00")),
                    ("current_weight", Decimal("0.5")),
                    ("target_weight", Decimal("0")),
                ):
                    assert Decimal(ui_sell_item[key]) == expected
                    assert Decimal(api_sell_item[key]) == expected
                for key in (
                    "status",
                    "reference_price",
                    "suggested_quantity",
                    "actionable_quantity",
                    "suggested_amount",
                    "fee",
                    "price_publication",
                ):
                    assert ui_sell_item[key] == api_sell_item[key]
                for key in (
                    "cash_before",
                    "estimated_sell_gross",
                    "estimated_sell_fees",
                    "estimated_sell_net",
                    "projected_cash_after_sells",
                ):
                    assert tui_plan[key] == comparison_plan[key]
                assert Decimal(ui_sell_item["actionable_quantity"]) > 0
                assert Decimal(ui_sell_item["fee"]["commission"]) > 0
                assert Decimal(ui_sell_item["fee"]["stamp_duty"]) > 0
                assert (
                    _db_call(
                        lambda: DailyInspectionReportModel.objects.filter(
                            account_id=account.pk
                        ).count()
                    )
                    == report_count_before + 1
                )

            page.screenshot(path=str(evidence_dir / "viewport.png"), full_page=False)
            if held_sell:
                page.set_viewport_size({"width": 390, "height": 844})
                narrow_panel = page.locator("[data-main-panel]")
                expect(narrow_panel).to_be_visible()
                narrow_text = narrow_panel.inner_text()
                assert "Local fixture held security" in narrow_text
                assert fee_summary in narrow_text
                assert cash_fields[projected_cash_key] in narrow_text
                assert page.evaluate(
                    "() => document.documentElement.scrollWidth <= window.innerWidth"
                )
                summary_box = narrow_panel.locator("[data-task-result-summary]").bounding_box()
                assert summary_box is not None
                assert 0 <= summary_box["x"]
                assert summary_box["x"] + summary_box["width"] <= 390
                page.screenshot(
                    path=str(evidence_dir / "narrow-viewport.png"),
                    full_page=False,
                )

                quantity_detail = narrow_panel.locator("[data-detail-section]").filter(
                    has_text="单标的数量建议"
                )
                assert quantity_detail.get_attribute("open") is not None
                quantity_detail.scroll_into_view_if_needed()
                quantity_row = quantity_detail.locator(".tui-mini-table tbody tr").filter(
                    has_text="Local fixture held security"
                )
                expect(quantity_row).to_be_visible()
                actionable_cell = quantity_row.locator("td").nth(5)
                actionable_cell.scroll_into_view_if_needed()
                actionable_label = quantity_detail.get_by_text(
                    "规则约束后建议数量",
                    exact=True,
                )
                expect(actionable_label).to_be_visible()
                expect(actionable_cell).to_be_visible()
                displayed_actionable = actionable_cell.inner_text().strip().replace(",", "")
                expected_actionable = str(asset_fields["actionable"]).replace(",", "")
                assert Decimal(displayed_actionable) == Decimal(expected_actionable)
                actionable_box = actionable_cell.bounding_box()
                assert actionable_box is not None
                assert 0 <= actionable_box["x"]
                assert actionable_box["x"] + actionable_box["width"] <= 390
                assert 0 <= actionable_box["y"]
                assert actionable_box["y"] + actionable_box["height"] <= 844
                page.screenshot(
                    path=str(evidence_dir / "narrow-quantity.png"),
                    full_page=False,
                )

                fee_detail = narrow_panel.locator("[data-detail-section]").filter(
                    has_text="单标的费用、来源与限制"
                )
                assert fee_detail.get_attribute("open") is not None
                fee_detail.scroll_into_view_if_needed()
                fee_row = fee_detail.locator(".tui-mini-table tbody tr").filter(
                    has_text="Local fixture held security"
                )
                expect(fee_row).to_be_visible()
                fee_cell = fee_row.locator("td").nth(1)
                fee_cell.scroll_into_view_if_needed()
                fee_fragments = fee_summary.split("；")
                for index, fragment in enumerate(fee_fragments):
                    visible_fragment = fee_cell.evaluate(
                        """(cell, fragment) => {
                            const scroller = cell.closest('.tui-table-scroll');
                            if (!scroller) return {found: false};
                            const walker = document.createTreeWalker(
                                cell,
                                NodeFilter.SHOW_TEXT
                            );
                            let textNode = null;
                            let startOffset = -1;
                            while (walker.nextNode()) {
                                const candidate = walker.currentNode.nodeValue || '';
                                const offset = candidate.indexOf(fragment);
                                if (offset >= 0) {
                                    textNode = walker.currentNode;
                                    startOffset = offset;
                                    break;
                                }
                            }
                            if (!textNode || startOffset < 0) return {found: false};
                            const range = document.createRange();
                            range.setStart(textNode, startOffset);
                            range.setEnd(textNode, startOffset + fragment.length);
                            const port = scroller.getBoundingClientRect();
                            const portLeft = port.left + scroller.clientLeft;
                            const contentRect = range.getBoundingClientRect();
                            const fragmentLeft = contentRect.left - portLeft + scroller.scrollLeft;
                            const fragmentRight = contentRect.right - portLeft + scroller.scrollLeft;
                            let nextScrollLeft = scroller.scrollLeft;
                            if (fragmentLeft < scroller.scrollLeft) {
                                nextScrollLeft = fragmentLeft - 2;
                            } else if (fragmentRight > scroller.scrollLeft + scroller.clientWidth) {
                                nextScrollLeft = fragmentRight - scroller.clientWidth + 2;
                            }
                            scroller.scrollLeft = Math.max(
                                0,
                                Math.min(
                                    scroller.scrollWidth - scroller.clientWidth,
                                    nextScrollLeft
                                )
                            );
                            const viewport = scroller.getBoundingClientRect();
                            const viewportLeft = viewport.left + scroller.clientLeft;
                            const viewportRight = viewportLeft + scroller.clientWidth;
                            const rects = Array.from(range.getClientRects()).map(rect => ({
                                left: rect.left,
                                right: rect.right,
                                top: rect.top,
                                bottom: rect.bottom
                            }));
                            return {
                                found: true,
                                text: range.toString(),
                                scroll_left: scroller.scrollLeft,
                                viewport_left: viewportLeft,
                                viewport_right: viewportRight,
                                window_width: window.innerWidth,
                                window_height: window.innerHeight,
                                rects
                            };
                        }""",
                        fragment,
                    )
                    assert visible_fragment["found"] is True
                    assert visible_fragment["text"] == fragment
                    rects = visible_fragment["rects"]
                    assert isinstance(rects, list) and rects
                    visible_left = max(0.0, visible_fragment["viewport_left"])
                    visible_right = min(
                        390.0,
                        visible_fragment["window_width"],
                        visible_fragment["viewport_right"],
                    )
                    for rect in rects:
                        assert visible_left <= rect["left"]
                        assert rect["right"] <= visible_right
                        assert 0 <= rect["top"]
                        assert rect["bottom"] <= visible_fragment["window_height"]
                    fee_fragment_observations.append(
                        {
                            "fragment": fragment,
                            "visible_after_native_horizontal_scroll": True,
                            "scroll_left": visible_fragment["scroll_left"],
                            "rectangle_count": len(rects),
                        }
                    )
                    if index == 0:
                        page.screenshot(
                            path=str(evidence_dir / "narrow-fee-first-component.png"),
                            full_page=False,
                        )
                assert [
                    observation["fragment"] for observation in fee_fragment_observations
                ] == fee_fragments
                assert all(
                    observation["visible_after_native_horizontal_scroll"] is True
                    for observation in fee_fragment_observations
                )
                page.screenshot(
                    path=str(evidence_dir / "narrow-fee-last-component.png"),
                    full_page=False,
                )

                return_to_workspace = page.locator(
                    "[data-main-panel] [data-return-dashboard-workspace]"
                )
                return_to_workspace.wait_for(state="visible")
                return_to_workspace.click()
                form.wait_for(state="visible")
                foreign_option = form.locator('[name="account_id"]')
                expect(
                    foreign_option.locator(f'option[value="{foreign_account_id}"]')
                ).to_have_count(0)
                foreign_option.evaluate(
                    """(select, accountId) => {
                        const option = document.createElement('option');
                        option.value = String(accountId);
                        option.textContent = 'Foreign account';
                        select.append(option);
                    }""",
                    foreign_account_id,
                )
                foreign_option.select_option(str(foreign_account_id))
                form.locator('[name="reference_price_basis"]').select_option("published_close")
                form.locator('[name="temporary_target_weights"]').fill(target_text)
                with page.expect_response(
                    lambda response: urlsplit(response.url).path == _ACTION_PATH
                ) as foreign_confirmation_info:
                    form.locator(".tui-action-submit").click()
                foreign_confirmation = foreign_confirmation_info.value
                assert foreign_confirmation.status == 200
                assert foreign_confirmation.json()["confirmation_required"] is True
                with page.expect_response(
                    lambda response: urlsplit(response.url).path == _ACTION_PATH
                ) as foreign_result_info:
                    page.locator("[data-confirm-action]").click()
                foreign_result = foreign_result_info.value
                assert foreign_result.status == 200
                foreign_envelope = foreign_result.json()
                assert foreign_envelope["confirmation_required"] is False
                assert foreign_envelope["response"]["status_code"] == 403
                foreign_view_model = foreign_envelope["view_model"]
                assert isinstance(foreign_view_model, dict)
                assert foreign_view_model["kind"] == "message"
                assert foreign_view_model["outcome"] == "blocked"
                assert foreign_view_model["sections"] == []
                assert "没有展示计划明细" in foreign_view_model["business_summary"]
                assert len(owner_route_responses) == 2
                assert owner_route_responses[-1]["status_code"] == 403
                blocked_text = page.locator("[data-main-panel]").inner_text()
                assert "Local fixture held security" not in blocked_text
                assert "费用合计" not in blocked_text
                assert browser_errors == []

            confirmed_action_requests = [
                request
                for request in observed_requests
                if request["path"] == _ACTION_PATH and request["method"] == "POST"
            ]
            assert len(confirmed_action_requests) == (4 if held_sell else 2)
            assert all(request["loopback"] for request in confirmed_action_requests)
            assert all(request["session_cookie"] for request in confirmed_action_requests)
            assert all(request["csrf_header"] for request in confirmed_action_requests)
            assert _db_call(owner_case._financial_snapshot) == financial_before
            expected_report_count = report_count_before + 1
            assert (
                _db_call(
                    lambda: DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
                )
                == expected_report_count
            )
            assert (
                _db_call(
                    lambda: RebalanceProposalModel.objects.filter(account_id=account.pk).count()
                )
                == proposal_count_before
            )
            if held_sell:
                assert foreign_account_id is not None
                assert (
                    _db_call(
                        lambda: DailyInspectionReportModel.objects.filter(
                            account_id=foreign_account_id
                        ).count()
                    )
                    == 0
                )
            assert browser_errors == []
            if not held_sell:
                page.screenshot(path=str(evidence_dir / "viewport.png"), full_page=False)
            context.tracing.stop(path=str(evidence_dir / "trace.zip"))
            (evidence_dir / "browser-observations.json").write_text(
                json.dumps(
                    {
                        "synthetic_dev_evidence": True,
                        "production_account_613_evidence": False,
                        "journey": "held_sell" if held_sell else "buy",
                        "requests": observed_requests,
                        "delegated_owner_responses": owner_route_responses,
                        "separate_live_owner_api": {
                            "request": separate_owner_api_request,
                            "status_code": separate_owner_api_status,
                            "response": separate_owner_api_payload,
                        },
                        "owner_api_agreement": owner_api_agreement,
                        "fee_fragments": fee_fragment_observations,
                        "owner_route_status_codes": [
                            response["status_code"] for response in owner_route_responses
                        ],
                        "page_errors": browser_errors,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            context.close()
            browser.close()
    finally:
        if changed_policy:
            asyncio.set_event_loop_policy(original_policy)
