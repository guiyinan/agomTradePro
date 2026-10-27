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
from tests.integration.simulated_trading import test_m1_published_close_owner_api as owner_case
from tests.integration.simulated_trading.test_fee_correction_confirmation_browser import (
    _db_call,
)
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(transaction=True)

_SCREEN_KEY = "task.account-inspection"
_ACTION_KEY = "account-inspection.run"
_ACTION_PATH = f"/api/tui/actions/{_ACTION_KEY}/run/"
_DASHBOARD_PANEL_KEY = "account-inspection-run"
_TARGET_TEXT = f"{owner_case.ASSET_BUY},10"
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

    try:
        with django_db_blocker.unblock():
            database.ensure_connection()
            with database.cursor() as cursor:
                cursor.execute(f"SELECT 1 FROM {quote(original_table)} LIMIT 1")
                assert cursor.fetchone() is None, "Public M1 revision table must remain empty."
                cursor.execute(f"CREATE SCHEMA {quote(schema_name)}")
            schema_created = True

            M1RebalanceRiskPolicyRevisionModel._meta.db_table = qualified_table
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
        M1RebalanceRiskPolicyRevisionModel._meta.db_table = original_table
        if schema_created:
            with django_db_blocker.unblock():
                database.ensure_connection()
                assert_native_postgres_test_database()
                with database.cursor() as cursor:
                    cursor.execute("RESET search_path")
                    cursor.execute(f"DROP SCHEMA {quote(schema_name)} CASCADE")


def test_ordinary_owner_sees_published_close_preview_through_live_tui_http(
    live_server: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_m1_revision_table: None,
) -> None:
    """Show one 10% temporary target and its verified close without writing a trade."""

    del isolated_m1_revision_table
    assert_native_postgres_test_database()
    owner_case._install_session_clock(monkeypatch)
    owner, account = owner_case._create_owner_account(
        username="m1-published-close-live-browser",
        positions=(),
        cash=Decimal("100000.00"),
        max_position_pct=100.0,
        max_total_position_pct=100.0,
    )
    assert owner.is_staff is False
    assert owner.is_superuser is False

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
    evidence_dir = tmp_path / "published-close-browser"
    evidence_dir.mkdir()
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
            target.fill(_TARGET_TEXT)

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
            buy_fees = Decimal(cash_fields["estimated_buy_fees"])
            cash_after = Decimal(cash_fields["projected_cash_after_buys"])
            assert cash_before == Decimal("100000.00")
            assert buy_fees > 0
            assert Decimal(cash_fields["estimated_buy_gross"]) > 0
            assert Decimal(cash_fields["estimated_buy_total"]) > buy_fees
            assert Decimal("0") < cash_after < cash_before

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
            assert cash_fields["projected_cash_after_buys"] in panel_text
            assert browser_errors == []

            confirmed_action_requests = [
                request
                for request in observed_requests
                if request["path"] == _ACTION_PATH and request["method"] == "POST"
            ]
            assert len(confirmed_action_requests) == 2
            assert all(request["loopback"] for request in confirmed_action_requests)
            assert all(request["session_cookie"] for request in confirmed_action_requests)
            assert all(request["csrf_header"] for request in confirmed_action_requests)
            assert _db_call(owner_case._financial_snapshot) == financial_before
            assert (
                _db_call(
                    lambda: DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
                )
                == report_count_before + 1
            )
            assert (
                _db_call(
                    lambda: RebalanceProposalModel.objects.filter(account_id=account.pk).count()
                )
                == proposal_count_before
            )
            assert browser_errors == []
            page.screenshot(path=str(evidence_dir / "viewport.png"), full_page=False)
            context.tracing.stop(path=str(evidence_dir / "trace.zip"))
            (evidence_dir / "browser-observations.json").write_text(
                json.dumps(
                    {
                        "synthetic_dev_evidence": True,
                        "production_account_613_evidence": False,
                        "requests": observed_requests,
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
